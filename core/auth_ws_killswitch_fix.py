"""
core/auth_ws_killswitch_fix.py — JWT + WebSocket Auth Fix

Enhanced token creation with explicit role/email claims and a streamlined
WebSocket auth guard that validates JWT from query param or
Sec-WebSocket-Protocol header.

Zone: core/ — shared utility, no execution authority.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# JWT helpers (HMAC-SHA256, no external lib dependency)
# ---------------------------------------------------------------------------
import base64  # noqa: E402
import contextlib
import hashlib
import hmac
import json  # noqa: E402
import time
from typing import Any

from fastapi import WebSocket
from loguru import logger


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def _sign(header_b64: str, payload_b64: str, secret: str) -> str:
    msg = f"{header_b64}.{payload_b64}".encode("ascii")
    sig = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).digest()
    return _b64url_encode(sig)


_FORBIDDEN_SECRETS = {"CHANGE_ME", "CHANGE_ME_SUPER_SECRET", "CHANGE_ME_TO_RANDOM_STRING"}


def _is_strong_secret(secret: str) -> bool:
    return bool(secret) and secret not in _FORBIDDEN_SECRETS and len(secret) >= 32


# ---------------------------------------------------------------------------
# Fixed token creation — adds role + email as first-class claims
# ---------------------------------------------------------------------------


def create_token_fixed(
    user_id: str,
    email: str,
    *,
    role: str = "trader",
    jwt_secret: str,
    expire_min: int = 60,
) -> str:
    """Create a signed JWT with explicit user_id, email, and role claims.

    Args:
        user_id: Subject claim (user identifier).
        email: Email claim for audit trail.
        role: User role — 'trader', 'admin', 'viewer'. Default 'trader'.
        jwt_secret: HMAC secret (must be >=32 chars).
        expire_min: Token lifetime in minutes (default 60).

    Returns:
        Encoded JWT string.

    Raises:
        RuntimeError: If jwt_secret is missing or weak.
        ValueError: If role is not in allowed set.
    """
    if not _is_strong_secret(jwt_secret):
        raise RuntimeError("JWT secret is missing/weak. Provide a strong secret (>=32 chars).")

    allowed_roles = {"trader", "admin", "viewer", "service"}
    if role not in allowed_roles:
        raise ValueError(f"Invalid role '{role}'. Must be one of: {allowed_roles}")

    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": user_id,
        "email": email,
        "role": role,
        "iat": now,
        "exp": now + expire_min * 60,
    }

    header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    signature = _sign(header_b64, payload_b64, jwt_secret)

    return f"{header_b64}.{payload_b64}.{signature}"


def _decode_token(raw: str, jwt_secret: str) -> dict[str, Any] | None:
    """Decode and validate a JWT against the given secret.

    Returns payload dict if valid + not expired, else None.
    """
    if not _is_strong_secret(jwt_secret):
        logger.warning("JWT verification disabled: secret is missing/weak")
        return None

    try:
        parts = raw.split(".")
        if len(parts) != 3:
            return None

        header_b64, payload_b64, sig_b64 = parts

        header = json.loads(_b64url_decode(header_b64))
        if header.get("alg") != "HS256":
            return None

        expected_sig = _sign(header_b64, payload_b64, jwt_secret)
        if not hmac.compare_digest(sig_b64, expected_sig):
            return None

        payload = json.loads(_b64url_decode(payload_b64))

        exp = payload.get("exp")
        if exp is not None and int(exp) < int(time.time()):
            logger.debug("JWT expired")
            return None

        return payload

    except Exception as exc:
        logger.debug(f"JWT decode error: {exc}")
        return None


# ---------------------------------------------------------------------------
# Fixed WebSocket auth — extracts token, validates, returns payload
# ---------------------------------------------------------------------------


def _extract_ws_token(ws: WebSocket) -> str | None:
    """Extract token from query param or Sec-WebSocket-Protocol header."""
    # 1. Query param  (?token=...)
    token = ws.query_params.get("token")
    if token:
        return token

    # 2. Authorization header (Bearer ...)
    auth_header = ws.headers.get("authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        return auth_header.split(" ", 1)[1].strip()

    # 3. Sec-WebSocket-Protocol header (auth.<TOKEN>)
    proto_header = ws.headers.get("sec-websocket-protocol")
    if proto_header:
        for part in proto_header.split(","):
            stripped = part.strip()
            lower = stripped.lower()
            for prefix in ("auth.", "token."):
                if lower.startswith(prefix):
                    return stripped[len(prefix) :]

    return None


async def ws_auth_fixed(
    ws: WebSocket,
    jwt_secret: str,
) -> dict[str, Any] | None:
    """Authenticate a WebSocket connection using JWT.

    Extracts token from query-param / header / subprotocol, validates it,
    and returns the payload dict on success.  On failure, closes the
    connection with an appropriate code and returns None.

    Args:
        ws: Accepted WebSocket instance.
        jwt_secret: HMAC secret for JWT verification.

    Returns:
        JWT payload dict on success, None on failure (connection closed).
    """
    token = _extract_ws_token(ws)
    if not token:
        logger.warning("WS auth failed: no token provided")
        with contextlib.suppress(Exception):
            await ws.close(code=4001, reason="Missing authentication token")
        return None

    payload = _decode_token(token, jwt_secret)
    if payload is None:
        logger.warning("WS auth failed: invalid or expired token")
        with contextlib.suppress(Exception):
            await ws.close(code=4001, reason="Invalid or expired token")
        return None

    # Verify exp claim exists for JWT tokens
    exp = payload.get("exp")
    if exp is None:
        logger.warning("WS auth failed: JWT missing exp claim")
        with contextlib.suppress(Exception):
            await ws.close(code=4001, reason="Token missing exp claim")
        return None

    logger.debug(f"WS auth OK: user={payload.get('sub')} role={payload.get('role')}")
    return payload
