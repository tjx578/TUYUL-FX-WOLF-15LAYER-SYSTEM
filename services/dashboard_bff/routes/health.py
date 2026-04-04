"""BFF health endpoints — /healthz and /readyz.

These are the BFF's own liveness/readiness probes, separate from core-api.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from services.dashboard_bff.http_client import get_client

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> JSONResponse:
    """Liveness — is the BFF process alive?"""
    return JSONResponse({"status": "ok", "service": "dashboard-bff"})


@router.get("/health")
async def health_alias() -> JSONResponse:
    """Liveness alias."""
    return JSONResponse({"status": "ok", "service": "dashboard-bff"})


@router.get("/readyz")
async def readyz() -> JSONResponse:
    """Readiness — can the BFF serve traffic?

    Checks that the shared httpx client is open (i.e. core-api is
    reachable, barring network issues).
    """
    client = get_client()
    if client.is_closed:
        return JSONResponse(
            {"status": "not_ready", "reason": "http_client_closed"},
            status_code=503,
        )
    return JSONResponse({"status": "ready", "service": "dashboard-bff"})
