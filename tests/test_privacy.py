"""Data minimisation as a property of the whole system: look for the identifiers everywhere, and show the search can see."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, text

from pulse.clock import FixedClock
from pulse.exchange.queue import enqueue_many
from pulse.identifiers import Pseudonymizer
from pulse.privacy import TEXT_TYPES, find_values
from pulse.sync import Syncer
from pulse.synthetic import Dataset, generate
from tests.conftest import FakeRegistry

pytestmark = pytest.mark.integration


def synced(db: Engine, data: Dataset, pseudonyms: Pseudonymizer, clock: FixedClock) -> None:
    result = Syncer(db, FakeRegistry(data), pseudonyms, clock, page_size=80).run()
    assert result.status == "ok", result.error


def identifiers_of(data: Dataset) -> list[str]:
    return [v for p in data.people for v in (p["name"], p["national_id"], p["id"])]


def test_after_a_full_sync_no_name_no_national_id_and_no_registry_id_is_stored_anywhere(
    db: Engine, pseudonyms: Pseudonymizer, clock: FixedClock
) -> None:
    data = generate(seed=21, subjects=150)
    synced(db, data, pseudonyms, clock)
    scan = find_values(db, identifiers_of(data))
    assert scan.matches == ()
    assert scan.columns_examined >= 20  # a scan that looked at nothing proves nothing


@pytest.mark.parametrize(
    ("table", "column", "value_sql"),
    [
        ("sync_runs", "error", "'failed for {v}'"),  # a text column
        ("outbox", "payload", 'CAST(\'{{"note": "{v}"}}\' AS jsonb)'),  # inside a json document
        ("lab_state", "value", "CAST('\"{v}\"' AS jsonb)"),
        ("kb_chunks", "content", "'about {v}'"),
    ],
)
def test_the_scan_finds_a_planted_value_in_text_and_inside_json_so_a_clean_result_means_something(
    db: Engine, clock: FixedClock, table: str, column: str, value_sql: str
) -> None:
    planted = "Zxqv Plantedname"
    expression = value_sql.format(v=planted)
    with db.begin() as conn:
        if table == "sync_runs":
            conn.execute(
                text(f"INSERT INTO sync_runs (started_at, status, error) VALUES (:t, 'failed', {expression})"),
                {"t": clock.now()},
            )
        elif table == "outbox":
            conn.execute(
                text(
                    f"INSERT INTO outbox (idempotency_key, kind, payload, status, not_before, created_at, updated_at) "
                    f"VALUES ('k', 'x', {expression}, 'pending', :t, :t, :t)"
                ),
                {"t": clock.now()},
            )
        elif table == "lab_state":
            conn.execute(text(f"INSERT INTO lab_state (key, value) VALUES ('k', {expression})"))
        else:
            conn.execute(
                text(
                    f"INSERT INTO kb_chunks (doc_id, chunk_no, title, category, content, embedding) "
                    f"VALUES ('d', 0, 't', 'c', {expression}, CAST(:e AS vector))"
                ),
                {"e": "[" + ",".join(["0.1"] * 256) + "]"},
            )
    scan = find_values(db, ["Someone Else", planted])
    assert [(t, c) for t, c, _ in scan.matches] == [(table, column)]


def test_regular_expression_characters_in_a_value_are_matched_literally(db: Engine, clock: FixedClock) -> None:
    with db.begin() as conn:
        conn.execute(
            text("INSERT INTO sync_runs (started_at, status, error) VALUES (:t, 'failed', 'axb (1) [x] a.b')"),
            {"t": clock.now()},
        )
    assert find_values(db, ["a.b"]).matches == (("sync_runs", "error", 1),)  # the dot is a dot...
    assert find_values(db, ["a+b"]).matches == ()  # ...and a plus is not "one or more a"
    assert find_values(db, ["a.c"]).matches == ()
    assert find_values(db, ["(1)", "[x]"]).matches == (("sync_runs", "error", 1),)  # brackets do not break the pattern


def test_nothing_to_look_for_is_an_error_not_a_clean_result() -> None:
    with pytest.raises(ValueError, match="nothing to look for"):
        find_values(None, [])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="nothing to look for"):
        find_values(None, ["", ""])  # type: ignore[arg-type]


def test_every_text_like_column_is_examined(db: Engine) -> None:
    with db.connect() as conn:
        expected = conn.execute(
            text(
                "SELECT count(*) FROM information_schema.columns WHERE table_schema = current_schema() AND data_type = ANY(:t)"
            ),
            {"t": list(TEXT_TYPES)},
        ).scalar()
    assert find_values(db, ["anything"]).columns_examined == expected


# ---- the schema is a closed list -------------------------------------------------------------------------------

EXPECTED_COLUMNS = {
    "subjects": {
        "subject_key",
        "key_id",
        "team_id",
        "birth_month",
        "chronic",
        "registered_on",
        "registry_refreshed_on",
        "version",
        "deleted",
        "source_updated_at",
    },
    "encounters": {
        "encounter_id",
        "subject_key",
        "team_id",
        "kind",
        "occurred_on",
        "version",
        "deleted",
        "source_updated_at",
    },
    "sync_state": {"entity", "cursor_updated_at", "updated_at"},
}


@pytest.mark.parametrize("table", sorted(EXPECTED_COLUMNS))
def test_the_tables_that_describe_people_have_exactly_these_columns_and_a_new_one_must_be_a_decision(
    db: Engine, table: str
) -> None:
    with db.connect() as conn:
        columns = {
            r[0]
            for r in conn.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_name = :t"), {"t": table}
            )
        }
    assert columns == EXPECTED_COLUMNS[table]


def test_a_person_is_stored_under_a_keyed_hash_with_the_birth_date_cut_to_the_month(
    db: Engine, pseudonyms: Pseudonymizer, clock: FixedClock
) -> None:
    data = generate(seed=22, subjects=60)
    synced(db, data, pseudonyms, clock)
    person = data.people[1]  # index 0 carries the deliberately wrong check digit and is refused
    with db.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM subjects WHERE subject_key = :k"), {"k": pseudonyms.subject_key(person["id"])}
        ).one()
    assert row.subject_key.startswith("pt1.") and person["id"] not in row.subject_key
    assert row.birth_month.isoformat() == person["birth_date"][:8] + "01"
    assert row.key_id == "t1"


def test_a_field_the_registry_starts_sending_is_dropped_at_the_edge_and_never_reaches_the_database(
    db: Engine, pseudonyms: Pseudonymizer, clock: FixedClock
) -> None:
    data = generate(seed=23, subjects=40)
    for person in data.people:
        person["phone"] = "+00 555 0100"
        person["email"] = "someone@example.test"
    synced(db, data, pseudonyms, clock)
    assert find_values(db, ["+00 555 0100", "someone@example.test"]).matches == ()


def test_the_queue_carries_the_pseudonym_and_the_kind_of_encounter_and_nothing_that_names_anyone(
    db: Engine, pseudonyms: Pseudonymizer, clock: FixedClock
) -> None:
    data = generate(seed=24, subjects=40)
    synced(db, data, pseudonyms, clock)
    with db.connect() as conn:
        payloads: list[dict[str, Any]] = [r[0] for r in conn.execute(text("SELECT payload FROM outbox LIMIT 50"))]
    assert payloads
    assert all(set(p) == {"encounter_id", "subject_key", "kind", "occurred_on", "version", "deleted"} for p in payloads)
    assert all(p["subject_key"].startswith("pt1.") for p in payloads)


def test_a_message_enqueued_by_hand_is_still_scanned_like_any_other(db: Engine, clock: FixedClock) -> None:
    with db.begin() as conn:
        enqueue_many(
            conn, [("k1", "encounter-report", {"subject_key": "pt1.fine", "note": "Zxqv Plantedname"})], clock.now()
        )
    assert find_values(db, ["Zxqv Plantedname"]).matches == (("outbox", "payload", 1),)
