"""The application factory."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from pulse.api.lab import build_lab_router
from pulse.api.routes import build_live_router, build_router
from pulse.api.security import Headers, LabGate, api_key_dependency
from pulse.config import Settings, get_settings
from pulse.health import collect, rollup
from pulse.services import Services


def create_app(settings: Settings | None = None, services: Services | None = None) -> FastAPI:
    settings = settings or get_settings()
    services = services or Services(settings)
    app = FastAPI(
        title="pulse",
        version="0.1.0",
        docs_url="/api/docs" if settings.lab_mode else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.lab_mode else None,
    )
    app.state.services = services

    app.add_middleware(Headers)
    if settings.lab_mode:
        app.add_middleware(LabGate)  # added last, so it runs first

    app.include_router(build_live_router())
    app.include_router(build_router(services, api_key_dependency(settings)))
    if settings.lab_mode:
        app.include_router(build_lab_router(services), dependencies=[])

    @app.get("/health/ready", response_model=None)
    def ready() -> Any:
        checks = collect(services.engine, services.clock, services.ping_broker)
        status = rollup(checks)
        body = {"status": status, "checks": [{"component": c.component, "status": c.status} for c in checks]}
        return JSONResponse(body, status_code=503 if status == "down" else 200)

    if settings.site_dir:
        site = Path(settings.site_dir)
        if not site.is_dir():
            raise ValueError(f"SITE_DIR is not a directory: {site}")
        app.mount("/", StaticFiles(directory=site, html=True), name="site")  # last: every route above wins
    return app


def app_factory() -> FastAPI:  # uvicorn --factory pulse.api.app:app_factory
    return create_app()
