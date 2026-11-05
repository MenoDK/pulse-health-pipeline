"""The registry client: what it asks, how it retries, and what it will not repeat in an error."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from pulse.records import Page
from pulse.registry import HttpRegistryClient, RegistryError

PLANTED = "Maria Silva 123.456.789-09"
STAMP = datetime(2026, 6, 1, 10, 30, tzinfo=UTC)


class Registry:
    def __init__(self, *answers: httpx.Response | Exception) -> None:
        self.answers = list(answers)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return answer


def client(registry: Registry, delays: list[float] | None = None, retries: int = 2) -> HttpRegistryClient:
    sink = delays if delays is not None else []
    return HttpRegistryClient(
        "https://registry.test", retries=retries, transport=httpx.MockTransport(registry), sleep=sink.append
    )


PAGE = httpx.Response(200, json={"items": [{"id": "reg-t-01", "updated_at": STAMP.isoformat()}], "has_more": True})


def test_the_first_request_has_only_a_limit_and_the_next_carries_the_position() -> None:
    registry = Registry(PAGE)
    c = client(registry)
    page = c.fetch("teams", None, None, 50)
    assert page == Page(items=[{"id": "reg-t-01", "updated_at": STAMP.isoformat()}], has_more=True)
    assert dict(registry.requests[0].url.params) == {"limit": "50"}

    c.fetch("encounters", STAMP, "reg-e-0000007", 200)
    params = registry.requests[1].url.params
    assert registry.requests[1].url.path == "/v1/encounters"
    assert params["after_updated_at"] == STAMP.isoformat()  # the '+' of the offset survived the query string
    assert params["after_id"] == "reg-e-0000007"


def test_an_id_without_a_timestamp_is_not_sent_on_its_own() -> None:
    registry = Registry(PAGE)
    client(registry).fetch("teams", None, "reg-t-01", 10)
    assert "after_id" not in registry.requests[0].url.params


def test_a_busy_registry_is_retried_with_a_growing_pause_and_then_answers() -> None:
    registry = Registry(httpx.Response(503), httpx.Response(502), PAGE)
    delays: list[float] = []
    assert client(registry, delays).fetch("teams", None, None, 10).has_more is True
    assert len(registry.requests) == 3
    assert delays == [0.2, 0.4]


def test_a_registry_that_stays_down_ends_in_an_error_after_the_configured_tries_and_no_pause_after_the_last() -> None:
    registry = Registry(httpx.Response(503))
    delays: list[float] = []
    with pytest.raises(RegistryError, match="after 3 tries: HTTP 503"):
        client(registry, delays).fetch("teams", None, None, 10)
    assert len(registry.requests) == 3
    assert delays == [0.2, 0.4]


@pytest.mark.parametrize("status", [400, 401, 404, 422])
def test_a_refusal_is_not_retried_because_asking_again_cannot_help(status: int) -> None:
    registry = Registry(httpx.Response(status))
    delays: list[float] = []
    with pytest.raises(RegistryError, match=f"refused the request with {status}"):
        client(registry, delays).fetch("people", None, None, 10)
    assert len(registry.requests) == 1 and delays == []


def test_a_dropped_connection_is_retried_and_named_when_it_gives_up() -> None:
    registry = Registry(httpx.ConnectError("no route"))
    with pytest.raises(RegistryError, match="ConnectError"):
        client(registry).fetch("teams", None, None, 10)
    assert len(registry.requests) == 3


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(f"<html>{PLANTED}</html>".encode(), id="not-json"),
        pytest.param(b'{"items": "' + PLANTED.encode() + b'", "has_more": false}', id="items-not-a-list"),
        pytest.param(b'{"items": ["' + PLANTED.encode() + b'"], "has_more": false}', id="item-not-an-object"),
        pytest.param(b'{"items": [], "has_more": "' + PLANTED.encode() + b'"}', id="flag-not-a-boolean"),
    ],
)
def test_a_page_that_is_not_a_page_is_an_error_that_does_not_repeat_what_it_was_sent(body: bytes) -> None:
    registry = Registry(httpx.Response(200, content=body, headers={"content-type": "application/json"}))
    with pytest.raises(RegistryError) as raised:
        client(registry).fetch("people", None, None, 10)
    assert str(raised.value) == "the registry answered something that is not a page"
    assert PLANTED not in str(raised.value)
    assert raised.value.__cause__ is None


def test_the_empty_last_page_is_a_valid_page() -> None:
    page = client(Registry(httpx.Response(200, json={"items": [], "has_more": False}))).fetch("teams", None, None, 10)
    assert page.items == [] and page.has_more is False
