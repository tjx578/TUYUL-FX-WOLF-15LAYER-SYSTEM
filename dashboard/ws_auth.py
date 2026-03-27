"""
dashboard/ws_auth.py — WebSocket Authentication

Provides JWT-based WebSocket authentication including:
- Token creation and validation (HMAC-SHA256, stdlib only — no PyJWT)
- Sec-WebSocket-Protocol subprotocol token extraction
- Token-in-URL rejection (security: tokens must never appear in URLs)
- Error-to-code mapping

Uses the same HMAC-SHA256 algorithm as ``api.middleware.auth`` so tokens
are cross-compatible.  The only difference is that WSTokenManager accepts
a per-instance secret (useful for tests) while ``api.middleware.auth``
reads from environment variables.

Authority: Dashboard-layer security. No market decisions.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# ---------------------------------------------------------------------------
# Lightweight JWT helpers — same algorithm as api.middleware.auth
# ---------------------------------------------------------------------------


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def _hmac_sign(header_b64: str, payload_b64: str, secret: str) -> str:
    """HMAC-SHA256 signature over ``header.payload``."""
    msg = f"{header_b64}.{payload_b64}".encode("ascii")
    sig = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).digest()
    return _b64url_encode(sig)


class AuthErrorCode(Enum):
    """Machine-readable WebSocket authentication error codes."""

    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    TOKEN_REVOKED = "TOKEN_REVOKED"
    TOKEN_INVALID = "TOKEN_INVALID"
    AUTH_TIMEOUT = "AUTH_TIMEOUT"
    NO_TOKEN = "NO_TOKEN"
    TOKEN_IN_URL = "TOKEN_IN_URL"


class AuthError(ValueError):
    """Raised when WebSocket authentication fails."""


@dataclass
class SessionInfo:
    """Validated session information."""

    user_id: str
    session_id: str
    issued_at: float = field(default_factory=time.time)
    expires_at: float = 0.0

    @property
    def is_expired(self) -> bool:
        if self.expires_at == 0.0:
            return False
        return time.time() > self.expires_at


_TOKEN_IN_URL_PARAMS = frozenset({"token", "auth", "access_token", "api_key"})


def reject_token_in_url(query_string: str) -> None:
    """Reject WebSocket connections that embed tokens in the URL query string.

    Args:
        query_string: URL-decoded query string (e.g. 'token=abc&foo=bar').

    Raises:
        AuthError: If a token-bearing param is found.
    """
    if not query_string:
        return
    for part in query_string.split("&"):
        key = part.split("=")[0].lower().strip()
        if key in _TOKEN_IN_URL_PARAMS:
            raise AuthError(
                f"{AuthErrorCode.TOKEN_IN_URL.value}: credential found in URL query string — use Sec-WebSocket-Protocol header"
            )


def _parse_ws_subprotocol_token(ws: Any) -> str | None:
    """Extract token from Sec-WebSocket-Protocol header.

    Looks for subprotocols matching 'auth.<TOKEN>' or 'token.<TOKEN>' (case-insensitive).

    Args:
        ws: WebSocket instance with .headers attribute.

    Returns:
        Extracted token string or None.
    """
    headers = getattr(ws, "headers", None)
    if headers is None:
        return None

    header_val: str | None = None
    if callable(getattr(headers, "get", None)):
        header_val = headers.get("sec-websocket-protocol")
    if not header_val:
        return None

    for part in header_val.split(","):
        stripped = part.strip()
        lower = stripped.lower()
        for prefix in ("auth.", "token."):
            if lower.startswith(prefix):
                return stripped[len(prefix) :]
    return None


class WSTokenManager:
    """JWT-based WebSocket token manager.

    Args:
        secret_key: HMAC secret (minimum 32 chars recommended).
        max_age: Token max age in seconds (default 3600).
    """

    def __init__(self, secret_key: str, max_age: int = 3600) -> None:
        super().__init__()
        if not secret_key:
            raise ValueError("WS_SECRET_KEY must not be empty")
        self._secret = secret_key
        self._max_age = max_age
        self._revoked: set[str] = set()  # revoked session-ids
        self._revoked_tokens: set[str] = set()  # revoked individual JWT strings
        # session_id -> {"user_id": str, "tokens": list[str], "expires_at": float}
        self._sessions: dict[str, dict[str, Any]] = {}

    def create_token(
        self,
        user_id: str,
        *,
        role: str = "trader",
        _session_id: str | None = None,
    ) -> dict[str, str]:
        """Create a signed JWT for the given user.

        Args:
            user_id: Subject claim.
            role: User role — 'trader', 'admin', 'viewer'. Default 'trader'.
            _session_id: Reuse an existing session (internal, for rotation).

        Returns:
            Dict with keys 'token', 'session_id', 'expires_in'.
        """
        session_id = _session_id or secrets.token_hex(16)
        now = time.time()
        exp = now + self._max_age
        payload: dict[str, Any] = {
            "sub": user_id,
            "sid": session_id,
            "jti": secrets.token_hex(8),
            "role": role,
            "iat": now,
            "exp": exp,
        }
        header = {"alg": "HS256", "typ": "JWT"}
        header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode())
        payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
        signature = _hmac_sign(header_b64, payload_b64, self._secret)
        token = f"{header_b64}.{payload_b64}.{signature}"

        # Track session
        if session_id not in self._sessions:
            self._sessions[session_id] = {
                "user_id": user_id,
                "role": role,
                "tokens": [],
                "expires_at": exp,
            }
        self._sessions[session_id]["tokens"].append(token)
        self._sessions[session_id]["expires_at"] = exp

        return {"token": token, "session_id": session_id, "expires_in": str(self._max_age)}

    def validate_token(self, token: str) -> SessionInfo:
        """Validate and decode a JWT.

        Raises:
            AuthError: If token is invalid, expired, or revoked.
        """
        if token in self._revoked_tokens:
            raise AuthError(AuthErrorCode.TOKEN_REVOKED.value)

        try:
            parts = token.split(".")
            if len(parts) != 3:
                raise AuthError(f"{AuthErrorCode.TOKEN_INVALID.value}: malformed JWT")

            header_b64, payload_b64, sig_b64 = parts

            # Verify header
            header = json.loads(_b64url_decode(header_b64))
            if header.get("alg") != "HS256":
                raise AuthError(f"{AuthErrorCode.TOKEN_INVALID.value}: unsupported algorithm")

            # Verify signature
            expected_sig = _hmac_sign(header_b64, payload_b64, self._secret)
            if not hmac.compare_digest(sig_b64, expected_sig):
                raise AuthError(f"{AuthErrorCode.TOKEN_INVALID.value}: signature mismatch")

            # Decode payload
            payload: dict[str, Any] = json.loads(_b64url_decode(payload_b64))

            # Check expiry
            exp = payload.get("exp")
            if exp is not None and time.time() > float(exp):
                raise AuthError(AuthErrorCode.TOKEN_EXPIRED.value)

        except AuthError:
            raise
        except Exception as exc:
            raise AuthError(f"{AuthErrorCode.TOKEN_INVALID.value}: {exc}") from exc

        session_id: str = payload.get("sid", "")
        if session_id in self._revoked:
            raise AuthError(AuthErrorCode.TOKEN_REVOKED.value)

        return SessionInfo(
            user_id=str(payload.get("sub", "")),
            session_id=session_id,
            issued_at=float(payload.get("iat", 0)),
            expires_at=float(payload.get("exp", 0)),
        )

    def revoke_session(self, session_id: str) -> None:
        """Revoke a session and all its tokens."""
        self._revoked.add(session_id)
        rec = self._sessions.get(session_id)
        if rec:
            for tok in rec["tokens"]:
                self._revoked_tokens.add(tok)

    def rotate_token(self, session_id: str) -> dict[str, str]:
        """Issue a new token for an existing session, revoking old tokens.

        Args:
            session_id: The session to rotate.

        Returns:
            New token dict with 'token', 'session_id', 'expires_in'.

        Raises:
            AuthError: If session is unknown, revoked, or expired.
        """
        if session_id in self._revoked:
            raise AuthError(f"{AuthErrorCode.TOKEN_INVALID.value}: session revoked")

        rec = self._sessions.get(session_id)
        if not rec:
            raise AuthError(f"{AuthErrorCode.TOKEN_INVALID.value}: session not found")

        if time.time() > rec["expires_at"]:
            raise AuthError(f"{AuthErrorCode.TOKEN_INVALID.value}: session expired")

        # Revoke all existing tokens for this session
        for tok in rec["tokens"]:
            self._revoked_tokens.add(tok)
        rec["tokens"].clear()

        # Create new token reusing the same session_id (preserve role)
        return self.create_token(rec["user_id"], role=rec.get("role", "trader"), _session_id=session_id)

    def revoke_all_for_user(self, user_id: str) -> int:
        """Revoke all sessions belonging to a user.

        Returns:
            Number of sessions revoked.
        """
        to_revoke = [
            sid for sid, rec in self._sessions.items() if rec["user_id"] == user_id and sid not in self._revoked
        ]
        for sid in to_revoke:
            self.revoke_session(sid)
        return len(to_revoke)


async def authenticate_websocket(
    ws: Any,
    manager: WSTokenManager,
    timeout: float = 10.0,
) -> SessionInfo:
    """Full WebSocket authentication flow.

    1. Reject token in URL query string.
    2. Try Sec-WebSocket-Protocol header token.
    3. Fall back to first message JSON auth.
    4. Send auth_ok on success; send_error_and_close on failure.

    Args:
        ws: WebSocket instance.
        manager: WSTokenManager for token validation.
        timeout: Seconds to wait for auth message (default 10).

    Returns:
        SessionInfo on success.

    Raises:
        AuthError: On any authentication failure.
    """
    # 1. Reject tokens in URL
    scope = getattr(ws, "scope", {})
    qs = scope.get("query_string", b"")
    if isinstance(qs, bytes):
        qs = qs.decode("utf-8", errors="replace")
    reject_token_in_url(qs)

    # 2. Try subprotocol header
    token = _parse_ws_subprotocol_token(ws)

    # 3. Try first message
    if not token:
        try:
            raw = await asyncio.wait_for(ws.receive_text(), timeout=timeout)
        except TimeoutError:
            await _send_error_and_close(ws, AuthErrorCode.AUTH_TIMEOUT, "Authentication timeout", close_code=1008)
            raise AuthError(AuthErrorCode.AUTH_TIMEOUT.value)  # noqa: B904

        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            await _send_error_and_close(ws, AuthErrorCode.NO_TOKEN, "Malformed JSON", close_code=1002)
            raise AuthError(AuthErrorCode.NO_TOKEN.value)  # noqa: B904

        if not isinstance(data, dict) or "token" not in data:
            await _send_error_and_close(ws, AuthErrorCode.NO_TOKEN, "Missing token field", close_code=1002)
            raise AuthError(AuthErrorCode.NO_TOKEN.value)

        token = data["token"]

    # 4. Reject empty / blank tokens
    if not token or (isinstance(token, str) and not token.strip()):
        await _send_error_and_close(ws, AuthErrorCode.NO_TOKEN, "Empty token", close_code=1008)
        raise AuthError(AuthErrorCode.NO_TOKEN.value)

    # 5. Validate
    try:
        session = manager.validate_token(token)
    except AuthError as exc:
        error_code = _map_auth_error_to_code(exc)
        await _send_error_and_close(ws, error_code, str(exc), close_code=1008)
        raise

    # 6. Send auth_ok confirmation
    with contextlib.suppress(Exception):
        await ws.send_text(json.dumps({"type": "auth_ok", "session_id": session.session_id}))

    return session


def _map_auth_error_to_code(error: AuthError) -> AuthErrorCode:
    """Map an AuthError to the corresponding AuthErrorCode.

    Inspects the error message for known error code values.
    Falls back to TOKEN_INVALID for unrecognised messages.
    """
    msg = str(error)
    for code in AuthErrorCode:
        if code.value in msg:
            return code
    return AuthErrorCode.TOKEN_INVALID


async def _send_error_and_close(
    ws: Any,
    error_code: AuthErrorCode,
    message: str,
    close_code: int = 1008,
) -> None:
    """Send an auth_error JSON payload and close the WebSocket.

    Silently swallows exceptions from already-closed connections.
    """
    with contextlib.suppress(Exception):
        await ws.send_text(json.dumps({"type": "auth_error", "code": error_code.value, "message": message}))
    with contextlib.suppress(Exception):
        await ws.close(code=close_code)
