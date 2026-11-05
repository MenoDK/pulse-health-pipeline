"""The registry stand-in: the day its data is "up to date" to, and how that day is chosen when it starts."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from pulse.standin.registry_app import app_factory, create_registry_app

DEFAULT_DAY = date(2026, 6, 30)


def stamps(app: FastAPI) -> list[datetime]:
    async def fetch() -> dict[str, Any]:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://registry") as client:
            response = await client.get("/v1/encounters", params={"limit": 5000})
            response.raise_for_status()
            return dict(response.json())

    page = asyncio.run(fetch())
    assert page["has_more"] is False and page["items"]
    return [datetime.fromisoformat(item["updated_at"]) for item in page["items"]]


def midnight(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def test_without_a_day_the_data_is_up_to_date_to_a_fixed_one_so_tests_and_recordings_never_drift() -> None:
    found = stamps(create_registry_app(subjects=30))
    assert midnight(DEFAULT_DAY) - timedelta(days=30) <= max(found) <= midnight(DEFAULT_DAY)


def test_the_day_it_is_asked_for_is_the_day_the_data_is_up_to_date_to() -> None:
    day = date(2027, 2, 1)
    found = stamps(create_registry_app(subjects=30, as_of=day))
    assert max(found) <= midnight(day)  # nothing from after that day
    assert max(found) >= midnight(day) - timedelta(days=30)  # and the data is recent for it, not for the default day
    assert min(found) >= midnight(day) - timedelta(days=201)


def test_the_start_up_reads_the_day_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STANDIN_SUBJECTS", "30")
    monkeypatch.setenv("STANDIN_AS_OF", "2027-02-01")
    found = stamps(app_factory())
    assert midnight(date(2027, 2, 1)) - timedelta(days=30) <= max(found) <= midnight(date(2027, 2, 1))


@pytest.mark.parametrize("empty", ["", "  "])
def test_an_empty_setting_means_the_fixed_day(monkeypatch: pytest.MonkeyPatch, empty: str) -> None:
    monkeypatch.setenv("STANDIN_SUBJECTS", "30")
    monkeypatch.setenv("STANDIN_AS_OF", empty)  # docker compose passes an unset variable as an empty one
    assert max(stamps(app_factory())) <= midnight(DEFAULT_DAY)


def test_a_day_that_is_not_a_date_stops_the_start_up_instead_of_being_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STANDIN_AS_OF", "yesterday")
    with pytest.raises(ValueError, match="Invalid isoformat"):
        app_factory()
