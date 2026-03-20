"""
WebSocket authentication tests.

Covers all 5 high-impact security enhancements:
1. Sec-WebSocket-Protocol token parsing
2. asyncio.TimeoutError handling (not builtin TimeoutError)
3. _send_error_and_close (proper close codes)
4. _map_auth_error_to_code (expired/revoked/invalid mapping)
5. WSTokenManager.rotate_token
6. Full authenticate_websocket flow (header + message auth)
"""

from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from dashboard.ws_auth import (
    AuthError,
    AuthErrorCode,
    WSTokenManager,
    _map_auth_error_to_code,
    _parse_ws_subprotocol_token,
    _send_error_and_close,
    authenticate_websocket,
)

# ── Helpers ───────────────────────────────────────────────────────

def _make_manager(max_age: int = 3600) -> WSTokenManager:
    return WSTokenManager(secret_key="test-secret-key-32chars-minimum!", max_age=max_age)


def _fake_websocket(
    headers: dict[str, str] | None = None,
    query_string: bytes = b"",
    receive_messages: list[str] | None = None,
) -> AsyncMock:
    """Build a mock WebSocket with configurable headers, scope, send/receive."""
    ws = AsyncMock()

    # Headers — behave like Starlette's Headers (dict-like .get())
    hdr = headers or {}
    ws.headers = MagicMock()
    ws.headers.get = lambda key, default=None: hdr.get(key, default)

    # Scope (for reject_token_in_url)
    ws.scope = {"query_string": query_string}

    # Receive queue
    if receive_messages:
        ws.receive_text = AsyncMock(side_effect=receive_messages)
    else:
        ws.receive_text = AsyncMock(side_effect=asyncio.TimeoutError)

    # Track sent messages
    sent: list[str] = []

    async def _send_text(msg: str) -> None:
        sent.append(msg)

    ws.send_text = AsyncMock(side_effect=_send_text)
    ws._sent = sent  # expose for assertions
    ws.close = AsyncMock()

    return ws


# ═══════════════════════════════════════════════════════════════════
# 1. Sec-WebSocket-Protocol header parsing
# ═══════════════════════════════════════════════════════════════════


class TestParseWSSubprotocolToken:

    def test_auth_dot_token(self):
        ws = _fake_websocket(headers={"sec-websocket-protocol": "json, auth.MY_SECRET_TOKEN"})
        assert _parse_ws_subprotocol_token(ws) == "MY_SECRET_TOKEN"

    def test_token_dot_token(self):
        ws = _fake_websocket(headers={"sec-websocket-protocol": "auth, token.MY_SECRET_TOKEN"})
        assert _parse_ws_subprotocol_token(ws) == "MY_SECRET_TOKEN"

    def test_auth_dot_only_subprotocol(self):
        ws = _fake_websocket(headers={"sec-websocket-protocol": "auth.ABC123"})
        assert _parse_ws_subprotocol_token(ws) == "ABC123"

    def test_no_header_returns_none(self):
        ws = _fake_websocket(headers={})
        assert _parse_ws_subprotocol_token(ws) is None

    def test_no_matching_prefix_returns_none(self):
        ws = _fake_websocket(headers={"sec-websocket-protocol": "json, graphql"})
        assert _parse_ws_subprotocol_token(ws) is None

    def test_empty_header_returns_none(self):
        ws = _fake_websocket(headers={"sec-websocket-protocol": ""})
        assert _parse_ws_subprotocol_token(ws) is None

    def test_case_insensitive_prefix(self):
        ws = _fake_websocket(headers={"sec-websocket-protocol": "AUTH.CaseToken"})
        assert _parse_ws_subprotocol_token(ws) == "CaseToken"

    def test_token_dot_case_insensitive(self):
        ws = _fake_websocket(headers={"sec-websocket-protocol": "TOKEN.CaseToken"})
        assert _parse_ws_subprotocol_token(ws) == "CaseToken"

    def test_no_headers_attr_returns_none(self):
        ws = SimpleNamespace()  # no .headers attribute
        assert _parse_ws_subprotocol_token(ws) is None

    def test_multiple_formats_picks_first(self):
        ws = _fake_websocket(
            headers={"sec-websocket-protocol": "auth.FIRST, token.SECOND"}
        )
        assert _parse_ws_subprotocol_token(ws) == "FIRST"


# ═══════════════════════════════════════════════════════════════════
# 2. _map_auth_error_to_code
# ═══════════════════════════════════════════════════════════════════


class TestMapAuthErrorToCode:

    def test_expired_maps_correctly(self):
        err = AuthError(AuthErrorCode.TOKEN_EXPIRED.value)
        assert _map_auth_error_to_code(err) == AuthErrorCode.TOKEN_EXPIRED

    def test_revoked_maps_correctly(self):
        err = AuthError(AuthErrorCode.TOKEN_REVOKED.value)
        assert _map_auth_error_to_code(err) == AuthErrorCode.TOKEN_REVOKED

    def test_invalid_maps_correctly(self):
        err = AuthError(AuthErrorCode.TOKEN_INVALID.value)
        assert _map_auth_error_to_code(err) == AuthErrorCode.TOKEN_INVALID

    def test_timeout_maps_correctly(self):
        err = AuthError(AuthErrorCode.AUTH_TIMEOUT.value)
        assert _map_auth_error_to_code(err) == AuthErrorCode.AUTH_TIMEOUT

    def test_no_token_maps_correctly(self):
        err = AuthError(AuthErrorCode.NO_TOKEN.value)
        assert _map_auth_error_to_code(err) == AuthErrorCode.NO_TOKEN

    def test_unknown_falls_back_to_invalid(self):
        err = AuthError("some random message")
        assert _map_auth_error_to_code(err) == AuthErrorCode.TOKEN_INVALID


# ═══════════════════════════════════════════════════════════════════
# 3. _send_error_and_close
# ═══════════════════════════════════════════════════════════════════


class TestSendErrorAndClose:

    @pytest.mark.asyncio
    async def test_sends_error_json_then_closes(self):
        ws = _fake_websocket()
        await _send_error_and_close(ws, AuthErrorCode.TOKEN_EXPIRED, "Token expired", close_code=1008)

        assert ws.send_text.called
        sent_json = json.loads(ws._sent[0])
        assert sent_json["type"] == "auth_error"
        assert sent_json["code"] == "TOKEN_EXPIRED"
        assert sent_json["message"] == "Token expired"

        ws.close.assert_called_once_with(code=1008)

    @pytest.mark.asyncio
    async def test_close_code_1002_for_protocol_error(self):
        ws = _fake_websocket()
        await _send_error_and_close(ws, AuthErrorCode.NO_TOKEN, "Malformed", close_code=1002)
        ws.close.assert_called_once_with(code=1002)

    @pytest.mark.asyncio
    async def test_survives_send_failure(self):
        ws = _fake_websocket()
        ws.send_text = AsyncMock(side_effect=RuntimeError("already closed"))
        # Should not raise
        await _send_error_and_close(ws, AuthErrorCode.TOKEN_INVALID, "fail")
        ws.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_survives_close_failure(self):
        ws = _fake_websocket()
        ws.close = AsyncMock(side_effect=RuntimeError("already closed"))
        # Should not raise
        await _send_error_and_close(ws, AuthErrorCode.TOKEN_INVALID, "fail")


# ═══════════════════════════════════════════════════════════════════
# 4. WSTokenManager.rotate_token
# ═══════════════════════════════════════════════════════════════════


class TestWSTokenRotation:

    def test_rotate_returns_new_token(self):
        mgr = _make_manager()
        original = mgr.create_token("user:admin")
        rotated = mgr.rotate_token(original["session_id"])

        assert rotated["token"] != original["token"]
        assert rotated["session_id"] == original["session_id"]
        assert "expires_in" in rotated

    def test_old_token_revoked_after_rotate(self):
        mgr = _make_manager()
        original = mgr.create_token("user:admin")
        mgr.rotate_token(original["session_id"])

        with pytest.raises(AuthError, match="TOKEN_REVOKED"):
            mgr.validate_token(original["token"])

    def test_new_token_validates(self):
        mgr = _make_manager()
        original = mgr.create_token("user:admin")
        rotated = mgr.rotate_token(original["session_id"])

        session = mgr.validate_token(rotated["token"])
        assert session.user_id == "user:admin"
        assert session.session_id == original["session_id"]
        assert not session.is_expired

    def test_rotate_expired_session_raises(self):
        mgr = _make_manager(max_age=0)
        original = mgr.create_token("user:admin")
        time.sleep(0.01)

        with pytest.raises(AuthError, match="TOKEN_INVALID"):
            mgr.rotate_token(original["session_id"])

    def test_rotate_revoked_session_raises(self):
        mgr = _make_manager()
        original = mgr.create_token("user:admin")
        mgr.revoke_session(original["session_id"])

        with pytest.raises(AuthError, match="TOKEN_INVALID"):
            mgr.rotate_token(original["session_id"])

    def test_rotate_nonexistent_session_raises(self):
        mgr = _make_manager()
        with pytest.raises(AuthError, match="TOKEN_INVALID"):
            mgr.rotate_token("nonexistent-session-id")

    def test_multiple_rotations(self):
        mgr = _make_manager()
        original = mgr.create_token("user:admin")
        rotated1 = mgr.rotate_token(original["session_id"])
        rotated2 = mgr.rotate_token(original["session_id"])

        # Only the latest token should work
        with pytest.raises(AuthError):
            mgr.validate_token(original["token"])
        with pytest.raises(AuthError):
            mgr.validate_token(rotated1["token"])

        session = mgr.validate_token(rotated2["token"])
        assert session.user_id == "user:admin"


# ═══════════════════════════════════════════════════════════════════
# 5. authenticate_websocket — full flow
# ═══════════════════════════════════════════════════════════════════


class TestAuthenticateWebsocket:

    @pytest.mark.asyncio
    async def test_auth_via_subprotocol_header(self):
        mgr = _make_manager()
        result = mgr.create_token("user:admin")

        ws = _fake_websocket(
            headers={"sec-websocket-protocol": f"json, auth.{result['token']}"},
        )

        session = await authenticate_websocket(ws, mgr)
        assert session.user_id == "user:admin"

        # Should have sent auth_ok
        assert len(ws._sent) == 1
        ok_msg = json.loads(ws._sent[0])
        assert ok_msg["type"] == "auth_ok"
        assert ok_msg["session_id"] == session.session_id

    @pytest.mark.asyncio
    async def test_auth_via_first_message(self):
        mgr = _make_manager()
        result = mgr.create_token("user:admin")

        auth_msg = json.dumps({"type": "auth", "token": result["token"]})
        ws = _fake_websocket(receive_messages=[auth_msg])

        session = await authenticate_websocket(ws, mgr)
        assert session.user_id == "user:admin"

    @pytest.mark.asyncio
    async def test_reject_token_in_url(self):
        mgr = _make_manager()
        ws = _fake_websocket(query_string=b"token=evil")

        with pytest.raises(AuthError, match="TOKEN_IN_URL"):
            await authenticate_websocket(ws, mgr)

    @pytest.mark.asyncio
    async def test_timeout_raises_and_closes(self):
        mgr = _make_manager()
        ws = _fake_websocket()  # receive_text raises asyncio.TimeoutError by default

        with pytest.raises(AuthError, match="AUTH_TIMEOUT"):
            await authenticate_websocket(ws, mgr, timeout=0.01)

        # Verify close was called with 1008
        ws.close.assert_called_once_with(code=1008)

    @pytest.mark.asyncio
    async def test_malformed_json_closes_with_1002(self):
        mgr = _make_manager()
        ws = _fake_websocket(receive_messages=["not-json-at-all"])

        with pytest.raises(AuthError, match="NO_TOKEN"):
            await authenticate_websocket(ws, mgr)

        ws.close.assert_called_once_with(code=1002)

    @pytest.mark.asyncio
    async def test_wrong_message_type_closes_with_1002(self):
        mgr = _make_manager()
        ws = _fake_websocket(
            receive_messages=[json.dumps({"type": "subscribe", "channel": "signals"})]
        )

        with pytest.raises(AuthError, match="NO_TOKEN"):
            await authenticate_websocket(ws, mgr)

        ws.close.assert_called_once_with(code=1002)

    @pytest.mark.asyncio
    async def test_invalid_token_closes_with_1008(self):
        mgr = _make_manager()
        ws = _fake_websocket(
            receive_messages=[json.dumps({"type": "auth", "token": "fake-token"})]
        )

        with pytest.raises(AuthError, match="TOKEN_INVALID"):
            await authenticate_websocket(ws, mgr)

        ws.close.assert_called_once_with(code=1008)

    @pytest.mark.asyncio
    async def test_expired_token_returns_correct_code(self):
        mgr = _make_manager(max_age=0)
        result = mgr.create_token("user:admin")
        time.sleep(0.01)

        ws = _fake_websocket(
            receive_messages=[json.dumps({"type": "auth", "token": result["token"]})]
        )

        with pytest.raises(AuthError, match="TOKEN_EXPIRED"):
            await authenticate_websocket(ws, mgr)

        # Verify error message sent is TOKEN_EXPIRED, not TOKEN_INVALID
        sent_json = json.loads(ws._sent[0])
        assert sent_json["code"] == "TOKEN_EXPIRED"
        ws.close.assert_called_once_with(code=1008)

    @pytest.mark.asyncio
    async def test_revoked_token_returns_correct_code(self):
        mgr = _make_manager()
        result = mgr.create_token("user:admin")
        mgr.revoke_session(result["session_id"])

        ws = _fake_websocket(
            receive_messages=[json.dumps({"type": "auth", "token": result["token"]})]
        )

        with pytest.raises(AuthError, match="TOKEN_REVOKED"):
            await authenticate_websocket(ws, mgr)

        sent_json = json.loads(ws._sent[0])
        assert sent_json["code"] == "TOKEN_REVOKED"

    @pytest.mark.asyncio
    async def test_empty_token_in_message_closes(self):
        mgr = _make_manager()
        ws = _fake_websocket(
            receive_messages=[json.dumps({"type": "auth", "token": "  "})]
        )

        with pytest.raises(AuthError, match="NO_TOKEN"):
            await authenticate_websocket(ws, mgr)

        ws.close.assert_called_once_with(code=1008)

    @pytest.mark.asyncio
    async def test_header_preferred_over_message(self):
        """If subprotocol header has a valid token, first message is not consumed."""
        mgr = _make_manager()
        result = mgr.create_token("user:admin")

        ws = _fake_websocket(
            headers={"sec-websocket-protocol": f"auth.{result['token']}"},
            receive_messages=[json.dumps({"type": "auth", "token": "should-not-be-used"})],
        )

        session = await authenticate_websocket(ws, mgr)
        assert session.user_id == "user:admin"
        # receive_text should NOT have been called since header had the token
        ws.receive_text.assert_not_called()
