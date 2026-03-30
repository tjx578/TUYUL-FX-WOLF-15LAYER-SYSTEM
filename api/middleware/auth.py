"""
Dashboard Authentication — owner-only JWT + machine-key support.

Auth model: OWNER-ONLY.  This dashboard is private and single-tenant.
  - No public-user login flow exists.
  - Browser-facing API key submission is NOT allowed.
  - Machine/service API keys (DASHBOARD_API_KEY) are for server-to-server use only.
  - Owner identity is established via server-side auth injection (Next.js middleware).

See docs/architecture/dashboard-control-surface.md for the canonical auth contract.

Provides:
  - ``create_token(sub, extra)`` — issue a signed JWT.
  - ``decode_token(raw)`` — decode and validate a JWT; returns payload or None.
  - ``validate_api_key(key)`` — check against the static machine API key.
  - ``verify_token(authorization)`` — FastAPI Depends() for HTTP routes.
  - ``verify_ws_token(websocket)`` — WS-safe auth via query param.

Environment variables:
  DASHBOARD_JWT_SECRET       — canonical HMAC secret (required, strong value)
  DASHBOARD_JWT_ALGO         — algorithm (default HS256)
  DASHBOARD_TOKEN_EXPIRE_MIN — token lifetime in minutes (default 60)
  DASHBOARD_API_KEY          — machine-only API key for service-to-service calls
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Any, Literal

from fastapi import Header, HTTPException, Query, Request, Response, WebSocket
from loguru import logger

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_DASHBOARD_JWT_SECRET = os.getenv("DASHBOARD_JWT_SECRET", "").strip()
_LEGACY_JWT_SECRET = os.getenv("JWT_SECRET", "").strip()

JWT_SECRET: str = _DASHBOARD_JWT_SECRET or _LEGACY_JWT_SECRET
JWT_VERIFY_SECRETS: tuple[str, ...] = (JWT_SECRET,) if JWT_SECRET else ()
JWT_ALGO: str = os.getenv("DASHBOARD_JWT_ALGO", "HS256")
TOKEN_EXPIRE_MIN: int = int(os.getenv("DASHBOARD_TOKEN_EXPIRE_MIN", "60"))
API_KEY: str = os.getenv("DASHBOARD_API_KEY", "")

_FORBIDDEN_DEFAULT_JWT_SECRETS = {
    "CHANGE_ME",
    "CHANGE_ME_SUPER_SECRET",
    "CHANGE_ME_TO_RANDOM_STRING",
}


def _is_strong_jwt_secret(secret: str) -> bool:
    return bool(secret) and secret not in _FORBIDDEN_DEFAULT_JWT_SECRETS and len(secret) >= 32


if not _is_strong_jwt_secret(JWT_SECRET):
    # Downgraded from error → warning.  Services that only use API-key
    # auth (e.g. ingest) don't need JWT_SECRET at all.  Actual JWT
    # operations (create_token, decode_token) already fail closed when
    # the secret is missing, so this log is purely informational.
    logger.warning(
        "DASHBOARD_JWT_SECRET is missing/weak. "
        "JWT issuance/verification will fail closed until a strong secret (>=32 chars) is configured."
    )
elif _LEGACY_JWT_SECRET and not _DASHBOARD_JWT_SECRET:
    logger.warning("Using legacy JWT_SECRET env var; please migrate to DASHBOARD_JWT_SECRET.")

# ---------------------------------------------------------------------------
# Cookie configuration
# ---------------------------------------------------------------------------

COOKIE_NAME: str = os.getenv("AUTH_COOKIE_NAME", "wolf15_session")
COOKIE_SECURE: bool = os.getenv("AUTH_COOKIE_SECURE", "true").strip().lower() in {"1", "true", "yes"}
_SameSite = Literal["lax", "strict", "none"]
_VALID_SAMESITE: set[_SameSite] = {"lax", "strict", "none"}
_raw_samesite = os.getenv("AUTH_COOKIE_SAMESITE", "lax").strip().lower()
COOKIE_SAMESITE: _SameSite = _raw_samesite if _raw_samesite in _VALID_SAMESITE else "lax"
COOKIE_DOMAIN: str | None = os.getenv("AUTH_COOKIE_DOMAIN", "").strip() or None
COOKIE_PATH: str = os.getenv("AUTH_COOKIE_PATH", "/")
COOKIE_MAX_AGE: int = TOKEN_EXPIRE_MIN * 60

# ---------------------------------------------------------------------------
# Lightweight JWT helpers (no external lib needed -- HMAC-SHA256 only)
# ---------------------------------------------------------------------------

import base64  # noqa: E402
import json  # noqa: E402


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
    if not _is_strong_jwt_secret(JWT_SECRET):
        raise RuntimeError(
            "DASHBOARD_JWT_SECRET is missing/weak. Configure a strong secret (>=32 chars) before issuing JWTs."
        )

    if JWT_ALGO != "HS256":
        logger.warning(f"Unsupported DASHBOARD_JWT_ALGO={JWT_ALGO}. Falling back to HS256.")
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


def decode_token(raw: str) -> dict[str, Any] | None:
    """
    Decode and validate a JWT.

    Returns:
        Payload dict if valid and not expired, else None.
    """
    if not _is_strong_jwt_secret(JWT_SECRET):
        logger.warning("JWT verification disabled: DASHBOARD_JWT_SECRET is missing/weak")
        return None

    try:
        parts = raw.split(".")
        if len(parts) != 3:
            return None

        header_b64, payload_b64, sig_b64 = parts

        header = json.loads(_b64url_decode(header_b64))
        if header.get("alg") != "HS256":
            return None

        # Verify signature against accepted secrets.
        matched_secret = False
        for secret in JWT_VERIFY_SECRETS:
            expected_sig = _sign(header_b64, payload_b64, secret)
            if hmac.compare_digest(sig_b64, expected_sig):
                matched_secret = True
                break
        if not matched_secret:
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
# Cookie helpers
# ---------------------------------------------------------------------------


def set_auth_cookie(response: Response, token: str) -> None:
    """Set an HttpOnly session cookie containing the JWT."""
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        domain=COOKIE_DOMAIN,
        path=COOKIE_PATH,
        max_age=COOKIE_MAX_AGE,
    )


def clear_auth_cookie(response: Response) -> None:
    """Delete the session cookie."""
    response.delete_cookie(
        key=COOKIE_NAME,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        domain=COOKIE_DOMAIN,
        path=COOKIE_PATH,
    )


def _extract_cookie_token(request: Request | None) -> str | None:
    """Read the session JWT from the request cookie, if present."""
    if request is None:
        return None
    return request.cookies.get(COOKIE_NAME)


# ---------------------------------------------------------------------------
# FastAPI HTTP dependency
# ---------------------------------------------------------------------------


def verify_token(
    request: Request,
    authorization: str = Header(None),
) -> dict[str, Any]:
    """
    FastAPI dependency for HTTP routes.

    Accepts (checked in order):
      1. ``Authorization: Bearer <jwt>``
      2. ``Authorization: Bearer <api_key>``
      3. HttpOnly session cookie (``wolf15_session``)

    Raises HTTPException 401 on failure.
    Returns payload dict on success.
    """
    # ── 1. Try Authorization header ──
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer" and token:
            payload = decode_token(token)
            if payload is not None:
                return payload
            if validate_api_key(token):
                return {"sub": "api_key_user", "auth_method": "api_key"}

    # ── 2. Fallback: HttpOnly cookie ──
    cookie_token = _extract_cookie_token(request)
    if cookie_token:
        payload = decode_token(cookie_token)
        if payload is not None:
            return payload

    raise HTTPException(status_code=401, detail="Missing or invalid credentials")


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
