"""The worker, the connector and the gateway stand-in together: every scenario the lab offers, over real HTTP."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from sqlalchemy import Engine, text

from pulse.clock import FixedClock
from pulse.exchange.gateway import GatewayClient
from pulse.exchange.queue import claim, counts, enqueue_many, finish
from pulse.exchange.worker import drain
from pulse.standin.gateway_app import create_gateway_app
from tests.conftest import RunningServer

pytestmark = pytest.mark.integration


class Harness:
    def __init__(self, server: RunningServer, db: Engine, clock: FixedClock, timeout: float = 5.0) -> None:
        self.base = f"http://127.0.0.1:{server.port}"
        self.db, self.clock = db, clock
        self.control = httpx.Client(base_url=self.base, timeout=5)
        self.client = GatewayClient(
            base_url=self.base,
            token_url=f"{self.base}/oauth/token",
            client_id="pulse-demo",
            client_secret="pulse-demo-secret",
            clock=clock,
            timeout=timeout,
        )

    def put(self, n: int) -> None:
        with self.db.begin() as conn:
            enqueue_many(conn, [(f"k{i:03d}", "encounter-report", {"n": i}) for i in range(n)], self.clock.now())

    def scenario(self, name: str) -> None:
        self.control.post("/control/scenario", json={"name": name}).raise_for_status()

    def state(self) -> dict[str, Any]:
        return dict(self.control.get("/control/state").json())

    def drain(self, **kwargs: Any) -> Any:
        return drain(self.db, self.client, self.clock, worker="w", **kwargs)

    def message(self, n: int = 1) -> Any:
        with self.db.connect() as conn:
            return conn.execute(text("SELECT * FROM outbox WHERE id = :i"), {"i": n}).one()


@pytest.fixture
def lab(db: Engine, clock: FixedClock) -> Iterator[Harness]:
    with RunningServer(create_gateway_app(control=True, slow_seconds=1.5)) as server:
        harness = Harness(server, db, clock, timeout=0.4)
        yield harness
        harness.client.close()
        harness.control.close()


def test_a_normal_gateway_takes_every_message_once(lab: Harness) -> None:
    lab.put(3)
    report = lab.drain()
    assert report.delivered == 3
    state = lab.state()
    assert (state["received_unique"], state["token_requests"], state["duplicates"]) == (3, 1, 0)


def test_an_outage_delays_the_messages_and_the_recovery_delivers_them_without_losing_one(lab: Harness) -> None:
    lab.put(4)
    lab.scenario("outage")
    first = lab.drain()
    assert (first.retried, first.delivered) == (4, 0)
    assert counts(lab.db)["pending"] == 4

    lab.scenario("normal")
    assert lab.drain().claimed == 0  # nothing is due until the backoff has passed
    lab.clock.advance(3600)
    assert lab.drain().delivered == 4
    assert lab.state()["received_unique"] == 4


def test_a_refused_payload_goes_dead_on_the_first_try(lab: Harness) -> None:
    lab.put(1)
    lab.scenario("reject")
    assert lab.drain().dead == 1
    assert lab.message().status == "dead"
    assert lab.state()["requests"] == 1


def test_a_rate_limit_is_waited_out_for_as_long_as_the_gateway_asked(lab: Harness) -> None:
    lab.put(1)
    lab.scenario("rate-limit")  # 429 with Retry-After: 120
    lab.drain(backoff_base=30)
    assert (lab.message().not_before - lab.clock.now()).total_seconds() == 120


def test_a_lost_acknowledgement_does_not_make_the_effect_happen_twice(lab: Harness) -> None:
    """The gateway stores the report and the answer is lost. The retry meets the duplicate answer and the message ends done."""
    lab.put(1)
    lab.scenario("lose-ack")
    assert lab.drain().retried == 1  # 500, although the report is stored
    lab.scenario("normal")
    lab.clock.advance(3600)
    report = lab.drain()
    assert (report.duplicate, report.delivered) == (1, 0)
    assert lab.message().status == "done"
    state = lab.state()
    assert (state["received_unique"], state["duplicates"]) == (1, 1)  # sent twice, effect once


def test_an_expired_token_is_replaced_once_and_nothing_is_lost(lab: Harness) -> None:
    lab.put(2)
    assert lab.drain().delivered == 2
    lab.control.post("/control/expire-tokens").raise_for_status()
    with lab.db.begin() as conn:
        enqueue_many(conn, [("later-1", "encounter-report", {}), ("later-2", "encounter-report", {})], lab.clock.now())
    report = lab.drain()
    assert report.delivered == 2
    assert lab.state()["token_requests"] == 2  # one for the first batch, one replacement for the second


def test_a_revoked_credential_keeps_the_messages_waiting_instead_of_killing_them(lab: Harness) -> None:
    lab.put(3)
    lab.scenario("revoked")
    lab.control.post("/control/expire-tokens").raise_for_status()
    report = lab.drain()
    assert (report.dead, report.delivered) == (0, 0)
    assert counts(lab.db)["dead"] == 0
    assert lab.state()["requests"] == 0  # no report was sent with a token that could not be obtained

    lab.scenario("normal")
    lab.clock.advance(3600)
    assert lab.drain().delivered == 3


def test_a_gateway_slower_than_the_timeout_is_a_retry_with_no_status(lab: Harness) -> None:
    lab.put(1)
    lab.scenario("slow")  # answers after 1.5 s; the client waits 0.4 s
    report = lab.drain()
    assert report.retried == 1
    message = lab.message()
    assert message.last_status is None
    assert "ReadTimeout" in message.last_error


def test_a_worker_that_lost_its_lease_after_sending_leaves_the_gateway_with_one_copy(lab: Harness) -> None:
    """Two workers both send the same message. The key makes the second a duplicate, the fence makes only one result count."""
    lab.put(1)

    class SlowThenReplaced:
        def send(self, key: str, payload: dict[str, Any]) -> Any:
            result = lab.client.send(key, payload)  # the slow worker's request reaches the gateway
            lab.clock.advance(61)  # ... and its lease runs out before it can write the result
            (taken,) = claim(lab.db, worker="other", now=lab.clock.now(), limit=1, lease_seconds=60)
            second = lab.client.send(taken.idempotency_key, taken.payload)
            assert second.outcome == "duplicate"
            assert finish(
                lab.db, taken, worker="other", now=lab.clock.now(), outcome="duplicate", http_status=409, detail="seen"
            )
            return result

    report = drain(lab.db, SlowThenReplaced(), lab.clock, worker="slow", lease_seconds=60, lease_margin_seconds=10)
    assert report.lost_lease == 1
    assert lab.message().status == "done"
    state = lab.state()
    assert (state["received_unique"], state["duplicates"]) == (1, 1)
