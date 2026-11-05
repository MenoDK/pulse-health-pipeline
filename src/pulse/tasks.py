"""The scheduled work, as Celery tasks.

The tasks are thin: each calls a function that is tested without Celery. The settings that matter for correctness are
`acks_late` and `reject_on_worker_lost` (a task is acknowledged after it ran, and returned to the broker if its worker
dies), and a prefetch of one (a long task cannot sit behind a prefetched one).

In lab mode the scheduled drain and sync wait for the "autopilot" switch, so a visitor can make the queue do one thing
at a time; the heartbeat and the health sample always run.
"""

from __future__ import annotations

import os
import socket
from collections.abc import Callable
from typing import Any, TypeVar

from celery import Celery

from pulse.config import get_settings
from pulse.db import LAB_AUTOPILOT_KEY, lab_get
from pulse.exchange.worker import drain
from pulse.health import beat, collect, record
from pulse.services import Services, get_services

settings = get_settings()
celery_app = Celery("pulse", broker=settings.redis_url, backend=None, include=["pulse.tasks"])
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    task_ignore_result=True,
    timezone="UTC",
    beat_schedule={
        "sync": {"task": "pulse.sync", "schedule": 900.0},
        "drain": {"task": "pulse.drain", "schedule": 30.0},
        "heartbeat": {"task": "pulse.heartbeat", "schedule": 60.0},
        "health": {"task": "pulse.health", "schedule": 60.0},
    },
)

WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"

F = TypeVar("F", bound=Callable[..., Any])


def scheduled(name: str) -> Callable[[F], F]:
    """Register a function as a Celery task and hand the function back unchanged.

    Celery ships no type information, so decorating directly would make every task untyped. Here the registration is
    done once and the function keeps its own signature, which also means a task can be called as a plain function.
    """

    def register(function: F) -> F:
        celery_app.task(name=name)(function)
        return function

    return register


def autopilot_on(services: Services) -> bool:
    """Outside the lab the scheduled work always runs. In the lab it runs only when the visitor switched it on."""
    if not services.settings.lab_mode:
        return True
    with services.engine.connect() as conn:
        return bool(lab_get(conn, LAB_AUTOPILOT_KEY, False))


@scheduled("pulse.sync")
def sync_task() -> dict[str, Any]:
    services = get_services()
    if not autopilot_on(services):
        return {"skipped": "autopilot is off"}
    result = services.syncer().run()
    return {"status": result.status, "applied": result.total("applied")}


@scheduled("pulse.drain")
def drain_task() -> dict[str, Any]:
    services = get_services()
    if not autopilot_on(services):
        return {"skipped": "autopilot is off"}
    s = services.settings
    report = drain(
        services.engine,
        services.gateway,
        services.clock,
        worker=WORKER_ID,
        batch=s.queue_batch,
        lease_seconds=s.queue_lease_seconds,
        max_attempts=s.queue_max_attempts,
        backoff_base=s.queue_backoff_base_seconds,
        backoff_cap=s.queue_backoff_cap_seconds,
    )
    return {"claimed": report.claimed, "delivered": report.delivered, "retried": report.retried, "dead": report.dead}


@scheduled("pulse.heartbeat")
def heartbeat_task() -> str:
    services = get_services()
    beat(services.engine, services.clock)
    return "beat"


@scheduled("pulse.health")
def health_task() -> str:
    services = get_services()
    record(services.engine, services.clock, collect(services.engine, services.clock, services.ping_broker))
    return "recorded"
