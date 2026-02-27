"""
WebSocket authentication middleware.

Zone: dashboard (API security). No market analysis.

SECURITY FIXES:
- Token MUST be sent via first message or Sec-WebSocket-Protocol header.
- Token in query string is REJECTED (visible in access logs, browser history, proxies).
- Short-lived session tokens with rotation.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any  # noqa: UP035

logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────────

WS_AUTH_TIMEOUT_SECONDS = 10       # Max time to wait for auth message
WS_TOKEN_MAX_AGE_SECONDS = 3600   # 1 hour
WS_TOKEN_LENGTH = 48               # bytes of randomness


class AuthError(Exception):
    """WebSocket authentication error."""
    pass


class AuthErrorCode(Enum):
    TOKEN_IN_URL = "TOKEN_IN_URL"
    NO_TOKEN = "NO_TOKEN"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    TOKEN_INVALID = "TOKEN_INVALID"
    TOKEN_REVOKED = "TOKEN_REVOKED"
    AUTH_TIMEOUT = "AUTH_TIMEOUT"


@dataclass
class WSSession:
    """An authenticated WebSocket session."""
    session_id: str
    user_id: str
    token_hash: str            # SHA-256 hash — never store raw tokens
    created_at: float
    expires_at: float
    revoked: bool = False

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at


# ── Token Manager ────────────────────────────────────────────────────

class WSTokenManager:
    """
    Manages WebSocket session tokens.

    Tokens are:
    - Generated server-side, returned via HTTPS REST endpoint (never in URL).
    - Stored as SHA-256 hashes (raw token never persisted).
    - Time-limited with configurable expiry.
    - Revocable.
    """

    def __init__(self, secret_key: str | None = None, max_age: int = WS_TOKEN_MAX_AGE_SECONDS) -> None:
        self._secret = (secret_key or os.environ.get("WS_SECRET_KEY", "")).encode()
        if not self._secret:
            raise ValueError(
                "WS_SECRET_KEY must be set. Never use empty secret in production."
            )
        self._max_age = max_age
        self._sessions: dict[str, WSSession] = {}  # session_id → WSSession
        self._token_index: dict[str, str] = {}      # token_hash → session_id
        self._revoked_tokens: set[str] = set()       # token_hashes

    def create_token(self, user_id: str) -> dict[str, str]:
        """
        Create a new WS session token.

        Returns dict with 'token' and 'session_id'.
        The raw token is returned ONCE — caller must send it to user via HTTPS.
        """
        raw_token = secrets.token_urlsafe(WS_TOKEN_LENGTH)
        token_hash = self._hash_token(raw_token)
        session_id = secrets.token_urlsafe(16)
        now = time.time()

        session = WSSession(
            session_id=session_id,
            user_id=user_id,
            token_hash=token_hash,
            created_at=now,
            expires_at=now + self._max_age,
        )

        self._sessions[session_id] = session
        self._token_index[token_hash] = session_id

        logger.info(
            "WS session created: session_id=%s user=%s expires_in=%ds",
            session_id, user_id, self._max_age,
        )

        return {
            "token": raw_token,
            "session_id": session_id,
            "expires_in": self._max_age, # pyright: ignore[reportReturnType]
        }

    def validate_token(self, raw_token: str) -> WSSession:
        """
        Validate a raw token. Returns the session if valid.

        Raises AuthError with appropriate code if invalid.
        """
        token_hash = self._hash_token(raw_token)

        if token_hash in self._revoked_tokens:
            raise AuthError(AuthErrorCode.TOKEN_REVOKED.value)

        session_id = self._token_index.get(token_hash)
        if session_id is None:
            raise AuthError(AuthErrorCode.TOKEN_INVALID.value)

        session = self._sessions.get(session_id)
        if session is None:
            raise AuthError(AuthErrorCode.TOKEN_INVALID.value)

        if session.is_expired:
            self._cleanup_session(session_id, token_hash)
            raise AuthError(AuthErrorCode.TOKEN_EXPIRED.value)

        if session.revoked:
            raise AuthError(AuthErrorCode.TOKEN_REVOKED.value)

        return session

    def revoke_session(self, session_id: str) -> bool:
        """Revoke a session. Returns True if found and revoked."""
        session = self._sessions.get(session_id)
        if session is None:
            return False

        session.revoked = True
        self._revoked_tokens.add(session.token_hash)
        logger.info("WS session revoked: session_id=%s user=%s", session_id, session.user_id)
        return True

    def revoke_all_for_user(self, user_id: str) -> int:
        """Revoke all sessions for a user. Returns count revoked."""
        count = 0
        for session in self._sessions.values():
            if session.user_id == user_id and not session.revoked:
                session.revoked = True
                self._revoked_tokens.add(session.token_hash)
                count += 1
        if count:
            logger.info("Revoked %d sessions for user=%s", count, user_id)
        return count

    def cleanup_expired(self) -> int:
        """Remove expired sessions. Call periodically."""
        now = time.time()
        expired_ids = [
            sid for sid, s in self._sessions.items()
            if now > s.expires_at
        ]
        for sid in expired_ids:
            session = self._sessions.pop(sid, None)
            if session:
                self._token_index.pop(session.token_hash, None)
                self._revoked_tokens.discard(session.token_hash)
        return len(expired_ids)

    def rotate_token(self, session_id: str) -> dict[str, str]:
        """
        Rotate (replace) token for an existing session.

        Old token is revoked, a new token is issued for the same user/session.
        Returns dict with 'token', 'session_id', 'expires_in'.
        The raw token is returned ONCE.
        """
        session = self._sessions.get(session_id)
        if session is None or session.revoked or session.is_expired:
            raise AuthError(AuthErrorCode.TOKEN_INVALID.value)

        # Revoke old token
        self._revoked_tokens.add(session.token_hash)
        self._token_index.pop(session.token_hash, None)

        # Issue new token for same session/user
        raw_token = secrets.token_urlsafe(WS_TOKEN_LENGTH)
        token_hash = self._hash_token(raw_token)
        now = time.time()

        session.token_hash = token_hash
        session.created_at = now
        session.expires_at = now + self._max_age
        session.revoked = False

        self._token_index[token_hash] = session_id

        logger.info(
            "WS token rotated: session_id=%s user=%s expires_in=%ds",
            session_id, session.user_id, self._max_age,
        )

        return {
            "token": raw_token,
            "session_id": session_id,
            "expires_in": self._max_age,  # pyright: ignore[reportReturnType]
        }

    def _hash_token(self, raw_token: str) -> str:
        return hmac.new(self._secret, raw_token.encode(), hashlib.sha256).hexdigest()

    def _cleanup_session(self, session_id: str, token_hash: str) -> None:
        self._sessions.pop(session_id, None)
        self._token_index.pop(token_hash, None)


# ── WebSocket Auth Middleware ────────────────────────────────────────

def reject_token_in_url(query_string: str) -> None:
    """
    MUST be called before accepting a WebSocket connection.
    Rejects any connection that passes a token in the URL query string.

    This prevents tokens from appearing in:
    - Server access logs
    - Browser history
    - Proxy logs
    - Referer headers
    """
    qs_lower = query_string.lower()
    dangerous_params = {"token", "auth", "key", "api_key", "apikey", "access_token", "jwt"}
    for param in dangerous_params:
        if f"{param}=" in qs_lower:
            logger.warning(
                "SECURITY: Rejected WS connection with token in URL query string. "
                "param=%s", param,
            )
            raise AuthError(
                f"{AuthErrorCode.TOKEN_IN_URL.value}: "
                f"Token in query string is forbidden. Use the auth message protocol."
            )


def _parse_ws_subprotocol_token(websocket: Any) -> str | None:
    """
    Extract token from Sec-WebSocket-Protocol header.

    Supported formats:
      Sec-WebSocket-Protocol: json, auth.<token>
      Sec-WebSocket-Protocol: auth, token.<token>

    Returns raw token string or None.
    """
    headers = getattr(websocket, "headers", None)
    if not headers:
        return None

    try:
        proto = headers.get("sec-websocket-protocol")
    except Exception:
        proto = None

    if not proto:
        return None

    # Header value is a comma-separated list of subprotocol names
    parts = [p.strip() for p in proto.split(",") if p.strip()]
    for p in parts:
        lower = p.lower()
        if lower.startswith("auth."):
            return p.split(".", 1)[1].strip()
        if lower.startswith("token."):
            return p.split(".", 1)[1].strip()

    return None


def _map_auth_error_to_code(err: AuthError) -> AuthErrorCode:
    """
    Map an AuthError back to the correct AuthErrorCode.

    AuthError messages are currently set to AuthErrorCode.value strings,
    so we parse that back. Falls back to TOKEN_INVALID for unknown errors.
    """
    msg = str(err)
    try:
        return AuthErrorCode(msg)
    except ValueError:
        return AuthErrorCode.TOKEN_INVALID


async def _send_error_and_close(
    websocket: Any,
    code: AuthErrorCode,
    message: str,
    close_code: int = 1008,
) -> None:
    """
    Send auth error JSON and close the WebSocket connection.

    Close codes:
      1008 — Policy Violation (auth failures)
      1002 — Protocol Error (malformed frames / unexpected message format)
    """
    try:  # noqa: SIM105
        await websocket.send_text(json.dumps({
            "type": "auth_error",
            "code": code.value,
            "message": message,
        }))
    except Exception:
        pass  # Connection might already be closed
    with contextlib.suppress(Exception):
        await websocket.close(code=close_code)


async def authenticate_websocket(
    websocket: Any,
    token_manager: WSTokenManager,
    timeout: float = WS_AUTH_TIMEOUT_SECONDS,
) -> WSSession:
    """
    Authenticate a WebSocket connection.

    Token MUST be provided by:
      - Sec-WebSocket-Protocol header (preferred for browsers), OR
      - First message: {"type": "auth", "token": "<token>"}

    Token in query string is REJECTED.

    Args:
        websocket: A WebSocket connection object (FastAPI/Starlette compatible).
        token_manager: The WSTokenManager instance.
        timeout: Max seconds to wait for auth message.

    Returns:
        WSSession on success.

    Raises:
        AuthError on failure.
    """
    import asyncio

    # Step 1: Reject token in URL
    scope = getattr(websocket, "scope", {}) or {}
    query_string = scope.get("query_string", b"").decode("utf-8", errors="ignore")
    reject_token_in_url(query_string)

    # Step 2: Try Sec-WebSocket-Protocol token first
    raw_token = _parse_ws_subprotocol_token(websocket)

    # If not present in header, wait for first auth message
    if not raw_token:
        try:
            raw_message = await asyncio.wait_for(
                websocket.receive_text(), timeout=timeout,
            )
        except TimeoutError:
            await _send_error_and_close(
                websocket,
                AuthErrorCode.AUTH_TIMEOUT,
                "Authentication timeout",
                close_code=1008,
            )
            raise AuthError(AuthErrorCode.AUTH_TIMEOUT.value)  # noqa: B904

        try:
            message = json.loads(raw_message)
        except (json.JSONDecodeError, TypeError):
            await _send_error_and_close(
                websocket,
                AuthErrorCode.NO_TOKEN,
                "Invalid auth message format",
                close_code=1002,
            )
            raise AuthError(AuthErrorCode.NO_TOKEN.value)  # noqa: B904

        if message.get("type") != "auth" or "token" not in message:
            await _send_error_and_close(
                websocket,
                AuthErrorCode.NO_TOKEN,
                "Expected {type: 'auth', token: '...'}",
                close_code=1002,
            )
            raise AuthError(AuthErrorCode.NO_TOKEN.value)

        raw_token = str(message["token"]).strip()

    if not raw_token:
        await _send_error_and_close(
            websocket,
            AuthErrorCode.NO_TOKEN,
            "Missing token",
            close_code=1008,
        )
        raise AuthError(AuthErrorCode.NO_TOKEN.value)

    # Step 3: Validate
    try:
        session = token_manager.validate_token(raw_token)
    except AuthError as e:
        code = _map_auth_error_to_code(e)
        await _send_error_and_close(
            websocket,
            code,
            code.value,  # avoid echoing internal details
            close_code=1008,
        )
        raise

    # Step 4: Success
    await websocket.send_text(json.dumps({
        "type": "auth_ok",
        "session_id": session.session_id,
    }))

    logger.info(
        "WS authenticated: session_id=%s user=%s",
        session.session_id, session.user_id,
    )
    return session


async def _send_error(websocket: Any, code: AuthErrorCode, message: str) -> None:
    """Send auth error (without closing). Kept for backward compatibility."""
    try:  # noqa: SIM105
        await websocket.send_text(json.dumps({
            "type": "auth_error",
            "code": code.value,
            "message": message,
        }))
    except Exception:
        pass  # Connection might already be closed
