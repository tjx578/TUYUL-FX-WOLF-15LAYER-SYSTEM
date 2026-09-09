"""
Auth Router — owner-only session management.

This is a private owner dashboard.  There is no public-user login flow.
Authentication is owner-only: the Next.js middleware injects a server-side
API key or session cookie for every proxied request.

Endpoints:
  POST /auth/owner-login   — bounded human-password exchange for a viewer JWT.
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

import base64
import hashlib
import hmac
import os
import threading
import time
from collections import deque
from typing import Any

import anyio
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

OWNER_SESSION_SECONDS = 15 * 60
OWNER_VIEWER_SUBJECT = "dashboard-owner-viewer"


class _OwnerLoginGate:
    """Bound hashing per worker, including direct core requests.

    Five admissions per rolling minute, one active hash, no hash queue.
    Deliberately not keyed by attacker-controlled usernames/proxy headers.
    Replicas/workers have separate budgets; restart resets this local budget.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._attempts: deque[float] = deque()
        self._active = False

    def acquire(self) -> bool:
        now = time.monotonic()
        with self._lock:
            while self._attempts and self._attempts[0] <= now - 60:
                self._attempts.popleft()
            if self._active or len(self._attempts) >= 5:
                return False
            self._attempts.append(now)
            self._active = True
            return True

    def release(self) -> None:
        with self._lock:
            self._active = False


_owner_login_gate = _OwnerLoginGate()


# ── Response model ────────────────────────────────────────────────────────────


class SessionUserResponse(BaseModel):
    """Matches the frontend SessionUserSchema (Zod)."""

    user_id: str = Field(..., min_length=1)
    email: str
    role: str
    name: str | None = None
    scopes: list[str] = Field(default_factory=list)
    auth_method: str


class RefreshResponse(SessionUserResponse):
    """Refresh response includes the new JWT alongside user info."""

    token: str


class OwnerLoginRequest(BaseModel):
    """Human owner credentials; never accepts a machine API key."""

    username: str = Field(..., min_length=1, max_length=254)
    password: str = Field(..., min_length=1, max_length=1024)


class OwnerLoginResponse(BaseModel):
    """Server-to-server response consumed by the Next.js session boundary."""

    token: str


# ── Helpers ───────────────────────────────────────────────────────────────────


def _session_from_payload(payload: dict[str, Any]) -> SessionUserResponse:
    """
    Extract SessionUser fields from a decoded JWT payload.

    The JWT ``sub`` claim is used as ``user_id``.  ``email``, ``role``, and
    ``name`` are pulled from extra claims embedded at token-creation time.
    Falls back to sensible defaults so the endpoint never 500s for a valid JWT.
    """
    raw_scopes = payload.get("scopes", payload.get("scope", []))
    if isinstance(raw_scopes, str):
        scopes = raw_scopes.split()
    elif isinstance(raw_scopes, (list, tuple, set)):
        scopes = [str(scope) for scope in raw_scopes if str(scope)]
    else:
        scopes = []

    return SessionUserResponse(
        user_id=str(payload.get("sub", "unknown")),
        email=str(payload.get("email", payload.get("sub", "unknown"))),
        role=str(payload.get("role", "unknown")),
        name=payload.get("name"),
        scopes=sorted(set(scopes)),
        auth_method=str(payload.get("auth_method", "unknown")),
    )


def _verify_owner_password(password: str, encoded: str) -> bool:
    """Verify ``pbkdf2_sha256$iterations$salt_b64$digest_b64`` fail-closed."""
    try:
        algorithm, raw_iterations, salt_b64, digest_b64 = encoded.split("$", 3)
        iterations = int(raw_iterations)
        if algorithm != "pbkdf2_sha256" or not 210_000 <= iterations <= 2_000_000:
            return False
        if len(encoded) > 256:
            return False
        salt = base64.urlsafe_b64decode(salt_b64 + "=" * (-len(salt_b64) % 4))
        expected = base64.urlsafe_b64decode(digest_b64 + "=" * (-len(digest_b64) % 4))
        if len(salt) < 16 or len(expected) != 32:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except (TypeError, ValueError, UnicodeError):
        return False


def _owner_credentials_valid(username: str, password: str) -> bool:
    configured_username = os.getenv("DASHBOARD_OWNER_USERNAME", "").strip()
    password_hash = os.getenv("DASHBOARD_OWNER_PASSWORD_HASH", "").strip()
    if not configured_username or not password_hash:
        return False
    try:
        username_ok = hmac.compare_digest(username.strip().encode(), configured_username.encode())
    except UnicodeError:
        return False
    password_ok = _verify_owner_password(password, password_hash)
    return username_ok and password_ok


# ── Endpoints ─────────────────────────────────────────────────────────────────


def _require_renewable_session(payload: dict[str, Any]) -> None:
    # verify_token replaces auth_method with the transport used. The signed,
    # reserved subject survives every legacy exchange and identifies this flow.
    if payload.get("sub") == OWNER_VIEWER_SUBJECT:
        raise HTTPException(
            status_code=403,
            detail="Password reauthentication required",
            headers={"Cache-Control": "no-store"},
        )


@router.post("/owner-login", response_model=OwnerLoginResponse)
async def owner_login(body: OwnerLoginRequest, response: Response) -> OwnerLoginResponse:
    """Exchange owner credentials for a short-lived read-only viewer JWT."""
    gate = _owner_login_gate
    if not gate.acquire():
        raise HTTPException(
            status_code=429,
            detail="Try again later",
            headers={"Retry-After": "60", "Cache-Control": "no-store"},
        )

    def verify() -> bool:
        try:
            return _owner_credentials_valid(body.username, body.password)
        finally:
            # Release in the worker, not when a disconnected caller cancels.
            gate.release()

    with anyio.CancelScope(shield=True):
        valid = await anyio.to_thread.run_sync(verify, abandon_on_cancel=False)
    if not valid:
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
            headers={"Cache-Control": "no-store"},
        )

    now = int(time.time())
    token = create_token(
        sub=OWNER_VIEWER_SUBJECT,
        extra={
            "email": body.username.strip(),
            "name": "WOLF15 Owner",
            "role": "viewer",
            "scopes": ["read:dashboard"],
            "auth_method": "owner_password",
            "iat": now,
            "exp": now + OWNER_SESSION_SECONDS,
        },
    )
    response.headers["Cache-Control"] = "no-store"
    return OwnerLoginResponse(token=token)


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
    _require_renewable_session(payload)
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
        _require_renewable_session(payload)
        token = create_token(
            sub=str(payload.get("sub", "dashboard")),
            extra={k: payload[k] for k in ("email", "role", "name", "scope", "scopes") if k in payload},
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

    Legacy sessions refresh their cookie. Password-issued owner viewer sessions
    are validation-only so polling cannot extend their absolute expiry.
    """
    if payload.get("sub") and payload.get("sub") != OWNER_VIEWER_SUBJECT:
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
    _require_renewable_session(payload)
    extra: dict[str, Any] = {}
    for key in ("email", "role", "name", "scope", "scopes"):
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
