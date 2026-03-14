"""
Auth Compat — read-only session probe for legacy frontend.

The old dashboard calls ``GET /auth/session`` (without ``/api`` prefix)
and expects a 200 with an ``authenticated`` boolean regardless of auth
state.  This compatibility shim satisfies that contract without granting
any execution authority.

Zone: api/ — read-only compatibility endpoint.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

router: Final[APIRouter] = APIRouter(prefix="/auth", tags=["auth-compat"])


@router.get("/session")
async def get_session(request: Request) -> JSONResponse:
    """Compatibility endpoint for dashboard session probing."""
    user = getattr(request.state, "user", None)

    if user is None:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "authenticated": False,
                "user": None,
                "expires_at": None,
                "server_time": datetime.now(UTC).isoformat(),
            },
        )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "authenticated": True,
            "user": {
                "id": str(getattr(user, "id", "")),
                "email": getattr(user, "email", None),
                "role": getattr(user, "role", "viewer"),
            },
            "expires_at": None,
            "server_time": datetime.now(UTC).isoformat(),
        },
    )
