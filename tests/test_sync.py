"""Synchronisation against a real PostgreSQL: resumable, idempotent, late-arrival tolerant, one at a time, atomic."""

from __future__ import annotations

import random
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, text

from pulse.clock import FixedClock
from pulse.identifiers import Pseudonymizer
from pulse.sync import Syncer, SyncError
from pulse.synthetic import Dataset, evolve, generate
from tests.conftest import FakeRegistry

pytestmark = pytest.mark.integration


def make(db: Engine, registry: FakeRegistry, pseudonyms: Pseudonymizer, clock: FixedClock, **kwargs: Any) -> Syncer:
    return Syncer(db, registry, pseudonyms, clock, page_size=kwargs.pop("page_size", 50), **kwargs)


def table_counts(db: Engine) -> dict[str, int]:
    with db.connect() as conn:
        return {
            t: int(conn.execute(text(f"SELECT count(*) FROM {t}")).scalar() or 0)
            for t in ("teams", "subjects", "encounters", "outbox")
        }


def snapshot(db: Engine) -> list[tuple[Any, ...]]:
    with db.connect() as conn:
        return [
            tuple(r)
            for r in conn.execute(
                text(
                    "SELECT 'e', encounter_id, subject_key, kind, occurred_on::text, version, deleted FROM encounters "
                    "UNION ALL SELECT 's', subject_key, team_id, birth_month::text, chronic::text, version, deleted FROM subjects "
                    "UNION ALL SELECT 't', team_id, name, kind, active::text, version, false FROM teams ORDER BY 1, 2"
                )
            )
        ]


@pytest.fixture
def data() -> Dataset:
    return generate(seed=11, subjects=120)


def test_first_run_loads_everything_valid_and_counts_what_it_rejected(
    db: Engine, data: Dataset, pseudonyms: Pseudonymizer, clock: FixedClock
) -> None:
    result = make(db, FakeRegistry(data), pseudonyms, clock).run()
    assert result.status == "ok", result.error
    counts = table_counts(db)
    bad_ids = len(data.people[::100])
    assert result.entities["people"].rejected == bad_ids
    assert counts["subjects"] == len(data.people) - bad_ids
    assert counts["encounters"] == len(data.encounters)
    assert counts["teams"] == 8  # eleven rows from the registry, three of them second listings of a team code
    assert result.entities["teams"].stale == 3


def test_replaying_everything_changes_nothing(
    db: Engine, data: Dataset, pseudonyms: Pseudonymizer, clock: FixedClock
) -> None:
    syncer = make(db, FakeRegistry(data), pseudonyms, clock)
    syncer.run()
    before, queued = snapshot(db), table_counts(db)["outbox"]
    again = syncer.run(full=True)  # ignores the stored position: every record is offered again
    assert again.total("applied") == 0
    assert again.total("stale") == again.total("fetched") - again.total("rejected")
    assert snapshot(db) == before
    assert table_counts(db)["outbox"] == queued


def test_an_older_version_never_overwrites_a_newer_one(
    db: Engine, data: Dataset, pseudonyms: Pseudonymizer, clock: FixedClock
) -> None:
    syncer = make(db, FakeRegistry(data), pseudonyms, clock)
    syncer.run()
    victim = dict(data.encounters[0])
    stale = {
        **victim,
        "version": victim["version"] - 1,
        "kind": "vaccination",
        "updated_at": (datetime.fromisoformat(victim["updated_at"]) + timedelta(days=1)).isoformat(),
    }
    data.encounters[0] = stale
    syncer.run(full=True)
    with db.connect() as conn:
        kind = conn.execute(text("SELECT kind FROM encounters WHERE encounter_id = :i"), {"i": victim["id"]}).scalar()
    assert kind == victim["kind"]


def test_a_crash_between_pages_loses_nothing_and_repeats_nothing(
    db: Engine, data: Dataset, pseudonyms: Pseudonymizer, clock: FixedClock
) -> None:
    def crash_on_third_page(entity: str, page: int) -> None:
        if entity == "encounters" and page == 3:
            raise ConnectionError("the process died")

    registry = FakeRegistry(data)
    # The hook fires on the 3rd call to fetch overall; count calls to the encounters entity only.
    seen = {"n": 0}

    def hook(entity: str, _n: int) -> None:
        if entity == "encounters":
            seen["n"] += 1
            crash_on_third_page(entity, seen["n"])

    registry.on_fetch = hook
    syncer = make(db, registry, pseudonyms, clock)
    failed = syncer.run()
    assert failed.status == "failed"
    assert "ConnectionError" in (failed.error or "")
    partial = table_counts(db)["encounters"]
    assert 0 < partial < len(data.encounters)  # two pages were committed, the rest was not

    registry.on_fetch = None
    resumed = syncer.run()
    assert resumed.status == "ok"
    assert table_counts(db)["encounters"] == len(data.encounters)

    # And the end state is exactly what one uninterrupted run produces.
    interrupted = snapshot(db)
    with db.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE encounters, subjects, teams, sync_state, sync_runs, outbox, outbox_attempts RESTART IDENTITY"
            )
        )
    make(db, FakeRegistry(data), pseudonyms, clock).run()
    assert snapshot(db) == interrupted


def test_the_position_moves_with_each_committed_page(
    db: Engine, data: Dataset, pseudonyms: Pseudonymizer, clock: FixedClock
) -> None:
    positions: list[Any] = []

    def record(entity: str, page: int) -> None:
        with db.connect() as conn:
            positions.append(
                (
                    entity,
                    page,
                    conn.execute(text("SELECT cursor_updated_at FROM sync_state WHERE entity = 'encounters'")).scalar(),
                )
            )

    make(db, FakeRegistry(data), pseudonyms, clock, on_page_committed=record).run()
    encounter_positions = [p[2] for p in positions if p[0] == "encounters"]
    assert len(encounter_positions) >= 3
    assert encounter_positions == sorted(set(encounter_positions))  # strictly later after every committed page


def test_the_stored_position_never_moves_backwards_when_the_registry_has_lost_its_newest_records(
    db: Engine, data: Dataset, pseudonyms: Pseudonymizer, clock: FixedClock
) -> None:
    """A re-read of the overlap window ends before the stored position when the newest records are gone (a restore, a
    redaction). If the position followed the page, the next run would start earlier each time."""
    syncer = make(db, FakeRegistry(data), pseudonyms, clock)
    syncer.run()

    def stored() -> datetime:
        with db.connect() as conn:
            return conn.execute(
                text("SELECT cursor_updated_at FROM sync_state WHERE entity = 'encounters'")
            ).scalar_one()

    position = stored()
    newest = max(datetime.fromisoformat(e["updated_at"]) for e in data.encounters)
    assert position == newest
    person = data.people[1]
    data.encounters[:] = [
        e for e in data.encounters if datetime.fromisoformat(e["updated_at"]) < newest - timedelta(hours=1)
    ]
    data.encounters.append(
        {
            "id": "reg-e-9100001",
            "person_id": person["id"],
            "team_code": person["team_code"],
            "kind": "consultation",
            "occurred_on": "2026-06-01",
            "version": 1,
            "deleted": False,
            "updated_at": (newest - timedelta(seconds=60)).isoformat(),
        }
    )
    result = syncer.run()
    assert result.status == "ok", result.error
    assert result.entities["encounters"].fetched == 1  # the window did re-read it, and it ends before the position
    assert stored() == position


def _arrive_behind_the_position(
    db: Engine, data: Dataset, pseudonyms: Pseudonymizer, clock: FixedClock, overlap_seconds: int
) -> tuple[Syncer, set[str]]:
    """Sync, move the stored position forward with a newer record, then let two records arrive behind it.

    One is 1 minute behind the position, one is an hour behind. Returns the syncer and the late ids stored after an
    incremental run.
    """
    syncer = make(db, FakeRegistry(data), pseudonyms, clock, overlap_seconds=overlap_seconds)
    syncer.run()
    with db.connect() as conn:
        newest = conn.execute(text("SELECT max(source_updated_at) FROM encounters")).scalar()
    position = newest + timedelta(hours=2)
    person = data.people[1]

    def record(identifier: str, seconds_behind_position: int) -> dict[str, Any]:
        stamp = position - timedelta(seconds=seconds_behind_position)
        return {
            "id": identifier,
            "person_id": person["id"],
            "team_code": person["team_code"],
            "kind": "consultation",
            "occurred_on": "2026-06-01",
            "version": 1,
            "deleted": False,
            "updated_at": stamp.isoformat(),
        }

    data.encounters.append(record("reg-e-9000001", 0))  # the newer record that moves the position
    syncer.run()
    data.encounters.append(record("reg-e-9000002", 60))
    data.encounters.append(record("reg-e-9000003", 3600))
    syncer.run()
    return syncer, stored_late_ids(db)


def stored_late_ids(db: Engine) -> set[str]:
    with db.connect() as conn:
        return {
            r[0]
            for r in conn.execute(text("SELECT encounter_id FROM encounters WHERE encounter_id LIKE 'reg-e-900000%'"))
        }


def test_a_late_arrival_inside_the_overlap_window_is_seen_and_one_outside_is_not_until_a_full_run(
    db: Engine, data: Dataset, pseudonyms: Pseudonymizer, clock: FixedClock
) -> None:
    syncer, present = _arrive_behind_the_position(db, data, pseudonyms, clock, overlap_seconds=300)
    assert "reg-e-9000002" in present  # 1 minute behind a 5 minute window
    assert "reg-e-9000003" not in present  # an hour behind: the documented limit of an incremental run

    syncer.run(full=True)
    assert "reg-e-9000003" in stored_late_ids(db)


def test_without_the_overlap_window_the_same_late_arrival_is_lost(
    db: Engine, data: Dataset, pseudonyms: Pseudonymizer, clock: FixedClock
) -> None:
    # The control for the test above: it is the window, and nothing else, that catches the record 1 minute behind.
    _, present = _arrive_behind_the_position(db, data, pseudonyms, clock, overlap_seconds=0)
    assert "reg-e-9000001" in present
    assert "reg-e-9000002" not in present


def test_a_team_listed_twice_in_one_page_collapses_to_one_row_with_the_newest_version(
    db: Engine, pseudonyms: Pseudonymizer, clock: FixedClock
) -> None:
    stamp = datetime(2026, 6, 1, tzinfo=UTC)
    data = Dataset(
        teams=[
            {
                "id": "reg-t-01",
                "code": "T01",
                "name": "Old name",
                "kind": "mobile",
                "active": True,
                "version": 1,
                "updated_at": stamp.isoformat(),
            },
            {
                "id": "reg-t-09",
                "code": "T01",
                "name": "New name",
                "kind": "mobile",
                "active": True,
                "version": 2,
                "updated_at": (stamp + timedelta(hours=1)).isoformat(),
            },
        ]
    )
    result = make(db, FakeRegistry(data), pseudonyms, clock).run()
    assert result.status == "ok", result.error
    with db.connect() as conn:
        rows = conn.execute(text("SELECT team_id, name, version FROM teams")).all()
    assert [tuple(r) for r in rows] == [("T01", "New name", 2)]


def test_two_runs_at_once_do_not_race_and_the_second_says_so(
    db: Engine, data: Dataset, pseudonyms: Pseudonymizer, clock: FixedClock
) -> None:
    registry = FakeRegistry(data)
    inside = threading.Event()
    release = threading.Event()

    def hold(entity: str, n: int) -> None:
        if n == 1:
            inside.set()
            assert release.wait(10)

    registry.on_fetch = hold
    first_result: list[Any] = []
    first = threading.Thread(target=lambda: first_result.append(make(db, registry, pseudonyms, clock).run()))
    first.start()
    assert inside.wait(10)
    second = make(db, FakeRegistry(data), pseudonyms, clock).run()
    release.set()
    first.join(20)
    assert second.status == "skipped"
    assert first_result[0].status == "ok"


def test_the_lock_is_released_after_a_failed_run(
    db: Engine, data: Dataset, pseudonyms: Pseudonymizer, clock: FixedClock
) -> None:
    registry = FakeRegistry(data)
    registry.on_fetch = lambda *_: (_ for _ in ()).throw(ConnectionError("down"))
    assert make(db, registry, pseudonyms, clock).run().status == "failed"
    registry.on_fetch = None
    assert make(db, registry, pseudonyms, clock).run().status == "ok"


def test_a_page_out_of_order_fails_the_run_and_does_not_move_the_position(
    db: Engine, data: Dataset, pseudonyms: Pseudonymizer, clock: FixedClock
) -> None:
    class Shuffled(FakeRegistry):
        def fetch(self, entity: str, after_updated_at: datetime | None, after_id: str | None, limit: int) -> Any:
            page = super().fetch(entity, after_updated_at, after_id, limit)
            page.items.reverse()
            return page

    result = make(db, Shuffled(data), pseudonyms, clock).run()
    assert result.status == "failed"
    assert "out of order" in (result.error or "")
    with db.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM sync_state")).scalar() == 0


def test_a_page_with_no_readable_position_fails_instead_of_guessing(
    db: Engine, pseudonyms: Pseudonymizer, clock: FixedClock
) -> None:
    from pulse.records import Page

    class Garbage:
        def fetch(self, entity: str, *_: Any) -> Page:
            items = [{"id": "x", "code": "T1", "updated_at": "not a time"}] if entity == "teams" else []
            return Page(items=items, has_more=False)

    outcome = Syncer(db, Garbage(), pseudonyms, clock).run()  # type: ignore[arg-type]
    assert outcome.status == "failed"
    assert "position" in (outcome.error or "")


def test_a_record_that_does_not_fit_is_counted_and_never_stored(
    db: Engine, pseudonyms: Pseudonymizer, clock: FixedClock
) -> None:
    good = generate(seed=1, subjects=5)
    good.encounters[0]["kind"] = "not-a-kind"
    result = make(db, FakeRegistry(good), pseudonyms, clock).run()
    assert result.entities["encounters"].rejected == 1
    assert table_counts(db)["encounters"] == len(good.encounters) - 1


def test_an_encounter_and_its_message_are_written_together_or_not_at_all(
    db: Engine, data: Dataset, pseudonyms: Pseudonymizer, clock: FixedClock
) -> None:
    make(db, FakeRegistry(data), pseudonyms, clock).run()
    counts = table_counts(db)
    assert counts["outbox"] == counts["encounters"]
    with db.connect() as conn:
        orphans = conn.execute(
            text(
                "SELECT count(*) FROM outbox o WHERE NOT EXISTS "
                "(SELECT 1 FROM encounters e WHERE split_part(o.idempotency_key, ':', 2) = e.encounter_id)"
            )
        ).scalar()
    assert orphans == 0


def test_a_failure_inside_a_page_rolls_back_the_page_and_its_messages(
    db: Engine, data: Dataset, pseudonyms: Pseudonymizer, clock: FixedClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pulse.sync as sync_module

    real = sync_module.enqueue_many
    calls = {"n": 0}

    def exploding(conn: Any, messages: Any, now: Any) -> int:
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("the queue write failed")
        return real(conn, messages, now)

    monkeypatch.setattr(sync_module, "enqueue_many", exploding)
    result = make(db, FakeRegistry(data), pseudonyms, clock).run()
    assert result.status == "failed"
    counts = table_counts(db)
    assert counts["outbox"] == counts["encounters"]  # the page that failed left neither an encounter nor a message


def test_withdrawn_records_stay_as_tombstones_and_are_reported(
    db: Engine, data: Dataset, pseudonyms: Pseudonymizer, clock: FixedClock
) -> None:
    syncer = make(db, FakeRegistry(data), pseudonyms, clock)
    syncer.run()
    evolve(data, random.Random(5), datetime(2026, 7, 2, tzinfo=UTC), new=0, changed=0, removed=3)
    result = syncer.run()
    assert result.entities["encounters"].applied == 3
    with db.connect() as conn:
        deleted = conn.execute(text("SELECT count(*) FROM encounters WHERE deleted")).scalar()
        reported = conn.execute(
            text(
                "SELECT count(*) FROM outbox WHERE split_part(idempotency_key, ':', 3) = 'v2' AND payload ->> 'deleted' = 'true'"
            )
        ).scalar()
    assert deleted == 3
    assert reported == 3


def test_every_run_is_recorded_with_its_counts(
    db: Engine, data: Dataset, pseudonyms: Pseudonymizer, clock: FixedClock
) -> None:
    result = make(db, FakeRegistry(data), pseudonyms, clock).run()
    with db.connect() as conn:
        row = conn.execute(
            text("SELECT status, applied, rejected, finished_at FROM sync_runs WHERE id = :i"), {"i": result.run_id}
        ).one()
    assert row.status == "ok" and row.applied == result.total("applied") and row.rejected == result.total("rejected")
    assert row.finished_at is not None


PLANTED = "Maria Silva 123.456.789-09"


def test_the_error_of_a_failed_run_names_the_kind_of_failure_and_quotes_nothing(
    db: Engine, data: Dataset, pseudonyms: Pseudonymizer, clock: FixedClock
) -> None:
    registry = FakeRegistry(data)
    registry.on_fetch = lambda *_: (_ for _ in ()).throw(RuntimeError(f"cannot parse {PLANTED}"))
    result = make(db, registry, pseudonyms, clock).run()
    assert result.status == "failed"
    assert result.error == "RuntimeError"  # the message may have quoted a record, so it is not kept
    with db.connect() as conn:
        stored = conn.execute(text("SELECT error FROM sync_runs WHERE id = :i"), {"i": result.run_id}).scalar()
    assert stored == "RuntimeError"


def test_a_database_error_that_quotes_the_failing_row_is_reduced_to_its_code(
    db: Engine, data: Dataset, pseudonyms: Pseudonymizer, clock: FixedClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy.exc import IntegrityError

    class FakeDriverError(Exception):
        sqlstate = "23514"

    def refuse(self: Syncer, *args: Any) -> None:
        raise IntegrityError(
            f"INSERT ... DETAIL: Failing row contains ({PLANTED})", {"name": PLANTED}, FakeDriverError(PLANTED)
        )

    monkeypatch.setattr(Syncer, "_advance", refuse)
    result = make(db, FakeRegistry(data), pseudonyms, clock).run()
    assert result.error == "IntegrityError (SQLSTATE 23514)"
    assert PLANTED not in (result.error or "")


def test_the_errors_the_pipeline_raises_itself_keep_their_message_because_it_is_ours(
    db: Engine, data: Dataset, pseudonyms: Pseudonymizer, clock: FixedClock
) -> None:
    class Shuffled(FakeRegistry):
        def fetch(self, entity: str, after_updated_at: datetime | None, after_id: str | None, limit: int) -> Any:
            page = super().fetch(entity, after_updated_at, after_id, limit)
            page.items.reverse()
            return page

    result = make(db, Shuffled(data), pseudonyms, clock).run()
    assert result.error is not None and result.error.startswith("SyncError: the registry returned records out of order")


def test_syncerror_is_a_runtime_error() -> None:
    assert issubclass(SyncError, RuntimeError)
