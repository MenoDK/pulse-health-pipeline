"""Draining the queue.

A worker claims a batch, sends each message, and records each result under its own name. Two rules keep an outage
from wasting work and attempts:

* After `stop_after_failures` consecutive transport failures it stops and **releases** the rest of the batch without
  spending their attempts. Without this, a batch of fifty against an unreachable gateway is fifty timeouts in a row,
  which outlasts the lease, and fifty attempts spent in one cycle instead of three.
* A message whose lease is about to run out is released too, so a slow gateway cannot make a worker send messages that
  another worker is about to claim.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import Engine, text

from pulse.clock import Clock
from pulse.exchange.backoff import backoff_seconds
from pulse.exchange.gateway import Delivery, Sender
from pulse.exchange.queue import Message, claim, finish, reap_exhausted

log = logging.getLogger(__name__)


@dataclass
class DrainReport:
    reaped: int = 0
    claimed: int = 0
    taken_over: int = 0  # of those claimed, how many another worker had claimed and then stopped answering
    delivered: int = 0
    duplicate: int = 0
    retried: int = 0
    dead: int = 0
    released: int = 0
    lost_lease: int = 0
    stopped: str | None = None
    notes: list[str] = field(default_factory=list)


def release(engine: Engine, messages: list[Message], *, worker: str) -> int:
    """Give claimed messages back untouched: pending again, and the attempt the claim spent is refunded."""
    if not messages:
        return 0
    with engine.begin() as conn:
        result = conn.execute(
            text(
                "UPDATE outbox SET status = 'pending', attempts = attempts - 1, lease_until = NULL, locked_by = NULL "
                "WHERE id = ANY(:ids) AND status = 'sending' AND locked_by = :worker"
            ),
            {"ids": [m.id for m in messages], "worker": worker},
        )
        return result.rowcount


def drain(
    engine: Engine,
    sender: Sender,
    clock: Clock,
    *,
    worker: str,
    batch: int = 50,
    lease_seconds: int = 120,
    max_attempts: int = 10,
    backoff_base: int = 30,
    backoff_cap: int = 21_600,
    stop_after_failures: int = 3,
    lease_margin_seconds: int = 10,
    after_claim: Callable[[list[Message]], None] | None = None,
) -> DrainReport:
    report = DrainReport()
    report.reaped = reap_exhausted(engine, clock.now(), max_attempts)
    messages = claim(engine, worker=worker, now=clock.now(), limit=batch, lease_seconds=lease_seconds)
    report.claimed = len(messages)
    report.taken_over = sum(1 for m in messages if m.taken_over)
    if report.taken_over:
        log.warning("%s took over %d messages from a worker that stopped answering", worker, report.taken_over)
    deadline = clock.now() + timedelta(seconds=lease_seconds - lease_margin_seconds)
    if after_claim is not None:
        after_claim(messages)  # a hook for tests and the lab: raise here to behave like a worker that died

    failures = 0
    for index, message in enumerate(messages):
        if clock.now() >= deadline:
            report.stopped = "lease about to expire"
            report.released = release(engine, messages[index:], worker=worker)
            break
        delivery = sender.send(message.idempotency_key, message.payload)
        _record(engine, clock, report, message, delivery, worker, max_attempts, backoff_base, backoff_cap)
        failures = failures + 1 if delivery.outcome == "retry" and delivery.http_status is None else 0
        if failures >= stop_after_failures and index + 1 < len(messages):
            report.stopped = f"{failures} transport failures in a row"
            report.released = release(engine, messages[index + 1 :], worker=worker)
            break
    return report


def _record(
    engine: Engine,
    clock: Clock,
    report: DrainReport,
    message: Message,
    delivery: Delivery,
    worker: str,
    max_attempts: int,
    backoff_base: int,
    backoff_cap: int,
) -> None:
    outcome, detail, retry_in = delivery.outcome, delivery.detail, None
    if outcome == "retry":
        if message.attempts >= max_attempts:
            outcome, detail = "dead", f"gave up after {message.attempts} attempts: {delivery.detail}"
        else:
            retry_in = min(
                backoff_cap,
                max(
                    backoff_seconds(message.attempts, message.idempotency_key, base=backoff_base, cap=backoff_cap),
                    delivery.retry_after or 0,
                ),
            )
    won = finish(
        engine,
        message,
        worker=worker,
        now=clock.now(),
        outcome=outcome,
        http_status=delivery.http_status,
        detail=detail,
        retry_in=retry_in,
    )
    if not won:
        report.lost_lease += 1
        report.notes.append(f"message {message.id}: the lease was taken over; this result was discarded")
        return
    if outcome == "delivered":
        report.delivered += 1
    elif outcome == "duplicate":
        report.duplicate += 1
    elif outcome == "retry":
        report.retried += 1
    else:
        report.dead += 1
