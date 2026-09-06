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
    """Readiness — can the BFF reach a healthy core-api dependency?"""
    client = get_client()
    try:
        response = await client.get("/healthz")
    except Exception:
        return JSONResponse(
            {"status": "not_ready", "reason": "core_api_unavailable"},
            status_code=503,
        )
    if not response.is_success:
        return JSONResponse(
            {"status": "not_ready", "reason": "core_api_unhealthy"},
            status_code=503,
        )
    return JSONResponse({"status": "ready", "service": "dashboard-bff"})
