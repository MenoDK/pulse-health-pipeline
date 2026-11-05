"""A transmission queue in PostgreSQL.

* A message is written in the same transaction as the change that caused it (`enqueue_many` takes the caller's
  connection), so there is never a change without its message or a message without its change.
* `claim` takes due messages with `FOR UPDATE SKIP LOCKED` and a lease. A worker that dies leaves its messages in
  `sending` until the lease runs out, and then they are due again. Attempts are counted at claim time, so a message
  that kills its worker every time still ends in `dead` instead of looping forever.
* Every state change after a claim names the worker (`locked_by`): a worker whose lease was taken over cannot
  overwrite the result of the one that took over. This is fencing, and `finish` reports whether it won.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, Engine, text


@dataclass(frozen=True)
class Message:
    id: int
    idempotency_key: str
    kind: str
    payload: dict[str, Any]
    attempts: int
    taken_over: bool = False  # claimed after another worker's lease ran out: the sign that a worker died


def enqueue_many(conn: Connection, messages: list[tuple[str, str, dict[str, Any]]], now: datetime) -> int:
    """Insert (key, kind, payload) messages in the caller's transaction. A key already queued is left alone.

    Returns how many were new.
    """
    if not messages:
        return 0
    inserted = 0
    for key, kind, payload in messages:
        result = conn.execute(
            text(
                "INSERT INTO outbox "
                "  (idempotency_key, kind, payload, status, attempts, not_before, created_at, updated_at) "
                "VALUES (:key, :kind, CAST(:payload AS jsonb), 'pending', 0, :now, :now, :now) "
                "ON CONFLICT (idempotency_key) DO NOTHING"
            ),
            {"key": key, "kind": kind, "payload": json.dumps(payload, sort_keys=True), "now": now},
        )
        inserted += result.rowcount
    return inserted


def reap_exhausted(engine: Engine, now: datetime, max_attempts: int) -> int:
    """Messages whose lease ran out after their last allowed attempt are dead: nobody will try them again."""
    with engine.begin() as conn:
        result = conn.execute(
            text(
                "UPDATE outbox SET status = 'dead', lease_until = NULL, locked_by = NULL, updated_at = :now, "
                "last_error = 'the worker stopped answering on the last allowed attempt' "
                "WHERE status = 'sending' AND lease_until < :now AND attempts >= :max"
            ),
            {"now": now, "max": max_attempts},
        )
        return result.rowcount


# What "due" means, as (condition, order). Each is answered by its own partial index, in index order, so a claim reads
# `limit` rows however large the backlog. One query with an OR between the two reads every due row and sorts them, which
# was measured at 10 000 rows for a batch of 50. Messages whose worker died come first: they have waited the longest.
EXPIRED = ("status = 'sending' AND lease_until < :now", "lease_until, id")
PENDING = ("status = 'pending' AND not_before <= :now", "not_before, id")


def due_select(condition: str, order: str) -> str:
    """The SELECT that picks the next messages, for one of the two kinds above (fixed strings, never input)."""
    return f"SELECT id FROM outbox WHERE {condition} ORDER BY {order} LIMIT :limit FOR UPDATE SKIP LOCKED"  # noqa: S608


def claim(engine: Engine, *, worker: str, now: datetime, limit: int, lease_seconds: int) -> list[Message]:
    """Take up to `limit` due messages: ones whose lease has run out first, then pending ones whose time has come."""
    taken: list[Any] = []
    took_over: set[int] = set()
    with engine.begin() as conn:
        for is_takeover, (condition, order) in ((True, EXPIRED), (False, PENDING)):
            room = limit - len(taken)
            if room <= 0:
                break
            rows = conn.execute(
                text(
                    f"WITH due AS ({due_select(condition, order)}) "  # noqa: S608
                    "UPDATE outbox o SET status = 'sending', attempts = o.attempts + 1, locked_by = :worker, "
                    "  lease_until = :lease_until, updated_at = :now "
                    "FROM due WHERE o.id = due.id "
                    "RETURNING o.id, o.idempotency_key, o.kind, o.payload, o.attempts"
                ),
                {"now": now, "limit": room, "worker": worker, "lease_until": now + timedelta(seconds=lease_seconds)},
            ).all()
            if is_takeover:
                took_over.update(r.id for r in rows)
            taken += rows
    return [
        Message(r.id, r.idempotency_key, r.kind, r.payload, r.attempts, r.id in took_over)
        for r in sorted(taken, key=lambda r: r.id)
    ]


def record_attempt(
    conn: Connection, message_id: int, at: datetime, outcome: str, status: int | None, detail: str
) -> None:
    conn.execute(
        text(
            "INSERT INTO outbox_attempts (outbox_id, at, outcome, http_status, detail) "
            "VALUES (:id, :at, :outcome, :status, :detail)"
        ),
        {"id": message_id, "at": at, "outcome": outcome, "status": status, "detail": detail[:300]},
    )


def finish(
    engine: Engine,
    message: Message,
    *,
    worker: str,
    now: datetime,
    outcome: str,
    http_status: int | None,
    detail: str,
    retry_in: int | None = None,
) -> bool:
    """Record the result of an attempt. `outcome` is delivered, duplicate, retry or dead.

    Returns False when the lease had been taken over by another worker: the result is then discarded, and the other
    worker's stands.
    """
    if outcome in ("delivered", "duplicate"):
        new_status, not_before = "done", now
    elif outcome == "retry":
        if retry_in is None:
            raise ValueError("a retry needs a delay")
        new_status, not_before = "pending", now + timedelta(seconds=retry_in)
    elif outcome == "dead":
        new_status, not_before = "dead", now
    else:
        raise ValueError(f"unknown outcome {outcome!r}")
    with engine.begin() as conn:
        result = conn.execute(
            text(
                "UPDATE outbox SET status = :status, not_before = :not_before, lease_until = NULL, locked_by = NULL, "
                "  last_status = :http_status, last_error = :error, updated_at = :now, "
                "  done_at = CASE WHEN :status = 'done' THEN :now ELSE done_at END "
                "WHERE id = :id AND status = 'sending' AND locked_by = :worker"
            ),
            {
                "status": new_status,
                "not_before": not_before,
                "http_status": http_status,
                "error": None if new_status == "done" else detail[:300],
                "now": now,
                "id": message.id,
                "worker": worker,
            },
        )
        if result.rowcount == 1:
            record_attempt(conn, message.id, now, outcome, http_status, detail)
        return result.rowcount == 1


def requeue_dead(engine: Engine, now: datetime, *, ids: list[int] | None = None) -> int:
    """Give dead messages another full set of attempts (all of them, or the ones named). Returns how many moved.

    `dead` is a state a person looks at, not a grave: after a long outage or a fixed payload this is the way back.
    """
    with engine.begin() as conn:
        result = conn.execute(
            text(
                "UPDATE outbox SET status = 'pending', attempts = 0, not_before = :now, lease_until = NULL, "
                "  locked_by = NULL, last_error = NULL, updated_at = :now "
                "WHERE status = 'dead' AND (CAST(:ids AS bigint[]) IS NULL OR id = ANY(CAST(:ids AS bigint[])))"
            ),
            {"now": now, "ids": ids},
        )
        return result.rowcount


def counts(engine: Engine) -> dict[str, int]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT status, count(*) FROM outbox GROUP BY status")).all()
    found = {r[0]: int(r[1]) for r in rows}
    return {s: found.get(s, 0) for s in ("pending", "sending", "done", "dead")}
