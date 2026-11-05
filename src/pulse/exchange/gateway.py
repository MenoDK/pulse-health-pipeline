"""The connector to the national gateway.

Three things worth reading here:

* **TokenCache** refreshes a token once, however many threads ask at the same moment, and an `invalidate` only
  clears the token that actually failed (so a slow thread cannot throw away a fresh one).
* **classify** decides what a response means for the *message*: a gateway that is down, a token that expired and a
  credential that was revoked are not the message's fault, so they are retried with backoff instead of failing at
  once; a payload the gateway refuses is its fault, and retrying it helps nobody, so it is dead at once. Any message
  is dead after `max_attempts` however it failed (a long enough outage can do that); `requeue_dead` brings it back.
* **mTLS**: when a client certificate is configured the connection presents it, and a handshake that fails is an
  ordinary, retryable transport error with a name, not a crash.
"""

from __future__ import annotations

import ssl
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

import httpx

from pulse.clock import Clock


@dataclass(frozen=True)
class Token:
    value: str
    expires_at: datetime


class TokenUnavailable(RuntimeError):
    """The token endpoint did not give a token. A configuration or availability problem, not the message's."""


class TokenCache:
    def __init__(self, fetch: Callable[[], Token], clock: Clock, margin_seconds: int) -> None:
        self._fetch = fetch
        self._clock = clock
        self._margin = timedelta(seconds=margin_seconds)
        self._token: Token | None = None
        self._lock = threading.Lock()

    def get(self) -> str:
        with self._lock:
            token = self._token
            if token is None or self._clock.now() >= token.expires_at - self._margin:
                token = self._token = self._fetch()
            return token.value

    def invalidate(self, value: str) -> None:
        with self._lock:
            if self._token is not None and self._token.value == value:
                self._token = None


@dataclass(frozen=True)
class Delivery:
    outcome: str  # delivered | duplicate | retry | dead
    http_status: int | None
    detail: str
    retry_after: int | None = None


class Sender(Protocol):
    def send(self, key: str, payload: dict[str, Any]) -> Delivery: ...


def _retry_after(response: httpx.Response) -> int | None:
    raw = response.headers.get("retry-after", "")
    return int(raw) if raw.isdigit() and int(raw) <= 86_400 else None


def classify(response: httpx.Response) -> Delivery:
    status = response.status_code
    if status in (200, 201, 202, 204):
        return Delivery("delivered", status, "accepted")
    if status == 409:
        try:
            body = response.json()
        except ValueError:
            body = {}
        if isinstance(body, dict) and body.get("error") == "duplicate":
            return Delivery("duplicate", status, "the gateway already had this key")
        return Delivery("dead", status, "conflict that is not a duplicate")
    if status in (400, 413, 422):
        return Delivery("dead", status, f"the gateway refuses this payload ({status})")
    if status in (401, 403, 404, 405, 408, 425, 429) or status >= 500 or 300 <= status < 400:
        # 3xx is a misconfigured address (a redirect is not followed): every message would fail, none by its own fault
        return Delivery("retry", status, f"HTTP {status}", _retry_after(response))
    return Delivery("dead", status, f"unexpected HTTP {status}")


class GatewayClient:
    def __init__(
        self,
        *,
        base_url: str,
        token_url: str,
        client_id: str,
        client_secret: str,
        clock: Clock,
        timeout: float = 5.0,
        margin_seconds: int = 60,
        ca_file: str = "",
        cert_file: str = "",
        key_file: str = "",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        verify: ssl.SSLContext | bool = True
        if ca_file or cert_file:
            context = ssl.create_default_context(cafile=ca_file or None)
            if cert_file:
                context.load_cert_chain(cert_file, key_file or None)
            verify = context
        self._http = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout, verify=verify, transport=transport)
        self._token_url = token_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._clock = clock
        self.tokens = TokenCache(self._fetch_token, clock, margin_seconds)

    def close(self) -> None:
        self._http.close()

    def raw(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """A request over the same connection settings (certificate included), for the lab's control calls."""
        return self._http.request(method, path, **kwargs)

    def _fetch_token(self) -> Token:
        try:
            response = self._http.post(
                self._token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
            )
        except httpx.TransportError as exc:
            raise TokenUnavailable(f"token endpoint unreachable: {type(exc).__name__}") from exc
        if response.status_code != 200:
            raise TokenUnavailable(f"token endpoint answered {response.status_code}")
        try:  # a 200 with a page from a proxy in it is still not a token
            body = response.json()
            value, lifetime = body["access_token"], int(body.get("expires_in", 300))
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise TokenUnavailable("token endpoint answered something that is not a token") from exc
        if not isinstance(value, str) or not value or lifetime <= 0:
            raise TokenUnavailable("token endpoint answered something that is not a token")
        return Token(value, self._clock.now() + timedelta(seconds=lifetime))

    def send(self, key: str, payload: dict[str, Any]) -> Delivery:
        for reauthenticated in (False, True):
            try:
                token = self.tokens.get()
            except TokenUnavailable as exc:
                return Delivery("retry", None, str(exc))
            try:
                response = self._http.post(
                    "/v1/reports", json=payload, headers={"Authorization": f"Bearer {token}", "Idempotency-Key": key}
                )
            except httpx.TransportError as exc:
                return Delivery("retry", None, f"transport error: {type(exc).__name__}")
            if response.status_code == 401 and not reauthenticated:
                self.tokens.invalidate(token)  # the token we used, not whichever one is cached now
                continue
            return classify(response)
        raise AssertionError("unreachable")  # pragma: no cover
