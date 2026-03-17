"""WebSocket Authentication — canonical token validation for WS connections.

This is the **single source of truth** for WebSocket authentication.
Both HTTP and WS endpoints share the same JWT / API-key verifiers via
``dashboard.backend.auth``.  Do NOT add a parallel auth system.

Provides:
  - ``extract_token()``     -- pull token from Authorization header OR query param.
  - ``verify_token()``      -- validate a raw token string, return payload or None.
  - ``ws_authenticate()``   -- validates token, sets websocket.state.user, returns bool.
  - ``ws_auth_guard()``     -- high-level guard returning payload dict or None.
  - ``require_ws_token()``  -- FastAPI dependency for WebSocket endpoints.

All JWT tokens are validated via the unified ``dashboard.backend.auth`` module
(HMAC-SHA256, canonical secret ``DASHBOARD_JWT_SECRET``). This keeps HTTP and
WebSocket authentication on one compatible trust boundary.

See also:
  - ``dashboard.backend.auth.verify_token`` (HTTP FastAPI Depends)
  - ``dashboard.backend.auth.verify_ws_token`` (WS FastAPI Depends via query)
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import time
from typing import Any

import fastapi
from fastapi import WebSocket

from api.middleware.auth import decode_token, validate_api_key

logger = logging.getLogger(__name__)

_WS_ALLOWED_ORIGINS_RAW = os.getenv("WS_ALLOWED_ORIGINS", "").strip()
# If WS_ALLOWED_ORIGINS is not explicitly set, inherit from CORS_ORIGINS so
# the Vercel frontend domain is automatically allowed for WebSocket connections.
_ws_origins_source = _WS_ALLOWED_ORIGINS_RAW or os.getenv("CORS_ORIGINS", "").strip()

WS_ALLOWED_ORIGINS = {origin.strip().rstrip("/") for origin in _ws_origins_source.split(",") if origin.strip()}
# Also pick up VERCEL_FRONTEND_URL if set (matches CORS logic in app_factory).
_vercel_url = os.getenv("VERCEL_FRONTEND_URL", "").strip()
if _vercel_url:
    for u in _vercel_url.split(","):
        u = u.strip().rstrip("/")
        if u:
            WS_ALLOWED_ORIGINS.add(u)

# Regex pattern for dynamic origins (e.g. Vercel preview deployments).
# Set CORS_ORIGIN_REGEX to a regex like r"https://tuyul-fx-.*\.vercel\.app"
_ORIGIN_REGEX_RAW = os.getenv("CORS_ORIGIN_REGEX", "").strip()
_ORIGIN_REGEX: re.Pattern[str] | None = None
if _ORIGIN_REGEX_RAW:
    try:
        _ORIGIN_REGEX = re.compile(_ORIGIN_REGEX_RAW)
    except re.error:
        logger.error("Invalid CORS_ORIGIN_REGEX: %s", _ORIGIN_REGEX_RAW)
else:
    # Auto-derive regex for Vercel preview deployments from static origins.
    # Preview URLs follow the pattern: <project>-<hash>-<scope>.vercel.app
    _vercel_patterns: list[str] = []
    for _o in WS_ALLOWED_ORIGINS:
        if _o.endswith(".vercel.app"):
            _prefix = re.escape(_o.rsplit(".vercel.app", 1)[0])
            _vercel_patterns.append(f"{_prefix}(-[a-z0-9-]+)?\\.vercel\\.app")
    if _vercel_patterns:
        with contextlib.suppress(re.error):
            _ORIGIN_REGEX = re.compile("|".join(_vercel_patterns))


def _is_origin_allowed(origin: str) -> bool:
    """Check origin against exact set and optional regex pattern."""
    if origin in WS_ALLOWED_ORIGINS:
        return True
    return bool(_ORIGIN_REGEX is not None and _ORIGIN_REGEX.fullmatch(origin))


class WSAuthError(Exception):
    """Raised when WebSocket authentication fails."""


# ---------------------------------------------------------------------------
# Shared helpers — usable by both HTTP and WS layers
# ---------------------------------------------------------------------------


def extract_token(headers: dict[str, str], query_params: dict[str, str]) -> str | None:
    """Extract a bearer token from headers or a ``token`` query param.

    Lookup order:
      1. ``?token=<token>`` query parameter (preferred for WS)
      2. ``Authorization: Bearer <token>`` header

    Returns the raw token string, or ``None`` if absent.
    """
    # 1. Query parameter (preferred for WS)
    token = query_params.get("token")
    if token:
        return token

    # 2. Authorization header
    auth = headers.get("authorization") or headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    if auth:
        return auth

    return None


def verify_token(token: str) -> dict[str, Any] | None:
    """Validate a raw token string (JWT or API key).

    Delegates to ``dashboard.backend.auth.decode_token`` and
    ``validate_api_key`` — the same verifiers used for HTTP routes.

    Returns:
        Payload dict on success, ``None`` on failure.
    """
    with contextlib.suppress(Exception):
        payload = decode_token(token)
        if payload is not None:
            return payload

    with contextlib.suppress(Exception):
        result = validate_api_key(token)
        if result:
            return {"sub": "api_key_user", "auth_method": "api_key"}

    return None


def _claim_set(payload: dict[str, Any], key: str) -> set[str]:
    raw = payload.get(key)
    out: set[str] = set()
    if isinstance(raw, str):
        out.update(part for part in raw.replace(",", " ").split() if part)
    elif isinstance(raw, list):
        out.update(str(item).strip() for item in raw if str(item).strip())
    return out


def _has_account_access(payload: dict[str, Any], requested_account: str | None) -> bool:
    role = str(payload.get("role", "")).strip().lower()
    if role == "admin":
        return True

    account_claim = str(payload.get("account_id") or payload.get("account") or "").strip().upper()
    allowed_accounts = {a.upper() for a in _claim_set(payload, "accounts")}
    scopes = _claim_set(payload, "scopes") | _claim_set(payload, "scope")

    if not requested_account:
        return bool(account_claim or allowed_accounts or "account:*" in scopes)

    account = requested_account.strip().upper()
    if account_claim and account_claim == account:
        return True

    if account in allowed_accounts:
        return True

    return bool("account:*" in scopes or f"account:{account}" in scopes)


async def ws_authenticate(websocket: WebSocket) -> bool:
    """
    Authenticate a WebSocket connection via query-param token.

    Reads ``?token=<jwt_or_api_key>`` from the URL.  On success, sets
    ``websocket.state.user`` to the subject claim and returns ``True``.
    On failure, closes the connection with code 4401 and returns ``False``.
    """
    token = extract_token(dict(websocket.headers), dict(websocket.query_params))  # noqa: F821
    if not token:
        await websocket.close(code=4401, reason="Missing authentication token")
        return False

    payload = verify_token(token)
    if payload is not None:
        websocket.state.user = payload.get("sub")
        websocket.state.auth_payload = payload
        logger.debug(f"WS auth OK: user={websocket.state.user}")
        return True

    await websocket.close(code=4401, reason="Invalid or expired token")
    return False


async def ws_auth_guard(websocket: WebSocket) -> dict[str, Any] | None:
    """
    High-level WebSocket auth guard for route handlers.

    Usage::

        @router.websocket("/ws/prices")
        async def price_stream(websocket: WebSocket):
            user = await ws_auth_guard(websocket)
            if not user:
                return  # Connection already closed
            # ... handle authenticated connection

    Returns:
        User payload dict if authenticated, ``None`` if auth failed.
    """
    if WS_ALLOWED_ORIGINS or _ORIGIN_REGEX:
        origin = (websocket.headers.get("origin") or "").strip().rstrip("/")
        if origin and not _is_origin_allowed(origin):
            # Browser client with a disallowed origin — reject immediately.
            logger.warning("WS auth rejected: forbidden origin %s", origin)
            with contextlib.suppress(Exception):
                await websocket.close(code=4003, reason="Forbidden origin")
            return None
        # No origin header = non-browser client (EA, service-to-service).
        # Allow through; token validation below will still gate access.

    token = extract_token(dict(websocket.headers), dict(websocket.query_params))
    if not token:
        logger.warning("WS auth rejected: missing token")
        with contextlib.suppress(Exception):
            await websocket.close(code=4001, reason="Missing authentication token")
        return None

    payload = verify_token(token)
    if payload is not None:
        if payload.get("auth_method") != "api_key":
            exp = payload.get("exp")
            if exp is None:
                logger.warning("WS auth rejected: JWT missing exp claim")
                with contextlib.suppress(Exception):
                    await websocket.close(code=4001, reason="Token missing exp claim")
                return None
            if int(exp) <= int(time.time()):
                logger.warning("WS auth rejected: token expired")
                with contextlib.suppress(Exception):
                    await websocket.close(code=4001, reason="Token expired")
                return None

        requested_account = websocket.query_params.get("account_id")
        if not _has_account_access(payload, requested_account):
            logger.warning("WS auth rejected: account scope denied")
            with contextlib.suppress(Exception):
                await websocket.close(code=4003, reason="Account scope denied")
            return None

        websocket.state.auth_payload = payload
        websocket.state.auth_exp = int(payload.get("exp", 0) or 0)
        logger.debug(f"WS auth OK: user={payload.get('sub')}")
        return payload

    logger.warning("WS auth rejected: invalid or expired token")
    with contextlib.suppress(Exception):
        await websocket.close(code=4001, reason="Invalid or expired token")
    return None


def require_ws_token(websocket: fastapi.WebSocket) -> str | None:
    """
    FastAPI dependency that extracts the WS token from query params.

    This is a *sync* dependency for documentation purposes.
    Actual validation should use ``ws_authenticate()`` which is async.

    Returns:
        The raw token string (or None).
    """
    return websocket.query_params.get("token")
