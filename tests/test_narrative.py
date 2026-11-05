"""The narration check: a text may say anything about the numbers except a different number."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from pulse.indicators.lab_narrators import NARRATORS
from pulse.indicators.narrative import MAX_LENGTH, TemplateNarrator, allowed_numbers, check, narrate, numbers_in
from pulse.indicators.queries import INDICATORS
from pulse.indicators.report import Report
from pulse.indicators.scoring import evaluate

COUNTS = [(63, 100), (5, 10), (0, 0), (30, 50), (9, 10)]


@pytest.fixture
def report() -> dict[str, Any]:
    return dated(date(2026, 6, 30))


def test_the_template_passes_its_own_check_for_every_shape_of_report(report: dict[str, Any]) -> None:
    assert check(TemplateNarrator().narrate(report), report) == []
    empty = {
        **report,
        "score": None,
        "grade": None,
        "indicators_with_data": 0,
        "indicators": [
            {**i, "percent": None, "target_percent": i["target_percent"], "gap_points": None, "status": "no-data"}
            for i in report["indicators"]
        ],
    }
    assert check(TemplateNarrator().narrate(empty), empty) == []


def test_an_invented_number_is_caught_and_the_template_text_is_used(report: dict[str, Any]) -> None:
    result = narrate(report, NARRATORS["invents"])
    assert not result.accepted
    assert result.source == "template"
    assert any("12.5" in v for v in result.violations)
    assert "12.5" not in result.text


def test_a_rounded_figure_is_caught_even_when_the_rounded_value_is_a_count(report: dict[str, Any]) -> None:
    # In this report 63.0% is 63 of 100, so "63" is a perfectly good count. As a percentage it is wrong.
    assert any(i["numerator"] == 63 for i in report["indicators"])
    result = narrate(report, NARRATORS["rounds"])
    assert not result.accepted
    assert result.violations == ("the percentage 63% is not in the report",)


def test_a_pseudonym_shaped_token_is_caught(report: dict[str, Any]) -> None:
    result = narrate(report, NARRATORS["leaks"])
    assert not result.accepted
    assert any("pseudonym" in v for v in result.violations)


def test_a_narrator_that_raises_is_replaced_not_propagated(report: dict[str, Any]) -> None:
    class Broken:
        def narrate(self, report: dict[str, Any]) -> str:
            raise RuntimeError("model unavailable")

    result = narrate(report, Broken())
    assert not result.accepted
    assert result.violations == ("the narrator failed: RuntimeError",)
    assert result.text == TemplateNarrator().narrate(report)


@pytest.mark.parametrize("text", ["", "   ", "x" * (MAX_LENGTH + 1)])
def test_empty_and_oversized_texts_are_refused(report: dict[str, Any], text: str) -> None:
    assert check(text, report)


def test_every_number_in_the_report_may_be_used_in_its_own_role(report: dict[str, Any]) -> None:
    allowed = allowed_numbers(report)
    for item in report["indicators"]:
        assert str(item["numerator"]) in allowed.plain
        assert str(item["denominator"]) in allowed.plain
        if item["percent"] is not None:
            assert item["percent"] in allowed.percent
    assert report["score"] in allowed.plain


def dated(day: date) -> dict[str, Any]:
    return Report(day, tuple(evaluate(d, n, den) for d, (n, den) in zip(INDICATORS, COUNTS, strict=True))).to_dict()


def test_a_date_may_be_written_with_or_without_its_leading_zeros(report: dict[str, Any]) -> None:
    march_7th = dated(date(2026, 3, 7))
    elsewhere = allowed_numbers({**march_7th, "as_of": "2026-12-31"}).plain
    assert not {"3", "7"} & elsewhere  # so only the date can be what allows them here
    assert check("Figures as of day 7, month 3, year 2026.", march_7th) == []
    assert check("Figures as of day 07, month 03, year 2026.", march_7th) == []
    assert check("Figures as of day 8.", march_7th) == ["the number 8 is not in the report"]


def test_a_shortfall_may_be_quoted_without_its_minus_sign(report: dict[str, Any]) -> None:
    gaps = [i["gap_points"] for i in report["indicators"] if str(i["gap_points"]).startswith("-")]
    assert gaps == ["-35.0"], "the fixture has to contain a shortfall for this test to mean anything"
    assert check("It fell 35.0 percent short.", report) == []
    assert check("It fell 35.0% short.", report) == []
    assert check("It fell 35 percent short.", report) == ["the percentage 35% is not in the report"]


def test_thousands_separators_and_decimal_commas_are_read_as_numbers() -> None:
    assert numbers_in("1,234 people and 63,4% and 2026-06-30") == ["1234", "63.4", "2026", "06", "30"]


def test_a_number_that_is_not_in_the_report_is_named_in_the_violation(report: dict[str, Any]) -> None:
    assert check("Exactly 7777 people were seen.", report) == ["the number 7777 is not in the report"]


def test_a_number_is_compared_whole_not_by_its_digits(report: dict[str, Any]) -> None:
    # 63.0% is in the report. 63% and 6.3% are not: a text may not round a figure or take a piece of it.
    assert "63.0" in allowed_numbers(report).percent
    assert check("It reached 63.0 percent.", report) == []
    assert check("It reached 63.0%.", report) == []
    assert check("It reached 63 percent.", report) == ["the percentage 63% is not in the report"]
    assert check("It reached 6.3 percent.", report) == ["the percentage 6.3% is not in the report"]
    assert check("It reached 63.0 points.", report) == [
        "the number 63.0 is not in the report"
    ]  # a percentage is not a count
