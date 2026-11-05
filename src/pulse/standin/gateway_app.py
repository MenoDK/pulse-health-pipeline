"""A stand-in for the national gateway: OAuth client credentials, an idempotent report endpoint, and ways to fail.

Scenarios (set from `/control/scenario`):

    normal        accept a new key with 201, answer a repeated key with 409 {"error": "duplicate"}
    outage        503 for every report
    reject        400 for every report (the payload is refused)
    rate-limit    429 with Retry-After
    lose-ack      store the report, then answer 500; a retry finds the key and gets the duplicate answer
    slow          wait before answering, longer than the sender's timeout
    revoked       the token endpoint answers 401 (the credential was revoked)

`/control/expire-tokens` makes every token issued so far invalid, which is what an expiry looks like from outside.
"""

from __future__ import annotations

import asyncio
import os
import secrets
import threading
from typing import Any

from fastapi import APIRouter, FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

SCENARIOS = ("normal", "outage", "reject", "rate-limit", "lose-ack", "slow", "revoked")


class _State:
    def __init__(self, client_id: str, client_secret: str, slow_seconds: float) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.slow_seconds = slow_seconds
        self.lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        self.scenario = "normal"
        self.tokens: set[str] = set()
        self.received: dict[str, dict[str, Any]] = {}
        self.requests = 0
        self.duplicates = 0
        self.token_requests = 0
        self.log: list[str] = []

    def note(self, line: str) -> None:
        self.log.append(line)
        del self.log[:-40]


def create_gateway_app(
    *,
    client_id: str = "pulse-demo",
    client_secret: str = "pulse-demo-secret",  # noqa: S107  (a placeholder for the stand-in, not a credential)
    slow_seconds: float = 8.0,
    control: bool = False,
) -> FastAPI:
    state = _State(client_id, client_secret, slow_seconds)
    app = FastAPI(title="gateway stand-in", docs_url=None, redoc_url=None, openapi_url=None)

    @app.post("/oauth/token")
    def token(grant_type: str = Form(...), client_id: str = Form(...), client_secret: str = Form(...)) -> JSONResponse:
        with state.lock:
            state.token_requests += 1
            if state.scenario == "revoked" or grant_type != "client_credentials":
                state.note("token: refused")
                return JSONResponse({"error": "invalid_client"}, status_code=401)
            if not (
                secrets.compare_digest(client_id, state.client_id)
                and secrets.compare_digest(client_secret, state.client_secret)
            ):
                state.note("token: wrong credentials")
                return JSONResponse({"error": "invalid_client"}, status_code=401)
            value = secrets.token_urlsafe(24)
            state.tokens.add(value)
            state.note("token: issued")
        return JSONResponse({"access_token": value, "token_type": "Bearer", "expires_in": 300})

    @app.post("/v1/reports")
    async def report(
        request: Request,
        authorization: str = Header(default=""),
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    ) -> JSONResponse:
        bearer = authorization.removeprefix("Bearer ").strip()
        with state.lock:
            state.requests += 1
            if bearer not in state.tokens:
                state.note("report: 401 (token unknown or expired)")
                return JSONResponse({"error": "invalid_token"}, status_code=401)
            scenario = state.scenario
        if not idempotency_key:
            return JSONResponse({"error": "Idempotency-Key is required"}, status_code=400)
        if scenario == "outage":
            return JSONResponse({"error": "unavailable"}, status_code=503)
        if scenario == "reject":
            return JSONResponse({"error": "invalid payload"}, status_code=400)
        if scenario == "rate-limit":
            return JSONResponse({"error": "slow down"}, status_code=429, headers={"Retry-After": "120"})
        if scenario == "slow":
            await asyncio.sleep(state.slow_seconds)
        body = await request.json()
        with state.lock:
            if idempotency_key in state.received:
                state.duplicates += 1
                state.note(f"report {idempotency_key}: duplicate")
                return JSONResponse({"error": "duplicate"}, status_code=409)
            state.received[idempotency_key] = body
            state.note(f"report {idempotency_key}: stored")
            if scenario == "lose-ack":
                return JSONResponse({"error": "internal"}, status_code=500)
        return JSONResponse({"status": "accepted"}, status_code=201)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    if control:
        app.include_router(_control(state))
    return app


class Scenario(BaseModel):
    name: str


def _control(state: _State) -> APIRouter:
    router = APIRouter(prefix="/control")

    @router.get("/state")
    def get_state() -> dict[str, Any]:
        with state.lock:
            return {
                "scenario": state.scenario,
                "received_unique": len(state.received),
                "requests": state.requests,
                "duplicates": state.duplicates,
                "token_requests": state.token_requests,
                "log": list(state.log),
            }

    @router.post("/scenario")
    def set_scenario(body: Scenario) -> dict[str, str]:
        if body.name not in SCENARIOS:
            raise HTTPException(422, f"unknown scenario; choose one of {', '.join(SCENARIOS)}")
        with state.lock:
            state.scenario = body.name
            state.note(f"scenario: {body.name}")
        return {"scenario": body.name}

    @router.post("/expire-tokens")
    def expire() -> dict[str, int]:
        with state.lock:
            count = len(state.tokens)
            state.tokens.clear()
            state.note("tokens: all expired")
        return {"expired": count}

    @router.post("/reset")
    def reset() -> dict[str, str]:
        with state.lock:
            state.reset()
        return {"status": "reset"}

    return router


def app_factory() -> FastAPI:
    return create_gateway_app(
        client_id=os.environ.get("GATEWAY_CLIENT_ID", "pulse-demo"),
        client_secret=os.environ.get("GATEWAY_CLIENT_SECRET", "pulse-demo-secret"),
        slow_seconds=float(os.environ.get("STANDIN_SLOW_SECONDS", "8")),
        control=os.environ.get("STANDIN_CONTROL", "").lower() in {"1", "true", "yes"},
    )
