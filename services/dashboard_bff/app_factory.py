"""Dashboard BFF — FastAPI application factory.

Creates a minimal FastAPI app scoped to dashboard-specific aggregation
and read-model endpoints.  The BFF is non-authoritative: it reads from
core-api and/or Redis, composes dashboard-friendly payloads, and returns
them.  It never produces verdicts, risk decisions, or execution commands.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from services.dashboard_bff.http_client import close_client, get_client


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Startup: eagerly create the shared client so first request is fast.
    logger.info("[bff] Starting dashboard-bff service")
    get_client()
    yield
    # Shutdown: close the shared httpx pool.
    logger.info("[bff] Shutting down dashboard-bff service")
    await close_client()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Wolf-15 Dashboard BFF",
        description="Non-authoritative backend-for-frontend for dashboard aggregation.",
        version="0.1.0",
        docs_url="/docs" if os.getenv("APP_ENV") != "production" else None,
        redoc_url=None,
        lifespan=_lifespan,
    )

    # ── Routes ────────────────────────────────────────────────────────────
    from services.dashboard_bff.routes.health import router as health_router
    from services.dashboard_bff.routes.read_model import router as read_model_router
    from services.dashboard_bff.routes.status import router as status_router

    app.include_router(health_router)
    app.include_router(status_router, prefix="/api/bff")
    app.include_router(read_model_router, prefix="/api/dashboard")

    return app
