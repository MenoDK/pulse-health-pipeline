"""Scoring in exact arithmetic.

No float appears between the counts and the score. A ratio is a `Fraction`; the comparison with a target is an
integer comparison; rounding is done once, at the end, half up, on the exact value. Two details that are easy to get
wrong are written down here because tests pin them:

* a numerator of **zero is a result** (0%), not "no data". Only a **denominator** of zero means there was nobody to
  measure.
* an indicator without data is left out of both sides of the score, and the report says how many were left out, so a
  score built on one indicator out of five cannot pass for a full one.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from fractions import Fraction


class Band(IntEnum):
    NO_DATA = 0
    POOR = 1
    FAIR = 2
    GOOD = 3
    EXCELLENT = 4


@dataclass(frozen=True)
class IndicatorDef:
    code: str
    name: str
    description: str
    weight: int
    target: Fraction  # illustrative values for this demonstration, not any programme's


@dataclass(frozen=True)
class IndicatorResult:
    code: str
    name: str
    description: str
    weight: int
    target: Fraction
    numerator: int
    denominator: int
    band: Band

    @property
    def ratio(self) -> Fraction | None:
        return None if self.denominator == 0 else Fraction(self.numerator, self.denominator)

    @property
    def points(self) -> int:
        return int(self.band) * self.weight

    @property
    def gap(self) -> Fraction | None:
        ratio = self.ratio
        return None if ratio is None else self.target - ratio


def band_for(numerator: int, denominator: int, target: Fraction) -> Band:
    """EXCELLENT at or above the target, GOOD from 90% of it, FAIR from 70% of it, POOR below that."""
    if numerator < 0 or denominator < 0 or numerator > denominator:
        raise ValueError("counts must satisfy 0 <= numerator <= denominator")
    if target <= 0 or target > 1:
        raise ValueError("a target is a ratio in (0, 1]")
    if denominator == 0:
        return Band.NO_DATA
    ratio = Fraction(numerator, denominator)
    if ratio >= target:
        return Band.EXCELLENT
    if ratio * 10 >= target * 9:
        return Band.GOOD
    if ratio * 10 >= target * 7:
        return Band.FAIR
    return Band.POOR


def evaluate(definition: IndicatorDef, numerator: int, denominator: int) -> IndicatorResult:
    return IndicatorResult(
        code=definition.code,
        name=definition.name,
        description=definition.description,
        weight=definition.weight,
        target=definition.target,
        numerator=numerator,
        denominator=denominator,
        band=band_for(numerator, denominator, definition.target),
    )


def overall(results: list[IndicatorResult]) -> Fraction | None:
    """0 to 10, or None when no indicator had data. Weighted, over the indicators that had data only."""
    scored = [r for r in results if r.band != Band.NO_DATA]
    if not scored:
        return None
    return Fraction(10 * sum(r.points for r in scored), 4 * sum(r.weight for r in scored))


def grade(score: Fraction | None) -> str | None:
    if score is None:
        return None
    if score >= 8:
        return "excellent"
    if score >= Fraction(13, 2):
        return "good"
    if score >= 5:
        return "fair"
    return "poor"


def round_half_up(value: Fraction, places: int = 2) -> str:
    """Exact decimal text of a Fraction, rounded half up (not half to even, and not through a float)."""
    scale = 10**places
    negative = value < 0
    magnitude = -value if negative else value
    scaled = (2 * magnitude.numerator * scale + magnitude.denominator) // (2 * magnitude.denominator)
    whole, fraction = divmod(scaled, scale)
    text = f"{whole}.{fraction:0{places}d}" if places else str(whole)
    return f"-{text}" if negative and scaled else text


def percent(ratio: Fraction | None) -> str | None:
    return None if ratio is None else round_half_up(ratio * 100, 1)
