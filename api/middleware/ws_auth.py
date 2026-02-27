"""
WebSocket Authentication -- token validation for WS connections.

WebSocket clients authenticate by passing a token as a query parameter:
    ws://host/ws/prices?token=<JWT_OR_API_KEY>

This module provides:
  - ``ws_authenticate()`` -- validates token, sets websocket.state.user, returns bool.
  - ``ws_auth_guard()`` -- high-level guard returning payload dict or None.
  - ``require_ws_token()`` -- FastAPI dependency for WebSocket endpoints.

All JWT tokens are validated via the unified ``dashboard.backend.auth`` module
(HMAC-SHA256, secret from ``DASHBOARD_JWT_SECRET`` env var).  A single secret
is used for both HTTP and WebSocket authentication.
"""

from __future__ import annotations

from typing import Any

import fastapi  # pyright: ignore[reportMissingImports]
from fastapi import WebSocket  # pyright: ignore[reportMissingImports]
from loguru import logger  # pyright: ignore[reportMissingImports]

from dashboard.backend.auth import decode_token, validate_api_key


class WSAuthError(Exception):
    """Raised when WebSocket authentication fails."""


async def ws_authenticate(websocket: WebSocket) -> bool:
    """
    Authenticate a WebSocket connection via query-param token.

    Reads ``?token=<jwt_or_api_key>`` from the URL.  On success, sets
    ``websocket.state.user`` to the subject claim and returns ``True``.
    On failure, closes the connection with code 4401 and returns ``False``.
    """
    token: str | None = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4401, reason="Missing authentication token")
        return False

    payload = decode_token(token)
    if payload is not None:
        websocket.state.user = payload.get("sub")
        logger.debug(f"WS auth via JWT: user={websocket.state.user}")
        return True

    if validate_api_key(token):
        websocket.state.user = "api_key_user"
        logger.debug("WS auth via API key")
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
    token: str | None = websocket.query_params.get("token")
    if not token:
        logger.warning("WS auth rejected: missing token")
        try:
            await websocket.send_json({"type": "auth_error", "detail": "Missing authentication token"})
            await websocket.close(code=4001, reason="Missing authentication token")
        except Exception:
            pass
        return None

    payload = decode_token(token)
    if payload is not None:
        logger.debug(f"WS auth via JWT: user={payload.get('sub')}")
        return payload

    if validate_api_key(token):
        logger.debug("WS auth via API key")
        return {"sub": "api_key_user", "auth_method": "api_key"}

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
