"""Health, per component, with a rule for how the parts add up.

A queue that is long but moving is healthy; one whose oldest due message is old is not, so the age of the oldest due
message is what is measured, not the depth. A worker is judged by a heartbeat that a scheduled task writes: a
dead scheduler and a dead worker look the same from outside, and both should page someone.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import Engine, text

from pulse.clock import Clock

CRITICAL = ("database", "broker")
HEARTBEAT_INTERVAL_SECONDS = 60
OLDEST_DUE_DEGRADED_SECONDS = 900
OLDEST_DUE_DOWN_SECONDS = 3600
SYNC_STALE_SECONDS = 6 * 3600


@dataclass(frozen=True)
class Check:
    component: str
    status: str  # ok | degraded | down
    detail: str
    latency_ms: int | None = None


def rollup(checks: list[Check]) -> str:
    """down when a critical component is down; degraded when anything else is not ok; otherwise ok."""
    if any(c.status == "down" and c.component in CRITICAL for c in checks):
        return "down"
    if any(c.status != "ok" for c in checks):
        return "degraded"
    return "ok"


def _timed(component: str, probe: Callable[[], tuple[str, str]]) -> Check:
    started = time.perf_counter()
    try:
        status, detail = probe()
    except Exception as exc:
        return Check(component, "down", f"{type(exc).__name__}", None)
    return Check(component, status, detail, int((time.perf_counter() - started) * 1000))


def beat(engine: Engine, clock: Clock, component: str = "worker") -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO heartbeats (component, at) VALUES (:c, :at) "
                "ON CONFLICT (component) DO UPDATE SET at = excluded.at"
            ),
            {"c": component, "at": clock.now()},
        )


def collect(engine: Engine, clock: Clock, ping_broker: Callable[[], None] | None) -> list[Check]:
    now = clock.now()

    def database() -> tuple[str, str]:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return "ok", "answers"

    def broker() -> tuple[str, str]:
        if ping_broker is None:
            return "ok", "not configured"
        ping_broker()
        return "ok", "answers"

    def worker() -> tuple[str, str]:
        with engine.connect() as conn:
            at = conn.execute(text("SELECT at FROM heartbeats WHERE component = 'worker'")).scalar()
        if at is None:
            return "degraded", "no heartbeat yet"
        age = (now - at).total_seconds()
        if age > 3 * HEARTBEAT_INTERVAL_SECONDS:
            return "down", f"last heartbeat {int(age)} s ago"
        return "ok", f"last heartbeat {int(max(age, 0))} s ago"

    def queue() -> tuple[str, str]:
        with engine.connect() as conn:
            oldest = conn.execute(
                text(
                    "SELECT min(not_before) FROM outbox WHERE (status = 'pending' AND not_before <= :now) "
                    "OR (status = 'sending' AND lease_until < :now)"
                ),
                {"now": now},
            ).scalar()
            dead = conn.execute(text("SELECT count(*) FROM outbox WHERE status = 'dead'")).scalar() or 0
        if oldest is None:
            return ("degraded", f"{dead} dead") if dead else ("ok", "nothing due")
        age = (now - oldest).total_seconds()
        if age > OLDEST_DUE_DOWN_SECONDS:
            return "down", f"oldest due message is {int(age)} s old"
        if age > OLDEST_DUE_DEGRADED_SECONDS or dead:
            return "degraded", f"oldest due message is {int(age)} s old, {dead} dead"
        return "ok", f"oldest due message is {int(max(age, 0))} s old"

    def sync() -> tuple[str, str]:
        with engine.connect() as conn:
            at = conn.execute(text("SELECT max(finished_at) FROM sync_runs WHERE status = 'ok'")).scalar()
        if at is None:
            return "degraded", "no successful run yet"
        age = (now - at).total_seconds()
        return (
            ("degraded", f"last success {int(age)} s ago")
            if age > SYNC_STALE_SECONDS
            else ("ok", f"last success {int(age)} s ago")
        )

    def index() -> tuple[str, str]:
        with engine.connect() as conn:
            n = conn.execute(text("SELECT count(*) FROM kb_chunks")).scalar() or 0
        return ("ok", f"{n} chunks") if n else ("degraded", "the search index is empty")

    return [
        _timed("database", database),
        _timed("broker", broker),
        _timed("worker", worker),
        _timed("queue", queue),
        _timed("sync", sync),
        _timed("search-index", index),
    ]


def record(engine: Engine, clock: Clock, checks: list[Check]) -> None:
    with engine.begin() as conn:
        for c in checks:
            conn.execute(
                text(
                    "INSERT INTO health_samples (at, component, status, latency_ms, detail) "
                    "VALUES (:at, :c, :s, :l, :d)"
                ),
                {"at": clock.now(), "c": c.component, "s": c.status, "l": c.latency_ms, "d": c.detail[:200]},
            )


def uptime(engine: Engine, clock: Clock, component: str, hours: int = 24) -> dict[str, Any]:
    """Share of samples that were ok in the last `hours`; parameterised, never built from the argument."""
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT count(*) AS total, count(*) FILTER (WHERE status = 'ok') AS ok FROM health_samples "
                "WHERE component = :c AND at >= :since"
            ),
            {"c": component, "since": clock.now() - timedelta(hours=hours)},
        ).one()
    total = int(row.total)
    return {
        "component": component,
        "hours": hours,
        "samples": total,
        "uptime_percent": None if total == 0 else round(100 * int(row.ok) / total, 2),
    }
