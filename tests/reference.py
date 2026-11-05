"""The indicator counts, recomputed in plain Python from rows.

Written from the definitions in the README, not from the SQL, and sharing nothing with `pulse.indicators.queries`
except the indicator codes. A test compares the two over random data; where they disagree, one of them is wrong.
"""

from __future__ import annotations

import calendar
from collections.abc import Iterable, Mapping
from datetime import date
from typing import Any

Row = Mapping[str, Any]


def months_between(earlier: date, later: date) -> int:
    return (later.year * 12 + later.month) - (earlier.year * 12 + earlier.month)


def minus_months(day: date, months: int) -> date:
    """`day` minus whole calendar months, the day clamped to the end of a shorter month (31 March - 1 month = 28 February)."""
    index = day.year * 12 + (day.month - 1) - months
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def reference_counts(subjects: Iterable[Row], encounters: Iterable[Row], as_of: date) -> dict[str, tuple[int, int]]:
    people = [
        (s, months_between(s["birth_month"], as_of)) for s in subjects if not s["deleted"] and s["birth_month"] <= as_of
    ]
    seen: dict[str, list[Row]] = {}
    for e in encounters:
        if not e["deleted"] and e["occurred_on"] <= as_of:
            seen.setdefault(e["subject_key"], []).append(e)

    def within(person: Row, kind: str, months: int) -> int:
        floor = minus_months(as_of, months)
        return sum(1 for e in seen.get(person["subject_key"], []) if e["kind"] == kind and e["occurred_on"] > floor)

    def pair(group: list[tuple[Row, int]], met: Any) -> tuple[int, int]:
        return sum(1 for p, _ in group if met(p)), len(group)

    chronic = [(p, a) for p, a in people if p["chronic"]]
    children = [(p, a) for p, a in people if a < 24]
    adults = [(p, a) for p, a in people if 300 <= a < 780]
    elders = [(p, a) for p, a in people if a >= 780]
    return {
        "chronic-follow-up": pair(chronic, lambda p: within(p, "consultation", 12) >= 1),
        "child-checkups": pair(children, lambda p: within(p, "checkup", 24) >= 3),
        "adult-screening": pair(adults, lambda p: within(p, "screening", 36) >= 1),
        "registry-fresh": pair(people, lambda p: p["registry_refreshed_on"] > minus_months(as_of, 24)),
        "elder-home-visits": pair(elders, lambda p: within(p, "home-visit", 12) >= 1),
    }
