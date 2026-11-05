"""A narrator may say anything about the numbers except a different number.

The report is computed first, in code. A narrator (a template, or a language model behind the same interface) turns it
into prose. `narrate` then checks the prose against the report before anyone reads it:

* every number in the text must be one the report contains, written the way the report writes it, and in the same role:
  a figure followed by a percent sign must be one of the report's percentages, a bare figure one of its counts, weights,
  dates or its score (so "63%" cannot pass just because 63 happens to be a count);
* no token shaped like a stored pseudonym may appear.

Text that fails is replaced by the template's own text, and the response says so and why. The check is on digits: a
number spelled out in words ("seventy percent") is not detected, and the README lists that as a limit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

_NUMBER = re.compile(r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:[.,]\d+)?)(?P<pct>\s?(?:%|percent\b))?")
_THOUSANDS = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?")
SCALE_MAX = "10"  # the score is "out of 10": a constant of the scale, not a result
_PSEUDONYM = re.compile(r"\bp[a-z0-9]{1,16}\.[a-z2-7]{20,}\b", re.IGNORECASE)
MAX_LENGTH = 1500


class Narrator(Protocol):
    def narrate(self, report: dict[str, Any]) -> str: ...


def typed_numbers(text: str) -> list[tuple[str, bool]]:
    """(number, is_percentage) for each number written in a text.

    Normalised: thousands separators removed, a decimal comma read as a point.
    """
    found = []
    for match in _NUMBER.finditer(text):
        raw = match.group("num")
        value = raw.replace(",", "") if _THOUSANDS.fullmatch(raw) else raw.replace(",", ".")
        found.append((value, match.group("pct") is not None))
    return found


def numbers_in(text: str) -> list[str]:
    return [value for value, _ in typed_numbers(text)]


@dataclass(frozen=True)
class Allowed:
    plain: frozenset[str]  # counts, weights, points, the score, the date, the scale
    percent: frozenset[str]  # the report's percentages, targets and gaps


def allowed_numbers(report: dict[str, Any]) -> Allowed:
    plain: set[str] = {str(report["indicators_with_data"]), str(report["indicators_total"]), SCALE_MAX}
    for part in str(report["as_of"]).split("-"):
        plain.update({part, part.lstrip("0") or "0"})
    if report.get("score") is not None:
        plain.add(str(report["score"]))
    percent: set[str] = set()
    for item in report["indicators"]:
        for key in ("numerator", "denominator", "weight", "points"):
            plain.add(str(item[key]))
        for key in ("percent", "target_percent", "gap_points"):
            if item.get(key) is not None:
                percent.add(str(item[key]).lstrip("-"))
    return Allowed(frozenset(plain), frozenset(percent))


class TemplateNarrator:
    """The default and the fallback: deterministic, and it only repeats what the report says."""

    def narrate(self, report: dict[str, Any]) -> str:
        if report["score"] is None:
            return f"As of {report['as_of']} no indicator has data, so there is no score."
        lines = [
            f"As of {report['as_of']} the overall score is {report['score']} out of 10 ({report['grade']}), "
            f"from {report['indicators_with_data']} of {report['indicators_total']} indicators with data."
        ]
        for item in report["indicators"]:
            if item["percent"] is None:
                lines.append(f"{item['name']}: nobody to measure.")
            else:
                lines.append(
                    f"{item['name']}: {item['percent']}% against a target of {item['target_percent']}% "
                    f"({item['numerator']} of {item['denominator']}), {item['status'].replace('-', ' ')}."
                )
        weakest = [i for i in report["indicators"] if i["status"] == "critical"]
        if weakest:
            lines.append("Needs attention first: " + ", ".join(i["name"] for i in weakest) + ".")
        return " ".join(lines)


@dataclass(frozen=True)
class Narration:
    text: str
    accepted: bool
    violations: tuple[str, ...]
    source: str  # "narrator" when its text passed, "template" when it was replaced


def check(text: str, report: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    allowed = allowed_numbers(report)
    for number, is_percent in dict.fromkeys(typed_numbers(text)):
        if is_percent and number not in allowed.percent:
            problems.append(f"the percentage {number}% is not in the report")
        elif not is_percent and number not in allowed.plain:
            problems.append(f"the number {number} is not in the report")
    if _PSEUDONYM.search(text):
        problems.append("the text contains a token shaped like a stored pseudonym")
    if len(text) > MAX_LENGTH:
        problems.append(f"the text is longer than {MAX_LENGTH} characters")
    if not text.strip():
        problems.append("the text is empty")
    return problems


def narrate(report: dict[str, Any], narrator: Narrator) -> Narration:
    try:
        text = narrator.narrate(report)
    except Exception as exc:
        text, problems = "", [f"the narrator failed: {type(exc).__name__}"]
    else:
        problems = check(text, report)
    if not problems:
        return Narration(text, True, (), "narrator")
    return Narration(TemplateNarrator().narrate(report), False, tuple(problems), "template")
