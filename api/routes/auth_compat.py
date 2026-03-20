"""
Auth Compat — session probe at ``/auth/session`` (no ``/api`` prefix).

The dashboard may call ``GET /auth/session`` directly (e.g. when the
Next.js rewrite layer is bypassed).  This shim validates the caller's
JWT / API-key via the same ``decode_token`` / ``validate_api_key``
helpers used by the primary ``/api/auth/session`` endpoint, and returns
a normalised response with ``authenticated``, ``user``, and
``expires_at`` fields.

The endpoint never raises 401 — it always returns 200 with
``authenticated: false`` when no valid credential is supplied.

Zone: api/ — read-only compatibility endpoint, no execution authority.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from ..middleware.auth import COOKIE_NAME, decode_token, validate_api_key

router: Final[APIRouter] = APIRouter(prefix="/auth", tags=["auth-compat"])


def _extract_bearer(authorization: str | None) -> str | None:
    """Return the raw token from ``Authorization: Bearer <tok>``."""
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def _build_user(payload: dict[str, Any]) -> dict[str, Any]:
    """Build a normalised user dict from a decoded JWT payload."""
    return {
        "user_id": str(payload.get("sub", "unknown")),
        "email": str(payload.get("email", payload.get("sub", "unknown"))),
        "role": str(payload.get("role", "viewer")),
        "name": payload.get("name"),
    }


def _expires_at_iso(payload: dict[str, Any]) -> str | None:
    """Return the ISO-8601 expiry from the JWT ``exp`` claim, or None."""
    exp = payload.get("exp")
    if exp is None:
        return None
    return datetime.fromtimestamp(int(exp), tz=UTC).isoformat()


@router.get("/session")
async def get_session(request: Request) -> JSONResponse:
    """Compatibility endpoint — always 200, with ``authenticated`` flag."""
    authorization = request.headers.get("authorization")
    raw_token = _extract_bearer(authorization)

    if raw_token is None:
        # Fallback: try HttpOnly session cookie
        raw_token = request.cookies.get(COOKIE_NAME)

    if raw_token is None:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "authenticated": False,
                "user": None,
                "expires_at": None,
            },
        )

    # Try JWT first
    payload = decode_token(raw_token)
    if payload is not None:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "authenticated": True,
                "user": _build_user(payload),
                "expires_at": _expires_at_iso(payload),
            },
        )

    # Fall back to static API key
    if validate_api_key(raw_token):
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "authenticated": True,
                "user": _build_user({"sub": "api_key_user", "auth_method": "api_key"}),
                "expires_at": None,
            },
        )

    # Invalid token — not authenticated, but still 200
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "authenticated": False,
            "user": None,
            "expires_at": None,
        },
    )
