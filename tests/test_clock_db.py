"""Time as an argument, and the small database helpers the lab is built on."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine

from pulse.clock import FixedClock, OffsetClock, SystemClock
from pulse.config import Settings
from pulse.db import LAB_CLOCK_KEY, iso, lab_get, lab_set, make_clock, make_engine


def test_the_system_clock_is_aware_and_in_utc() -> None:
    now = SystemClock().now()
    assert now.tzinfo is not None and now.utcoffset() == timedelta(0)
    assert abs((datetime.now(UTC) - now).total_seconds()) < 5


def test_a_fixed_clock_only_moves_when_told_and_refuses_a_time_without_a_zone() -> None:
    start = datetime(2026, 7, 1, 9, 0, tzinfo=UTC)
    clock = FixedClock(start)
    assert clock.now() == clock.now() == start
    assert clock.advance(90.5) == start + timedelta(seconds=90.5)
    with pytest.raises(ValueError, match="aware"):
        FixedClock(datetime(2026, 7, 1, 9, 0))


def test_an_offset_clock_reads_its_offset_on_every_call_so_a_change_made_elsewhere_is_seen_at_once() -> None:
    offset = {"seconds": 0}
    clock = OffsetClock(lambda: offset["seconds"])
    assert abs((clock.now() - datetime.now(UTC)).total_seconds()) < 5
    offset["seconds"] = 86_400
    assert 86_390 < (clock.now() - datetime.now(UTC)).total_seconds() < 86_410


def test_outside_the_lab_there_is_no_offset_clock_at_all() -> None:
    settings = Settings(_env_file=None, lab_mode=False)  # type: ignore[call-arg]
    assert isinstance(make_clock(settings, None), SystemClock)  # type: ignore[arg-type]


def test_the_engine_keeps_a_small_pool_and_checks_a_connection_before_using_it() -> None:
    engine = make_engine(Settings(_env_file=None), pool_size=3)  # type: ignore[call-arg]
    assert engine.pool.size() == 3 and engine.pool._pre_ping is True
    engine.dispose()


def test_iso_formats_a_moment_and_passes_none_through() -> None:
    assert iso(datetime(2026, 7, 1, 9, 0, tzinfo=UTC)) == "2026-07-01T09:00:00+00:00"
    assert iso(None) is None


@pytest.mark.integration
def test_lab_state_stores_json_values_and_overwrites_in_place(db: Engine) -> None:
    with db.begin() as conn:
        assert lab_get(conn, "missing", "fallback") == "fallback"
        for value in (7, True, "text", {"a": [1, 2]}, [1, "x"], None):
            lab_set(conn, "k", value)
            assert lab_get(conn, "k", "fallback") == value
        lab_set(conn, "k", 1)
        lab_set(conn, "k", 2)
    with db.connect() as conn:
        assert lab_get(conn, "k", None) == 2


@pytest.mark.integration
def test_in_the_lab_the_clock_follows_the_offset_kept_in_the_database(db: Engine) -> None:
    settings = Settings(_env_file=None, lab_mode=True)  # type: ignore[call-arg]
    clock = make_clock(settings, db)
    assert isinstance(clock, OffsetClock)
    base = clock.now()
    with db.begin() as conn:
        lab_set(conn, LAB_CLOCK_KEY, 7200)
    assert 7190 < (clock.now() - base).total_seconds() < 7210
