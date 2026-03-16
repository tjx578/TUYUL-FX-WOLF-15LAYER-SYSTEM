"""
dashboard/ws_auth.py — WebSocket Authentication

Provides JWT-based WebSocket authentication including:
- Token creation and validation (JWT via PyJWT)
- Sec-WebSocket-Protocol subprotocol token extraction
- Token-in-URL rejection (security: tokens must never appear in URLs)
- Error-to-code mapping

Authority: Dashboard-layer security. No market decisions.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import secrets
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, cast

_jwt_available = False
try:
    import jwt as _jwt  # PyJWT

    _jwt_available = True
except ImportError:
    _jwt = None


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
        self._secret = secret_key
        self._max_age = max_age
        self._revoked: set[str] = set()

    def create_token(self, user_id: str) -> dict[str, str]:
        """Create a signed JWT for the given user.

        Returns:
            Dict with keys 'token' and 'session_id'.
        """
        session_id = secrets.token_hex(16)
        now = time.time()
        payload: dict[str, Any] = {
            "sub": user_id,
            "sid": session_id,
            "iat": now,
            "exp": now + self._max_age,
        }
        if _jwt_available and _jwt is not None:
            token = _jwt.encode(payload, self._secret, algorithm="HS256")
            if isinstance(token, bytes):
                token = token.decode("utf-8")
        else:
            # Fallback: simple base64-encoded JSON (not production-safe)
            import base64

            token = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
        return {"token": token, "session_id": session_id}

    def validate_token(self, token: str) -> SessionInfo:
        """Validate and decode a JWT.

        Args:
            token: The JWT to validate.

        Returns:
            SessionInfo with user_id and session details.

        Raises:
            AuthError: If token is invalid, expired, or revoked.
        """
        try:
            if _jwt_available and _jwt is not None:
                payload = cast(
                    dict[str, Any],
                    _jwt.decode(
                        token,
                        self._secret,
                        algorithms=["HS256"],
                        options={"verify_exp": True},
                    ),
                )
            else:
                import base64

                raw = base64.urlsafe_b64decode(token + "==")
                payload = json.loads(raw.decode())
                if "exp" in payload and time.time() > payload["exp"]:
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
        """Revoke a session by its session_id."""
        self._revoked.add(session_id)

    def rotate_token(self, old_token: str) -> dict[str, str]:
        """Validate old token, revoke it, and issue a new one.

        Args:
            old_token: The JWT to rotate.

        Returns:
            New token dict with 'token' and 'session_id'.
        """
        session = self.validate_token(old_token)
        self.revoke_session(session.session_id)
        return self.create_token(session.user_id)


async def authenticate_websocket(ws: Any, manager: WSTokenManager) -> SessionInfo:
    """Full WebSocket authentication flow.

    1. Reject token in URL query string.
    2. Try Sec-WebSocket-Protocol header token.
    3. Fall back to first message JSON auth.

    Args:
        ws: WebSocket instance.
        manager: WSTokenManager for token validation.

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
            raw = await asyncio.wait_for(ws.receive_text(), timeout=10.0)
            data = json.loads(raw)
            token = data.get("token")
        except TimeoutError:
            raise AuthError(AuthErrorCode.AUTH_TIMEOUT.value)  # noqa: B904
        except Exception:
            raise AuthError(AuthErrorCode.TOKEN_INVALID.value)  # noqa: B904

    if not token:
        raise AuthError(AuthErrorCode.NO_TOKEN.value)

    return manager.validate_token(token)


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
