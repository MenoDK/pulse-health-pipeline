"""The indicator report: counts from one snapshot, scored exactly."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from fractions import Fraction
from typing import Any

from sqlalchemy import Engine

from pulse.indicators.queries import INDICATORS, counts
from pulse.indicators.scoring import Band, IndicatorResult, evaluate, grade, overall, percent, round_half_up

STATUS = {
    Band.EXCELLENT: "on-target",
    Band.GOOD: "near-target",
    Band.FAIR: "at-risk",
    Band.POOR: "critical",
    Band.NO_DATA: "no-data",
}


@dataclass(frozen=True)
class Report:
    as_of: date
    results: tuple[IndicatorResult, ...]

    @property
    def score(self) -> Fraction | None:
        return overall(list(self.results))

    @property
    def excluded(self) -> list[str]:
        return [r.code for r in self.results if r.band == Band.NO_DATA]

    def to_dict(self) -> dict[str, Any]:
        score = self.score
        return {
            "as_of": self.as_of.isoformat(),
            "score": None if score is None else round_half_up(score, 2),
            "grade": grade(score),
            "indicators_with_data": len(self.results) - len(self.excluded),
            "indicators_total": len(self.results),
            "excluded": self.excluded,
            "indicators": [
                {
                    "code": r.code,
                    "name": r.name,
                    "description": r.description,
                    "weight": r.weight,
                    "numerator": r.numerator,
                    "denominator": r.denominator,
                    "percent": percent(r.ratio),
                    "target_percent": percent(r.target),
                    "gap_points": None if r.gap is None else round_half_up(r.gap * 100, 1),
                    "band": r.band.name.lower().replace("_", "-"),
                    "status": STATUS[r.band],
                    "points": r.points,
                }
                for r in self.results
            ],
        }


def build_report(engine: Engine, as_of: date) -> Report:
    """All five counts come from one REPEATABLE READ snapshot, so a sync that commits meanwhile cannot skew them."""
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn, conn.begin():
        found = counts(conn, as_of)
    return Report(as_of, tuple(evaluate(d, *found[d.code]) for d in INDICATORS))
