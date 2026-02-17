"""
WebSocket authentication middleware.

Zone: dashboard (API security). No market analysis.

SECURITY FIXES:
- Token MUST be sent via first message or Sec-WebSocket-Protocol header.
- Token in query string is REJECTED (visible in access logs, browser history, proxies).
- Short-lived session tokens with rotation.
"""

from __future__ import annotations

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


async def authenticate_websocket(
    websocket: Any,
    token_manager: WSTokenManager,
    timeout: float = WS_AUTH_TIMEOUT_SECONDS,
) -> WSSession:
    """
    Authenticate a WebSocket connection.

    Protocol:
    1. Client connects (no token in URL).
    2. Client sends first message: {"type": "auth", "token": "<token>"}
    3. Server validates and responds:
       - Success: {"type": "auth_ok", "session_id": "..."}
       - Failure: {"type": "auth_error", "code": "...", "message": "..."}
         then closes connection.

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
    # Access query string from the websocket scope
    scope = getattr(websocket, "scope", {})
    query_string = scope.get("query_string", b"").decode("utf-8", errors="ignore")
    reject_token_in_url(query_string)

    # Step 2: Wait for auth message
    try:
        raw_message = await asyncio.wait_for(websocket.receive_text(), timeout=timeout)
    except TimeoutError:
        await _send_error(websocket, AuthErrorCode.AUTH_TIMEOUT, "Authentication timeout")
        raise AuthError(AuthErrorCode.AUTH_TIMEOUT.value)  # noqa: B904

    try:
        message = json.loads(raw_message)
    except (json.JSONDecodeError, TypeError):
        await _send_error(websocket, AuthErrorCode.NO_TOKEN, "Invalid auth message format")
        raise AuthError(AuthErrorCode.NO_TOKEN.value)  # noqa: B904

    if message.get("type") != "auth" or "token" not in message:
        await _send_error(websocket, AuthErrorCode.NO_TOKEN, "Expected {type: 'auth', token: '...'}")
        raise AuthError(AuthErrorCode.NO_TOKEN.value)

    raw_token = message["token"]

    # Step 3: Validate
    try:
        session = token_manager.validate_token(raw_token)
    except AuthError as e:
        await _send_error(websocket, AuthErrorCode.TOKEN_INVALID, str(e))
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
    """Send auth error and close."""
    try:  # noqa: SIM105
        await websocket.send_text(json.dumps({
            "type": "auth_error",
            "code": code.value,
            "message": message,
        }))
    except Exception:
        pass  # Connection might already be closed
