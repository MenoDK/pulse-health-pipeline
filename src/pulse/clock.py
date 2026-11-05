"""Time as an argument.

Everything that waits (a retry backoff, a lease, a token margin, "no contact in 12 months") reads the clock it is given,
so a test, or the lab, can move time instead of sleeping. The offset clock is what the lab uses: it adds a number of
seconds that lives in the database, so every process sees the same "now".
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class OffsetClock:
    """The system clock plus an offset read on every call (so a change made by another process is seen at once)."""

    def __init__(self, read_offset_seconds: Callable[[], int]) -> None:
        self._read = read_offset_seconds

    def now(self) -> datetime:
        return datetime.now(UTC) + timedelta(seconds=self._read())


class FixedClock:
    """A clock that only moves when told to. For tests."""

    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None:
            raise ValueError("a clock needs an aware datetime")
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> datetime:
        self._now += timedelta(seconds=seconds)
        return self._now
