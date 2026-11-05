"""The composition root: the only place that knows which concrete classes are wired together."""

from __future__ import annotations

from collections.abc import Callable
from functools import cached_property

from sqlalchemy import Engine

from pulse.clock import Clock
from pulse.config import Settings, get_settings
from pulse.db import make_clock, make_engine
from pulse.exchange.gateway import GatewayClient
from pulse.identifiers import Pseudonymizer
from pulse.registry import HttpRegistryClient
from pulse.search.embedding import HashingNgramEmbedder
from pulse.sync import Syncer


class Services:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @cached_property
    def engine(self) -> Engine:
        return make_engine(self.settings)

    @cached_property
    def clock(self) -> Clock:
        return make_clock(self.settings, self.engine)

    @cached_property
    def pseudonyms(self) -> Pseudonymizer:
        return Pseudonymizer(self.settings.pseudonym_key, self.settings.pseudonym_key_id)

    @cached_property
    def embedder(self) -> HashingNgramEmbedder:
        return HashingNgramEmbedder(self.settings.embedding_dim)

    @cached_property
    def registry(self) -> HttpRegistryClient:
        return HttpRegistryClient(self.settings.registry_url, timeout=self.settings.registry_timeout_seconds)

    @cached_property
    def gateway(self) -> GatewayClient:
        s = self.settings
        return GatewayClient(
            base_url=s.gateway_url,
            token_url=s.token_url,
            client_id=s.gateway_client_id,
            client_secret=s.gateway_client_secret,
            clock=self.clock,
            timeout=s.gateway_timeout_seconds,
            margin_seconds=s.token_margin_seconds,
            ca_file=s.gateway_ca_file,
            cert_file=s.gateway_cert_file,
            key_file=s.gateway_key_file,
        )

    def syncer(self) -> Syncer:
        return Syncer(self.engine, self.registry, self.pseudonyms, self.clock, page_size=self.settings.sync_page_size)

    @cached_property
    def ping_broker(self) -> Callable[[], None]:
        import redis

        client = redis.Redis.from_url(self.settings.redis_url, socket_timeout=2, socket_connect_timeout=2)

        def ping() -> None:
            client.ping()

        return ping


_services: Services | None = None


def get_services() -> Services:
    global _services
    if _services is None:
        _services = Services(get_settings())
    return _services
