"""BFF dashboard read-model endpoints.

These endpoints serve pre-composed dashboard data by reading from
core-api and/or Redis.  All endpoints are read-only — no mutations.

Routing: Next.js proxy forwards /api/proxy/dashboard/* paths here.
Auth: Authorization header forwarded from the proxy unchanged.
Trace: x-request-id forwarded from proxy unchanged.
"""

from __future__ import annotations

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse

from services.dashboard_bff.http_client import get_client

router = APIRouter(tags=["read-model"])


@router.get("/overview")
async def dashboard_overview(
    authorization: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None, alias="x-request-id"),
) -> JSONResponse:
    """Compose a dashboard overview snapshot.

    Phase 1: fetches key surfaces from core-api in parallel and returns
    a unified payload.  Phase 2: adds Redis-cached enrichment.
    """
    client = get_client()

    fwd_headers: dict[str, str] = {"accept": "application/json"}
    if authorization:
        fwd_headers["authorization"] = authorization
    if x_request_id:
        fwd_headers["x-request-id"] = x_request_id

    # Parallel fetch from core-api.
    import asyncio

    status_req = client.get("/api/v1/status", headers=fwd_headers)
    health_req = client.get("/healthz")

    results = await asyncio.gather(status_req, health_req, return_exceptions=True)

    def _safe_json(result: object) -> object:
        if isinstance(result, BaseException):
            return {"error": str(result)}
        if hasattr(result, "json"):
            try:
                return result.json()  # type: ignore[union-attr]
            except Exception:
                return {"error": "invalid json"}
        return {"error": "unexpected result type"}

    payload = {
        "status": _safe_json(results[0]),
        "health": _safe_json(results[1]),
        "bff": {
            "surface": "bff",
            "phase": 1,
            "cache": "MISS",
        },
    }

    resp_headers: dict[str, str] = {
        "x-bff-cache": "MISS",
        "cache-control": "no-store",
    }
    if x_request_id:
        resp_headers["x-request-id"] = x_request_id

    return JSONResponse(payload, headers=resp_headers)


@router.get("/feed-status")
async def feed_status(
    authorization: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None, alias="x-request-id"),
) -> JSONResponse:
    """Ingest feed health summary for the dashboard.

    Phase 1: proxies /api/v1/feed-status from core-api.
    Phase 2: reads directly from Redis producer heartbeats.
    """
    client = get_client()

    fwd_headers: dict[str, str] = {"accept": "application/json"}
    if authorization:
        fwd_headers["authorization"] = authorization
    if x_request_id:
        fwd_headers["x-request-id"] = x_request_id

    try:
        resp = await client.get("/api/v1/feed-status", headers=fwd_headers)
        data = resp.json()
    except Exception as exc:
        data = {"error": "core-api unreachable from BFF", "detail": str(exc)}
        resp_headers: dict[str, str] = {"x-bff-cache": "MISS"}
        if x_request_id:
            resp_headers["x-request-id"] = x_request_id
        return JSONResponse(data, status_code=502, headers=resp_headers)

    resp_headers = {
        "x-bff-cache": "MISS",
        "cache-control": "no-store",
    }
    if x_request_id:
        resp_headers["x-request-id"] = x_request_id

    return JSONResponse(data, status_code=resp.status_code, headers=resp_headers)
