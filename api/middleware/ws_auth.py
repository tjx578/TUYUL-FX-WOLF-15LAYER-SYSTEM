"""
WebSocket Authentication — token validation for WS connections.

WebSocket clients authenticate by passing a token as a query parameter:
    ws://host/ws/prices?token=<JWT_OR_API_KEY>

This module provides:
  - ``ws_authenticate()`` — validates token and returns the WebSocket or closes it.
  - ``require_ws_token()`` — FastAPI dependency for WebSocket endpoints.
"""

from __future__ import annotations

import fastapi  # pyright: ignore[reportMissingImports]

from loguru import logger  # pyright: ignore[reportMissingImports]

from dashboard.backend.auth import (  # pyright: ignore[reportAttributeAccessIssue]
    decode_token,  # pyright: ignore[reportAttributeAccessIssue]
    validate_api_key,  # pyright: ignore[reportAttributeAccessIssue]
)


async def ws_authenticate(
    websocket: fastapi.WebSocket,
) -> bool:
    """
    Authenticate a WebSocket connection using query-param token.

    Accepts either:
      1. A valid JWT (``?token=eyJ...``)
      2. A valid API key (``?token=<raw_api_key>``)

    On failure the websocket is closed with code 4401 (custom "Unauthorized").

    Returns:
        True if authenticated, False if connection was closed.
    """
    token: str | None = websocket.query_params.get("token")

    if not token:
        logger.warning("WS connection rejected: no token provided")
        await websocket.close(code=4401, reason="Missing authentication token")
        return False

    # Try JWT first, then API key
    payload = decode_token(token)
    if payload is not None:
        # Attach user info to websocket state for downstream use
        websocket.state.user = payload.get("sub", "authenticated")
        return True

    if validate_api_key(token):
        websocket.state.user = "api_key_user"
        return True

    logger.warning("WS connection rejected: invalid token")
    await websocket.close(code=4401, reason="Invalid or expired token")
    return False


def require_ws_token(websocket: fastapi.WebSocket) -> str | None:
    """
    FastAPI dependency that extracts the WS token from query params.

    This is a *sync* dependency for documentation purposes.
    Actual validation should use ``ws_authenticate()`` which is async.

    Returns:
        The raw token string (or None).
    """
    return websocket.query_params.get("token")
