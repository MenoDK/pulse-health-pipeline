"""The source system, seen through one small interface.

`RegistryClient.fetch` returns records strictly after a (updated_at, id) position, oldest first, at most `limit` at a
time. Ordering by the pair, not by the timestamp alone, is what keeps a page boundary from landing in the middle of a
run of records that share a timestamp.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime
from typing import Protocol

import httpx

from pulse.records import Page


class RegistryError(RuntimeError):
    """The registry could not be read. Retried by the HTTP client; after that, the sync run fails."""


class RegistryClient(Protocol):
    def fetch(self, entity: str, after_updated_at: datetime | None, after_id: str | None, limit: int) -> Page: ...


class HttpRegistryClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 10.0,
        retries: int = 2,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._http = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout, transport=transport)
        self._retries = retries
        self._sleep = sleep

    def close(self) -> None:
        self._http.close()

    def fetch(self, entity: str, after_updated_at: datetime | None, after_id: str | None, limit: int) -> Page:
        params: dict[str, str | int] = {"limit": limit}
        if after_updated_at is not None:
            params["after_updated_at"] = after_updated_at.isoformat()
            if after_id is not None:
                params["after_id"] = after_id
        last_problem = "no attempt was made"
        for attempt in range(self._retries + 1):
            try:
                response = self._http.get(f"/v1/{entity}", params=params)
            except httpx.TransportError as exc:
                last_problem = f"{type(exc).__name__}"
            else:
                if response.status_code == 200:
                    try:
                        return Page.model_validate(response.json())
                    except ValueError:  # includes pydantic's ValidationError, whose message quotes the input
                        raise RegistryError("the registry answered something that is not a page") from None
                if response.status_code < 500:
                    # A 4xx will not get better by asking again (a wrong entity, a bad cursor): fail at once.
                    raise RegistryError(f"the registry refused the request with {response.status_code}")
                last_problem = f"HTTP {response.status_code}"
            if attempt < self._retries:
                self._sleep(0.2 * (2**attempt))
        raise RegistryError(f"the registry could not be read after {self._retries + 1} tries: {last_problem}")
