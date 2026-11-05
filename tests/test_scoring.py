"""Scoring: boundaries exactly on the line, zero versus no data, and properties over random inputs."""

from __future__ import annotations

from fractions import Fraction

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pulse.indicators.queries import INDICATORS
from pulse.indicators.scoring import (
    Band,
    IndicatorDef,
    band_for,
    evaluate,
    grade,
    overall,
    percent,
    round_half_up,
)

TARGET = Fraction(7, 10)


def test_exactly_on_the_target_is_excellent_and_one_short_is_not() -> None:
    assert band_for(7, 10, TARGET) == Band.EXCELLENT
    assert band_for(69, 100, TARGET) == Band.GOOD


def test_the_ninety_and_seventy_percent_lines_are_exact() -> None:
    # 90% of 70% is 63%; 70% of 70% is 49%.
    assert band_for(63, 100, TARGET) == Band.GOOD
    assert band_for(62, 100, TARGET) == Band.FAIR
    assert band_for(49, 100, TARGET) == Band.FAIR
    assert band_for(48, 100, TARGET) == Band.POOR


def test_zero_of_something_is_a_result_and_zero_of_nothing_is_no_data() -> None:
    assert band_for(0, 40, TARGET) == Band.POOR
    assert band_for(0, 0, TARGET) == Band.NO_DATA


@pytest.mark.parametrize(("n", "d"), [(-1, 5), (6, 5), (1, -1)])
def test_impossible_counts_are_refused(n: int, d: int) -> None:
    with pytest.raises(ValueError, match="counts"):
        band_for(n, d, TARGET)


@pytest.mark.parametrize("target", [Fraction(0), Fraction(-1, 2), Fraction(3, 2)])
def test_a_target_must_be_a_ratio(target: Fraction) -> None:
    with pytest.raises(ValueError, match="target"):
        band_for(1, 2, target)


def test_an_indicator_without_data_is_left_out_of_both_sides_of_the_score() -> None:
    a = evaluate(INDICATORS[0], 70, 100)  # excellent, weight 2
    b = evaluate(INDICATORS[1], 0, 0)  # no data
    assert overall([a, b]) == overall([a]) == Fraction(10)


def test_with_no_data_at_all_there_is_no_score_instead_of_zero() -> None:
    assert overall([evaluate(d, 0, 0) for d in INDICATORS]) is None
    assert grade(None) is None


def test_the_weighted_score_is_exact() -> None:
    results = [evaluate(INDICATORS[0], 70, 100), evaluate(INDICATORS[1], 0, 10)]  # 4x2 and 1x2 points of 16
    assert overall(results) == Fraction(10 * (8 + 2), 4 * 4)


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (Fraction(8), "excellent"),
        (Fraction(79, 10), "good"),
        (Fraction(13, 2), "good"),
        (Fraction(129, 20), "fair"),
        (Fraction(5), "fair"),
        (Fraction(49, 10), "poor"),
    ],
)
def test_grade_boundaries(score: Fraction, expected: str) -> None:
    assert grade(score) == expected


@pytest.mark.parametrize(
    ("value", "places", "text"),
    [
        (Fraction(1, 8), 2, "0.13"),
        (Fraction(5, 2), 0, "3"),
        (Fraction(1, 3), 2, "0.33"),
        (Fraction(2, 3), 1, "0.7"),
        (Fraction(999, 1000), 2, "1.00"),
        (Fraction(0), 2, "0.00"),
        (Fraction(-1, 8), 2, "-0.13"),
        (Fraction(-1, 200), 2, "-0.01"),  # half up on the size: -0.005 is -0.01
        (Fraction(-1, 1000), 2, "0.00"),  # rounds to nothing, so it has no sign: "-0.00" would read as a shortfall
        (Fraction(-4, 100), 1, "0.0"),
    ],
)
def test_rounding_is_half_up_on_the_exact_value(value: Fraction, places: int, text: str) -> None:
    assert round_half_up(value, places) == text


def test_half_up_is_not_half_to_even_and_not_a_float() -> None:
    # 0.125 is exact in binary and Python's round() would say 0.12; 2.675 is not, and round() says 2.67.
    assert round_half_up(Fraction(125, 1000), 2) == "0.13"
    assert round_half_up(Fraction(2675, 1000), 2) == "2.68"


def test_percent_has_one_decimal_and_none_without_a_ratio() -> None:
    assert percent(Fraction(2, 3)) == "66.7"
    assert percent(None) is None


# ---- properties ------------------------------------------------------------------------------------------------


counts = st.integers(min_value=0, max_value=5000).flatmap(lambda d: st.tuples(st.integers(0, d), st.just(d)))
targets = st.fractions(min_value=Fraction(1, 100), max_value=1)


@given(counts, targets, st.integers(min_value=1, max_value=7))
def test_scaling_both_counts_never_changes_the_band(pair: tuple[int, int], target: Fraction, k: int) -> None:
    n, d = pair
    assert band_for(n, d, target) == band_for(n * k, d * k, target)


@given(counts, targets)
def test_more_numerator_never_lowers_the_band(pair: tuple[int, int], target: Fraction) -> None:
    n, d = pair
    if d and n < d:
        assert band_for(n + 1, d, target) >= band_for(n, d, target)


@given(st.lists(st.tuples(st.integers(0, 3), st.integers(1, 5)), min_size=1, max_size=8))
def test_the_overall_score_is_always_between_zero_and_ten(pairs: list[tuple[int, int]]) -> None:
    defs = [IndicatorDef(f"i{i}", "n", "d", w, Fraction(1, 2)) for i, (_, w) in enumerate(pairs)]
    results = [evaluate(d, band, 3) for d, (band, _) in zip(defs, pairs, strict=True)]
    score = overall(results)
    assert score is not None
    assert 0 <= score <= 10
