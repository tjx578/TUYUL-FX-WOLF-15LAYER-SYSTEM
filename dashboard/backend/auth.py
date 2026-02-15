"""
Dashboard Authentication — JWT + API-key support.

Provides:
  - ``create_token(sub, extra)`` — issue a signed JWT.
  - ``decode_token(raw)`` — decode and validate a JWT; returns payload or None.
  - ``validate_api_key(key)`` — check against the static API key.
  - ``verify_token(authorization)`` — FastAPI Depends() for HTTP routes.
  - ``verify_ws_token_from_query(websocket)`` — WS-safe auth via query param.

Environment variables:
  DASHBOARD_JWT_SECRET        — HMAC secret (MUST change in prod)
  DASHBOARD_JWT_ALGO          — algorithm (default HS256)
  DASHBOARD_TOKEN_EXPIRE_MIN  — token lifetime in minutes (default 60)
  DASHBOARD_API_KEY           — optional static API key for service-to-service calls
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Any, Optional

from fastapi import Header, HTTPException, WebSocket, Query  # pyright: ignore[reportMissingImports]
from loguru import logger  # pyright: ignore[reportMissingImports]

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

JWT_SECRET: str = os.getenv("DASHBOARD_JWT_SECRET", "CHANGE_ME")
JWT_ALGO: str = os.getenv("DASHBOARD_JWT_ALGO", "HS256")
TOKEN_EXPIRE_MIN: int = int(os.getenv("DASHBOARD_TOKEN_EXPIRE_MIN", "60"))
API_KEY: str = os.getenv("DASHBOARD_API_KEY", "")

# Warn loudly if secret is still the default
if JWT_SECRET == "CHANGE_ME":
    logger.warning(
        "⚠️  DASHBOARD_JWT_SECRET is set to default 'CHANGE_ME'. "
        "Set a strong secret via environment variable before deploying to production."
    )

# ---------------------------------------------------------------------------
# Lightweight JWT helpers (no external lib needed — HMAC-SHA256 only)
# ---------------------------------------------------------------------------

import base64
import json


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    # Re-add padding
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def _sign(header_b64: str, payload_b64: str, secret: str) -> str:
    """HMAC-SHA256 signature."""
    msg = f"{header_b64}.{payload_b64}".encode("ascii")
    sig = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).digest()
    return _b64url_encode(sig)


def create_token(sub: str = "dashboard", extra: dict[str, Any] | None = None) -> str:
    """
    Create a signed JWT with HMAC-SHA256.

    Args:
        sub: Subject claim (e.g. user ID or service name).
        extra: Additional claims to embed in the payload.

    Returns:
        Encoded JWT string.
    """
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": sub,
        "iat": now,
        "exp": now + TOKEN_EXPIRE_MIN * 60,
    }
    if extra:
        payload.update(extra)

    header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    signature = _sign(header_b64, payload_b64, JWT_SECRET)

    return f"{header_b64}.{payload_b64}.{signature}"


def decode_token(raw: str) -> Optional[dict[str, Any]]:
    """
    Decode and validate a JWT.

    Returns:
        Payload dict if valid and not expired, else None.
    """
    try:
        parts = raw.split(".")
        if len(parts) != 3:
            return None

        header_b64, payload_b64, sig_b64 = parts

        # Verify signature
        expected_sig = _sign(header_b64, payload_b64, JWT_SECRET)
        if not hmac.compare_digest(sig_b64, expected_sig):
            return None

        # Decode payload
        payload = json.loads(_b64url_decode(payload_b64))

        # Check expiry
        exp = payload.get("exp")
        if exp is not None and int(exp) < int(time.time()):
            logger.debug("JWT expired")
            return None

        return payload

    except Exception as exc:
        logger.debug(f"JWT decode error: {exc}")
        return None


# ---------------------------------------------------------------------------
# API key validation
# ---------------------------------------------------------------------------

def validate_api_key(key: str) -> bool:
    """
    Validate a static API key (constant-time comparison).

    Returns True only when DASHBOARD_API_KEY is configured and matches.
    """
    if not API_KEY:
        return False
    return hmac.compare_digest(key, API_KEY)


# ---------------------------------------------------------------------------
# FastAPI HTTP dependency
# ---------------------------------------------------------------------------

def verify_token(authorization: str = Header(None)) -> dict[str, Any]:
    """
    FastAPI dependency for HTTP routes.

    Accepts:
      - ``Authorization: Bearer <jwt>``
      - ``Authorization: Bearer <api_key>``

    Raises HTTPException 401 on failure.
    Returns payload dict on success.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    # Strip 'Bearer ' prefix
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Invalid Authorization scheme. Use: Bearer <token>")

    # Try JWT first
    payload = decode_token(token)
    if payload is not None:
        return payload

    # Fall back to API key
    if validate_api_key(token):
        return {"sub": "api_key_user", "auth_method": "api_key"}

    raise HTTPException(status_code=401, detail="Invalid or expired token")


# ---------------------------------------------------------------------------
# FastAPI WebSocket dependency (query-param based)
# ---------------------------------------------------------------------------

async def verify_ws_token(
    websocket: WebSocket,
    token: str = Query(None),
) -> dict[str, Any]:
    """
    FastAPI dependency for WebSocket endpoints.

    Client must connect with ``?token=<jwt_or_api_key>``.
    On failure the WebSocket is closed with code 4401.
    """
    if not token:
        await websocket.close(code=4401, reason="Missing authentication token")
        raise HTTPException(status_code=401, detail="Missing token")

    payload = decode_token(token)
    if payload is not None:
        return payload

    if validate_api_key(token):
        return {"sub": "api_key_user", "auth_method": "api_key"}

    await websocket.close(code=4401, reason="Invalid or expired token")
    raise HTTPException(status_code=401, detail="Invalid token")
