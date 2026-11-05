"""The HTTP surface: who may call what, the lab's two gates, validation, and the whole lab flow over real stand-ins."""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import Engine

from pulse.api.app import create_app
from pulse.api.security import CSP, host_allowed
from pulse.config import Settings
from pulse.identifiers import is_valid_national_id
from pulse.services import Services
from pulse.standin.gateway_app import create_gateway_app
from pulse.standin.registry_app import create_registry_app
from tests.conftest import RunningServer, database_url

pytestmark = pytest.mark.integration

KEY = "k" * 24


@pytest.fixture(scope="module")
def standins() -> Iterator[tuple[RunningServer, RunningServer]]:
    with (
        RunningServer(create_registry_app(seed=3, subjects=60, control=True)) as registry,
        RunningServer(create_gateway_app(control=True)) as gateway,
    ):
        yield registry, gateway


@pytest.fixture(autouse=True)
def fresh_standins(standins: tuple[RunningServer, RunningServer], db: Engine) -> None:
    del db  # the database is emptied by its own fixture; this one only says "after that"
    registry, gateway = standins
    httpx.post(f"http://127.0.0.1:{registry.port}/control/reset", timeout=5).raise_for_status()
    httpx.post(f"http://127.0.0.1:{gateway.port}/control/reset", timeout=5).raise_for_status()


def build(standins: tuple[RunningServer, RunningServer], *, lab: bool, gateway_client: object | None = None) -> FastAPI:
    registry, gateway = standins
    settings = Settings(
        _env_file=None,
        database_url=database_url(),
        api_key=KEY,
        lab_mode=lab,
        registry_url=f"http://127.0.0.1:{registry.port}",
        gateway_url=f"http://127.0.0.1:{gateway.port}",
        queue_batch=50,
        gateway_timeout_seconds=3,
    )  # type: ignore[call-arg]
    services = Services(settings)
    if gateway_client is not None:
        services.gateway = gateway_client  # type: ignore[assignment]
    services.ping_broker = lambda: None  # type: ignore[method-assign,assignment]  # no Redis in these tests
    return create_app(settings, services)


@pytest.fixture(scope="module")
def servers(standins: tuple[RunningServer, RunningServer]) -> Iterator[tuple[RunningServer, RunningServer]]:
    """The application twice, as the world sees it: an ordinary one and one with the lab on. Real sockets, no test client."""
    with RunningServer(build(standins, lab=False)) as ordinary, RunningServer(build(standins, lab=True)) as with_lab:
        yield ordinary, with_lab


@pytest.fixture
def api(servers: tuple[RunningServer, RunningServer]) -> Iterator[httpx.Client]:
    with httpx.Client(base_url=f"http://localhost:{servers[0].port}", timeout=30) as client:
        yield client


@pytest.fixture
def lab(servers: tuple[RunningServer, RunningServer]) -> Iterator[httpx.Client]:
    with httpx.Client(base_url=f"http://localhost:{servers[1].port}", timeout=30) as client:
        yield client


AUTH = {"X-API-Key": KEY}

# ---- authentication and headers ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path", ["/api/health", "/api/queue", "/api/overview", "/api/indicators", "/api/sync/runs", "/api/search?q=lock"]
)
def test_every_api_route_refuses_a_missing_or_wrong_key_and_accepts_the_right_one(api: httpx.Client, path: str) -> None:
    assert api.get(path).status_code == 401
    assert api.get(path, headers={"X-API-Key": "wrong"}).status_code == 401
    assert api.get(path, headers={"X-API-Key": KEY + "x"}).status_code == 401
    assert api.get(path, headers=AUTH).status_code == 200


@pytest.mark.parametrize("path", ["/api/sync/run", "/api/queue/drain"])
def test_the_routes_that_do_work_need_the_key_too(api: httpx.Client, path: str) -> None:
    assert api.post(path).status_code == 401
    assert api.post(path, headers=AUTH).status_code == 200


def test_the_liveness_and_readiness_probes_need_no_key_and_reveal_no_detail(api: httpx.Client) -> None:
    assert api.get("/health/live").json() == {"status": "ok"}
    ready = api.get("/health/ready")
    assert ready.status_code in (200, 503)
    assert set(ready.json()) == {"status", "checks"}
    assert all(set(c) == {"component", "status"} for c in ready.json()["checks"])  # no latency, no detail, no counts


def test_every_response_carries_the_security_headers_and_the_api_is_never_cached(api: httpx.Client) -> None:
    for path, headers in (("/health/live", {}), ("/api/overview", AUTH), ("/api/overview", {}), ("/nowhere", {})):
        response = api.get(path, headers=headers)
        assert response.headers["content-security-policy"] == CSP
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["referrer-policy"] == "no-referrer"
    assert api.get("/api/overview", headers=AUTH).headers["cache-control"] == "no-store"


def test_the_policy_allows_no_inline_script_or_style_and_no_framing() -> None:
    assert "script-src 'self'" in CSP and "style-src 'self'" in CSP
    assert "unsafe-inline" not in CSP and "unsafe-eval" not in CSP
    assert "frame-ancestors 'none'" in CSP and "base-uri 'none'" in CSP


def test_outside_the_lab_there_is_no_lab_no_docs_and_no_schema(api: httpx.Client) -> None:
    for path in ("/api/lab/state", "/api/docs", "/api/openapi.json", "/docs", "/openapi.json"):
        assert api.get(path, headers=AUTH).status_code == 404, path
    assert api.post("/api/lab/clock", json={"seconds": 60}, headers=AUTH).status_code == 404


# ---- the lab's gates ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("host", "allowed"),
    [
        ("localhost", True),
        ("LOCALHOST:8300", True),
        ("127.0.0.1", True),
        ("127.0.0.1:8300", True),
        ("[::1]:8300", True),
        ("localhost.evil.example", False),
        ("evil.example", False),
        ("127.0.0.1.evil.example", False),
        ("localhost:abc", False),
        ("localhost:123456", False),
        ("", False),
        ("0.0.0.0", False),
        ("192.168.1.10:8300", False),
    ],
)
def test_the_hosts_the_lab_answers_to(host: str, allowed: bool) -> None:
    assert host_allowed(host) is allowed


def test_the_lab_refuses_a_request_addressed_to_any_other_name_which_is_what_dns_rebinding_looks_like(
    lab: httpx.Client,
) -> None:
    # A page on attacker.example whose DNS now points at this machine sends exactly this: our port, their Host.
    rebound = {"Host": "attacker.example"}
    assert lab.get("/api/lab/state", headers=rebound).status_code == 421
    assert (
        lab.get("/api/overview", headers=rebound).status_code == 421
    )  # the whole application, not only the lab routes
    assert lab.get("/api/lab/state").status_code == 200  # and our own name still works


def test_a_cross_site_request_cannot_press_the_labs_buttons(lab: httpx.Client) -> None:
    hostile_origin = {"Origin": "https://evil.example"}
    assert lab.post("/api/lab/clock", json={"seconds": 3600}, headers=hostile_origin).status_code == 403
    assert (
        lab.post("/api/lab/clock", json={"seconds": 3600}, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    )
    assert (
        lab.post("/api/lab/clock", json={"seconds": 3600}, headers={"Sec-Fetch-Site": "same-site"}).status_code == 403
    )
    assert lab.get("/api/lab/state").json()["offset_seconds"] == 0  # none of them did anything


def test_the_same_site_and_plain_clients_may_press_them(lab: httpx.Client) -> None:
    own = f"http://localhost:{lab.base_url.port}"  # what a browser sends from this page: scheme, name and port
    for headers in ({}, {"Origin": own}, {"Sec-Fetch-Site": "same-origin", "Origin": own}, {"Sec-Fetch-Site": "none"}):
        assert lab.post("/api/lab/clock", json={"seconds": 60}, headers=headers).status_code == 200, headers
    # The same name on another port is another origin: a different local server cannot press these buttons.
    assert lab.post("/api/lab/clock", json={"seconds": 60}, headers={"Origin": "http://localhost:1"}).status_code == 403


def test_reading_is_allowed_from_anywhere_because_it_changes_nothing(lab: httpx.Client) -> None:
    assert (
        lab.get(
            "/api/lab/state", headers={"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"}
        ).status_code
        == 200
    )


def test_the_lab_needs_no_key_but_the_ordinary_routes_do_not_become_open_either_outside_it(
    api: httpx.Client, lab: httpx.Client
) -> None:
    assert lab.get("/api/overview").status_code == 200  # the gates are the protection in the lab
    assert api.get("/api/overview").status_code == 401


# ---- the lab's levers --------------------------------------------------------------------------------------------


def test_the_clock_moves_forward_by_the_amount_asked_and_is_bounded(lab: httpx.Client) -> None:
    first = lab.post("/api/lab/clock", json={"seconds": 3600}).json()
    second = lab.post("/api/lab/clock", json={"seconds": 3600}).json()
    assert (first["offset_seconds"], second["offset_seconds"]) == (3600, 7200)
    for bad in (0, -5, 7 * 86_400 + 1):
        assert lab.post("/api/lab/clock", json={"seconds": bad}).status_code == 422
    assert lab.post("/api/lab/clock", json={"seconds": "soon"}).status_code == 422
    assert lab.post("/api/lab/clock", json={}).status_code == 422


def test_an_unknown_narrator_or_scenario_is_refused_and_a_known_one_is_remembered(lab: httpx.Client) -> None:
    assert lab.post("/api/lab/narrator", json={"mode": "improvise"}).status_code == 422
    assert lab.post("/api/lab/gateway/scenario", json={"name": "meltdown"}).status_code == 422
    assert lab.post("/api/lab/narrator", json={"mode": "invents"}).json() == {"narrator": "invents"}
    assert lab.get("/api/lab/state").json()["narrator"] == "invents"
    assert lab.post("/api/lab/autopilot", json={"on": True}).json() == {"autopilot": True}
    assert lab.get("/api/overview").json()["autopilot"] is True


@pytest.mark.parametrize("body", [{"new": -1}, {"new": 501}, {"changed": 501}, {"removed": -3}])
def test_the_registry_levers_are_bounded(lab: httpx.Client, body: dict[str, int]) -> None:
    assert lab.post("/api/lab/registry/advance", json=body).status_code == 422


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/lab/registry/late-arrival", {"behind_seconds": -1}),
        ("/api/lab/registry/late-arrival", {"behind_seconds": 10 * 86_400 + 1}),
        ("/api/lab/registry/late-arrival", {}),
        ("/api/lab/registry/flaky", {"next_requests": 101}),
        ("/api/lab/registry/flaky", {"next_requests": -1}),
        ("/api/lab/queue/crash", {"count": 0}),
        ("/api/lab/queue/crash", {"count": 51}),
        ("/api/lab/autopilot", {"on": "perhaps"}),
        ("/api/lab/connector/check", {}),
    ],
)
def test_the_other_levers_refuse_out_of_range_or_missing_values(
    lab: httpx.Client, path: str, body: dict[str, Any]
) -> None:
    assert lab.post(path, json=body).status_code == 422


# ---- validation of the ordinary routes ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    ["q=", "q=" + "x" * 201, "q=lock&mode=magic", "q=lock&k=0", "q=lock&k=21", "", "mode=hybrid"],
)
def test_search_validates_its_input(api: httpx.Client, query: str) -> None:
    assert api.get(f"/api/search?{query}", headers=AUTH).status_code == 422


def test_a_search_over_an_empty_index_answers_with_no_hits_rather_than_failing(api: httpx.Client) -> None:
    body = api.get("/api/search?q=advisory+lock", headers=AUTH).json()
    assert body["hits"] == [] and body["mode"] == "hybrid"


@pytest.mark.parametrize("query", ["as_of=yesterday", "as_of=2026-13-45", "as_of=2026-02-30"])
def test_the_indicator_date_must_be_a_real_date(api: httpx.Client, query: str) -> None:
    assert api.get(f"/api/indicators?{query}", headers=AUTH).status_code == 422


@pytest.mark.parametrize("limit", [0, 101, -1])
def test_the_run_history_is_bounded(api: httpx.Client, limit: int) -> None:
    assert api.get(f"/api/sync/runs?limit={limit}", headers=AUTH).status_code == 422


# ---- the lab's calls to the gateway ------------------------------------------------------------------------------


class ScriptedGateway:
    """Stands in for the gateway client: answers from a script, one item per call, and counts the calls."""

    def __init__(self, *script: Exception | httpx.Response) -> None:
        self.script = list(script)
        self.calls = 0

    def raw(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        self.calls += 1
        item = self.script.pop(0)  # a call nobody scripted ends in an IndexError, which the test sees as a 500
        if isinstance(item, Exception):
            raise item
        return item


def answer(status: int) -> httpx.Response:
    return httpx.Response(status, json={"scenario": "normal"}, request=httpx.Request("POST", "http://gateway/control"))


def press_scenario_button(standins: tuple[RunningServer, RunningServer], gateway: ScriptedGateway) -> httpx.Response:
    with RunningServer(build(standins, lab=True, gateway_client=gateway)) as server:
        return httpx.post(
            f"http://localhost:{server.port}/api/lab/gateway/scenario", json={"name": "normal"}, timeout=10
        )


def test_a_lab_call_whose_connection_broke_is_repeated_once_and_then_works(
    standins: tuple[RunningServer, RunningServer],
) -> None:
    gateway = ScriptedGateway(httpx.ReadError("the pooled connection was closed"), answer(200))
    assert press_scenario_button(standins, gateway).status_code == 200
    assert gateway.calls == 2


def test_a_gateway_that_stays_unreachable_gives_a_502_after_one_repeat_not_a_loop(
    standins: tuple[RunningServer, RunningServer],
) -> None:
    gateway = ScriptedGateway(httpx.ReadError("gone"), httpx.ConnectError("still gone"))
    response = press_scenario_button(standins, gateway)
    assert response.status_code == 502 and "ConnectError" in response.json()["detail"]
    assert gateway.calls == 2


def test_an_error_answer_from_the_gateway_is_reported_at_once_and_never_repeated(
    standins: tuple[RunningServer, RunningServer],
) -> None:
    gateway = ScriptedGateway(answer(500))
    response = press_scenario_button(standins, gateway)
    assert response.status_code == 502 and "HTTPStatusError" in response.json()["detail"]
    assert gateway.calls == 1


# ---- the whole flow, over the real stand-ins ---------------------------------------------------------------------

AS_OF = "2026-06-30"


def drain_until_empty(client: httpx.Client) -> dict[str, int]:
    totals = {"delivered": 0, "retried": 0, "dead": 0, "taken_over": 0}
    for _ in range(12):
        report = client.post("/api/queue/drain").json()
        for key in totals:
            totals[key] += report[key]
        if client.get("/api/queue").json()["due_now"] == 0:
            break
    return totals


def test_reset_sync_report_and_deliver_through_the_api(lab: httpx.Client) -> None:
    assert lab.post("/api/lab/reset").json() == {"status": "reset"}
    assert lab.get("/api/overview").json()["data"]["kb_chunks"] >= 36  # reset rebuilds the search index

    run = lab.post("/api/sync/run").json()
    assert run["status"] == "ok", run
    assert run["totals"]["applied"] > 100 and run["totals"]["rejected"] >= 1  # the invalid identifier(s) were refused
    assert run["queued"] > 0

    again = lab.post("/api/sync/run").json()
    assert again["totals"]["applied"] == 0  # nothing new, so nothing applied and nothing queued
    assert again["queued"] == 0

    delivered = drain_until_empty(lab)
    assert delivered["delivered"] == run["queued"] and delivered["dead"] == 0
    counts = lab.get("/api/queue").json()["counts"]
    assert counts == {"pending": 0, "sending": 0, "done": run["queued"], "dead": 0}
    assert lab.get("/api/lab/gateway").json()["received_unique"] == run["queued"]  # the gateway has each exactly once

    report = lab.get(f"/api/indicators?as_of={AS_OF}&narrate=true").json()
    assert report["indicators_with_data"] == 5
    assert report["narration"]["accepted"] is True and report["narration"]["source"] == "narrator"
    assert len({i["status"] for i in report["indicators"]}) >= 3  # the data is shaped so the bands differ

    hits = lab.get("/api/search?q=advisory+lock&mode=hybrid&k=3").json()["hits"]
    assert hits and hits[0]["ranks"]


def test_a_narrator_that_invents_a_number_is_replaced_and_the_response_says_why(lab: httpx.Client) -> None:
    lab.post("/api/lab/reset")
    lab.post("/api/sync/run")
    lab.post("/api/lab/narrator", json={"mode": "invents"})
    narration = lab.get(f"/api/indicators?as_of={AS_OF}&narrate=true").json()["narration"]
    assert narration["accepted"] is False and narration["source"] == "template"
    assert narration["violations"] and "12.5" not in narration["text"]


def test_nothing_that_identifies_a_person_is_anywhere_in_the_database_and_the_scan_proves_it_can_see(
    lab: httpx.Client,
) -> None:
    lab.post("/api/lab/reset")
    assert lab.post("/api/sync/run").json()["status"] == "ok"
    drain_until_empty(lab)

    proof = lab.get("/api/lab/privacy").json()
    assert proof["scan"]["matches"] == [], proof["scan"]["matches"]
    assert proof["scan"]["clean"] is True
    assert proof["scan"]["columns_examined"] >= 15  # a scan that looked at nothing proves nothing
    assert proof["searched_for"] == 120  # name, national id and registry id of 40 people
    sample, stored = proof["registry_sample"], proof["stored_for_them"]
    assert len(sample) == 3 and sample[0]["name"] and sample[0]["national_id"]
    # The registry's first person has the deliberately wrong identifier (refused, never stored). The lab shows people
    # the pipeline accepts, so "stored for them" has as many rows as there are people on the left.
    assert all(is_valid_national_id(p["national_id"]) for p in sample)
    assert len(stored) == 3
    for row in stored:
        assert set(row) == {"subject_key", "key_id", "birth_month", "team", "chronic"}
        assert row["subject_key"].startswith("pk1.") and row["birth_month"].endswith("-01")


def test_a_dead_worker_leaves_messages_that_come_back_when_its_lease_ends(lab: httpx.Client) -> None:
    lab.post("/api/lab/reset")
    lab.post("/api/sync/run")
    crash = lab.post("/api/lab/queue/crash", json={"count": 5}).json()
    assert len(crash["abandoned"]) == 5
    assert lab.get("/api/queue").json()["counts"]["sending"] == 5

    first = drain_until_empty(lab)  # everything except the five held by the dead worker
    waiting = lab.get("/api/queue").json()
    assert waiting["counts"]["sending"] == 5 and waiting["due_now"] == 0
    assert first["taken_over"] == 0  # nothing is taken over while the lease holds

    lab.post("/api/lab/clock", json={"seconds": crash["lease_seconds"] + 1})
    second = drain_until_empty(lab)
    assert second["delivered"] == 5
    assert second["taken_over"] == 5  # and the response says these five came from a worker that stopped answering
    assert lab.get("/api/queue").json()["counts"]["done"] == first["delivered"] + 5


def test_an_outage_then_a_recovery_through_the_lab_loses_nothing(lab: httpx.Client) -> None:
    lab.post("/api/lab/reset")
    lab.post("/api/sync/run")
    lab.post("/api/lab/gateway/scenario", json={"name": "outage"})
    during = lab.post("/api/queue/drain").json()
    assert during["delivered"] == 0 and during["retried"] > 0
    lab.post("/api/lab/gateway/scenario", json={"name": "normal"})
    lab.post("/api/lab/clock", json={"seconds": 86_400})
    drain_until_empty(lab)
    counts = lab.get("/api/queue").json()["counts"]
    assert counts["dead"] == 0 and counts["pending"] == 0 and counts["sending"] == 0
    assert lab.get("/api/lab/gateway").json()["received_unique"] == counts["done"]


def test_a_flaky_registry_is_retried_inside_one_run_and_a_down_one_fails_the_run_with_a_clean_error(
    lab: httpx.Client,
) -> None:
    lab.post("/api/lab/reset")
    lab.post("/api/lab/registry/flaky", json={"next_requests": 1})
    started = time.time()
    assert lab.post("/api/sync/run").json()["status"] == "ok"  # one 503, retried inside the client
    assert time.time() - started < 10

    lab.post("/api/lab/reset")
    lab.post("/api/lab/registry/flaky", json={"next_requests": 50})
    failed = lab.post("/api/sync/run").json()
    assert failed["status"] == "failed"
    assert failed["error"].startswith("RegistryError: the registry could not be read after 3 tries")


def test_the_connector_check_says_when_there_is_no_handshake_to_test(lab: httpx.Client) -> None:
    result: dict[str, Any] = lab.post("/api/lab/connector/check", json={"with_certificate": True}).json()
    assert result["tls"] is False and result["ok"] is False
