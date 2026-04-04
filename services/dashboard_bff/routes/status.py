"""BFF aggregated status endpoint.

Fetches /api/v1/status from core-api and enriches it with BFF-layer
metadata.  This is the BFF equivalent of the operator status surface —
it composes data from core-api but does not replace it.

Routing: Next.js proxy forwards /api/proxy/bff/aggregated-status here.
Auth: Authorization header forwarded from the proxy unchanged.
Trace: x-request-id forwarded from proxy unchanged.
"""

from __future__ import annotations

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from services.dashboard_bff.http_client import get_client

router = APIRouter(tags=["status"])


@router.get("/aggregated-status")
async def aggregated_status(
    request: Request,
    authorization: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None, alias="x-request-id"),
) -> JSONResponse:
    """Compose an aggregated operator status from core-api.

    Phase 1: simple pass-through with BFF metadata.
    Phase 2: multi-source composition (core-api + Redis + ingest health).
    """
    client = get_client()

    # Build headers to forward — auth + trace ID.
    fwd_headers: dict[str, str] = {"accept": "application/json"}
    if authorization:
        fwd_headers["authorization"] = authorization
    if x_request_id:
        fwd_headers["x-request-id"] = x_request_id

    try:
        resp = await client.get("/api/v1/status", headers=fwd_headers)
        core_data = resp.json()
    except Exception as exc:
        return JSONResponse(
            {
                "error": "core-api unreachable from BFF",
                "detail": str(exc),
                "surface": "bff",
            },
            status_code=502,
            headers=_trace_headers(x_request_id),
        )

    # Enrich with BFF metadata.
    payload = {
        "core_status": core_data,
        "bff": {
            "surface": "bff",
            "phase": 1,
            "cache": "MISS",  # Phase 1: no caching yet
        },
    }

    return JSONResponse(
        payload,
        status_code=resp.status_code,
        headers=_trace_headers(x_request_id),
    )


def _trace_headers(request_id: str | None) -> dict[str, str]:
    headers: dict[str, str] = {
        "x-bff-cache": "MISS",
        "cache-control": "no-store",
    }
    if request_id:
        headers["x-request-id"] = request_id
    return headers
