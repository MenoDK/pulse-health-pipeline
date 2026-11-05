"""The connector: one token however many threads, what each response means for the message, and a client that survives
nonsense. No network: the transport is replaced by a function."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import timedelta

import httpx
import pytest

from pulse.clock import FixedClock
from pulse.exchange.gateway import Delivery, GatewayClient, Token, TokenCache, TokenUnavailable, classify
from tests.conftest import START

# ------------------------------------------------------------------------------------------------ the token cache


def counting_fetch(clock: FixedClock, lifetime: int = 300, pause: float = 0.0) -> tuple[Callable[[], Token], list[int]]:
    calls: list[int] = []

    def fetch() -> Token:
        calls.append(1)
        if pause:
            time.sleep(pause)
        return Token(f"token-{len(calls)}", clock.now() + timedelta(seconds=lifetime))

    return fetch, calls


def test_thirty_two_threads_asking_at_once_cause_one_fetch() -> None:
    clock = FixedClock(START)
    fetch, calls = counting_fetch(clock, pause=0.05)
    cache = TokenCache(fetch, clock, margin_seconds=60)
    barrier = threading.Barrier(32)
    seen: list[str] = []

    def ask() -> None:
        barrier.wait()
        seen.append(cache.get())

    threads = [threading.Thread(target=ask) for _ in range(32)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert len(calls) == 1
    assert set(seen) == {"token-1"} and len(seen) == 32


def test_the_token_is_refreshed_inside_the_margin_and_not_before() -> None:
    clock = FixedClock(START)
    fetch, calls = counting_fetch(clock, lifetime=300)
    cache = TokenCache(fetch, clock, margin_seconds=60)
    assert cache.get() == "token-1"
    clock.advance(239)
    assert cache.get() == "token-1"  # 61 s of life left
    clock.advance(1)
    assert cache.get() == "token-2"  # 60 s left: inside the margin
    assert len(calls) == 2


def test_invalidating_a_token_that_is_no_longer_the_cached_one_does_nothing() -> None:
    clock = FixedClock(START)
    fetch, calls = counting_fetch(clock)
    cache = TokenCache(fetch, clock, margin_seconds=60)
    old = cache.get()
    cache.invalidate(old)
    fresh = cache.get()
    assert fresh != old
    # A slow thread that still holds the old token reports it as rejected. The fresh token must survive that.
    cache.invalidate(old)
    assert cache.get() == fresh
    assert len(calls) == 2


def test_a_failed_fetch_is_not_cached_and_the_next_call_tries_again() -> None:
    clock = FixedClock(START)
    attempts = {"n": 0}

    def flaky() -> Token:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise TokenUnavailable("down")
        return Token("ok", clock.now() + timedelta(seconds=300))

    cache = TokenCache(flaky, clock, margin_seconds=60)
    with pytest.raises(TokenUnavailable):
        cache.get()
    assert cache.get() == "ok"


# ------------------------------------------------------------------------------------------------ what a response means


def response(status: int, **kwargs: object) -> httpx.Response:
    return httpx.Response(status, **kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("status", "outcome"),
    [
        (200, "delivered"),
        (201, "delivered"),
        (202, "delivered"),
        (204, "delivered"),
        (400, "dead"),
        (413, "dead"),
        (422, "dead"),
        (401, "retry"),
        (403, "retry"),
        (404, "retry"),
        (405, "retry"),
        (408, "retry"),
        (425, "retry"),
        (429, "retry"),
        (500, "retry"),
        (502, "retry"),
        (503, "retry"),
        (504, "retry"),
        (301, "retry"),
        (302, "retry"),
        (308, "retry"),
        (410, "dead"),
        (415, "dead"),
        (418, "dead"),
    ],
)
def test_what_each_status_means_for_the_message(status: int, outcome: str) -> None:
    assert classify(response(status)).outcome == outcome


def test_a_409_is_a_duplicate_only_when_the_body_says_so() -> None:
    assert classify(response(409, json={"error": "duplicate"})).outcome == "duplicate"
    assert classify(response(409, json={"error": "stale version"})).outcome == "dead"
    assert classify(response(409, content=b"<html>conflict</html>")).outcome == "dead"
    assert classify(response(409, json=["duplicate"])).outcome == "dead"


@pytest.mark.parametrize(
    ("header", "seconds"),
    [
        ("120", 120),
        ("0", 0),
        ("86400", 86_400),
        ("86401", None),
        ("soon", None),
        ("-5", None),
        ("", None),
        ("Wed, 21 Oct 2026 07:28:00 GMT", None),
    ],
)
def test_retry_after_is_read_when_it_is_a_sane_number_of_seconds(header: str, seconds: int | None) -> None:
    assert classify(response(429, headers={"Retry-After": header})).retry_after == seconds


# ------------------------------------------------------------------------------------------------ the client


class Gateway:
    """A scripted gateway behind httpx's MockTransport. Thread-safe; records what it was asked."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.token_requests = 0
        self.report_requests: list[httpx.Request] = []
        self.valid: set[str] = set()
        self.refuse_every_token = False
        self.token_answer: Callable[[], httpx.Response] | None = None
        self.report_answer: Callable[[httpx.Request], httpx.Response] | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            with self.lock:
                self.token_requests += 1
                if self.token_answer is not None:
                    return self.token_answer()
                value = f"tok-{self.token_requests}"
                self.valid.add(value)
            return httpx.Response(200, json={"access_token": value, "expires_in": 300})
        with self.lock:
            self.report_requests.append(request)
            bearer = request.headers.get("authorization", "").removeprefix("Bearer ")
            if self.refuse_every_token or bearer not in self.valid:
                return httpx.Response(401, json={"error": "invalid_token"})
        if self.report_answer is not None:
            return self.report_answer(request)
        return httpx.Response(201, json={"status": "accepted"})


def client_for(gateway: Gateway, clock: FixedClock) -> GatewayClient:
    return GatewayClient(
        base_url="https://gateway.test",
        token_url="/oauth/token",
        client_id="id",
        client_secret="not-a-real-secret",
        clock=clock,
        transport=httpx.MockTransport(gateway),
    )


def test_a_report_carries_the_bearer_token_the_idempotency_key_and_the_payload() -> None:
    gateway, clock = Gateway(), FixedClock(START)
    delivery = client_for(gateway, clock).send("encounter:reg-e-1:v1", {"n": 1})
    assert delivery == Delivery("delivered", 201, "accepted")
    (request,) = gateway.report_requests
    assert request.headers["authorization"] == "Bearer tok-1"
    assert request.headers["idempotency-key"] == "encounter:reg-e-1:v1"
    assert request.content == b'{"n":1}'


def test_an_expired_token_is_replaced_once_and_the_report_goes_through() -> None:
    gateway, clock = Gateway(), FixedClock(START)
    client = client_for(gateway, clock)
    client.send("k1", {})
    gateway.valid.clear()  # the gateway forgot every token
    assert client.send("k2", {}).outcome == "delivered"
    assert gateway.token_requests == 2
    assert len(gateway.report_requests) == 3  # k1, k2 rejected, k2 again


def test_a_gateway_that_keeps_answering_401_is_asked_twice_not_forever() -> None:
    gateway, clock = Gateway(), FixedClock(START)
    gateway.refuse_every_token = True  # new tokens are issued and then refused anyway
    delivery = client_for(gateway, clock).send("k", {})
    assert (delivery.outcome, delivery.http_status) == ("retry", 401)
    assert len(gateway.report_requests) == 2  # the first try and exactly one retry with a fresh token


def test_sixteen_threads_sending_at_once_share_one_token() -> None:
    gateway, clock = Gateway(), FixedClock(START)
    client = client_for(gateway, clock)
    barrier = threading.Barrier(16)
    results: list[str] = []

    def go(n: int) -> None:
        barrier.wait()
        results.append(client.send(f"k{n}", {"n": n}).outcome)

    threads = [threading.Thread(target=go, args=(n,)) for n in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert results == ["delivered"] * 16
    assert gateway.token_requests == 1


def test_a_token_endpoint_that_refuses_makes_the_message_retry_without_sending_anything() -> None:
    gateway, clock = Gateway(), FixedClock(START)
    gateway.token_answer = lambda: httpx.Response(401, json={"error": "invalid_client"})
    delivery = client_for(gateway, clock).send("k", {})
    assert delivery.outcome == "retry"
    assert delivery.http_status is None
    assert "401" in delivery.detail
    assert gateway.report_requests == []


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param(lambda: httpx.Response(200, content=b"<html>Sign in to the guest network</html>"), id="html"),
        pytest.param(lambda: httpx.Response(200, json={}), id="empty-object"),
        pytest.param(lambda: httpx.Response(200, json=["tok"]), id="a-list"),
        pytest.param(lambda: httpx.Response(200, json={"access_token": ""}), id="empty-token"),
        pytest.param(lambda: httpx.Response(200, json={"access_token": 12345}), id="token-not-text"),
        pytest.param(
            lambda: httpx.Response(200, json={"access_token": "t", "expires_in": "soon"}), id="lifetime-not-a-number"
        ),
        pytest.param(lambda: httpx.Response(200, json={"access_token": "t", "expires_in": 0}), id="no-lifetime"),
    ],
)
def test_a_token_endpoint_that_answers_nonsense_is_unavailable_not_a_crash(
    answer: Callable[[], httpx.Response],
) -> None:
    gateway, clock = Gateway(), FixedClock(START)
    gateway.token_answer = answer
    delivery = client_for(gateway, clock).send("k", {})  # must return, not raise
    assert delivery.outcome == "retry" and delivery.http_status is None
    assert "not a token" in delivery.detail
    assert gateway.report_requests == []


def test_a_connection_failure_to_the_token_endpoint_is_a_retry_with_a_name() -> None:
    clock = FixedClock(START)

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    client = GatewayClient(
        base_url="https://gateway.test",
        token_url="/oauth/token",
        client_id="i",
        client_secret="s",
        clock=clock,
        transport=httpx.MockTransport(refuse),
    )
    delivery = client.send("k", {})
    assert (delivery.outcome, delivery.http_status) == ("retry", None)
    assert "unreachable" in delivery.detail and "ConnectError" in delivery.detail


def test_a_timeout_sending_a_report_is_a_retry_with_no_status() -> None:
    gateway, clock = Gateway(), FixedClock(START)

    def hang(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    gateway.report_answer = hang
    delivery = client_for(gateway, clock).send("k", {})
    assert delivery == Delivery("retry", None, "transport error: ReadTimeout")


def test_the_error_detail_never_contains_the_secret_or_the_token() -> None:
    gateway, clock = Gateway(), FixedClock(START)
    gateway.report_answer = lambda request: httpx.Response(500, text="internal error for tok-1 / not-a-real-secret")
    delivery = client_for(gateway, clock).send("k", {})
    assert "not-a-real-secret" not in repr(delivery) and "tok-1" not in repr(delivery)
