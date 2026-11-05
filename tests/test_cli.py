"""The command line: the same functions as the API and the workers, from a terminal."""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text

from pulse.cli import main
from pulse.config import get_settings
from pulse.exchange.queue import claim, enqueue_many, finish
from pulse.standin.gateway_app import create_gateway_app
from pulse.standin.registry_app import create_registry_app
from tests.conftest import START, RunningServer, database_url

pytestmark = pytest.mark.integration


@pytest.fixture
def cli(db: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    del db
    with (
        RunningServer(create_registry_app(seed=9, subjects=50)) as registry,
        RunningServer(create_gateway_app()) as gateway,
    ):
        monkeypatch.setenv("DATABASE_URL", database_url())
        monkeypatch.setenv("REGISTRY_URL", f"http://127.0.0.1:{registry.port}")
        monkeypatch.setenv("GATEWAY_URL", f"http://127.0.0.1:{gateway.port}")
        monkeypatch.setenv("APP_ENV", "development")
        get_settings.cache_clear()
        yield
    get_settings.cache_clear()


def test_the_commands_run_end_to_end(cli: None, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["index"]) == 0
    assert "indexed 36 chunks" in capsys.readouterr().out

    assert main(["sync"]) == 0
    synced = json.loads(capsys.readouterr().out)
    assert synced["status"] == "ok" and synced["totals"]["applied"] > 50

    assert main(["drain"]) == 0
    drained = json.loads(capsys.readouterr().out)
    assert drained["delivered"] > 0 and drained["dead"] == 0

    assert main(["indicators", "--as-of", "2026-06-30", "--narrate"]) == 0
    out = capsys.readouterr().out
    assert '"indicators_with_data": 5' in out and "As of 2026-06-30 the overall score is" in out

    assert main(["search", "advisory lock", "--mode", "lexical", "-k", "2"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert 1 <= len(lines) <= 2 and "kb-31" in lines[0]  # -k is a ceiling; only one note mentions an advisory lock

    assert main(["eval"]) == 0
    assert "hybrid" in capsys.readouterr().out


def test_requeue_brings_dead_messages_back_all_or_by_id(
    cli: None, db: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    with db.begin() as conn:
        enqueue_many(conn, [("a", "x", {}), ("b", "x", {})], START)
    for message in claim(db, worker="w", now=START, limit=2, lease_seconds=60):
        finish(db, message, worker="w", now=START, outcome="dead", http_status=422, detail="refused")
    assert main(["requeue", "1"]) == 0
    assert "requeued 1 messages" in capsys.readouterr().out
    assert main(["requeue"]) == 0
    assert "requeued 1 messages" in capsys.readouterr().out  # only the other one was still dead
    with db.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM outbox WHERE status = 'pending'")).scalar() == 2


def test_migrate_reports_the_schema_at_head(
    cli: None, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PULSE_ROOT", ".")
    assert main(["migrate"]) == 0
    assert "schema is at head" in capsys.readouterr().out


def test_an_unknown_command_or_a_bad_argument_exits_with_usage(capsys: pytest.CaptureFixture[str]) -> None:
    for argv in (["nonsense"], ["search"], ["indicators", "--as-of", "not-a-date"], ["requeue", "abc"], []):
        with pytest.raises(SystemExit) as raised:
            main(argv)
        assert raised.value.code == 2
    assert "usage: pulse" in capsys.readouterr().err
