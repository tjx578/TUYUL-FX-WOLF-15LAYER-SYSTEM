"""
Auth Router — session validation, login, logout, and token refresh.

Endpoints:
  POST /auth/login    — validate API key, issue JWT, set HttpOnly cookie.
  GET  /auth/session  — validate JWT (header or cookie), return SessionUser.
  POST /auth/refresh  — issue a fresh JWT from a still-valid token, update cookie.
  POST /auth/logout   — clear session cookie.

The dashboard frontend (Next.js) calls these on every page render and
on periodic client-side refresh.  The response shape matches the Zod
``SessionUserSchema`` defined in dashboard/nextjs/src/schema/authSchema.ts:

    { user_id: str, email: str, role: str, name?: str }
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from loguru import logger
from pydantic import BaseModel, Field

from .middleware.auth import (
    clear_auth_cookie,
    create_token,
    decode_token,
    set_auth_cookie,
    validate_api_key,
    verify_token,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ── Response model ────────────────────────────────────────────────────────────


class SessionUserResponse(BaseModel):
    """Matches the frontend SessionUserSchema (Zod)."""

    user_id: str = Field(..., min_length=1)
    email: str
    role: str
    name: str | None = None


class RefreshResponse(SessionUserResponse):
    """Refresh response includes the new JWT alongside user info."""

    token: str


# ── Helpers ───────────────────────────────────────────────────────────────────


def _session_from_payload(payload: dict[str, Any]) -> SessionUserResponse:
    """
    Extract SessionUser fields from a decoded JWT payload.

    The JWT ``sub`` claim is used as ``user_id``.  ``email``, ``role``, and
    ``name`` are pulled from extra claims embedded at token-creation time.
    Falls back to sensible defaults so the endpoint never 500s for a valid JWT.
    """
    return SessionUserResponse(
        user_id=str(payload.get("sub", "unknown")),
        email=str(payload.get("email", payload.get("sub", "unknown"))),
        role=str(payload.get("role", "viewer")),
        name=payload.get("name"),
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────


class LoginRequest(BaseModel):
    """Request body for POST /auth/login."""

    api_key: str = Field(..., min_length=1)


@router.post("/login")
async def login(body: LoginRequest, response: Response) -> dict[str, Any]:
    """
    Authenticate with an API key and receive a JWT + HttpOnly session cookie.

    The cookie is set automatically; the ``token`` field in the response body
    allows the frontend to store it for WebSocket auth (query-param based)
    or as a fallback for clients that cannot use cookies.
    """
    from .middleware.auth import API_KEY as CONFIGURED_API_KEY  # noqa: N811

    key = body.api_key.strip()

    # Try as JWT first (allows login with existing valid JWT)
    payload = decode_token(key)
    if payload is not None:
        token = create_token(
            sub=str(payload.get("sub", "dashboard")),
            extra={k: payload[k] for k in ("email", "role", "name") if k in payload},
        )
        set_auth_cookie(response, token)
        user = _session_from_payload(payload)
        return {"token": token, **user.model_dump()}

    # Try as static API key
    if validate_api_key(key):
        token = create_token(sub="api_key_user", extra={"role": "operator", "auth_method": "api_key"})
        set_auth_cookie(response, token)
        user = _session_from_payload({"sub": "api_key_user", "role": "operator", "auth_method": "api_key"})
        return {"token": token, **user.model_dump()}

    # Diagnostic logging — never log actual keys, only metadata
    logger.warning(
        "Login failed: DASHBOARD_API_KEY configured={}, key_len_match={}, jwt_decode={}",
        bool(CONFIGURED_API_KEY),
        len(key) == len(CONFIGURED_API_KEY) if CONFIGURED_API_KEY else "N/A",
        "no",
    )
    detail = "Invalid API key"
    if not CONFIGURED_API_KEY:
        detail = "Server misconfiguration: DASHBOARD_API_KEY not set"
        logger.error("DASHBOARD_API_KEY env var is empty — all login attempts will fail")
    raise HTTPException(status_code=401, detail=detail)


@router.get("/session", response_model=SessionUserResponse)
async def get_session(
    response: Response,
    payload: dict[str, Any] = Depends(verify_token),  # noqa: B008
) -> SessionUserResponse:
    """
    Validate the caller's JWT / API key and return the session user.

    On success, refreshes the session cookie to extend its lifetime.
    """
    if payload.get("sub"):
        token = create_token(
            sub=str(payload.get("sub", "dashboard")),
            extra={k: payload[k] for k in ("email", "role", "name") if k in payload},
        )
        set_auth_cookie(response, token)
    return _session_from_payload(payload)


@router.post("/refresh", response_model=RefreshResponse)
async def refresh_session(
    response: Response,
    payload: dict[str, Any] = Depends(verify_token),  # noqa: B008
) -> dict[str, Any]:
    """
    Issue a fresh JWT from a still-valid token, update the HttpOnly cookie.
    """
    extra: dict[str, Any] = {}
    for key in ("email", "role", "name"):
        if key in payload:
            extra[key] = payload[key]

    new_token = create_token(sub=str(payload.get("sub", "dashboard")), extra=extra or None)
    set_auth_cookie(response, new_token)
    user = _session_from_payload(payload)

    return {
        "token": new_token,
        **user.model_dump(),
    }


@router.post("/logout")
async def logout(response: Response) -> dict[str, str]:
    """Clear the session cookie."""
    clear_auth_cookie(response)
    return {"status": "logged_out"}
