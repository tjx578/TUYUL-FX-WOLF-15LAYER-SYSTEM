"""Regression: WebSocket auth guard (api/middleware/ws_auth.py) and WS event envelope.

Tests the ws_auth_guard function for token extraction, validation, expiry,
and account-scope checks.  Also tests _ws_event envelope structure from
api/ws_routes.py.
"""

from __future__ import annotations

import time

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

_TEST_SECRET = "test-jwt-secret-that-is-at-least-32-chars-long!"


def _make_mock_websocket(
    *,
    query_params: dict | None = None,
    headers: dict | None = None,
) -> MagicMock:
    """Create a mock WebSocket with realistic attributes."""
    ws = MagicMock()
    ws.query_params = query_params or {}
    ws.headers = headers or {}
    ws.state = MagicMock()
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    return ws


# ============================================================================
# ws_auth_guard tests
# ============================================================================

class TestWsAuthGuard:
    """Test api.middleware.ws_auth.ws_auth_guard."""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_token(self):
        from api.middleware.ws_auth import ws_auth_guard

        ws = _make_mock_websocket()
        result = await ws_auth_guard(ws)

        assert result is None
        ws.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_none_when_invalid_token(self):
        from api.middleware.ws_auth import ws_auth_guard

        ws = _make_mock_websocket(query_params={"token": "bogus.invalid.token"})
        result = await ws_auth_guard(ws)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_payload_with_valid_token(self):
        """Mock decode_token to return a valid payload."""
        now = int(time.time())
        fake_payload = {
            "sub": "test_user",
            "iat": now,
            "exp": now + 3600,
            "role": "admin",
        }
        with patch("api.middleware.ws_auth.decode_token", return_value=fake_payload):
            from api.middleware.ws_auth import ws_auth_guard

            ws = _make_mock_websocket(query_params={"token": "valid.jwt.token"})
            result = await ws_auth_guard(ws)

        assert result is not None
        assert result["sub"] == "test_user"
        assert ws.state.auth_payload == fake_payload

    @pytest.mark.asyncio
    async def test_returns_none_when_token_expired(self):
        """JWT with exp in the past should be rejected."""
        past = int(time.time()) - 3600
        expired_payload = {
            "sub": "test_user",
            "iat": past - 7200,
            "exp": past,
        }
        with patch("api.middleware.ws_auth.decode_token", return_value=expired_payload):
            from api.middleware.ws_auth import ws_auth_guard

            ws = _make_mock_websocket(query_params={"token": "expired.jwt.token"})
            result = await ws_auth_guard(ws)

        assert result is None

    @pytest.mark.asyncio
    async def test_account_scope_denied(self):
        """Token without access to requested account_id should be rejected."""
        now = int(time.time())
        payload = {
            "sub": "limited_user",
            "iat": now,
            "exp": now + 3600,
            "account_id": "ACCT-001",
        }
        with patch("api.middleware.ws_auth.decode_token", return_value=payload):
            from api.middleware.ws_auth import ws_auth_guard

            ws = _make_mock_websocket(
                query_params={"token": "valid.jwt.token", "account_id": "ACCT-999"},
            )
            result = await ws_auth_guard(ws)

        assert result is None

    @pytest.mark.asyncio
    async def test_account_scope_allowed_admin(self):
        """Admin role should have access to any account."""
        now = int(time.time())
        payload = {
            "sub": "admin_user",
            "iat": now,
            "exp": now + 3600,
            "role": "admin",
        }
        with patch("api.middleware.ws_auth.decode_token", return_value=payload):
            from api.middleware.ws_auth import ws_auth_guard

            ws = _make_mock_websocket(
                query_params={"token": "valid.jwt.token", "account_id": "ANY-ACCT"},
            )
            result = await ws_auth_guard(ws)

        assert result is not None
        assert result["role"] == "admin"

    @pytest.mark.asyncio
    async def test_api_key_auth_skips_expiry_check(self):
        """API key auth (via validate_api_key) has no exp; should still pass.

        The verify_token helper returns a payload with auth_method=api_key,
        which bypasses the JWT exp check.  We also need account scope to pass,
        so the mock payload includes ``scopes: "account:*"`` (string format —
        the _claim_set helper in ws_auth.py splits on whitespace/commas).
        """
        api_key_payload = {"sub": "api_key_user", "auth_method": "api_key", "scopes": "account:*"}
        with (
            patch("api.middleware.ws_auth.decode_token", return_value=None),
            patch("api.middleware.ws_auth.validate_api_key", return_value=True),
            patch("api.middleware.ws_auth.verify_token", return_value=api_key_payload) as mock_vt,
        ):
            from api.middleware.ws_auth import ws_auth_guard

            ws = _make_mock_websocket(query_params={"token": "my-api-key"})
            result = await ws_auth_guard(ws)

        assert result is not None
        assert result.get("auth_method") == "api_key"

    @pytest.mark.asyncio
    async def test_jwt_missing_exp_claim_rejected(self):
        """JWT without exp claim should be rejected (non-API-key)."""
        payload_no_exp = {
            "sub": "user",
            "iat": int(time.time()),
        }
        with patch("api.middleware.ws_auth.decode_token", return_value=payload_no_exp):
            from api.middleware.ws_auth import ws_auth_guard

            ws = _make_mock_websocket(query_params={"token": "jwt.no.exp"})
            result = await ws_auth_guard(ws)

        assert result is None


# ============================================================================
# extract_token tests
# ============================================================================

class TestExtractToken:
    def test_extracts_from_query_param(self):
        from api.middleware.ws_auth import extract_token

        result = extract_token({}, {"token": "my-token"})
        assert result == "my-token"

    def test_extracts_from_authorization_header(self):
        from api.middleware.ws_auth import extract_token

        result = extract_token({"authorization": "Bearer my-jwt"}, {})
        assert result == "my-jwt"

    def test_query_param_takes_priority(self):
        from api.middleware.ws_auth import extract_token

        result = extract_token(
            {"authorization": "Bearer header-token"},
            {"token": "query-token"},
        )
        assert result == "query-token"

    def test_returns_none_when_empty(self):
        from api.middleware.ws_auth import extract_token

        result = extract_token({}, {})
        assert result is None


# ============================================================================
# _ws_event envelope tests
# ============================================================================

class TestWsEventEnvelope:
    def test_envelope_structure(self):
        from api.ws_routes import _ws_event

        evt = _ws_event("price_update", {"symbol": "EURUSD", "bid": 1.1234})

        assert evt["event_version"] == "1.0"
        assert evt["event_type"] == "price_update"
        assert "event_id" in evt
        assert "server_ts" in evt
        assert "trace_id" in evt
        assert evt["payload"] == {"symbol": "EURUSD", "bid": 1.1234}

    def test_custom_trace_id(self):
        from api.ws_routes import _ws_event

        evt = _ws_event("trade_update", {"id": "T1"}, trace_id="custom-trace-123")

        assert evt["trace_id"] == "custom-trace-123"

    def test_auto_generated_trace_id(self):
        from api.ws_routes import _ws_event

        evt = _ws_event("test_event", {})

        assert isinstance(evt["trace_id"], str)
        assert len(evt["trace_id"]) == 16

    def test_server_ts_is_recent(self):
        from api.ws_routes import _ws_event

        before = time.time()
        evt = _ws_event("ts_check", {})
        after = time.time()

        assert before <= evt["server_ts"] <= after

    def test_event_id_is_unique(self):
        from api.ws_routes import _ws_event

        ids = {_ws_event("e", {})["event_id"] for _ in range(100)}
        assert len(ids) == 100
