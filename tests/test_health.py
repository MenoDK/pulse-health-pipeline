"""Health per component and the rule for how the parts add up."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import Engine, text

from pulse.clock import FixedClock
from pulse.exchange.queue import claim, enqueue_many, finish
from pulse.health import (
    HEARTBEAT_INTERVAL_SECONDS,
    OLDEST_DUE_DEGRADED_SECONDS,
    OLDEST_DUE_DOWN_SECONDS,
    SYNC_STALE_SECONDS,
    Check,
    beat,
    collect,
    record,
    rollup,
    uptime,
)

# ---- the rule: no database -------------------------------------------------------------------------------------


def c(component: str, status: str) -> Check:
    return Check(component, status, "")


def test_everything_ok_is_ok() -> None:
    assert rollup([c("database", "ok"), c("queue", "ok")]) == "ok"
    assert rollup([]) == "ok"


def test_a_critical_component_down_makes_the_whole_down() -> None:
    assert rollup([c("database", "down"), c("queue", "ok")]) == "down"
    assert rollup([c("broker", "down")]) == "down"


def test_a_component_that_is_not_critical_can_hurt_but_not_take_the_whole_down() -> None:
    for component in ("worker", "queue", "sync", "search-index"):
        assert rollup([c("database", "ok"), c(component, "down")]) == "degraded", component
    assert rollup([c("worker", "degraded")]) == "degraded"


def test_a_critical_component_that_is_only_degraded_is_degraded_not_down() -> None:
    assert rollup([c("database", "degraded")]) == "degraded"


# ---- the checks: against a database ----------------------------------------------------------------------------


def by_name(checks: list[Check]) -> dict[str, Check]:
    return {check.component: check for check in checks}


@pytest.mark.integration
def test_a_fresh_system_is_degraded_where_nothing_has_happened_yet_and_never_reports_a_false_ok(
    db: Engine, clock: FixedClock
) -> None:
    got = by_name(collect(db, clock, lambda: None))
    assert got["database"].status == "ok" and got["broker"].status == "ok"
    assert got["worker"].status == "degraded" and "no heartbeat" in got["worker"].detail
    assert got["sync"].status == "degraded"
    assert got["search-index"].status == "degraded"
    assert got["queue"].status == "ok"  # an empty queue has nothing overdue
    assert rollup(list(got.values())) == "degraded"


@pytest.mark.integration
def test_the_heartbeat_is_ok_while_recent_and_down_after_three_missed_beats(db: Engine, clock: FixedClock) -> None:
    beat(db, clock)
    assert by_name(collect(db, clock, None))["worker"].status == "ok"
    clock.advance(3 * HEARTBEAT_INTERVAL_SECONDS)
    assert by_name(collect(db, clock, None))["worker"].status == "ok"  # exactly three intervals: not yet
    clock.advance(1)
    stale = by_name(collect(db, clock, None))["worker"]
    assert stale.status == "down" and "181 s" in stale.detail
    beat(db, clock)
    assert by_name(collect(db, clock, None))["worker"].status == "ok"


@pytest.mark.integration
def test_a_second_heartbeat_replaces_the_first_instead_of_adding_a_row(db: Engine, clock: FixedClock) -> None:
    beat(db, clock)
    clock.advance(60)
    beat(db, clock)
    with db.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM heartbeats")).scalar() == 1


@pytest.mark.integration
def test_a_broker_that_does_not_answer_makes_the_whole_system_down(db: Engine, clock: FixedClock) -> None:
    def refuse() -> None:
        raise ConnectionError("no route to host 10.0.0.5")  # the address must not be repeated in the check

    checks = collect(db, clock, refuse)
    broker = by_name(checks)["broker"]
    assert broker.status == "down" and broker.detail == "ConnectionError"
    assert rollup(checks) == "down"


def put_due(db: Engine, clock: FixedClock, n: int = 1) -> None:
    with db.begin() as conn:
        enqueue_many(conn, [(f"k{i}", "encounter-report", {}) for i in range(n)], clock.now())


@pytest.mark.integration
def test_the_queue_is_judged_by_the_age_of_its_oldest_due_message_not_by_its_length(
    db: Engine, clock: FixedClock
) -> None:
    put_due(db, clock, 500)  # a long queue
    assert by_name(collect(db, clock, None))["queue"].status == "ok"  # ... that is moving is fine
    clock.advance(OLDEST_DUE_DEGRADED_SECONDS)
    assert by_name(collect(db, clock, None))["queue"].status == "ok"  # exactly at the line
    clock.advance(1)
    assert by_name(collect(db, clock, None))["queue"].status == "degraded"
    clock.advance(OLDEST_DUE_DOWN_SECONDS - OLDEST_DUE_DEGRADED_SECONDS)
    assert by_name(collect(db, clock, None))["queue"].status == "down"


@pytest.mark.integration
def test_a_message_waiting_for_its_backoff_is_not_overdue(db: Engine, clock: FixedClock) -> None:
    put_due(db, clock)
    (message,) = claim(db, worker="w", now=clock.now(), limit=1, lease_seconds=60)
    finish(db, message, worker="w", now=clock.now(), outcome="retry", http_status=503, detail="x", retry_in=7200)
    clock.advance(3600)  # old, but not due for another hour
    assert by_name(collect(db, clock, None))["queue"].status == "ok"


@pytest.mark.integration
def test_a_lease_that_ran_out_counts_as_due_from_the_moment_it_ran_out(db: Engine, clock: FixedClock) -> None:
    put_due(db, clock)
    claim(db, worker="dead", now=clock.now(), limit=1, lease_seconds=60)
    clock.advance(60 + OLDEST_DUE_DEGRADED_SECONDS + 1)
    assert by_name(collect(db, clock, None))["queue"].status == "degraded"


@pytest.mark.integration
def test_dead_messages_degrade_the_queue_even_when_nothing_else_is_waiting(db: Engine, clock: FixedClock) -> None:
    put_due(db, clock)
    (message,) = claim(db, worker="w", now=clock.now(), limit=1, lease_seconds=60)
    finish(db, message, worker="w", now=clock.now(), outcome="dead", http_status=422, detail="refused")
    queue = by_name(collect(db, clock, None))["queue"]
    assert queue.status == "degraded" and "1 dead" in queue.detail


@pytest.mark.integration
def test_the_last_successful_sync_goes_stale_after_six_hours(db: Engine, clock: FixedClock) -> None:
    with db.begin() as conn:
        conn.execute(
            text("INSERT INTO sync_runs (started_at, finished_at, status) VALUES (:t, :t, 'ok')"), {"t": clock.now()}
        )
        conn.execute(
            text("INSERT INTO sync_runs (started_at, finished_at, status) VALUES (:t, :t, 'failed')"),
            {"t": clock.now() + timedelta(hours=5)},
        )
    clock.advance(SYNC_STALE_SECONDS)
    assert by_name(collect(db, clock, None))["sync"].status == "ok"
    clock.advance(1)
    stale = by_name(collect(db, clock, None))["sync"]
    assert stale.status == "degraded"  # a later *failed* run does not refresh it


@pytest.mark.integration
def test_samples_are_recorded_and_uptime_is_the_share_that_were_ok(db: Engine, clock: FixedClock) -> None:
    for status in ("ok", "ok", "ok", "down"):
        record(db, clock, [Check("database", status, "detail", 3)])
        clock.advance(60)
    result = uptime(db, clock, "database")
    assert (result["samples"], result["uptime_percent"]) == (4, 75.0)
    assert uptime(db, clock, "nothing")["uptime_percent"] is None  # no samples is unknown, not 0 and not 100


@pytest.mark.integration
def test_uptime_only_looks_at_the_window_asked_for(db: Engine, clock: FixedClock) -> None:
    record(db, clock, [Check("database", "down", "", 1)])
    clock.advance(25 * 3600)
    record(db, clock, [Check("database", "ok", "", 1)])
    assert uptime(db, clock, "database", hours=24)["uptime_percent"] == 100.0
    assert uptime(db, clock, "database", hours=48)["uptime_percent"] == 50.0


@pytest.mark.integration
def test_the_component_name_is_a_parameter_never_part_of_the_sql(db: Engine, clock: FixedClock) -> None:
    record(db, clock, [Check("database", "ok", "", 1)])
    hostile = "database' OR '1'='1"
    assert uptime(db, clock, hostile)["samples"] == 0
