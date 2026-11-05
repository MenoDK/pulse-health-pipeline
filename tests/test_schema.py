"""The database against its description: what the migration builds is what `schema.py` says, the constraints hold, and
the hot queries stay cheap on a large table."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Boolean, Date, DateTime, Engine, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.exc import DataError, IntegrityError

from pulse import schema
from pulse.exchange.queue import EXPIRED, PENDING, due_select

pytestmark = pytest.mark.integration

NOW = datetime(2026, 7, 1, 9, 0, tzinfo=UTC)
# BigInteger subclasses Integer in SQLAlchemy, so it has to be asked first.
UDT = {
    Text: "text",
    BigInteger: "int8",
    Integer: "int4",
    Boolean: "bool",
    Date: "date",
    JSONB: "jsonb",
    TSVECTOR: "tsvector",
    Vector: "vector",
}


def expected_udt(column: Any) -> str:
    if isinstance(column.type, DateTime):
        return "timestamptz"
    return next(name for kind, name in UDT.items() if isinstance(column.type, kind))


def described(db: Engine) -> dict[str, dict[str, tuple[str, bool]]]:
    with db.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT table_name, column_name, udt_name, is_nullable FROM information_schema.columns WHERE table_schema = current_schema()"
            )
        ).all()
    found: dict[str, dict[str, tuple[str, bool]]] = {}
    for table, column, udt, nullable in rows:
        found.setdefault(table, {})[column] = (udt, nullable == "YES")
    return found


def test_the_migration_builds_exactly_the_tables_schema_py_describes(db: Engine) -> None:
    assert set(described(db)) - {"alembic_version"} == set(schema.metadata.tables)


@pytest.mark.parametrize("table", sorted(schema.metadata.tables))
def test_every_column_has_the_name_type_and_nullability_the_code_expects(db: Engine, table: str) -> None:
    actual = described(db)[table]
    declared = schema.metadata.tables[table]
    assert set(actual) == {c.name for c in declared.columns}
    for column in declared.columns:
        udt, nullable = actual[column.name]
        assert udt == expected_udt(column), (table, column.name)
        assert nullable == bool(column.nullable and not column.primary_key), (table, column.name)


@pytest.mark.parametrize("table", sorted(schema.metadata.tables))
def test_primary_keys_match(db: Engine, table: str) -> None:
    with db.connect() as conn:
        actual = {
            r[0]
            for r in conn.execute(
                text(
                    "SELECT a.attname FROM pg_index i JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
                    "WHERE i.indrelid = CAST(:t AS regclass) AND i.indisprimary"
                ),
                {"t": table},
            )
        }
    assert actual == {c.name for c in schema.metadata.tables[table].primary_key.columns}


def test_the_migration_can_be_undone_and_redone_and_lands_on_the_same_schema(db: Engine) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    cfg.set_main_option("script_location", "alembic")
    before = described(db)
    try:
        command.downgrade(cfg, "base")
        assert set(described(db)) <= {"alembic_version"}
    finally:
        command.upgrade(cfg, "head")
    assert described(db) == before


# ---- constraints --------------------------------------------------------------------------------------------------


def insert_subject(conn: Any, **overrides: Any) -> None:
    row = {"k": "s1", "birth": "2020-05-01", "version": 1, **overrides}
    conn.execute(
        text(
            "INSERT INTO subjects (subject_key, key_id, birth_month, chronic, registered_on, registry_refreshed_on, version, deleted, source_updated_at) "
            "VALUES (:k, 'k1', CAST(:birth AS date), false, '2020-06-01', '2020-06-01', :version, false, :t)"
        ),
        {**row, "t": NOW},
    )


@pytest.mark.parametrize("override", [{"birth": "2020-05-15"}, {"version": -1}])
def test_a_birth_date_with_a_day_or_a_negative_version_is_refused_by_the_database_itself(
    db: Engine, override: dict[str, Any]
) -> None:
    with pytest.raises(IntegrityError, match="check constraint"), db.begin() as conn:
        insert_subject(conn, **override)


def test_a_subject_key_is_unique(db: Engine) -> None:
    with db.begin() as conn:
        insert_subject(conn)
    with pytest.raises(IntegrityError, match="duplicate key"), db.begin() as conn:
        insert_subject(conn)


@pytest.mark.parametrize("table", ["sync_runs", "health_samples"])
def test_a_status_outside_the_known_words_is_refused(db: Engine, table: str) -> None:
    with pytest.raises(IntegrityError, match="check constraint"), db.begin() as conn:
        if table == "sync_runs":
            conn.execute(text("INSERT INTO sync_runs (started_at, status) VALUES (:t, 'maybe')"), {"t": NOW})
        else:
            conn.execute(
                text("INSERT INTO health_samples (at, component, status) VALUES (:t, 'x', 'maybe')"), {"t": NOW}
            )


def test_an_embedding_of_the_wrong_size_is_refused_instead_of_stored(db: Engine) -> None:
    with pytest.raises(DataError, match="dimensions"), db.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO kb_chunks (doc_id, chunk_no, title, category, content, embedding) VALUES ('d', 0, 't', 'c', 'x', CAST('[0.1,0.2]' AS vector))"
            )
        )


def test_a_chunk_is_unique_per_note_and_position(db: Engine) -> None:
    vector = "[" + ",".join(["0.1"] * 256) + "]"
    statement = text(
        "INSERT INTO kb_chunks (doc_id, chunk_no, title, category, content, embedding) VALUES ('d', 0, 't', 'c', 'x', CAST(:v AS vector))"
    )
    with db.begin() as conn:
        conn.execute(statement, {"v": vector})
    with pytest.raises(IntegrityError, match="duplicate key"), db.begin() as conn:
        conn.execute(statement, {"v": vector})


def test_the_attempt_log_of_a_message_goes_with_the_message_and_cannot_outlive_it(db: Engine) -> None:
    with db.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO outbox (idempotency_key, kind, payload, status, not_before, created_at, updated_at) VALUES ('k', 'x', '{}', 'pending', :t, :t, :t)"
            ),
            {"t": NOW},
        )
        conn.execute(text("INSERT INTO outbox_attempts (outbox_id, at, outcome) VALUES (1, :t, 'retry')"), {"t": NOW})
    with pytest.raises(IntegrityError, match="foreign key"), db.begin() as conn:
        conn.execute(text("INSERT INTO outbox_attempts (outbox_id, at, outcome) VALUES (999, :t, 'retry')"), {"t": NOW})
    with db.begin() as conn:
        conn.execute(text("DELETE FROM outbox"))
    with db.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM outbox_attempts")).scalar() == 0


def test_the_search_text_vector_is_generated_by_the_database_and_cannot_be_written(db: Engine) -> None:
    with pytest.raises(Exception, match="generated column"), db.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO kb_chunks (doc_id, chunk_no, title, category, content, embedding, tsv) VALUES ('d', 0, 't', 'c', 'x', CAST(:v AS vector), to_tsvector('x'))"
            ),
            {"v": "[" + ",".join(["0.1"] * 256) + "]"},
        )


# ---- the hot queries on a large table -------------------------------------------------------------------------------


def walk(node: dict[str, Any]) -> list[dict[str, Any]]:
    return [node, *(inner for child in node.get("Plans", []) for inner in walk(child))]


@pytest.mark.parametrize(("name", "kind"), [("messages whose lease ran out", EXPIRED), ("pending messages", PENDING)])
def test_claiming_a_batch_reads_the_batch_and_not_the_backlog(db: Engine, name: str, kind: tuple[str, str]) -> None:
    """200 000 messages, 95 % finished, 2 % due, 2 % held by a dead worker. A claim of 50 must not read the rest.

    A single query with an OR between the two conditions was measured reading and sorting every due row (10 000 here) to
    return 50. The plan, not the clock, is what is asserted: a time threshold would be a flaky test.
    """
    del name
    with db.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO outbox (idempotency_key, kind, payload, status, attempts, not_before, lease_until, created_at, updated_at, done_at) "
                "SELECT 'k' || g, 'encounter-report', '{}'::jsonb, "
                "  CASE WHEN g % 100 < 95 THEN 'done' WHEN g % 100 < 98 THEN 'pending' ELSE 'sending' END, 1, "
                "  CAST(:t AS timestamptz) - (g || ' seconds')::interval, "
                "  CASE WHEN g % 100 >= 98 THEN CAST(:t AS timestamptz) - interval '1 hour' END, :t, :t, "
                "  CASE WHEN g % 100 < 95 THEN CAST(:t AS timestamptz) END "
                "FROM generate_series(1, 200000) g"
            ),
            {"t": NOW},
        )
        conn.execute(text("ANALYZE outbox"))
    condition, order = kind
    with db.connect() as conn:
        raw = conn.execute(
            text("EXPLAIN (ANALYZE, FORMAT JSON, COSTS OFF) " + due_select(condition, order)), {"now": NOW, "limit": 50}
        ).scalar()
        conn.rollback()
    plan = (json.loads(raw) if isinstance(raw, str) else raw)[0]["Plan"]
    nodes = walk(plan)
    types = {n["Node Type"] for n in nodes}
    assert types.isdisjoint({"Seq Scan", "Sort", "Bitmap Heap Scan", "Incremental Sort"}), types
    scan = next(n for n in nodes if n["Node Type"] == "Index Scan")
    assert scan["Actual Rows"] == 50  # it stopped at the batch
    assert scan["Index Name"] in {"outbox_due_idx", "outbox_lease_idx"}
