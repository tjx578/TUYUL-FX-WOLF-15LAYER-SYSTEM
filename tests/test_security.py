"""
Security hardening tests.

Covers:
1. SQL injection prevention
2. WS token-in-URL rejection
3. TLS redirect middleware
4. API key rotation lifecycle
5. Audit trail immutability & chain integrity
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

# ═══════════════════════════════════════════════════════════════════
# 1. SQL Injection Prevention
# ═══════════════════════════════════════════════════════════════════
from dashboard.db import SQLInjectionError, sanitize_identifier, validate_query


class TestSQLInjectionGuard:
    def test_valid_asyncpg_query(self):
        validate_query("SELECT * FROM trades WHERE symbol = $1", ("EURUSD",))

    def test_valid_psycopg_query(self):
        validate_query("SELECT * FROM trades WHERE symbol = %s", ("EURUSD",))

    def test_valid_no_params(self):
        validate_query("SELECT count(*) FROM trades")

    def test_reject_fstring_interpolation(self):
        with pytest.raises(SQLInjectionError, match="interpolation"):
            validate_query("SELECT * FROM trades WHERE symbol = '{symbol}'")

    def test_reject_format_named(self):
        with pytest.raises(SQLInjectionError, match="interpolation"):
            validate_query("SELECT * FROM trades WHERE symbol = %(name)s", ("x",))

    def test_reject_params_without_placeholders(self):
        with pytest.raises(SQLInjectionError, match="no placeholders"):
            validate_query("SELECT * FROM trades", ("rogue_param",))

    def test_reject_placeholders_without_params(self):
        with pytest.raises(SQLInjectionError, match="no params"):
            validate_query("SELECT * FROM trades WHERE id = $1")

    def test_reject_param_count_mismatch(self):
        with pytest.raises(SQLInjectionError, match="mismatch"):
            validate_query("SELECT * FROM trades WHERE id = $1 AND symbol = $2", (1,))

    def test_reject_empty_query(self):
        with pytest.raises(SQLInjectionError, match="Empty"):
            validate_query("")


class TestSanitizeIdentifier:
    def test_valid_identifier(self):
        assert sanitize_identifier("trades") == '"trades"'
        assert sanitize_identifier("user_sessions") == '"user_sessions"'

    def test_reject_sql_injection_in_identifier(self):
        with pytest.raises(ValueError):
            sanitize_identifier("trades; DROP TABLE users")

    def test_reject_empty(self):
        with pytest.raises(ValueError):
            sanitize_identifier("")

    def test_reject_special_chars(self):
        with pytest.raises(ValueError):
            sanitize_identifier("table-name")

    def test_reject_starts_with_number(self):
        with pytest.raises(ValueError):
            sanitize_identifier("1table")


# ═══════════════════════════════════════════════════════════════════
# 2. WS Token-in-URL Rejection
# ═══════════════════════════════════════════════════════════════════

from dashboard.ws_auth import (  # noqa: E402
    AuthError,
    WSTokenManager,
    reject_token_in_url,
)


class TestWSTokenInURL:
    def test_reject_token_in_query_string(self):
        with pytest.raises(AuthError, match="TOKEN_IN_URL"):
            reject_token_in_url("token=abc123&foo=bar")

    def test_reject_auth_in_query_string(self):
        with pytest.raises(AuthError, match="TOKEN_IN_URL"):
            reject_token_in_url("auth=secret")

    def test_reject_access_token(self):
        with pytest.raises(AuthError, match="TOKEN_IN_URL"):
            reject_token_in_url("access_token=xyz")

    def test_reject_api_key(self):
        with pytest.raises(AuthError, match="TOKEN_IN_URL"):
            reject_token_in_url("api_key=abc")

    def test_allow_clean_query(self):
        reject_token_in_url("symbol=EURUSD&tf=M15")

    def test_allow_empty_query(self):
        reject_token_in_url("")


class TestWSTokenManager:
    def _make_manager(self):
        return WSTokenManager(secret_key="test-secret-key-32chars-minimum!")

    def test_create_and_validate(self):
        mgr = self._make_manager()
        result = mgr.create_token("user:admin")
        raw_token = result["token"]

        session = mgr.validate_token(raw_token)
        assert session.user_id == "user:admin"
        assert not session.is_expired

    def test_invalid_token_rejected(self):
        mgr = self._make_manager()
        with pytest.raises(AuthError):
            mgr.validate_token("totally-fake-token")

    def test_revoked_token_rejected(self):
        mgr = self._make_manager()
        result = mgr.create_token("user:admin")
        mgr.revoke_session(result["session_id"])

        with pytest.raises(AuthError):
            mgr.validate_token(result["token"])

    def test_expired_token_rejected(self):
        mgr = WSTokenManager(secret_key="test-secret-key-32chars-minimum!", max_age=0)
        result = mgr.create_token("user:admin")
        time.sleep(0.01)

        with pytest.raises(AuthError):
            mgr.validate_token(result["token"])

    def test_revoke_all_for_user(self):
        mgr = self._make_manager()
        r1 = mgr.create_token("user:admin")
        r2 = mgr.create_token("user:admin")
        r3 = mgr.create_token("user:other")

        count = mgr.revoke_all_for_user("user:admin")
        assert count == 2

        with pytest.raises(AuthError):
            mgr.validate_token(r1["token"])
        with pytest.raises(AuthError):
            mgr.validate_token(r2["token"])

        # Other user unaffected
        session = mgr.validate_token(r3["token"])
        assert session.user_id == "user:other"

    def test_no_secret_raises(self):
        with patch.dict(os.environ, {"WS_SECRET_KEY": ""}, clear=False):  # noqa: SIM117
            with pytest.raises(ValueError, match="WS_SECRET_KEY"):
                WSTokenManager(secret_key="")

    def test_rotate_token(self):
        mgr = self._make_manager()
        result = mgr.create_token("user:admin")
        old_token = result["token"]
        sid = result["session_id"]

        rotated = mgr.rotate_token(sid)
        new_token = rotated["token"]

        assert new_token != old_token
        assert rotated["session_id"] == sid

        # Old token must be revoked
        with pytest.raises(AuthError):
            mgr.validate_token(old_token)

        # New token must be valid
        session = mgr.validate_token(new_token)
        assert session.user_id == "user:admin"
        assert session.session_id == sid

    def test_rotate_revoked_session_fails(self):
        mgr = self._make_manager()
        result = mgr.create_token("user:admin")
        mgr.revoke_session(result["session_id"])

        with pytest.raises(AuthError):
            mgr.rotate_token(result["session_id"])

    def test_rotate_expired_session_fails(self):
        mgr = WSTokenManager(secret_key="test-secret-key-32chars-minimum!", max_age=0)
        result = mgr.create_token("user:admin")
        time.sleep(0.01)

        with pytest.raises(AuthError):
            mgr.rotate_token(result["session_id"])

    def test_rotate_nonexistent_session_fails(self):
        mgr = self._make_manager()
        with pytest.raises(AuthError):
            mgr.rotate_token("nonexistent-session-id")


from dashboard.ws_auth import (  # noqa: E402
    AuthErrorCode,
    _map_auth_error_to_code,
    _parse_ws_subprotocol_token,
    _send_error_and_close,
    authenticate_websocket,
)


class TestParseWSSubprotocolToken:
    """Tests for Sec-WebSocket-Protocol token extraction."""

    def test_auth_dot_token(self):
        ws = type("WS", (), {"headers": {"sec-websocket-protocol": "json, auth.mytoken123"}})()
        assert _parse_ws_subprotocol_token(ws) == "mytoken123"

    def test_token_dot_token(self):
        ws = type("WS", (), {"headers": {"sec-websocket-protocol": "auth, token.mytoken456"}})()
        assert _parse_ws_subprotocol_token(ws) == "mytoken456"

    def test_no_matching_prefix(self):
        ws = type("WS", (), {"headers": {"sec-websocket-protocol": "json, graphql"}})()
        assert _parse_ws_subprotocol_token(ws) is None

    def test_empty_header(self):
        ws = type("WS", (), {"headers": {"sec-websocket-protocol": ""}})()
        assert _parse_ws_subprotocol_token(ws) is None

    def test_no_header(self):
        ws = type("WS", (), {"headers": {}})()
        assert _parse_ws_subprotocol_token(ws) is None

    def test_no_headers_attr(self):
        ws = type("WS", (), {})()
        assert _parse_ws_subprotocol_token(ws) is None

    def test_case_insensitive_prefix(self):
        ws = type("WS", (), {"headers": {"sec-websocket-protocol": "json, AUTH.CaseSensitiveToken"}})()
        assert _parse_ws_subprotocol_token(ws) == "CaseSensitiveToken"


class TestMapAuthErrorToCode:
    """Tests for accurate AuthError → AuthErrorCode mapping."""

    def test_maps_expired(self):
        err = AuthError("TOKEN_EXPIRED")
        assert _map_auth_error_to_code(err) == AuthErrorCode.TOKEN_EXPIRED

    def test_maps_revoked(self):
        err = AuthError("TOKEN_REVOKED")
        assert _map_auth_error_to_code(err) == AuthErrorCode.TOKEN_REVOKED

    def test_maps_invalid(self):
        err = AuthError("TOKEN_INVALID")
        assert _map_auth_error_to_code(err) == AuthErrorCode.TOKEN_INVALID

    def test_unknown_falls_back_to_invalid(self):
        err = AuthError("SOMETHING_ELSE")
        assert _map_auth_error_to_code(err) == AuthErrorCode.TOKEN_INVALID


class TestSendErrorAndClose:
    """Tests that _send_error_and_close sends JSON and closes with correct code."""

    @pytest.mark.asyncio
    async def test_sends_and_closes(self):
        ws = AsyncMock()
        await _send_error_and_close(ws, AuthErrorCode.TOKEN_INVALID, "bad token", close_code=1008)

        ws.send_text.assert_called_once()
        sent = json.loads(ws.send_text.call_args[0][0])
        assert sent["type"] == "auth_error"
        assert sent["code"] == "TOKEN_INVALID"
        ws.close.assert_called_once_with(code=1008)

    @pytest.mark.asyncio
    async def test_protocol_error_close_code(self):
        ws = AsyncMock()
        await _send_error_and_close(ws, AuthErrorCode.NO_TOKEN, "malformed", close_code=1002)
        ws.close.assert_called_once_with(code=1002)

    @pytest.mark.asyncio
    async def test_tolerates_send_failure(self):
        ws = AsyncMock()
        ws.send_text.side_effect = RuntimeError("already closed")
        # Should not raise
        await _send_error_and_close(ws, AuthErrorCode.TOKEN_INVALID, "x")
        ws.close.assert_called_once()


class TestAuthenticateWebsocketSubprotocol:
    """Tests authenticate_websocket with Sec-WebSocket-Protocol header token."""

    def _make_manager(self):
        return WSTokenManager(secret_key="test-secret-key-32chars-minimum!")

    @pytest.mark.asyncio
    async def test_auth_via_subprotocol_header(self):
        mgr = self._make_manager()
        result = mgr.create_token("user:browser")
        raw_token = result["token"]

        ws = AsyncMock()
        ws.scope = {"query_string": b""}
        ws.headers = {"sec-websocket-protocol": f"json, auth.{raw_token}"}

        session = await authenticate_websocket(ws, mgr)
        assert session.user_id == "user:browser"
        ws.send_text.assert_called_once()  # auth_ok message

    @pytest.mark.asyncio
    async def test_auth_via_first_message_fallback(self):
        mgr = self._make_manager()
        result = mgr.create_token("user:js")
        raw_token = result["token"]

        ws = AsyncMock()
        ws.scope = {"query_string": b""}
        ws.headers = {}  # No subprotocol header
        ws.receive_text.return_value = json.dumps({"type": "auth", "token": raw_token})

        session = await authenticate_websocket(ws, mgr)
        assert session.user_id == "user:js"

    @pytest.mark.asyncio
    async def test_closes_on_invalid_token(self):
        mgr = self._make_manager()

        ws = AsyncMock()
        ws.scope = {"query_string": b""}
        ws.headers = {"sec-websocket-protocol": "json, auth.totally-fake-token"}

        with pytest.raises(AuthError):
            await authenticate_websocket(ws, mgr)

        ws.close.assert_called_once_with(code=1008)

    @pytest.mark.asyncio
    async def test_closes_on_malformed_json(self):
        mgr = self._make_manager()

        ws = AsyncMock()
        ws.scope = {"query_string": b""}
        ws.headers = {}
        ws.receive_text.return_value = "NOT JSON{{{{"

        with pytest.raises(AuthError):
            await authenticate_websocket(ws, mgr)

        ws.close.assert_called_once_with(code=1002)

    @pytest.mark.asyncio
    async def test_expired_token_returns_correct_code(self):
        mgr = WSTokenManager(secret_key="test-secret-key-32chars-minimum!", max_age=0)
        result = mgr.create_token("user:expiring")
        time.sleep(0.01)

        ws = AsyncMock()
        ws.scope = {"query_string": b""}
        ws.headers = {"sec-websocket-protocol": f"json, auth.{result['token']}"}

        with pytest.raises(AuthError, match="TOKEN_EXPIRED"):
            await authenticate_websocket(ws, mgr)

        # Verify error sent has correct code
        sent = json.loads(ws.send_text.call_args[0][0])
        assert sent["code"] == "TOKEN_EXPIRED"
        ws.close.assert_called_once_with(code=1008)


# ═══════════════════════════════════════════════════════════════════
# 3. TLS Redirect Middleware
# ═══════════════════════════════════════════════════════════════════

from dashboard.middleware.tls import TLSRedirectMiddleware  # noqa: E402


class TestTLSRedirect:
    @pytest.mark.asyncio
    async def test_http_gets_redirected(self):
        app = AsyncMock()
        TLSRedirectMiddleware(app)

        sent_messages = []

        async def mock_send(msg):
            sent_messages.append(msg)

        scope = {
            "type": "http",
            "scheme": "http",
            "path": "/api/signals",
            "headers": [(b"host", b"example.com")],
            "query_string": b"",
        }

        with patch.dict(os.environ, {"DISABLE_TLS_REDIRECT": ""}, clear=False):
            # Re-import to pick up env
            from importlib import reload

            import dashboard.middleware.tls as tls_mod

            reload(tls_mod)
            mw2 = tls_mod.TLSRedirectMiddleware(app)
            await mw2(scope, AsyncMock(), mock_send)

        assert len(sent_messages) >= 1
        start_msg = sent_messages[0]
        assert start_msg["status"] == 301
        # Check location header
        headers = dict(start_msg["headers"])
        assert b"location" in headers
        assert headers[b"location"].startswith(b"https://")

    @pytest.mark.asyncio
    async def test_https_passes_through(self):
        app = AsyncMock()
        TLSRedirectMiddleware(app)

        scope = {
            "type": "http",
            "scheme": "https",
            "path": "/api/signals",
            "headers": [(b"host", b"example.com")],
        }

        with patch.dict(os.environ, {"DISABLE_TLS_REDIRECT": ""}, clear=False):
            from importlib import reload

            import dashboard.middleware.tls as tls_mod

            reload(tls_mod)
            mw2 = tls_mod.TLSRedirectMiddleware(app)
            await mw2(scope, AsyncMock(), AsyncMock())

        app.assert_called_once()

    @pytest.mark.asyncio
    async def test_health_exempt(self):
        app = AsyncMock()

        scope = {
            "type": "http",
            "scheme": "http",
            "path": "/health",
            "headers": [],
        }

        with patch.dict(os.environ, {"DISABLE_TLS_REDIRECT": ""}, clear=False):
            from importlib import reload

            import dashboard.middleware.tls as tls_mod

            reload(tls_mod)
            mw = tls_mod.TLSRedirectMiddleware(app)
            await mw(scope, AsyncMock(), AsyncMock())

        app.assert_called_once()


# ═══════════════════════════════════════════════════════════════════
# 4. API Key Rotation
# ═══════════════════════════════════════════════════════════════════

from dashboard.api_key_manager import APIKeyManager, KeyStatus  # noqa: E402


class TestAPIKeyManager:
    def _make_manager(self, tmp_path: Path | None = None):  # noqa: F821
        return APIKeyManager(
            secret_key="test-api-secret-key-long-enough!!",
            storage_path=tmp_path / "keys.json" if tmp_path else None,
        )

    def test_create_and_validate(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        result = mgr.create_key("user:admin", label="test-key", scopes=["read", "trade"])

        assert result["raw_key"].startswith("wolf_")
        assert "key_id" in result

        record = mgr.validate_key(result["raw_key"])
        assert record is not None
        assert record.owner == "user:admin"
        assert record.scopes == ["read", "trade"]

    def test_invalid_key(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        assert mgr.validate_key("wolf_fake_key") is None

    def test_rotate_key(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        old = mgr.create_key("user:admin", label="main")
        old_key_id = old["key_id"]

        new = mgr.rotate_key(old_key_id)
        assert new is not None
        assert new["key_id"] != old_key_id

        # Both keys should be valid during grace period
        old_record = mgr.validate_key(old["raw_key"])
        assert old_record is not None
        assert old_record.status == KeyStatus.ROTATING

        new_record = mgr.validate_key(new["raw_key"])
        assert new_record is not None
        assert new_record.status == KeyStatus.ACTIVE

    def test_revoke_key(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        result = mgr.create_key("user:admin")
        mgr.revoke_key(result["key_id"])

        assert mgr.validate_key(result["raw_key"]) is None

    def test_list_keys_hides_hash(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        mgr.create_key("user:admin", label="k1")
        mgr.create_key("user:admin", label="k2")

        keys = mgr.list_keys(owner="user:admin")
        assert len(keys) == 2
        for k in keys:
            assert "key_hash" not in k
            assert "key_id" in k

    def test_persistence(self, tmp_path):
        mgr1 = self._make_manager(tmp_path)
        result = mgr1.create_key("user:admin", label="persistent")

        # Create new manager pointing to same file
        mgr2 = self._make_manager(tmp_path)
        record = mgr2.validate_key(result["raw_key"])
        assert record is not None
        assert record.label == "persistent"

    def test_no_secret_raises(self):
        with patch.dict(os.environ, {"API_KEY_SECRET": ""}, clear=False):  # noqa: SIM117
            with pytest.raises(ValueError, match="API_KEY_SECRET"):
                APIKeyManager(secret_key="")


# ═══════════════════════════════════════════════════════════════════
# 5. Audit Trail Immutability & Integrity
# ═══════════════════════════════════════════════════════════════════

from journal.audit_trail import AuditAction, AuditTrail  # noqa: E402


class TestAuditTrail:
    def test_append_and_count(self, tmp_path):
        trail = AuditTrail(log_path=tmp_path / "audit.jsonl")

        trail.log(
            AuditAction.SIGNAL_CREATED,
            actor="system:l12",
            resource="signal:abc123",
            details={"symbol": "EURUSD", "verdict": "EXECUTE"},
        )
        trail.log(
            AuditAction.ORDER_PLACED,
            actor="ea",
            resource="order:xyz789",
            details={"lot_size": 0.1},
        )

        assert trail.entry_count == 2

    def test_chain_integrity_valid(self, tmp_path):
        trail = AuditTrail(log_path=tmp_path / "audit.jsonl")

        for i in range(10):
            trail.log(
                AuditAction.RISK_CHECK_PASSED,
                actor="system:risk",
                resource=f"check:{i}",
                details={"iteration": i},
            )

        result = trail.verify_integrity()
        assert result["valid"] is True
        assert result["entries_checked"] == 10

    def test_chain_integrity_detects_tampering(self, tmp_path):
        log_path = tmp_path / "audit.jsonl"
        trail = AuditTrail(log_path=log_path)

        trail.log(AuditAction.SIGNAL_CREATED, "system", "sig:1")
        trail.log(AuditAction.ORDER_PLACED, "ea", "order:1")
        trail.log(AuditAction.ORDER_FILLED, "ea", "order:1")

        # Tamper with the second line
        lines = log_path.read_text().strip().split("\n")
        tampered = json.loads(lines[1])
        tampered["actor"] = "hacker"
        lines[1] = json.dumps(tampered, separators=(",", ":"), sort_keys=True)
        log_path.write_text("\n".join(lines) + "\n")

        result = trail.verify_integrity()
        assert result["valid"] is False
        assert result["first_bad_entry"] == 1

    def test_recovery_after_restart(self, tmp_path):
        log_path = tmp_path / "audit.jsonl"

        # Session 1
        trail1 = AuditTrail(log_path=log_path)
        trail1.log(AuditAction.SIGNAL_CREATED, "system", "sig:1")
        trail1.log(AuditAction.ORDER_PLACED, "ea", "order:1")

        # Session 2 (restart)
        trail2 = AuditTrail(log_path=log_path)
        assert trail2.entry_count == 2

        trail2.log(AuditAction.ORDER_FILLED, "ea", "order:1")
        assert trail2.entry_count == 3

        # Chain should still be valid
        result = trail2.verify_integrity()
        assert result["valid"] is True
        assert result["entries_checked"] == 3

    def test_rejected_setup_logged(self, tmp_path):
        """Constitutional requirement: all rejected setups MUST be journaled."""
        trail = AuditTrail(log_path=tmp_path / "audit.jsonl")

        entry = trail.log(
            AuditAction.SIGNAL_REJECTED,
            actor="system:l12",
            resource="signal:rej001",
            details={
                "symbol": "GBPJPY",
                "reason": "Wolf score below threshold",
                "wolf_score": 3.2,
                "threshold": 5.0,
            },
        )

        assert entry.action == "SIGNAL_REJECTED"
        assert entry.details["reason"] == "Wolf score below threshold"

    def test_entry_is_frozen(self, tmp_path):
        """AuditEntry is immutable (frozen dataclass)."""
        trail = AuditTrail(log_path=tmp_path / "audit.jsonl")
        entry = trail.log(AuditAction.SIGNAL_CREATED, "system", "sig:1")

        with pytest.raises(AttributeError):
            entry.action = "TAMPERED"  # type: ignore[misc]

    def test_prop_firm_violation_logged(self, tmp_path):
        trail = AuditTrail(log_path=tmp_path / "audit.jsonl")

        entry = trail.log(
            AuditAction.PROP_FIRM_VIOLATION,
            actor="system:risk",
            resource="account:ftmo_001",
            details={
                "rule": "max_daily_loss",
                "current_loss": -450.0,
                "limit": -500.0,
                "severity": "warning",
            },
        )

        assert entry.action == "PROP_FIRM_VIOLATION"
        assert entry.details["severity"] == "warning"


# ═══════════════════════════════════════════════════════════════════
# 6. Integration: Audit + API Key rotation
# ═══════════════════════════════════════════════════════════════════


class TestSecurityIntegration:
    def test_key_rotation_audited(self, tmp_path):
        """API key rotation events should be audit-loggable."""
        trail = AuditTrail(log_path=tmp_path / "audit.jsonl")
        mgr = APIKeyManager(
            secret_key="test-api-secret-key-long-enough!!",
            storage_path=tmp_path / "keys.json",
        )

        result = mgr.create_key("user:admin", label="main")

        # Log the creation
        trail.log(
            AuditAction.API_KEY_CREATED,
            actor="user:admin",
            resource=f"key:{result['key_id']}",
            details={"label": "main"},
        )

        # Rotate
        new_result = mgr.rotate_key(result["key_id"])
        trail.log(
            AuditAction.API_KEY_ROTATED,
            actor="user:admin",
            resource=f"key:{result['key_id']}",
            details={
                "old_key_id": result["key_id"],
                "new_key_id": new_result["key_id"],  # pyright: ignore[reportOptionalSubscript]
            },
        )

        integrity = trail.verify_integrity()
        assert integrity["valid"] is True
        assert integrity["entries_checked"] == 2
