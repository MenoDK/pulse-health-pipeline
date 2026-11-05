"""A stand-in for the source registry: paged, ordered by (updated_at, id), and changeable from the lab."""

from __future__ import annotations

import os
import random
import threading
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from pulse.records import ENTITY_MODELS
from pulse.synthetic import Dataset, evolve, generate


class _State:
    def __init__(self, seed: int, subjects: int, as_of: date) -> None:
        self.seed = seed
        self.subjects = subjects
        self.as_of = as_of
        self.lock = threading.Lock()
        self.fail_next = 0
        self.requests = 0
        self.reset()

    def reset(self) -> None:
        self.data: Dataset = generate(self.seed, self.subjects, self.as_of)
        self.rng = random.Random(self.seed + 1)
        self.fail_next = 0


def _key(record: dict[str, Any]) -> tuple[datetime, str]:
    return datetime.fromisoformat(record["updated_at"]), record["id"]


def create_registry_app(
    *, seed: int = 7, subjects: int = 600, as_of: date | None = None, control: bool = False
) -> FastAPI:
    """`as_of` is the day the generated registry is "up to date" to; the default is a fixed day, so tests and the
    recorded tour are the same on every machine. The demo passes today, so its indicators do not age."""
    state = _State(seed, subjects, as_of or Dataset().as_of)
    app = FastAPI(title="registry stand-in", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/v1/{entity}")
    def page(
        entity: str,
        limit: int = Query(100, ge=1, le=5000),
        after_updated_at: datetime | None = None,
        after_id: str | None = None,
    ) -> dict[str, Any]:
        if entity not in ENTITY_MODELS:
            raise HTTPException(404, "unknown entity")
        with state.lock:
            state.requests += 1
            if state.fail_next > 0:
                state.fail_next -= 1
                raise HTTPException(503, "the registry is busy")
            records = sorted(state.data.entity(entity), key=_key)
        if after_updated_at is not None:
            floor = (after_updated_at, after_id or "")
            records = [r for r in records if _key(r) > floor]
        chosen = records[:limit]
        return {"items": chosen, "has_more": len(records) > limit}

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    if control:
        app.include_router(_control(state))
    return app


class Advance(BaseModel):
    now: datetime
    new: int = Field(default=20, ge=0, le=500)
    changed: int = Field(default=10, ge=0, le=500)
    removed: int = Field(default=3, ge=0, le=500)


class LateArrival(BaseModel):
    """An encounter that becomes visible now but carries a timestamp from `behind_seconds` ago."""

    now: datetime
    behind_seconds: int = Field(ge=0, le=10 * 86_400)


class Flaky(BaseModel):
    next_requests: int = Field(ge=0, le=100)


def _control(state: _State) -> APIRouter:
    router = APIRouter(prefix="/control")

    @router.get("/state")
    def get_state() -> dict[str, Any]:
        with state.lock:
            return {
                "teams": len(state.data.teams),
                "people": len(state.data.people),
                "encounters": len(state.data.encounters),
                "requests": state.requests,
                "fail_next": state.fail_next,
                "latest_updated_at": max((r["updated_at"] for r in state.data.encounters), default=None),
            }

    @router.post("/reset")
    def reset() -> dict[str, str]:
        with state.lock:
            state.reset()
        return {"status": "reset"}

    @router.get("/identifiers")
    def identifiers(n: int = Query(40, ge=1, le=200)) -> dict[str, Any]:
        """The fictitious direct identifiers of the first `n` people, so the lab can prove they were not stored."""
        with state.lock:
            people = state.data.people[:n]
            return {"people": [{"id": p["id"], "name": p["name"], "national_id": p["national_id"]} for p in people]}

    @router.post("/advance")
    def advance(body: Advance) -> dict[str, int]:
        with state.lock:
            touched = evolve(state.data, state.rng, body.now, new=body.new, changed=body.changed, removed=body.removed)
        return {"touched": touched}

    @router.post("/late-arrival")
    def late(body: LateArrival) -> dict[str, str]:
        with state.lock:
            person = state.rng.choice([p for p in state.data.people if not p["deleted"]])
            number = max(int(e["id"].rsplit("-", 1)[1]) for e in state.data.encounters) + 1
            stamp = (body.now - timedelta(seconds=body.behind_seconds)).astimezone(UTC)
            record = {
                "id": f"reg-e-{number:07d}",
                "person_id": person["id"],
                "team_code": person["team_code"],
                "kind": "consultation",
                "occurred_on": stamp.date().isoformat(),
                "version": 1,
                "deleted": False,
                "updated_at": stamp.isoformat(),
            }
            state.data.encounters.append(record)
        return {"id": record["id"], "updated_at": record["updated_at"]}

    @router.post("/flaky")
    def flaky(body: Flaky) -> dict[str, int]:
        with state.lock:
            state.fail_next = body.next_requests
        return {"fail_next": body.next_requests}

    return router


def app_factory() -> FastAPI:
    as_of = os.environ.get("STANDIN_AS_OF", "").strip()  # an ISO date; a typo fails at start-up, not later
    return create_registry_app(
        seed=int(os.environ.get("STANDIN_SEED", "7")),
        subjects=int(os.environ.get("STANDIN_SUBJECTS", "600")),
        as_of=date.fromisoformat(as_of) if as_of else None,
        control=os.environ.get("STANDIN_CONTROL", "").lower() in {"1", "true", "yes"},
    )
