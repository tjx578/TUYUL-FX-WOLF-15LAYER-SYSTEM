"""
Auth Router — owner-only session management.

This is a private owner dashboard.  There is no public-user login flow.
Authentication is owner-only: the Next.js middleware injects a server-side
API key or session cookie for every proxied request.

Endpoints:
  POST /auth/owner-session — canonical owner auth (header-based, no body key).
  GET  /auth/session       — validate JWT (header or cookie), return SessionUser.
  POST /auth/refresh       — re-issue JWT from still-valid token, update cookie.
  POST /auth/logout        — clear session cookie.
  POST /auth/login         — DEPRECATED: body-based API-key login (backward compat).

The response shape matches the Zod ``SessionUserSchema`` in
dashboard/nextjs/src/schema/authSchema.ts:

    { user_id: str, email: str, role: str, name?: str }

Auth model contract (see docs/architecture/dashboard-control-surface.md):
  - public-user login semantics are NOT the primary architecture
  - browser-facing API key fallback is NOT allowed
  - machine/service API keys must remain machine-only
  - owner identity must be explicit and bounded
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

# ── Owner session (canonical) ─────────────────────────────────────────────────


@router.post("/owner-session")
async def owner_session(
    response: Response,
    payload: dict[str, Any] = Depends(verify_token),  # noqa: B008
) -> dict[str, Any]:
    """Canonical owner-session initialization — header-based auth only.

    The caller must present a valid ``Authorization: Bearer <jwt_or_api_key>``
    header.  In normal operation, Next.js middleware injects this server-side
    so the raw API key never reaches the browser.

    Returns a fresh owner-scoped JWT and sets the HttpOnly session cookie.
    Browser-facing API key submission is NOT allowed on this endpoint.
    """
    token = create_token(
        sub=str(payload.get("sub", "owner")),
        extra={
            "email": str(payload.get("email", "owner@tuyulfx.com")),
            "role": str(payload.get("role", "owner")),
            "name": payload.get("name", "TUYUL FX Owner"),
            "auth_method": "owner_session",
        },
    )
    set_auth_cookie(response, token)
    user = _session_from_payload(
        {
            "sub": payload.get("sub", "owner"),
            "email": payload.get("email", "owner@tuyulfx.com"),
            "role": payload.get("role", "owner"),
            "name": payload.get("name", "TUYUL FX Owner"),
        },
    )
    return {"token": token, **user.model_dump()}


# ── Deprecated login (backward compat) ────────────────────────────────────────


class LoginRequest(BaseModel):
    """Request body for POST /auth/login.  DEPRECATED — use /auth/owner-session."""

    api_key: str = Field(..., min_length=1)


@router.post("/login", deprecated=True)
async def login(body: LoginRequest, response: Response) -> dict[str, Any]:
    """DEPRECATED — use ``POST /auth/owner-session`` instead.

    This endpoint accepts a raw API key in the request body, which is a
    browser-facing API-key pattern.  New integrations must use
    ``/auth/owner-session`` with header-based auth.
    """
    logger.warning("[auth] POST /auth/login is deprecated — migrate to POST /auth/owner-session")
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
