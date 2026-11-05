"""The lab: levers that move time and break the two systems this pipeline depends on.

Only mounted when LAB_MODE is on, which the settings refuse in production. Every lever either changes a clock offset
or a switch in a stand-in, or calls a function the real pipeline calls; nothing here evaluates anything a visitor typed.
"""

from __future__ import annotations

import ssl
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from pulse.db import LAB_AUTOPILOT_KEY, LAB_CLOCK_KEY, LAB_NARRATOR_KEY, iso, lab_get, lab_set
from pulse.exchange.queue import claim
from pulse.identifiers import is_valid_national_id
from pulse.indicators.lab_narrators import NARRATORS
from pulse.privacy import find_values
from pulse.search.store import index_documents
from pulse.services import Services
from pulse.standin.gateway_app import SCENARIOS

DAY = 86_400


class Clock(BaseModel):
    seconds: int = Field(ge=1, le=7 * DAY)


class Switch(BaseModel):
    on: bool


class Narrator(BaseModel):
    mode: str


class Advance(BaseModel):
    new: int = Field(default=20, ge=0, le=500)
    changed: int = Field(default=10, ge=0, le=500)
    removed: int = Field(default=3, ge=0, le=500)


class Late(BaseModel):
    behind_seconds: int = Field(ge=0, le=10 * DAY)


class Flaky(BaseModel):
    next_requests: int = Field(ge=0, le=100)


class Scenario(BaseModel):
    name: str


class Crash(BaseModel):
    count: int = Field(default=5, ge=1, le=50)


class Connector(BaseModel):
    with_certificate: bool


def build_lab_router(services: Services) -> APIRouter:
    router = APIRouter(prefix="/api/lab")
    engine, clock, settings = services.engine, services.clock, services.settings

    def registry(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = httpx.request(method, settings.registry_url.rstrip("/") + path, timeout=10, **kwargs)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(502, f"the registry stand-in did not answer: {type(exc).__name__}") from exc
        return dict(response.json())

    def gateway(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        # Every call here is a lab control (read the state, pick a scenario, reset): repeating one changes nothing.
        # After a rejected attempt without a certificate (the "Connect without it" button) the first call down the
        # pooled, authenticated connection can fail with a transport error (a ReadError here, and the same family
        # elsewhere); the second call opens a new connection and works.
        # The cause was not found (docs/HANDOFF.md). The pipeline itself does not need this: its own retry rules
        # already treat a transport error as a failed attempt to be repeated later.
        try:
            try:
                response = services.gateway.raw(method, path, **kwargs)
            except httpx.TransportError:
                response = services.gateway.raw(method, path, **kwargs)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(502, f"the gateway stand-in did not answer: {type(exc).__name__}") from exc
        return dict(response.json())

    @router.get("/state")
    def state() -> dict[str, Any]:
        with engine.connect() as conn:
            return {
                "now": iso(clock.now()),
                "offset_seconds": int(lab_get(conn, LAB_CLOCK_KEY, 0)),
                "autopilot": bool(lab_get(conn, LAB_AUTOPILOT_KEY, False)),
                "narrator": lab_get(conn, LAB_NARRATOR_KEY, "template"),
                "narrators": sorted(NARRATORS),
                "scenarios": list(SCENARIOS),
            }

    @router.post("/reset")
    def reset() -> dict[str, str]:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "TRUNCATE teams, subjects, encounters, sync_state, sync_runs, outbox, outbox_attempts, "
                    "health_samples, heartbeats, lab_state RESTART IDENTITY"
                )
            )
        registry("POST", "/control/reset")
        gateway("POST", "/control/reset")
        index_documents(engine, services.embedder)
        return {"status": "reset"}

    @router.post("/clock")
    def move_clock(body: Clock) -> dict[str, Any]:
        with engine.begin() as conn:
            offset = int(lab_get(conn, LAB_CLOCK_KEY, 0)) + body.seconds
            lab_set(conn, LAB_CLOCK_KEY, offset)
        return {"offset_seconds": offset, "now": iso(clock.now())}

    @router.post("/autopilot")
    def autopilot(body: Switch) -> dict[str, bool]:
        with engine.begin() as conn:
            lab_set(conn, LAB_AUTOPILOT_KEY, body.on)
        return {"autopilot": body.on}

    @router.post("/narrator")
    def narrator(body: Narrator) -> dict[str, str]:
        if body.mode not in NARRATORS:
            raise HTTPException(422, f"unknown narrator; choose one of {', '.join(sorted(NARRATORS))}")
        with engine.begin() as conn:
            lab_set(conn, LAB_NARRATOR_KEY, body.mode)
        return {"narrator": body.mode}

    # --- the source registry ------------------------------------------------------------------------------
    @router.get("/registry")
    def registry_state() -> dict[str, Any]:
        return registry("GET", "/control/state")

    @router.post("/registry/advance")
    def registry_advance(body: Advance) -> dict[str, Any]:
        return registry("POST", "/control/advance", json={"now": clock.now().isoformat(), **body.model_dump()})

    @router.post("/registry/late-arrival")
    def registry_late(body: Late) -> dict[str, Any]:
        return registry("POST", "/control/late-arrival", json={"now": clock.now().isoformat(), **body.model_dump()})

    @router.post("/registry/flaky")
    def registry_flaky(body: Flaky) -> dict[str, Any]:
        return registry("POST", "/control/flaky", json=body.model_dump())

    # --- the gateway --------------------------------------------------------------------------------------
    @router.get("/gateway")
    def gateway_state() -> dict[str, Any]:
        return gateway("GET", "/control/state")

    @router.post("/gateway/scenario")
    def gateway_scenario(body: Scenario) -> dict[str, Any]:
        if body.name not in SCENARIOS:  # refuse here: the stand-in would too, and that would read as "did not answer"
            raise HTTPException(422, f"unknown scenario; choose one of {', '.join(SCENARIOS)}")
        return gateway("POST", "/control/scenario", json=body.model_dump())

    @router.post("/gateway/expire-tokens")
    def gateway_expire() -> dict[str, Any]:
        return gateway("POST", "/control/expire-tokens")

    @router.post("/connector/check")
    def connector(body: Connector) -> dict[str, Any]:
        """Open a connection to the gateway with or without the client certificate, and say what happened."""
        url = settings.gateway_url.rstrip("/") + "/health"
        if not url.startswith("https://"):
            return {
                "tls": False,
                "ok": False,
                "detail": "the gateway URL is not https, so there is no handshake to test",
            }
        try:
            if body.with_certificate:
                response = services.gateway.raw("GET", "/health")
            else:
                context = ssl.create_default_context(cafile=settings.gateway_ca_file or None)
                with httpx.Client(verify=context, timeout=4) as plain:
                    response = plain.get(url)
        except (httpx.TransportError, ssl.SSLError) as exc:
            return {"tls": True, "ok": False, "with_certificate": body.with_certificate, "detail": type(exc).__name__}
        return {
            "tls": True,
            "ok": response.status_code == 200,
            "with_certificate": body.with_certificate,
            "detail": f"HTTP {response.status_code}",
        }

    # --- the queue ----------------------------------------------------------------------------------------
    @router.post("/queue/crash")
    def crash(body: Crash) -> dict[str, Any]:
        """Claim messages the way a worker does, then walk away: what is left behind is what a dead worker leaves."""
        taken = claim(
            engine,
            worker="worker-that-died",
            now=clock.now(),
            limit=body.count,
            lease_seconds=settings.queue_lease_seconds,
        )
        return {"abandoned": [m.id for m in taken], "lease_seconds": settings.queue_lease_seconds}

    # --- privacy ------------------------------------------------------------------------------------------
    @router.get("/privacy")
    def privacy() -> dict[str, Any]:
        sample = registry("GET", "/control/identifiers", params={"n": 40})["people"]
        pseudonyms = services.pseudonyms
        values = [v for p in sample for v in (p["name"], p["national_id"], p["id"])]
        scan = find_values(engine, values)
        # Shown: people the pipeline accepts. One whose identifier fails its check digits is rejected, never stored.
        shown = [p for p in sample if is_valid_national_id(p["national_id"])][:3]
        with engine.connect() as conn:
            stored = conn.execute(
                text(
                    "SELECT subject_key, key_id, birth_month, team_id, chronic FROM subjects "
                    "WHERE subject_key = ANY(:keys)"
                ),
                {"keys": [pseudonyms.subject_key(p["id"]) for p in shown]},
            ).all()
        return {
            "registry_sample": shown,
            "stored_for_them": [
                {
                    "subject_key": r.subject_key,
                    "key_id": r.key_id,
                    "birth_month": r.birth_month.isoformat(),
                    "team": r.team_id,
                    "chronic": r.chronic,
                }
                for r in stored
            ],
            "searched_for": len(values),
            "scan": {
                "columns_examined": scan.columns_examined,
                "matches": [list(m) for m in scan.matches],
                "clean": scan.clean,
            },
        }

    return router
