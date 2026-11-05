"""The scheduled work: reliability settings that matter, the lab's autopilot gate, and each task doing its job."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import Engine, text

from pulse import tasks
from pulse.config import Settings
from pulse.db import LAB_AUTOPILOT_KEY, lab_set
from pulse.services import Services
from pulse.standin.gateway_app import create_gateway_app
from pulse.standin.registry_app import create_registry_app
from tests.conftest import RunningServer, database_url

# ---- configuration: no database --------------------------------------------------------------------------------


def test_a_task_is_acknowledged_after_it_ran_and_returned_to_the_broker_if_its_worker_dies() -> None:
    conf = tasks.celery_app.conf
    assert conf.task_acks_late is True
    assert conf.task_reject_on_worker_lost is True
    assert conf.worker_prefetch_multiplier == 1  # a long task cannot sit behind a prefetched one


def test_only_json_is_accepted_so_a_message_on_the_broker_cannot_carry_a_pickle() -> None:
    conf = tasks.celery_app.conf
    assert conf.task_serializer == "json" and list(conf.accept_content) == ["json"]


def test_every_scheduled_entry_names_a_task_that_exists_and_runs_at_the_documented_interval() -> None:
    schedule = tasks.celery_app.conf.beat_schedule
    registered = set(tasks.celery_app.tasks)
    assert {entry["task"] for entry in schedule.values()} <= registered
    assert {name: entry["schedule"] for name, entry in schedule.items()} == {
        "sync": 900.0,
        "drain": 30.0,
        "heartbeat": 60.0,
        "health": 60.0,
    }


def test_the_heartbeat_is_more_frequent_than_the_health_check_allows_it_to_go_missing() -> None:
    from pulse.health import HEARTBEAT_INTERVAL_SECONDS

    assert tasks.celery_app.conf.beat_schedule["heartbeat"]["schedule"] == HEARTBEAT_INTERVAL_SECONDS


def test_a_worker_has_a_name_that_tells_hosts_and_processes_apart() -> None:
    host, _, pid = tasks.WORKER_ID.rpartition(":")
    assert host and pid.isdigit()


# ---- the tasks: against a database and the stand-ins ---------------------------------------------------------------


@pytest.fixture(scope="module")
def standins() -> Iterator[tuple[RunningServer, RunningServer]]:
    with (
        RunningServer(create_registry_app(seed=5, subjects=60)) as registry,
        RunningServer(create_gateway_app()) as gateway,
    ):
        yield registry, gateway


def services_for(standins: tuple[RunningServer, RunningServer], *, lab: bool) -> Services:
    registry, gateway = standins
    settings = Settings(
        _env_file=None,
        database_url=database_url(),
        lab_mode=lab,
        registry_url=f"http://127.0.0.1:{registry.port}",
        gateway_url=f"http://127.0.0.1:{gateway.port}",
        gateway_timeout_seconds=3,
    )  # type: ignore[call-arg]
    services = Services(settings)
    services.ping_broker = lambda: None  # type: ignore[method-assign,assignment]
    return services


@pytest.fixture
def ordinary(standins: tuple[RunningServer, RunningServer], db: Engine, monkeypatch: pytest.MonkeyPatch) -> Services:
    del db
    services = services_for(standins, lab=False)
    monkeypatch.setattr(tasks, "get_services", lambda: services)
    return services


@pytest.fixture
def lab(standins: tuple[RunningServer, RunningServer], db: Engine, monkeypatch: pytest.MonkeyPatch) -> Services:
    del db
    services = services_for(standins, lab=True)
    monkeypatch.setattr(tasks, "get_services", lambda: services)
    return services


def switch(services: Services, on: bool) -> None:
    with services.engine.begin() as conn:
        lab_set(conn, LAB_AUTOPILOT_KEY, on)


@pytest.mark.integration
def test_outside_the_lab_the_scheduled_work_always_runs(ordinary: Services) -> None:
    assert tasks.autopilot_on(ordinary) is True


@pytest.mark.integration
def test_in_the_lab_it_runs_only_while_the_visitor_has_the_autopilot_on(lab: Services) -> None:
    assert tasks.autopilot_on(lab) is False  # off until switched on
    switch(lab, True)
    assert tasks.autopilot_on(lab) is True
    switch(lab, False)
    assert tasks.autopilot_on(lab) is False


@pytest.mark.integration
def test_with_the_autopilot_off_the_sync_and_the_drain_do_nothing_and_say_so(lab: Services) -> None:
    assert tasks.sync_task() == {"skipped": "autopilot is off"}
    assert tasks.drain_task() == {"skipped": "autopilot is off"}
    with lab.engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM sync_runs")).scalar() == 0


@pytest.mark.integration
def test_the_heartbeat_and_the_health_sample_run_even_with_the_autopilot_off(lab: Services) -> None:
    assert tasks.heartbeat_task() == "beat"
    assert tasks.health_task() == "recorded"
    with lab.engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM heartbeats")).scalar() == 1
        assert (conn.execute(text("SELECT count(*) FROM health_samples")).scalar() or 0) >= 6


@pytest.mark.integration
def test_sync_then_drain_move_data_from_the_registry_to_the_gateway(ordinary: Services) -> None:
    synced: dict[str, Any] = tasks.sync_task()
    assert synced["status"] == "ok" and synced["applied"] > 100
    delivered = 0
    for _ in range(10):
        report = tasks.drain_task()
        delivered += report["delivered"]
        if report["claimed"] == 0:
            break
    with ordinary.engine.connect() as conn:
        encounters = conn.execute(text("SELECT count(*) FROM encounters")).scalar()
        unfinished = conn.execute(text("SELECT count(*) FROM outbox WHERE status <> 'done'")).scalar()
    assert delivered == encounters > 50  # every stored encounter was reported once, and there was something to report
    assert report["dead"] == 0 and unfinished == 0
