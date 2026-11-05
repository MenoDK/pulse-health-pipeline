"""The transmission queue on a real PostgreSQL: claims, leases, fencing, attempts, and the way back from dead."""

from __future__ import annotations

import threading
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from pulse.clock import FixedClock
from pulse.exchange.queue import Message, claim, counts, enqueue_many, finish, reap_exhausted, requeue_dead

pytestmark = pytest.mark.integration


def put(db: Engine, clock: FixedClock, n: int, prefix: str = "k") -> None:
    with db.begin() as conn:
        enqueue_many(conn, [(f"{prefix}{i:03d}", "encounter-report", {"n": i}) for i in range(n)], clock.now())


def row(db: Engine, message_id: int) -> Any:
    with db.connect() as conn:
        return conn.execute(text("SELECT * FROM outbox WHERE id = :i"), {"i": message_id}).one()


def test_a_key_that_is_already_queued_is_not_queued_twice(db: Engine, clock: FixedClock) -> None:
    put(db, clock, 3)
    with db.begin() as conn:
        new = enqueue_many(
            conn, [("k000", "encounter-report", {"n": 0}), ("k999", "encounter-report", {"n": 9})], clock.now()
        )
    assert new == 1
    assert counts(db)["pending"] == 4


def test_nothing_is_written_when_the_callers_transaction_rolls_back(db: Engine, clock: FixedClock) -> None:
    with pytest.raises(RuntimeError), db.begin() as conn:
        enqueue_many(conn, [("k1", "encounter-report", {})], clock.now())
        raise RuntimeError("the change that caused the message failed")
    assert counts(db)["pending"] == 0


def test_a_claim_takes_due_messages_in_order_and_counts_the_attempt(db: Engine, clock: FixedClock) -> None:
    put(db, clock, 5)
    got = claim(db, worker="w1", now=clock.now(), limit=3, lease_seconds=60)
    assert [m.idempotency_key for m in got] == ["k000", "k001", "k002"]
    assert all(m.attempts == 1 for m in got)
    assert counts(db) == {"pending": 2, "sending": 3, "done": 0, "dead": 0}


def test_a_message_that_is_not_due_yet_is_not_claimed(db: Engine, clock: FixedClock) -> None:
    put(db, clock, 1)
    (message,) = claim(db, worker="w1", now=clock.now(), limit=5, lease_seconds=60)
    finish(db, message, worker="w1", now=clock.now(), outcome="retry", http_status=503, detail="HTTP 503", retry_in=120)
    assert claim(db, worker="w1", now=clock.now(), limit=5, lease_seconds=60) == []
    clock.advance(119)
    assert claim(db, worker="w1", now=clock.now(), limit=5, lease_seconds=60) == []
    clock.advance(1)
    assert len(claim(db, worker="w1", now=clock.now(), limit=5, lease_seconds=60)) == 1


def test_many_workers_claiming_at_once_never_get_the_same_message(db: Engine, clock: FixedClock) -> None:
    put(db, clock, 60)
    taken: dict[str, list[Message]] = {}
    barrier = threading.Barrier(6)

    def work(name: str) -> None:
        barrier.wait()
        mine: list[Message] = []
        for _ in range(60):  # bounded: a claim that never ran dry must fail this test, not hang the suite
            batch = claim(db, worker=name, now=clock.now(), limit=4, lease_seconds=60)
            if not batch:
                break
            mine.extend(batch)
        taken[name] = mine

    threads = [threading.Thread(target=work, args=(f"w{i}",)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    ids = [m.id for mine in taken.values() for m in mine]
    assert len(ids) == 60
    assert len(set(ids)) == 60  # no message handed to two workers
    assert sum(1 for mine in taken.values() if mine) > 1  # and the work was actually shared


def test_a_claim_steps_around_a_message_another_transaction_holds_instead_of_waiting_for_it(
    db: Engine, clock: FixedClock
) -> None:
    """The test above cannot tell SKIP LOCKED from plain locking: without it workers only queue up behind each other.

    Here one connection holds the lock on the oldest message and does not let go. A claim must return the others at once.
    """
    put(db, clock, 4)
    outcome: dict[str, list[Message]] = {}
    with db.connect() as holder:
        locked = holder.execute(text("SELECT id FROM outbox ORDER BY id LIMIT 1 FOR UPDATE")).scalar()
        worker = threading.Thread(
            target=lambda: outcome.update(got=claim(db, worker="w1", now=clock.now(), limit=10, lease_seconds=60))
        )
        worker.start()
        worker.join(5)
        waited_for_the_lock = worker.is_alive()
        holder.rollback()  # let go, so a blocked claim can finish and the test can report instead of hanging
        worker.join(10)
    assert not waited_for_the_lock, "the claim waited for a message another transaction was holding"
    assert locked not in [m.id for m in outcome["got"]]
    assert len(outcome["got"]) == 3


def test_a_message_whose_lease_ran_out_is_claimed_again_and_the_attempt_is_counted(
    db: Engine, clock: FixedClock
) -> None:
    put(db, clock, 1)
    (first,) = claim(db, worker="dead-worker", now=clock.now(), limit=1, lease_seconds=60)
    assert claim(db, worker="w2", now=clock.now(), limit=1, lease_seconds=60) == []  # the lease still holds
    clock.advance(61)
    (second,) = claim(db, worker="w2", now=clock.now(), limit=1, lease_seconds=60)
    assert second.id == first.id
    assert second.attempts == 2  # the first claim counted even though that worker never answered


def test_a_claim_never_takes_more_than_the_limit_even_when_both_kinds_of_message_are_due(
    db: Engine, clock: FixedClock
) -> None:
    put(db, clock, 2, prefix="old")
    claim(db, worker="dead-worker", now=clock.now(), limit=2, lease_seconds=60)
    clock.advance(61)  # the two are now expired, and ten more are pending
    put(db, clock, 10, prefix="new")
    got = claim(db, worker="w2", now=clock.now(), limit=5, lease_seconds=60)
    assert len(got) == 5
    assert {"old000", "old001"} <= {m.idempotency_key for m in got}  # the ones that waited longest come first
    assert sum(m.taken_over for m in got) == 2
    assert counts(db)["pending"] == 7  # ten new ones, three of them taken


def test_a_message_is_marked_as_taken_over_only_when_it_came_from_a_lease_that_ran_out(
    db: Engine, clock: FixedClock
) -> None:
    put(db, clock, 3)
    first = claim(db, worker="w1", now=clock.now(), limit=3, lease_seconds=60)
    assert [m.taken_over for m in first] == [False, False, False]  # taken fresh, attempt 1
    clock.advance(61)
    again = claim(db, worker="w2", now=clock.now(), limit=3, lease_seconds=60)
    assert [m.taken_over for m in again] == [True, True, True]
    assert [m.attempts for m in again] == [2, 2, 2]


def test_a_delivery_after_a_failure_leaves_no_error_behind(db: Engine, clock: FixedClock) -> None:
    put(db, clock, 1)
    (first,) = claim(db, worker="w1", now=clock.now(), limit=1, lease_seconds=60)
    finish(db, first, worker="w1", now=clock.now(), outcome="retry", http_status=503, detail="HTTP 503", retry_in=5)
    assert row(db, first.id).last_error == "HTTP 503"
    clock.advance(5)
    (second,) = claim(db, worker="w1", now=clock.now(), limit=1, lease_seconds=60)
    finish(db, second, worker="w1", now=clock.now(), outcome="delivered", http_status=201, detail="accepted")
    done = row(db, second.id)
    assert (done.status, done.last_status, done.last_error) == ("done", 201, None)


def test_a_worker_that_lost_its_lease_cannot_overwrite_the_one_that_took_over(db: Engine, clock: FixedClock) -> None:
    put(db, clock, 1)
    (slow,) = claim(db, worker="slow", now=clock.now(), limit=1, lease_seconds=60)
    clock.advance(61)
    (fast,) = claim(db, worker="fast", now=clock.now(), limit=1, lease_seconds=60)

    assert (
        finish(db, fast, worker="fast", now=clock.now(), outcome="delivered", http_status=200, detail="accepted")
        is True
    )
    # The slow worker comes back late with a failure. Its result must not undo the delivery.
    assert (
        finish(db, slow, worker="slow", now=clock.now(), outcome="retry", http_status=500, detail="boom", retry_in=30)
        is False
    )
    assert row(db, slow.id).status == "done"
    with db.connect() as conn:
        outcomes = [r[0] for r in conn.execute(text("SELECT outcome FROM outbox_attempts ORDER BY id"))]
    assert outcomes == ["delivered"]  # the discarded result left no attempt row behind


def test_a_result_for_a_message_nobody_holds_any_more_is_refused(db: Engine, clock: FixedClock) -> None:
    put(db, clock, 1)
    (message,) = claim(db, worker="w1", now=clock.now(), limit=1, lease_seconds=60)
    assert finish(db, message, worker="w1", now=clock.now(), outcome="delivered", http_status=200, detail="ok")
    assert not finish(db, message, worker="w1", now=clock.now(), outcome="dead", http_status=400, detail="late")
    assert row(db, message.id).status == "done"


def test_the_outcomes_map_to_states_and_a_retry_needs_a_delay(db: Engine, clock: FixedClock) -> None:
    put(db, clock, 4)
    a, b, c, d = claim(db, worker="w", now=clock.now(), limit=4, lease_seconds=60)
    finish(db, a, worker="w", now=clock.now(), outcome="delivered", http_status=201, detail="ok")
    finish(db, b, worker="w", now=clock.now(), outcome="duplicate", http_status=409, detail="seen")
    finish(db, c, worker="w", now=clock.now(), outcome="dead", http_status=422, detail="refused")
    with pytest.raises(ValueError, match="delay"):
        finish(db, d, worker="w", now=clock.now(), outcome="retry", http_status=503, detail="x")
    with pytest.raises(ValueError, match="unknown outcome"):
        finish(db, d, worker="w", now=clock.now(), outcome="shrug", http_status=None, detail="x")
    assert [row(db, m.id).status for m in (a, b, c, d)] == ["done", "done", "dead", "sending"]
    assert row(db, a.id).done_at is not None
    assert row(db, c.id).done_at is None


def test_a_message_that_kills_its_worker_every_time_still_ends_dead(db: Engine, clock: FixedClock) -> None:
    """Attempts are counted when a message is claimed, not when it is answered, so a crash cannot hide an attempt."""
    put(db, clock, 1)
    for _ in range(3):
        assert len(claim(db, worker="doomed", now=clock.now(), limit=1, lease_seconds=60)) == 1
        clock.advance(61)  # the worker died; the lease ran out; nobody ever called finish
    assert reap_exhausted(db, clock.now(), max_attempts=3) == 1
    assert counts(db)["dead"] == 1
    assert claim(db, worker="w2", now=clock.now(), limit=1, lease_seconds=60) == []
    assert "stopped answering" in row(db, 1).last_error


def test_a_message_with_attempts_left_is_not_reaped(db: Engine, clock: FixedClock) -> None:
    put(db, clock, 1)
    claim(db, worker="w", now=clock.now(), limit=1, lease_seconds=60)
    clock.advance(61)
    assert reap_exhausted(db, clock.now(), max_attempts=3) == 0
    assert counts(db)["sending"] == 1


def test_a_message_whose_lease_still_holds_is_never_reaped(db: Engine, clock: FixedClock) -> None:
    put(db, clock, 1)
    for _ in range(3):
        claim(db, worker="w", now=clock.now(), limit=1, lease_seconds=60)
        clock.advance(61)
    claim(db, worker="w", now=clock.now(), limit=1, lease_seconds=60)  # a fourth claim: the lease is live
    assert reap_exhausted(db, clock.now(), max_attempts=3) == 0


def test_dead_messages_can_be_requeued_all_or_by_id_with_a_fresh_set_of_attempts(db: Engine, clock: FixedClock) -> None:
    put(db, clock, 3)
    for message in claim(db, worker="w", now=clock.now(), limit=3, lease_seconds=60):
        finish(db, message, worker="w", now=clock.now(), outcome="dead", http_status=422, detail="refused")
    assert counts(db)["dead"] == 3

    assert requeue_dead(db, clock.now(), ids=[1]) == 1
    assert counts(db) == {"pending": 1, "sending": 0, "done": 0, "dead": 2}
    assert row(db, 1).attempts == 0
    assert row(db, 1).last_error is None
    assert len(claim(db, worker="w", now=clock.now(), limit=5, lease_seconds=60)) == 1

    assert requeue_dead(db, clock.now()) == 2
    assert counts(db)["dead"] == 0


def test_requeue_leaves_messages_that_are_not_dead_alone(db: Engine, clock: FixedClock) -> None:
    put(db, clock, 2)
    (message, _) = claim(db, worker="w", now=clock.now(), limit=2, lease_seconds=60)
    finish(db, message, worker="w", now=clock.now(), outcome="delivered", http_status=200, detail="ok")
    assert requeue_dead(db, clock.now()) == 0
    assert row(db, message.id).status == "done"


def test_the_database_itself_refuses_a_state_that_contradicts_itself(db: Engine, clock: FixedClock) -> None:
    put(db, clock, 1)
    with pytest.raises(IntegrityError, match="check constraint"), db.begin() as conn:
        conn.execute(text("UPDATE outbox SET status = 'sending', lease_until = NULL"))  # sending with no lease
    with pytest.raises(IntegrityError, match="check constraint"), db.begin() as conn:
        conn.execute(text("UPDATE outbox SET status = 'unheard-of'"))


def test_a_claim_at_a_later_time_sees_only_what_is_due_then(db: Engine, clock: FixedClock) -> None:
    with db.begin() as conn:
        enqueue_many(conn, [("later", "encounter-report", {})], clock.now() + timedelta(hours=1))
    assert claim(db, worker="w", now=clock.now(), limit=5, lease_seconds=60) == []
    assert len(claim(db, worker="w", now=clock.now() + timedelta(hours=1), limit=5, lease_seconds=60)) == 1
