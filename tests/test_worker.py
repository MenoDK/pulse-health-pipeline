"""Draining the queue: what a worker does with each answer, and what happens when it or the gateway fails."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import Engine, text

from pulse.clock import FixedClock
from pulse.exchange.backoff import backoff_seconds
from pulse.exchange.gateway import Delivery
from pulse.exchange.queue import Message, claim, counts, enqueue_many, finish
from pulse.exchange.worker import drain

pytestmark = pytest.mark.integration

OK = Delivery("delivered", 201, "accepted")
DOWN = Delivery("retry", None, "transport error: ConnectError")


class Scripted:
    """A sender that answers from a function of (key, how many sends so far)."""

    def __init__(self, answer: Callable[[str, int], Delivery]) -> None:
        self.answer = answer
        self.sent: list[str] = []

    def send(self, key: str, payload: dict[str, Any]) -> Delivery:
        del payload
        self.sent.append(key)
        return self.answer(key, len(self.sent))


def put(db: Engine, clock: FixedClock, n: int) -> None:
    with db.begin() as conn:
        enqueue_many(conn, [(f"k{i:03d}", "encounter-report", {"n": i}) for i in range(n)], clock.now())


def rows(db: Engine) -> list[Any]:
    with db.connect() as conn:
        return list(conn.execute(text("SELECT * FROM outbox ORDER BY id")))


def test_everything_due_is_delivered_and_marked_done(db: Engine, clock: FixedClock) -> None:
    put(db, clock, 5)
    report = drain(db, Scripted(lambda *_: OK), clock, worker="w")
    assert (report.claimed, report.delivered) == (5, 5)
    assert counts(db) == {"pending": 0, "sending": 0, "done": 5, "dead": 0}


def test_a_duplicate_answer_means_the_gateway_already_has_it_and_the_message_is_done(
    db: Engine, clock: FixedClock
) -> None:
    put(db, clock, 1)
    report = drain(
        db, Scripted(lambda *_: Delivery("duplicate", 409, "the gateway already had this key")), clock, worker="w"
    )
    assert (report.duplicate, report.delivered) == (1, 0)
    assert counts(db)["done"] == 1


def test_an_outage_stops_after_three_transport_failures_and_gives_the_rest_back_unspent(
    db: Engine, clock: FixedClock
) -> None:
    put(db, clock, 50)
    sender = Scripted(lambda *_: DOWN)
    report = drain(db, sender, clock, worker="w", batch=50)
    assert len(sender.sent) == 3  # not fifty timeouts in a row
    assert report.stopped == "3 transport failures in a row"
    assert (report.retried, report.released) == (3, 47)
    by_state = {r.idempotency_key: r for r in rows(db)}
    tried = [r for r in by_state.values() if r.attempts == 1]
    untouched = [r for r in by_state.values() if r.attempts == 0]
    assert len(tried) == 3 and len(untouched) == 47  # the 47 kept all their attempts
    assert all(r.status == "pending" and r.locked_by is None and r.lease_until is None for r in by_state.values())
    assert all(r.not_before > clock.now() for r in tried)  # the three that were tried wait for their backoff
    assert all(r.not_before <= clock.now() for r in untouched)  # the rest are due at once


def test_control_without_the_stop_rule_the_whole_batch_is_sent_and_spent(db: Engine, clock: FixedClock) -> None:
    put(db, clock, 50)
    sender = Scripted(lambda *_: DOWN)
    drain(db, sender, clock, worker="w", batch=50, stop_after_failures=10_000)
    assert len(sender.sent) == 50
    assert all(r.attempts == 1 for r in rows(db))


def test_transport_failures_that_are_not_in_a_row_do_not_stop_the_batch(db: Engine, clock: FixedClock) -> None:
    put(db, clock, 7)
    report = drain(db, Scripted(lambda _key, n: DOWN if n % 2 else OK), clock, worker="w")
    assert report.stopped is None
    assert (report.delivered, report.retried) == (3, 4)


def test_a_gateway_that_answers_with_an_error_does_not_stop_the_batch(db: Engine, clock: FixedClock) -> None:
    # A 5xx may be about one payload; only silence says nothing about the message, so only silence stops the batch.
    put(db, clock, 8)
    sender = Scripted(lambda *_: Delivery("retry", 503, "HTTP 503"))
    report = drain(db, sender, clock, worker="w")
    assert report.stopped is None
    assert len(sender.sent) == 8


def test_a_retry_waits_the_backoff_for_that_message_and_attempt(db: Engine, clock: FixedClock) -> None:
    put(db, clock, 1)
    drain(
        db,
        Scripted(lambda *_: Delivery("retry", 503, "HTTP 503")),
        clock,
        worker="w",
        backoff_base=30,
        backoff_cap=3600,
    )
    (message,) = rows(db)
    expected = backoff_seconds(1, "k000", base=30, cap=3600)
    assert (message.not_before - clock.now()).total_seconds() == expected
    assert message.last_status == 503 and message.last_error == "HTTP 503"


def test_a_longer_retry_after_wins_over_the_backoff_and_the_cap_still_applies(db: Engine, clock: FixedClock) -> None:
    put(db, clock, 2)
    answers = {"k000": Delivery("retry", 429, "HTTP 429", 600), "k001": Delivery("retry", 429, "HTTP 429", 86_400)}
    drain(db, Scripted(lambda key, _n: answers[key]), clock, worker="w", backoff_base=30, backoff_cap=1800)
    waits = {r.idempotency_key: (r.not_before - clock.now()).total_seconds() for r in rows(db)}
    assert waits["k000"] == 600  # the gateway asked for more than the backoff
    assert waits["k001"] == 1800  # and asked for more than we are willing to wait


def test_a_payload_the_gateway_refuses_is_dead_at_once_and_is_not_tried_again(db: Engine, clock: FixedClock) -> None:
    put(db, clock, 1)
    report = drain(
        db, Scripted(lambda *_: Delivery("dead", 422, "the gateway refuses this payload (422)")), clock, worker="w"
    )
    assert report.dead == 1
    (message,) = rows(db)
    assert (message.status, message.attempts) == ("dead", 1)
    assert drain(db, Scripted(lambda *_: OK), clock, worker="w").claimed == 0


def test_after_the_last_allowed_attempt_a_retry_becomes_dead_and_says_why(db: Engine, clock: FixedClock) -> None:
    put(db, clock, 1)
    sender = Scripted(lambda *_: Delivery("retry", 503, "HTTP 503"))
    for _ in range(3):
        drain(db, sender, clock, worker="w", max_attempts=3, backoff_cap=60)
        clock.advance(61)
    (message,) = rows(db)
    assert message.status == "dead"
    assert message.attempts == 3
    assert "gave up after 3 attempts" in message.last_error
    assert len(sender.sent) == 3


def test_a_message_the_worker_cannot_reach_before_its_lease_ends_is_released_not_sent(
    db: Engine, clock: FixedClock
) -> None:
    put(db, clock, 5)

    def slow(_key: str, _n: int) -> Delivery:
        clock.advance(100)  # each send takes 100 s; the lease is 120 s with a 10 s margin
        return OK

    sender = Scripted(slow)
    report = drain(db, sender, clock, worker="w", lease_seconds=120, lease_margin_seconds=10)
    assert len(sender.sent) == 2  # the third would start 200 s in, after the lease it was claimed under
    assert report.stopped == "lease about to expire"
    assert report.released == 3
    states = [(r.status, r.attempts) for r in rows(db)]
    assert states == [("done", 1), ("done", 1), ("pending", 0), ("pending", 0), ("pending", 0)]


def test_a_worker_that_lost_its_lease_while_sending_is_told_and_changes_nothing(db: Engine, clock: FixedClock) -> None:
    put(db, clock, 1)
    taken: list[Message] = []

    def slow_then_replaced(_key: str, _n: int) -> Delivery:
        clock.advance(61)  # the 60 s lease runs out while the request is in flight
        taken.extend(claim(db, worker="other", now=clock.now(), limit=1, lease_seconds=60))
        return Delivery("retry", 500, "boom")

    report = drain(db, Scripted(slow_then_replaced), clock, worker="slow", lease_seconds=60, lease_margin_seconds=10)
    assert report.lost_lease == 1
    assert report.retried == 0
    assert "lease was taken over" in report.notes[0]
    (message,) = rows(db)
    assert (message.status, message.locked_by, message.attempts) == (
        "sending",
        "other",
        2,
    )  # the other worker's claim stands

    assert finish(db, taken[0], worker="other", now=clock.now(), outcome="delivered", http_status=201, detail="ok")
    assert rows(db)[0].status == "done"


def test_a_crash_after_the_claim_loses_nothing_and_the_next_drain_delivers_everything(
    db: Engine, clock: FixedClock
) -> None:
    put(db, clock, 5)

    class Crash(Exception):
        pass

    def die(_messages: list[Message]) -> None:
        raise Crash

    with pytest.raises(Crash):
        drain(db, Scripted(lambda *_: OK), clock, worker="victim", lease_seconds=120, after_claim=die)
    assert counts(db)["sending"] == 5

    still_held = drain(db, Scripted(lambda *_: OK), clock, worker="rescuer", lease_seconds=120)
    assert (still_held.claimed, still_held.taken_over) == (0, 0)  # the lease still holds
    clock.advance(121)
    report = drain(db, Scripted(lambda *_: OK), clock, worker="rescuer", lease_seconds=120)
    assert report.delivered == 5
    assert report.taken_over == 5  # and the report says these came from a worker that stopped answering
    assert all(r.status == "done" and r.attempts == 2 for r in rows(db))  # the dead worker's claim counted


def test_only_messages_taken_from_a_dead_worker_are_reported_as_taken_over(db: Engine, clock: FixedClock) -> None:
    """Retried messages come back with attempts > 1 too, so the count cannot be derived from the attempts."""
    put(db, clock, 4)
    drain(db, Scripted(lambda *_: Delivery("retry", 503, "HTTP 503")), clock, worker="a", batch=4)  # all four retried
    clock.advance(3600)
    taken = claim(db, worker="dead", now=clock.now(), limit=1, lease_seconds=120)
    assert len(taken) == 1 and taken[0].attempts == 2 and not taken[0].taken_over  # attempt 2, but nobody died
    clock.advance(121)
    report = drain(db, Scripted(lambda *_: OK), clock, worker="b", batch=4)
    assert (report.claimed, report.taken_over) == (4, 1)


def test_a_process_killed_hard_in_the_middle_of_a_batch_loses_nothing(db: Engine, clock: FixedClock) -> None:
    """Not an exception: the whole process is gone with `os._exit`, no `finally`, no rollback of anything but the open one."""
    put(db, clock, 4)
    script = (
        "import os, sys\n"
        "from datetime import datetime\n"
        "from sqlalchemy import create_engine\n"
        "from pulse.clock import FixedClock\n"
        "from pulse.exchange.worker import drain\n"
        "def die(messages):\n"
        "    os._exit(137)\n"
        "class Never:\n"
        "    def send(self, key, payload):\n"
        "        raise SystemExit('unreachable')\n"
        "drain(create_engine(os.environ['PULSE_TEST_URL']), Never(), FixedClock(datetime.fromisoformat(sys.argv[1])),\n"
        "      worker='victim', lease_seconds=120, after_claim=die)\n"
    )
    url = db.url.render_as_string(hide_password=False)
    done = subprocess.run(
        [sys.executable, "-I", "-c", script, clock.now().isoformat()],
        env={"PULSE_TEST_URL": url},
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 137, done.stderr.decode()[-500:]
    assert counts(db) == {
        "pending": 0,
        "sending": 4,
        "done": 0,
        "dead": 0,
    }  # claimed by a process that no longer exists

    clock.advance(121)
    report = drain(db, Scripted(lambda *_: OK), clock, worker="rescuer", lease_seconds=120)
    assert report.delivered == 4
    assert counts(db)["done"] == 4


def test_messages_that_used_up_their_attempts_while_a_worker_was_dying_are_reaped_by_the_next_drain(
    db: Engine, clock: FixedClock
) -> None:
    put(db, clock, 1)
    for _ in range(3):
        claim(db, worker="doomed", now=clock.now(), limit=1, lease_seconds=60)
        clock.advance(61)
    report = drain(db, Scripted(lambda *_: OK), clock, worker="w", max_attempts=3)
    assert (report.reaped, report.claimed) == (1, 0)
    assert counts(db)["dead"] == 1
