"""Retry delays: bounded, growing, spread, and reproducible."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pulse.exchange.backoff import backoff_seconds


def test_the_first_failures_wait_roughly_the_base_then_double() -> None:
    delays = [backoff_seconds(n, "msg", base=30, cap=21_600) for n in range(1, 6)]
    for attempt, delay in enumerate(delays, start=1):
        raw = 30 * 2 ** (attempt - 1)
        assert raw // 2 <= delay <= raw


def test_the_delay_never_passes_the_cap_however_many_attempts() -> None:
    assert all(backoff_seconds(n, "msg", base=30, cap=600) <= 600 for n in (1, 5, 20, 100, 10_000))


def test_the_same_message_and_attempt_always_wait_the_same() -> None:
    assert backoff_seconds(4, "encounter:reg-e-1:v1", base=30, cap=3600) == backoff_seconds(
        4, "encounter:reg-e-1:v1", base=30, cap=3600
    )


def test_messages_that_failed_together_do_not_retry_together() -> None:
    delays = {backoff_seconds(3, f"encounter:reg-e-{n}:v1", base=30, cap=3600) for n in range(200)}
    assert len(delays) > 20  # spread over [60, 120], not one shared instant


@pytest.mark.parametrize(("attempt", "base", "cap"), [(0, 30, 600), (-1, 30, 600), (1, 0, 600), (1, 30, 0)])
def test_nonsense_arguments_are_refused(attempt: int, base: int, cap: int) -> None:
    with pytest.raises(ValueError, match=r"attempt|positive"):
        backoff_seconds(attempt, "msg", base=base, cap=cap)


@given(st.integers(1, 5000), st.text(max_size=40), st.integers(1, 600), st.integers(1, 100_000))
def test_the_delay_is_always_a_positive_whole_number_within_the_cap(
    attempt: int, key: str, base: int, cap: int
) -> None:
    delay = backoff_seconds(attempt, key, base=base, cap=cap)
    assert 1 <= delay <= cap


def test_a_one_second_delay_cannot_spread_down_to_an_immediate_retry() -> None:
    # raw = 1 spreads over [0, 1]; some keys land on 0. Found by the property above, kept as a plain case.
    assert all(backoff_seconds(1, f"key-{n}", base=1, cap=1) == 1 for n in range(200))


@given(st.integers(1, 20), st.text(max_size=20), st.integers(1, 120))
def test_the_floor_of_each_attempt_is_the_raw_delay_of_the_one_before(attempt: int, key: str, base: int) -> None:
    # The cap is far above 120 * 2**21, so only the doubling is in play.
    earlier_raw = base * 2 ** (attempt - 1)
    assert backoff_seconds(attempt + 1, key, base=base, cap=10**9) >= earlier_raw
