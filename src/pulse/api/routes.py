"""The JSON API."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text

from pulse.db import LAB_AUTOPILOT_KEY, LAB_NARRATOR_KEY, iso, lab_get
from pulse.exchange import queue
from pulse.exchange.worker import drain
from pulse.health import collect, rollup, uptime
from pulse.indicators.lab_narrators import NARRATORS
from pulse.indicators.narrative import TemplateNarrator, narrate
from pulse.indicators.report import build_report
from pulse.search.evaluate import evaluate
from pulse.search.store import MODES, Mode, search
from pulse.services import Services
from pulse.sync import SyncResult


class SyncRequest(BaseModel):
    full: bool = False


def sync_dict(result: SyncResult) -> dict[str, Any]:
    return {
        "status": result.status,
        "run_id": result.run_id,
        "error": result.error,
        "queued": result.queued,
        "entities": {name: asdict(e) for name, e in result.entities.items()},
        "totals": {k: result.total(k) for k in ("pages", "fetched", "applied", "stale", "rejected")},
    }


def build_live_router() -> APIRouter:
    router = APIRouter()

    @router.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "ok"}

    return router


def build_router(services: Services, auth: Any) -> APIRouter:
    router = APIRouter(prefix="/api", dependencies=[Depends(auth)])
    engine, clock, settings = services.engine, services.clock, services.settings

    def current_narrator() -> Any:
        if not settings.lab_mode:
            return TemplateNarrator()
        with engine.connect() as conn:
            return NARRATORS.get(str(lab_get(conn, LAB_NARRATOR_KEY, "template")), TemplateNarrator())

    @router.get("/health")
    def health() -> dict[str, Any]:
        checks = collect(engine, clock, services.ping_broker)
        return {
            "status": rollup(checks),
            "checks": [asdict(c) for c in checks],
            "uptime": [uptime(engine, clock, c.component) for c in checks],
        }

    @router.post("/sync/run")
    def sync_run(body: SyncRequest | None = None) -> dict[str, Any]:
        return sync_dict(services.syncer().run(full=bool(body and body.full)))

    @router.get("/sync/runs")
    def sync_runs(limit: int = Query(10, ge=1, le=100)) -> dict[str, Any]:
        with engine.connect() as conn:
            rows = (
                conn.execute(text("SELECT * FROM sync_runs ORDER BY id DESC LIMIT :n"), {"n": limit}).mappings().all()
            )
            state = conn.execute(text("SELECT entity, cursor_updated_at FROM sync_state ORDER BY entity")).all()
        return {
            "runs": [
                {**dict(r), "started_at": iso(r["started_at"]), "finished_at": iso(r["finished_at"])} for r in rows
            ],
            "positions": {e: {"updated_at": iso(at)} for e, at in state},
        }

    @router.get("/queue")
    def queue_state() -> dict[str, Any]:
        with engine.connect() as conn:
            attempts = conn.execute(
                text(
                    "SELECT a.outbox_id, a.at, a.outcome, a.http_status, a.detail FROM outbox_attempts a "
                    "ORDER BY a.id DESC LIMIT 12"
                )
            ).all()
            due = conn.execute(
                text(
                    "SELECT count(*) FROM outbox WHERE (status = 'pending' AND not_before <= :now) "
                    "OR (status = 'sending' AND lease_until < :now)"
                ),
                {"now": clock.now()},
            ).scalar()
            sample = conn.execute(
                text(
                    "SELECT id, status, attempts, not_before, lease_until, last_status, last_error FROM outbox "
                    "WHERE status <> 'done' ORDER BY id LIMIT 8"
                )
            ).all()
        return {
            "counts": queue.counts(engine),
            "due_now": int(due or 0),
            "now": iso(clock.now()),
            "waiting": [
                {
                    "id": r.id,
                    "status": r.status,
                    "attempts": r.attempts,
                    "not_before": iso(r.not_before),
                    "lease_until": iso(r.lease_until),
                    "last_status": r.last_status,
                    "last_error": r.last_error,
                }
                for r in sample
            ],
            "recent_attempts": [
                {
                    "message": r.outbox_id,
                    "at": iso(r.at),
                    "outcome": r.outcome,
                    "http_status": r.http_status,
                    "detail": r.detail,
                }
                for r in attempts
            ],
            "limits": {"max_attempts": settings.queue_max_attempts, "lease_seconds": settings.queue_lease_seconds},
        }

    @router.post("/queue/drain")
    def queue_drain() -> dict[str, Any]:
        report = drain(
            engine,
            services.gateway,
            clock,
            worker="api",
            batch=settings.queue_batch,
            lease_seconds=settings.queue_lease_seconds,
            max_attempts=settings.queue_max_attempts,
            backoff_base=settings.queue_backoff_base_seconds,
            backoff_cap=settings.queue_backoff_cap_seconds,
        )
        return asdict(report)

    @router.get("/indicators")
    def indicators(as_of: date | None = None, narrate_it: bool = Query(False, alias="narrate")) -> dict[str, Any]:
        report = build_report(engine, as_of or clock.now().date()).to_dict()
        if narrate_it:
            narration = narrate(report, current_narrator())
            report["narration"] = {
                "text": narration.text,
                "accepted": narration.accepted,
                "source": narration.source,
                "violations": list(narration.violations),
            }
        return report

    @router.get("/search")
    def search_endpoint(
        q: str = Query(min_length=1, max_length=200), mode: Mode = "hybrid", k: int = Query(5, ge=1, le=20)
    ) -> dict[str, Any]:
        if mode not in MODES:
            raise HTTPException(422, "unknown mode")
        hits = search(engine, services.embedder, q, mode, k=k, rrf_k=settings.search_rrf_k)
        return {"query": q, "mode": mode, "hits": [asdict(h) for h in hits]}

    @router.get("/search/eval")
    def search_eval() -> dict[str, Any]:
        table = evaluate(engine, services.embedder)
        return {mode: {kind: asdict(score) for kind, score in row.items()} for mode, row in table.items()}

    @router.get("/overview")
    def overview() -> dict[str, Any]:
        with engine.connect() as conn:

            def count(table: str) -> int:  # the names come from the fixed tuple below, never from a request
                return int(conn.execute(text(f"SELECT count(*) FROM {table}")).scalar() or 0)  # noqa: S608

            data = {t: count(t) for t in ("teams", "subjects", "encounters", "kb_chunks")}
            lab: dict[str, Any] = {}
            if settings.lab_mode:
                lab = {
                    "autopilot": bool(lab_get(conn, LAB_AUTOPILOT_KEY, False)),
                    "narrator": lab_get(conn, LAB_NARRATOR_KEY, "template"),
                }
        return {"lab": settings.lab_mode, "now": iso(clock.now()), "data": data, "queue": queue.counts(engine), **lab}

    return router
