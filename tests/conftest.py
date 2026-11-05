"""Shared fixtures.

Unit tests need nothing. Tests marked `integration` need PostgreSQL with pgvector: they run against DATABASE_URL, apply
the real migration once per session, and empty every table before each test. They are skipped, loudly, when the
database cannot be reached, never silently green.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
import uvicorn
from sqlalchemy import Engine, create_engine, text

from pulse.clock import FixedClock
from pulse.config import Settings
from pulse.identifiers import Pseudonymizer
from pulse.records import Page
from pulse.synthetic import Dataset

TABLES = "outbox_attempts, outbox, sync_runs, sync_state, encounters, subjects, teams, kb_chunks, health_samples, heartbeats, lab_state"
START = datetime(2026, 7, 1, 9, 0, tzinfo=UTC)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    del config
    if _database_reachable():
        return
    skip = pytest.mark.skip(
        reason="no database: set DATABASE_URL to a PostgreSQL with pgvector (make test-integration)"
    )
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


def _settings() -> Settings:
    return Settings(_env_file=None, database_url=os.environ.get("DATABASE_URL", Settings().database_url))  # type: ignore[call-arg]


def database_url() -> str:
    """The database the integration tests run against: DATABASE_URL, or the development default."""
    return _settings().database_url


def _database_reachable() -> bool:
    try:
        engine = create_engine(_settings().sqlalchemy_url, connect_args={"connect_timeout": 2})
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    from alembic import command
    from alembic.config import Config

    os.environ.setdefault("DATABASE_URL", _settings().database_url)
    os.environ["PULSE_ROOT"] = os.getcwd()
    from pulse.config import get_settings

    get_settings.cache_clear()
    cfg = Config("alembic.ini")
    cfg.set_main_option("script_location", "alembic")
    command.upgrade(cfg, "head")
    eng = create_engine(_settings().sqlalchemy_url, pool_size=10, max_overflow=10)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine: Engine) -> Engine:
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY"))
    return engine


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(START)


@pytest.fixture
def pseudonyms() -> Pseudonymizer:
    return Pseudonymizer("test-pseudonym-key-0123456789abcdef", "t1")


class FakeRegistry:
    """The registry's paging contract over an in-memory dataset: strictly after (updated_at, id), oldest first."""

    def __init__(self, data: Dataset) -> None:
        self.data = data
        self.calls: list[tuple[str, datetime | None, str | None]] = []
        self.on_fetch: Callable[[str, int], None] | None = None

    def fetch(self, entity: str, after_updated_at: datetime | None, after_id: str | None, limit: int) -> Page:
        self.calls.append((entity, after_updated_at, after_id))
        if self.on_fetch is not None:
            self.on_fetch(entity, len(self.calls))
        records = sorted(self.data.entity(entity), key=lambda r: (datetime.fromisoformat(r["updated_at"]), r["id"]))
        if after_updated_at is not None:
            floor = (after_updated_at, after_id or "")
            records = [r for r in records if (datetime.fromisoformat(r["updated_at"]), r["id"]) > floor]
        return Page(items=list(records[:limit]), has_more=len(records) > limit)


def free_port() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class RunningServer:
    def __init__(self, app: Any, **ssl_options: Any) -> None:
        self.port = free_port()
        config = uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="error", **ssl_options)
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self) -> RunningServer:
        self.thread.start()
        deadline = time.time() + 10
        while not self.server.started:
            if time.time() > deadline:
                raise RuntimeError("the test server did not start")
            time.sleep(0.02)
        return self

    def __exit__(self, *exc: object) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)
