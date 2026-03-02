"""WebSocket Authentication — canonical token validation for WS connections.

This is the **single source of truth** for WebSocket authentication.
Both HTTP and WS endpoints share the same JWT / API-key verifiers via
``api.auth``.  Do NOT add a parallel auth system.

Provides:
  - ``extract_token()``     -- pull token from Authorization header OR query param.
  - ``verify_token()``      -- validate a raw token string, return payload or None.
  - ``ws_authenticate()``   -- validates token, sets websocket.state.user, returns bool.
  - ``ws_auth_guard()``     -- high-level guard returning payload dict or None.
  - ``require_ws_token()``  -- FastAPI dependency for WebSocket endpoints.

All JWT tokens are validated via the unified ``api.auth`` module
(HMAC-SHA256, canonical secret ``DASHBOARD_JWT_SECRET``). This keeps HTTP and
WebSocket authentication on one compatible trust boundary.

See also:
  - ``api.auth.verify_token`` (HTTP FastAPI Depends)
  - ``api.auth.verify_ws_token`` (WS FastAPI Depends via query)
"""

from __future__ import annotations

import logging
from typing import Any

import fastapi
from fastapi import WebSocket

from api.auth import decode_token, validate_api_key

logger = logging.getLogger(__name__)


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

    Delegates to ``api.auth.decode_token`` and
    ``validate_api_key`` — the same verifiers used for HTTP routes.

    Returns:
        Payload dict on success, ``None`` on failure.
    """
    try:
        payload = decode_token(token)
        if payload is not None:
            return payload
    except Exception:
        pass

    try:
        result = validate_api_key(token)
        if result:
            return {"sub": "api_key_user", "auth_method": "api_key"}
    except Exception:
        pass

    return None


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
    token = extract_token(dict(websocket.headers), dict(websocket.query_params))
    if not token:
        logger.warning("WS auth rejected: missing token")
        try:
            await websocket.send_json({"type": "auth_error", "detail": "Missing authentication token"})
            await websocket.close(code=4001, reason="Missing authentication token")
        except Exception:
            pass
        return None

    payload = verify_token(token)
    if payload is not None:
        logger.debug(f"WS auth OK: user={payload.get('sub')}")
        return payload

    logger.warning("WS auth rejected: invalid or expired token")
    try:
        await websocket.send_json({"type": "auth_error", "detail": "Invalid or expired token"})
        await websocket.close(code=4001, reason="Invalid or expired token")
    except Exception:
        pass
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
