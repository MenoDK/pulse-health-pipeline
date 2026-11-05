"""Incremental synchronisation from the registry into the analytic layer.

The guarantees, each pinned by a test and a mutant:

* **Resumable.** A page is applied and the position is advanced in one transaction. A crash between pages loses
  nothing and repeats nothing: the next run starts from the last committed position.
* **Idempotent.** Replaying a page changes nothing. A row is written only when the incoming (version, timestamp) is
  newer than the stored one, so an old copy of a record can never overwrite a newer one.
* **Late-arrival tolerant.** A run re-reads a window before the stored position (`overlap_seconds`), because a record
  can be committed in the registry after one with a later timestamp. The guard above makes the re-read free.
* **One at a time.** A session-level advisory lock; a second run reports `skipped` instead of racing the first.
* **Atomic with the queue.** An encounter and the message that reports it to the gateway are written in the same
  transaction (the transactional outbox).
* **Minimal.** Names and national identifiers are checked and dropped; a person is stored under a keyed hash.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from pydantic import ValidationError
from sqlalchemy import Connection, Engine, text, tuple_
from sqlalchemy.dialects.postgresql import insert

from pulse import schema
from pulse.clock import Clock
from pulse.exchange.queue import enqueue_many
from pulse.identifiers import Pseudonymizer, is_valid_national_id
from pulse.records import (
    ENTITIES,
    ENTITY_MODELS,
    RegistryEncounter,
    RegistryPerson,
    RegistryTeam,
)
from pulse.registry import RegistryClient, RegistryError

log = logging.getLogger(__name__)

ADVISORY_LOCK_KEY = 7_340_113  # any constant: "pulse sync"


class SyncError(RuntimeError):
    """The run cannot continue (an out-of-order page, an unreadable position). The position is not advanced."""


def describe_failure(exc: BaseException) -> str:
    """What a failed run may say about itself: never a message that could carry a record.

    The messages of the errors this pipeline raises are written by us and safe. Anyone else's (a database error that
    quotes the failing row, a validation error that quotes its input) is reduced to its type and, for the database, the
    SQLSTATE code, because the run's error is stored and shown by the API.
    """
    if isinstance(exc, SyncError | RegistryError):
        return f"{type(exc).__name__}: {exc}"[:300]
    sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
    return type(exc).__name__ + (f" (SQLSTATE {sqlstate})" if isinstance(sqlstate, str) else "")


@dataclass
class EntityResult:
    pages: int = 0
    fetched: int = 0
    applied: int = 0
    stale: int = 0
    rejected: int = 0


@dataclass
class SyncResult:
    status: str = "ok"  # ok | failed | skipped
    run_id: int | None = None
    entities: dict[str, EntityResult] = field(default_factory=dict)
    error: str | None = None
    queued: int = 0

    def total(self, name: str) -> int:
        return sum(getattr(e, name) for e in self.entities.values())


def _position(items: list[dict[str, object]]) -> tuple[datetime, str]:
    """The (updated_at, id) of the last record we can read a position from."""
    for raw in reversed(items):
        try:
            return datetime.fromisoformat(str(raw["updated_at"])), str(raw["id"])
        except (KeyError, ValueError):
            continue
    raise SyncError("a page carried no readable position; refusing to guess one")


def _check_order(items: list[dict[str, object]], after: tuple[datetime, str] | None) -> None:
    previous = after
    for raw in items:
        try:
            current = (datetime.fromisoformat(str(raw["updated_at"])), str(raw["id"]))
        except (KeyError, ValueError):
            continue  # an unreadable record is rejected later; it cannot be placed in the order
        if previous is not None and current < previous:
            raise SyncError("the registry returned records out of order; the position cannot be trusted")
        previous = current


def _newer(table: Any) -> Any:
    excluded = insert(table).excluded
    return tuple_(excluded.version, excluded.source_updated_at) > tuple_(table.c.version, table.c.source_updated_at)


def _month(day: date) -> date:
    return day.replace(day=1)


class Syncer:
    def __init__(
        self,
        engine: Engine,
        client: RegistryClient,
        pseudonyms: Pseudonymizer,
        clock: Clock,
        *,
        page_size: int = 200,
        overlap_seconds: int = 300,
        on_page_committed: Callable[[str, int], None] | None = None,
    ) -> None:
        self._engine = engine
        self._client = client
        self._pseudonyms = pseudonyms
        self._clock = clock
        self._page_size = page_size
        self._overlap = timedelta(seconds=overlap_seconds)
        self._on_page_committed = on_page_committed

    # ------------------------------------------------------------------------------------------------ the run
    def run(self, *, full: bool = False) -> SyncResult:
        lock = self._engine.connect()
        try:
            got = lock.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": ADVISORY_LOCK_KEY}).scalar()
            lock.commit()
            if not got:
                return SyncResult(status="skipped", error="another run holds the lock")
            return self._run_locked(full)
        finally:
            try:
                lock.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": ADVISORY_LOCK_KEY})
                lock.commit()
            finally:
                lock.close()

    def _run_locked(self, full: bool) -> SyncResult:
        result = SyncResult()
        result.run_id = self._open_run()
        try:
            for entity in ENTITIES:
                result.entities[entity] = self._sync_entity(entity, full, result)
        except Exception as exc:
            result.status = "failed"
            result.error = describe_failure(exc)
            log.warning("sync run %s failed: %s", result.run_id, result.error)
        self._close_run(result)
        return result

    def _open_run(self) -> int:
        with self._engine.begin() as conn:
            row = conn.execute(
                text("INSERT INTO sync_runs (started_at, status) VALUES (:now, 'running') RETURNING id"),
                {"now": self._clock.now()},
            ).one()
        return int(row[0])

    def _close_run(self, result: SyncResult) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE sync_runs SET finished_at = :now, status = :status, pages = :pages, fetched = :fetched, "
                    "applied = :applied, stale = :stale, rejected = :rejected, error = :error WHERE id = :id"
                ),
                {
                    "now": self._clock.now(),
                    "status": result.status,
                    "pages": result.total("pages"),
                    "fetched": result.total("fetched"),
                    "applied": result.total("applied"),
                    "stale": result.total("stale"),
                    "rejected": result.total("rejected"),
                    "error": result.error,
                    "id": result.run_id,
                },
            )

    # ------------------------------------------------------------------------------------------------ one entity
    def _read_position(self, entity: str) -> datetime | None:
        """The stored position is a time and nothing else: a registry record id is never written to our database."""
        with self._engine.connect() as conn:
            row = conn.execute(
                text("SELECT cursor_updated_at FROM sync_state WHERE entity = :e"), {"e": entity}
            ).first()
        return None if row is None else row[0]

    def _sync_entity(self, entity: str, full: bool, run: SyncResult) -> EntityResult:
        out = EntityResult()
        stored = None if full else self._read_position(entity)
        # Start a little before the stored time: the overlap window. Inside a run the (time, id) position moves strictly
        # forward in memory, which is what keeps a page boundary from splitting records that share a timestamp; between
        # runs only the time is kept, and the overlap re-reads whatever shared it.
        after_at = None if stored is None else stored - self._overlap
        after_id: str | None = None
        while True:
            page = self._client.fetch(entity, after_at, after_id, self._page_size)
            if not page.items:
                break
            before = None if after_at is None else (after_at, after_id or "")
            _check_order(page.items, before)
            position = _position(page.items)
            with self._engine.begin() as conn:
                applied, stale, rejected, queued = self._apply(conn, entity, page.items)
                self._advance(conn, entity, position[0])
            out.pages += 1
            out.fetched += len(page.items)
            out.applied += applied
            out.stale += stale
            out.rejected += rejected
            run.queued += queued
            if self._on_page_committed is not None:
                self._on_page_committed(entity, out.pages)
            if not page.has_more:
                break
            after_at, after_id = position
        return out

    def _advance(self, conn: Connection, entity: str, at: datetime) -> None:
        """Move the stored time forward, never back: a re-read of the overlap window must not rewind it."""
        conn.execute(
            text(
                "INSERT INTO sync_state (entity, cursor_updated_at, updated_at) VALUES (:e, :at, :now) "
                "ON CONFLICT (entity) DO UPDATE SET cursor_updated_at = excluded.cursor_updated_at, "
                "  updated_at = excluded.updated_at "
                "WHERE sync_state.cursor_updated_at IS NULL "
                "   OR excluded.cursor_updated_at > sync_state.cursor_updated_at"
            ),
            {"e": entity, "at": at, "now": self._clock.now()},
        )

    # ------------------------------------------------------------------------------------------------ one page
    def _apply(self, conn: Connection, entity: str, items: list[dict[str, object]]) -> tuple[int, int, int, int]:
        model = ENTITY_MODELS[entity]
        valid: list[Any] = []
        rejected = 0
        for raw in items:
            try:
                valid.append(model.model_validate(raw))
            except ValidationError:
                rejected += 1  # counted, and never logged with its content
        if entity == "teams":
            rows = self._team_rows([r for r in valid if isinstance(r, RegistryTeam)])
            table, key = schema.teams, "team_id"
        elif entity == "people":
            rows, bad = self._person_rows([r for r in valid if isinstance(r, RegistryPerson)])
            rejected += bad
            table, key = schema.subjects, "subject_key"
        else:
            rows = self._encounter_rows([r for r in valid if isinstance(r, RegistryEncounter)])
            table, key = schema.encounters, "encounter_id"

        written: Sequence[Any] = []
        if rows:
            insertion = insert(table).values(rows)
            excluded = insertion.excluded
            update = {c.name: excluded[c.name] for c in table.c if c.name != key}
            upsert = insertion.on_conflict_do_update(
                index_elements=[table.c[key]], set_=update, where=_newer(table)
            ).returning(table.c[key], table.c.version)
            written = conn.execute(upsert).all()
        applied = len(written)
        queued = 0
        if entity == "encounters" and written:
            now = self._clock.now()
            by_id = {r["encounter_id"]: r for r in rows}
            messages = [
                (
                    f"encounter:{encounter_id}:v{version}",
                    "encounter-report",
                    {
                        "encounter_id": encounter_id,
                        "subject_key": by_id[encounter_id]["subject_key"],
                        "kind": by_id[encounter_id]["kind"],
                        "occurred_on": by_id[encounter_id]["occurred_on"].isoformat(),
                        "version": version,
                        "deleted": by_id[encounter_id]["deleted"],
                    },
                )
                for encounter_id, version in written
            ]
            queued = enqueue_many(conn, messages, now)
        # Stale = valid but not written: an older copy, a repeat, or the losing twin of a team listed twice.
        stale = len(items) - rejected - applied
        return applied, stale, rejected, queued

    # ------------------------------------------------------------------------------------------------ row builders
    @staticmethod
    def _dedupe(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
        """One row per key inside a page, the newest. A multi-row upsert refuses to touch the same row twice."""
        best: dict[str, dict[str, Any]] = {}
        for row in rows:
            current = best.get(row[key])
            if current is None or (row["version"], row["source_updated_at"]) > (
                current["version"],
                current["source_updated_at"],
            ):
                best[row[key]] = row
        return list(best.values())

    def _team_rows(self, teams: list[RegistryTeam]) -> list[dict[str, Any]]:
        rows = [
            {
                "team_id": t.code,
                "name": t.name,
                "kind": t.kind,
                "active": t.active,
                "version": t.version,
                "source_updated_at": t.updated_at,
            }
            for t in teams
        ]
        return self._dedupe(rows, "team_id")

    def _person_rows(self, people: list[RegistryPerson]) -> tuple[list[dict[str, Any]], int]:
        rows: list[dict[str, Any]] = []
        rejected = 0
        for p in people:
            if not is_valid_national_id(p.national_id):
                rejected += 1  # an identifier that fails its own checksum is not a record we can vouch for
                continue
            rows.append(
                {
                    "subject_key": self._pseudonyms.subject_key(p.id),
                    "key_id": self._pseudonyms.key_id,
                    "team_id": p.team_code,
                    "birth_month": _month(p.birth_date),
                    "chronic": p.chronic,
                    "registered_on": p.registered_on,
                    "registry_refreshed_on": p.refreshed_on,
                    "version": p.version,
                    "deleted": p.deleted,
                    "source_updated_at": p.updated_at,
                }
            )
        return self._dedupe(rows, "subject_key"), rejected

    def _encounter_rows(self, encounters: list[RegistryEncounter]) -> list[dict[str, Any]]:
        rows = [
            {
                "encounter_id": e.id,
                "subject_key": self._pseudonyms.subject_key(e.person_id),
                "team_id": e.team_code,
                "kind": e.kind,
                "occurred_on": e.occurred_on,
                "version": e.version,
                "deleted": e.deleted,
                "source_updated_at": e.updated_at,
            }
            for e in encounters
        ]
        return self._dedupe(rows, "encounter_id")
