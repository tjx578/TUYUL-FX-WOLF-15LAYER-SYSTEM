"""
WebSocket Authentication -- token validation for WS connections.

WebSocket clients authenticate by passing a token as a query parameter:
    ws://host/ws/prices?token=<JWT_OR_API_KEY>

This module provides:
  - ``ws_authenticate()`` -- validates token and returns the WebSocket or closes it.
  - ``require_ws_token()`` -- FastAPI dependency for WebSocket endpoints.
"""

from __future__ import annotations

import json

# --- New Robust WebSocket Auth Middleware ---
import os
from datetime import UTC, datetime
from typing import Any

import fastapi  # pyright: ignore[reportMissingImports]
import jwt
from fastapi import Query, WebSocket, WebSocketDisconnect  # pyright: ignore[reportMissingImports]
from loguru import logger  # pyright: ignore[reportMissingImports]

# JWT Configuration
JWT_SECRET = os.getenv("JWT_SECRET", "wolf-15-secret-change-in-production")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_ISSUER = os.getenv("JWT_ISSUER", "tuyul-fx-wolf15")

class WSAuthError(Exception):
    """Raised when WebSocket authentication fails."""

def decode_jwt_token(token: str) -> dict[str, Any]:
    """
    Decode and validate a JWT token.
    Args:
        token: Raw JWT string
    Returns:
        Decoded payload dictionary
    Raises:
        WSAuthError: If token is invalid, expired, or malformed
    """
    try:
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
            issuer=JWT_ISSUER,
            options={"require": ["exp", "sub", "iss"]},
        )
        exp = payload.get("exp", 0)
        if datetime.now(UTC).timestamp() > exp:
            raise WSAuthError("Token expired")
        return payload
    except jwt.ExpiredSignatureError:
        raise WSAuthError("Token expired")  # noqa: B904
    except jwt.InvalidIssuerError:
        raise WSAuthError(f"Invalid issuer (expected {JWT_ISSUER})")  # noqa: B904
    except jwt.DecodeError:
        raise WSAuthError("Invalid token format")  # noqa: B904
    except jwt.InvalidTokenError as e:
        raise WSAuthError(f"Token validation failed: {e}")  # noqa: B904

async def authenticate_websocket(
    websocket: WebSocket,
    token: str | None = Query(default=None),
) -> dict[str, Any]:
    """
    Authenticate a WebSocket connection.
    Accepts token from three sources (priority order):
    1. URL query parameter (?token=xxx) — default frontend method
    2. Subprotocol header (Sec-WebSocket-Protocol: bearer,<token>)
    3. First WebSocket message ({"type":"auth","token":"xxx"})
    Args:
        websocket: FastAPI WebSocket connection
        token: Token from URL query param (auto-extracted by FastAPI)
    Returns:
        Decoded JWT payload with user identity
    Raises:
        WSAuthError: If no valid token found from any source
    """
    # Source 1: URL query parameter
    if token:
        try:
            payload = decode_jwt_token(token)
            logger.debug(f"WS auth via query param: user={payload.get('sub')}")
            return payload
        except WSAuthError as e:
            logger.warning(f"WS query param token invalid: {e}")
    # Source 2: Subprotocol header
    subprotocols = websocket.headers.get("sec-websocket-protocol", "")
    if subprotocols:
        parts = [p.strip() for p in subprotocols.split(",")]
        if len(parts) >= 2 and parts[0].lower() == "bearer":
            try:
                payload = decode_jwt_token(parts[1])
                logger.debug(f"WS auth via subprotocol: user={payload.get('sub')}")
                return payload
            except WSAuthError as e:
                logger.warning(f"WS subprotocol token invalid: {e}")
    # Source 3: First message authentication
    await websocket.accept()
    try:
        import asyncio
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
        msg = json.loads(raw)
        if msg.get("type") == "auth" and msg.get("token"):
            payload = decode_jwt_token(msg["token"])
            logger.debug(f"WS auth via first message: user={payload.get('sub')}")
            await websocket.send_json({"type": "auth_success", "user": payload.get("sub")})
            return payload
        else:
            raise WSAuthError("First message was not an auth message")
    except TimeoutError:
        raise WSAuthError("Auth timeout: no token received within 10s")  # noqa: B904
    except json.JSONDecodeError:
        raise WSAuthError("Invalid auth message format (not JSON)")  # noqa: B904
    except WebSocketDisconnect:
        raise WSAuthError("Client disconnected during authentication")  # noqa: B904

async def ws_auth_guard(websocket: WebSocket) -> dict[str, Any] | None:
    """
    High-level WebSocket auth guard for route handlers.
    Usage:
        @router.websocket("/ws/prices")
        async def price_stream(websocket: WebSocket):
            user = await ws_auth_guard(websocket)
            if not user:
                return  # Connection already closed
            # ... handle authenticated connection
    Returns:
        User payload dict if authenticated, None if auth failed
    """
    token = websocket.query_params.get("token")
    try:
        payload = await authenticate_websocket(websocket, token=token)
        return payload
    except WSAuthError as e:
        logger.warning(f"WS auth rejected: {e}")
        try:
            await websocket.send_json({"type": "auth_error", "detail": str(e)})
            await websocket.close(code=4001, reason=str(e))
        except Exception:
            try:
                await websocket.accept()
                await websocket.send_json({"type": "auth_error", "detail": str(e)})
                await websocket.close(code=4001, reason=str(e))
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
