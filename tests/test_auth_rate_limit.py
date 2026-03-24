"""
Tests for rate limiting middleware and JWT/API-key authentication.

Covers:
  - Rate limiter sliding window logic
  - HTTP rate limit enforcement (429 response)
  - Rate limit headers in responses
  - Exempt paths bypass rate limiting
  - JWT create / decode / expiry
  - API key validation
  - verify_token HTTP dependency
  - WebSocket authentication (query param token)
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _configure_jwt_secret(monkeypatch):
    import api.middleware.auth as dashboard_auth  # noqa: PLC0415

    test_secret = "test-dashboard-secret-at-least-32-chars"
    monkeypatch.setattr(dashboard_auth, "JWT_SECRET", test_secret)
    monkeypatch.setattr(dashboard_auth, "JWT_VERIFY_SECRETS", (test_secret,))


# =========================================================================
# Rate limiter unit tests
# =========================================================================


class TestSlidingWindowStore:
    """Unit tests for the in-memory sliding window store."""

    def test_hit_increments_count(self):
        from api.middleware.rate_limit import SlidingWindowStore  # noqa: PLC0415

        store = SlidingWindowStore(window_sec=60)
        assert store.hit("1.2.3.4") == 1
        assert store.hit("1.2.3.4") == 2
        assert store.hit("1.2.3.4") == 3

    def test_different_ips_are_independent(self):
        from api.middleware.rate_limit import SlidingWindowStore  # noqa: PLC0415

        store = SlidingWindowStore(window_sec=60)
        store.hit("1.1.1.1")
        store.hit("1.1.1.1")
        assert store.hit("2.2.2.2") == 1  # Independent counter

    def test_get_count_without_hit(self):
        from api.middleware.rate_limit import SlidingWindowStore  # noqa: PLC0415

        store = SlidingWindowStore(window_sec=60)
        assert store.get_count("9.9.9.9") == 0
        store.hit("9.9.9.9")
        assert store.get_count("9.9.9.9") == 1

    def test_window_expiry(self):
        """Hits older than the window are pruned."""
        from api.middleware.rate_limit import SlidingWindowStore  # noqa: PLC0415

        store = SlidingWindowStore(window_sec=1)  # 1-second window
        store.hit("1.2.3.4")
        time.sleep(1.2)  # Wait for window to expire
        # Next hit should only count itself (old one expired)
        assert store.hit("1.2.3.4") == 1

    def test_reset_clears_all(self):
        from api.middleware.rate_limit import SlidingWindowStore  # noqa: PLC0415

        store = SlidingWindowStore(window_sec=60)
        store.hit("a")
        store.hit("b")
        store.reset()
        assert store.get_count("a") == 0
        assert store.get_count("b") == 0


# =========================================================================
# JWT tests
# =========================================================================


class TestJWT:
    """Tests for JWT create/decode/expiry in auth module."""

    def test_create_and_decode_token(self):
        from api.middleware.auth import create_token, decode_token  # noqa: PLC0415

        token = create_token(sub="test_user")
        payload = decode_token(token)

        assert payload is not None
        assert payload["sub"] == "test_user"
        assert "iat" in payload
        assert "exp" in payload

    def test_decode_invalid_token_returns_none(self):
        from api.middleware.auth import decode_token  # noqa: PLC0415

        assert decode_token("not.a.valid.jwt") is None
        assert decode_token("garbage") is None
        assert decode_token("") is None

    def test_decode_tampered_signature_returns_none(self):
        from api.middleware.auth import create_token, decode_token  # noqa: PLC0415

        token = create_token(sub="user")
        parts = token.split(".")
        # Tamper with signature
        parts[2] = parts[2][:-4] + "XXXX"
        tampered = ".".join(parts)
        assert decode_token(tampered) is None

    def test_decode_expired_token_returns_none(self):
        import json  # noqa: PLC0415

        from api.middleware.auth import (  # noqa: PLC0415
            JWT_SECRET,
            _b64url_encode,
            _sign,
        )

        # Build a token that expired 10 seconds ago
        header = {"alg": "HS256", "typ": "JWT"}
        payload = {
            "sub": "expired_user",
            "iat": int(time.time()) - 120,
            "exp": int(time.time()) - 10,
        }
        header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode())
        payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
        sig = _sign(header_b64, payload_b64, JWT_SECRET)
        expired_token = f"{header_b64}.{payload_b64}.{sig}"

        from api.middleware.auth import decode_token  # noqa: PLC0415

        assert decode_token(expired_token) is None

    def test_create_token_with_extra_claims(self):
        from api.middleware.auth import create_token, decode_token  # noqa: PLC0415

        token = create_token(sub="svc", extra={"role": "admin", "account": "123"})
        payload = decode_token(token)

        assert payload is not None
        assert payload["role"] == "admin"
        assert payload["account"] == "123"

    def test_decode_rejects_signature_from_different_secret(self):
        import json  # noqa: PLC0415

        import api.middleware.auth as dashboard_auth  # noqa: PLC0415

        now = int(time.time())
        header_b64 = dashboard_auth._b64url_encode(  # noqa: SLF001
            json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode()
        )
        payload_b64 = dashboard_auth._b64url_encode(  # noqa: SLF001
            json.dumps({"sub": "legacy_user", "iat": now, "exp": now + 60}, separators=(",", ":")).encode()
        )
        wrong_sig = dashboard_auth._sign(header_b64, payload_b64, "legacy-secret")  # noqa: SLF001
        token = f"{header_b64}.{payload_b64}.{wrong_sig}"

        with (
            patch.object(dashboard_auth, "JWT_SECRET", "dashboard-secret"),
            patch.object(
                dashboard_auth,
                "JWT_VERIFY_SECRETS",
                ("dashboard-secret",),
            ),
        ):
            payload = dashboard_auth.decode_token(token)

        assert payload is None

    def test_create_token_raises_if_secret_missing(self):
        import api.middleware.auth as dashboard_auth  # noqa: PLC0415

        with (
            patch.object(dashboard_auth, "JWT_SECRET", ""),
            patch.object(
                dashboard_auth,
                "JWT_VERIFY_SECRETS",
                (),
            ),
            pytest.raises(RuntimeError, match="DASHBOARD_JWT_SECRET"),
        ):
            dashboard_auth.create_token(sub="blocked_user")

    def test_decode_accepts_pyjwt_encoded_token(self):
        jwt = pytest.importorskip("jwt")

        import api.middleware.auth as dashboard_auth  # noqa: PLC0415

        shared_secret = "shared-secret-at-least-32-bytes-long"
        now = int(time.time())
        token = jwt.encode(
            {"sub": "pyjwt_user", "iat": now, "exp": now + 60},
            shared_secret,
            algorithm="HS256",
        )

        with (
            patch.object(dashboard_auth, "JWT_SECRET", shared_secret),
            patch.object(
                dashboard_auth,
                "JWT_VERIFY_SECRETS",
                (shared_secret,),
            ),
        ):
            payload = dashboard_auth.decode_token(token)

        assert payload is not None
        assert payload["sub"] == "pyjwt_user"

    def test_custom_token_is_decodable_by_pyjwt(self):
        jwt = pytest.importorskip("jwt")

        import api.middleware.auth as dashboard_auth  # noqa: PLC0415

        shared_secret = "shared-secret-at-least-32-bytes-long"
        with (
            patch.object(dashboard_auth, "JWT_SECRET", shared_secret),
            patch.object(
                dashboard_auth,
                "JWT_VERIFY_SECRETS",
                (shared_secret,),
            ),
        ):
            token = dashboard_auth.create_token(sub="custom_user")

        payload = jwt.decode(token, shared_secret, algorithms=["HS256"])

        assert payload["sub"] == "custom_user"


# =========================================================================
# API key tests
# =========================================================================


class TestAPIKey:
    """Tests for static API key validation."""

    def test_validate_with_matching_key(self):
        with patch("api.middleware.auth.API_KEY", "my-secret-key-123"):
            from api.middleware.auth import validate_api_key  # noqa: PLC0415

            assert validate_api_key("my-secret-key-123") is True

    def test_validate_with_wrong_key(self):
        with patch("api.middleware.auth.API_KEY", "my-secret-key-123"):
            from api.middleware.auth import validate_api_key  # noqa: PLC0415

            assert validate_api_key("wrong-key") is False

    def test_validate_with_empty_configured_key(self):
        with patch("api.middleware.auth.API_KEY", ""):
            from api.middleware.auth import validate_api_key  # noqa: PLC0415

            # If no API key is configured, always reject
            assert validate_api_key("anything") is False


# =========================================================================
# verify_token HTTP dependency tests
# =========================================================================


class TestVerifyToken:
    """Tests for the HTTP Bearer token verification dependency."""

    @staticmethod
    def _request_without_cookie() -> MagicMock:
        req = MagicMock()
        req.cookies = {}
        return req

    def test_missing_header_raises_401(self):
        from fastapi import HTTPException  # noqa: PLC0415

        from api.middleware.auth import verify_token  # noqa: PLC0415

        with pytest.raises(HTTPException) as exc_info:
            verify_token(request=self._request_without_cookie(), authorization=None)  # pyright: ignore[reportArgumentType]
        assert exc_info.value.status_code == 401

    def test_invalid_scheme_raises_401(self):
        from fastapi import HTTPException  # noqa: PLC0415

        from api.middleware.auth import verify_token  # noqa: PLC0415

        with pytest.raises(HTTPException) as exc_info:
            verify_token(request=self._request_without_cookie(), authorization="Basic dXNlcjpwYXNz")
        assert exc_info.value.status_code == 401

    def test_valid_jwt_returns_payload(self):
        from api.middleware.auth import create_token, verify_token  # noqa: PLC0415

        token = create_token(sub="dashboard")
        result = verify_token(request=self._request_without_cookie(), authorization=f"Bearer {token}")
        assert result["sub"] == "dashboard"

    def test_valid_api_key_returns_payload(self):
        with patch("api.middleware.auth.API_KEY", "test-api-key"):
            from api.middleware.auth import verify_token  # noqa: PLC0415

            result = verify_token(request=self._request_without_cookie(), authorization="Bearer test-api-key")
            assert result["sub"] == "api_key_user"

    def test_invalid_token_raises_401(self):
        from fastapi import HTTPException  # noqa: PLC0415

        from api.middleware.auth import verify_token  # noqa: PLC0415

        with pytest.raises(HTTPException) as exc_info:
            verify_token(request=self._request_without_cookie(), authorization="Bearer invalid-garbage")
        assert exc_info.value.status_code == 401


# =========================================================================
# WebSocket authentication tests
# =========================================================================


class TestWSAuth:
    """Tests for WebSocket query-param authentication."""

    @pytest.mark.asyncio
    async def test_ws_no_token_closes_connection(self):
        from api.middleware.ws_auth import ws_authenticate  # noqa: PLC0415

        ws = AsyncMock(spec=["query_params", "headers", "close", "state"])
        ws.query_params = {}  # No token
        ws.headers = {}
        ws.close = AsyncMock()

        result = await ws_authenticate(ws)

        assert result is False
        ws.close.assert_awaited_once()
        # Check close code is 4401
        call_args = ws.close.call_args
        assert call_args.kwargs.get("code") == 4401 or (call_args.args and call_args.args[0] == 4401)

    @pytest.mark.asyncio
    async def test_ws_invalid_token_closes_connection(self):
        from api.middleware.ws_auth import ws_authenticate  # noqa: PLC0415

        ws = AsyncMock(spec=["query_params", "headers", "close", "state"])
        ws.query_params = {"token": "invalid-garbage"}
        ws.headers = {}
        ws.close = AsyncMock()

        result = await ws_authenticate(ws)

        assert result is False
        ws.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ws_valid_jwt_authenticates(self):
        from api.middleware.auth import create_token  # noqa: PLC0415
        from api.middleware.ws_auth import ws_authenticate  # noqa: PLC0415

        token = create_token(sub="ws_test_user")
        ws = AsyncMock(spec=["query_params", "headers", "close", "state"])
        ws.query_params = {"token": token}
        ws.headers = {}
        ws.state = MagicMock()
        ws.close = AsyncMock()  # explicit AsyncMock so assert_not_awaited works

        result = await ws_authenticate(ws)

        assert result is True
        assert ws.state.user == "ws_test_user"
        ws.close.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_ws_valid_api_key_authenticates(self):
        with patch("api.middleware.ws_auth.validate_api_key", return_value=True):
            from api.middleware.ws_auth import ws_authenticate  # noqa: PLC0415

            ws = AsyncMock(spec=["query_params", "headers", "close", "state"])
            ws.query_params = {"token": "valid-api-key"}
            ws.headers = {}
            ws.state = MagicMock()

            result = await ws_authenticate(ws)

            assert result is True
            assert ws.state.user == "api_key_user"

    @pytest.mark.asyncio
    async def test_ws_accepts_pyjwt_token_with_shared_secret(self):
        jwt = pytest.importorskip("jwt")

        import api.middleware.auth as dashboard_auth  # noqa: PLC0415
        from api.middleware.ws_auth import ws_authenticate  # noqa: PLC0415

        shared_secret = "shared-secret-at-least-32-bytes-long"
        now = int(time.time())
        token = jwt.encode(
            {"sub": "ws_pyjwt_user", "iat": now, "exp": now + 60},
            shared_secret,
            algorithm="HS256",
        )

        ws = AsyncMock(spec=["query_params", "headers", "close", "state"])
        ws.query_params = {"token": token}
        ws.headers = {}
        ws.state = MagicMock()
        ws.close = AsyncMock()

        with (
            patch.object(dashboard_auth, "JWT_SECRET", shared_secret),
            patch.object(
                dashboard_auth,
                "JWT_VERIFY_SECRETS",
                (shared_secret,),
            ),
        ):
            result = await ws_authenticate(ws)

        assert result is True
        assert ws.state.user == "ws_pyjwt_user"
        ws.close.assert_not_awaited()


# =========================================================================
# Integration-style: rate limiter applied to FastAPI app
# =========================================================================


class TestRateLimitIntegration:
    """Test rate limiting middleware with a real FastAPI test client."""

    def test_rate_limit_headers_present(self):
        """Responses should include X-RateLimit-* headers."""
        import fastapi  # noqa: PLC0415
        from fastapi.testclient import (  # noqa: PLC0415
            TestClient,
        )

        from api.middleware.rate_limit import RateLimitMiddleware  # noqa: PLC0415

        app = fastapi.FastAPI()
        app.add_middleware(RateLimitMiddleware)

        @app.get("/test")
        async def _test():
            return {"ok": True}

        client = TestClient(app)
        resp = client.get("/test")
        assert resp.status_code == 200
        assert "X-RateLimit-Limit" in resp.headers
        assert "X-RateLimit-Remaining" in resp.headers

    def test_exempt_paths_skip_rate_limit(self):
        """Health and root endpoints should NOT have rate limit headers."""
        import fastapi  # noqa: PLC0415
        from fastapi.testclient import (  # noqa: PLC0415
            TestClient,
        )

        from api.middleware.rate_limit import RateLimitMiddleware  # noqa: PLC0415

        app = fastapi.FastAPI()
        app.add_middleware(RateLimitMiddleware)

        @app.get("/health")
        async def _health():
            return {"status": "ok"}

        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        # Exempt paths don't get rate limit headers
        assert "X-RateLimit-Limit" not in resp.headers

    def test_burst_triggers_429(self, monkeypatch):
        """Exceeding burst limit should return 429."""
        import fastapi  # noqa: PLC0415
        from fastapi.testclient import (  # noqa: PLC0415
            TestClient,
        )

        from api.middleware.rate_limit import (  # noqa: PLC0415
            RateLimitMiddleware,
            _http_store,
        )

        # Force deterministic in-memory limiter and a small limit for fast tests.
        monkeypatch.setattr("api.middleware.rate_limit.RATE_LIMIT_BACKEND", "memory")
        monkeypatch.setattr("api.middleware.rate_limit.REQUESTS_PER_MIN", 2)
        monkeypatch.setattr("api.middleware.rate_limit.BURST", 0)

        # Reset state
        _http_store.reset()

        app = fastapi.FastAPI()
        app.add_middleware(RateLimitMiddleware)

        @app.get("/api/v1/test")
        async def _test():
            return {"ok": True}

        client = TestClient(app)

        # Flood with requests up to and beyond the test limit.
        hit_429 = False
        for _ in range(6):
            resp = client.get("/api/v1/test")
            if resp.status_code == 429:
                hit_429 = True
                body = resp.json()
                assert "retry_after_sec" in body
                assert resp.headers.get("Retry-After") == "60"
                break

        assert hit_429, "Expected 429 after exceeding rate limit"

        # Cleanup
        _http_store.reset()

    def test_authenticated_actors_isolated_on_same_ip(self, monkeypatch):
        """Different authenticated actors should not collide on a shared IP."""
        import fastapi  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        from api.middleware.auth import create_token  # noqa: PLC0415
        from api.middleware.rate_limit import RateLimitMiddleware, _http_store  # noqa: PLC0415

        monkeypatch.setattr("api.middleware.rate_limit.RATE_LIMIT_BACKEND", "memory")
        monkeypatch.setattr("api.middleware.rate_limit.REQUESTS_PER_MIN", 1)
        monkeypatch.setattr("api.middleware.rate_limit.BURST", 0)
        _http_store.reset()

        app = fastapi.FastAPI()
        app.add_middleware(RateLimitMiddleware)

        @app.get("/api/v1/test")
        async def _test():
            return {"ok": True}

        token_a = create_token(sub="operator_a")
        token_b = create_token(sub="operator_b")
        client = TestClient(app)

        resp_a1 = client.get("/api/v1/test", headers={"Authorization": f"Bearer {token_a}"})
        resp_b1 = client.get("/api/v1/test", headers={"Authorization": f"Bearer {token_b}"})
        resp_a2 = client.get("/api/v1/test", headers={"Authorization": f"Bearer {token_a}"})

        assert resp_a1.status_code == 200
        assert resp_b1.status_code == 200
        assert resp_a2.status_code == 429

        _http_store.reset()

    def test_trade_write_limits_partition_by_account(self, monkeypatch):
        """Trade-write limits should isolate different accounts for the same actor."""
        import fastapi  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        from api.middleware.auth import create_token  # noqa: PLC0415
        from api.middleware.rate_limit import RateLimitMiddleware, _trade_write_store  # noqa: PLC0415

        monkeypatch.setattr("api.middleware.rate_limit.RATE_LIMIT_BACKEND", "memory")
        monkeypatch.setattr("api.middleware.rate_limit.TRADE_WRITE_PER_MIN", 1)
        _trade_write_store.reset()

        app = fastapi.FastAPI()
        app.add_middleware(RateLimitMiddleware)

        @app.post("/api/v1/trades/confirm")
        async def _confirm(payload: dict):
            return {"ok": True, "payload": payload}

        token = create_token(sub="desk_operator")
        headers = {"Authorization": f"Bearer {token}"}
        client = TestClient(app)

        resp_acc_1 = client.post("/api/v1/trades/confirm", headers=headers, json={"account_id": "ACC-1"})
        resp_acc_2 = client.post("/api/v1/trades/confirm", headers=headers, json={"account_id": "ACC-2"})
        resp_acc_1_again = client.post("/api/v1/trades/confirm", headers=headers, json={"account_id": "ACC-1"})

        assert resp_acc_1.status_code == 200
        assert resp_acc_2.status_code == 200
        assert resp_acc_1_again.status_code == 429

        _trade_write_store.reset()

    def test_take_limits_partition_by_ea_instance(self, monkeypatch):
        """Take bucket should isolate EA instances under the same actor/account."""
        import fastapi  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415

        from api.middleware.auth import create_token  # noqa: PLC0415
        from api.middleware.rate_limit import RateLimitMiddleware, _take_store  # noqa: PLC0415

        monkeypatch.setattr("api.middleware.rate_limit.RATE_LIMIT_BACKEND", "memory")
        monkeypatch.setattr("api.middleware.rate_limit.TAKE_PER_MIN", 1)
        _take_store.reset()

        app = fastapi.FastAPI()
        app.add_middleware(RateLimitMiddleware)

        @app.post("/api/v1/execution/take-signal")
        async def _take(payload: dict):
            return {"ok": True, "payload": payload}

        token = create_token(sub="desk_operator")
        headers = {"Authorization": f"Bearer {token}"}
        client = TestClient(app)

        body_1 = {"account_id": "ACC-1", "ea_instance_id": "EA-A"}
        body_2 = {"account_id": "ACC-1", "ea_instance_id": "EA-B"}
        resp_1 = client.post("/api/v1/execution/take-signal", headers=headers, json=body_1)
        resp_2 = client.post("/api/v1/execution/take-signal", headers=headers, json=body_2)
        resp_1_again = client.post("/api/v1/execution/take-signal", headers=headers, json=body_1)

        assert resp_1.status_code == 200
        assert resp_2.status_code == 200
        assert resp_1_again.status_code == 429

        _take_store.reset()


# =========================================================================
# Path-bucket routing tests (new granular buckets)
# =========================================================================


class TestPathBucketRouting:
    """Test that _path_bucket correctly routes to the right bucket/limit."""

    def test_ea_restart_bucket(self):
        from api.middleware.rate_limit import EA_CONTROL_PER_MIN, _path_bucket  # noqa: PLC0415

        result = _path_bucket("/ea/restart", "POST", False)
        assert result is not None
        assert result[0] == "ea_control"
        assert result[1] == EA_CONTROL_PER_MIN

    def test_ea_safe_mode_bucket(self):
        from api.middleware.rate_limit import _path_bucket  # noqa: PLC0415

        result = _path_bucket("/ea/safe-mode", "POST", False)
        assert result is not None
        assert result[0] == "ea_control"

    def test_trades_take_bucket(self):
        from api.middleware.rate_limit import TAKE_PER_MIN, _path_bucket  # noqa: PLC0415

        result = _path_bucket("/trades/take", "POST", False)
        assert result is not None
        assert result[0] == "take"
        assert result[1] == TAKE_PER_MIN

    def test_signals_take_bucket(self):
        from api.middleware.rate_limit import _path_bucket  # noqa: PLC0415

        result = _path_bucket("/signals/take", "POST", False)
        assert result is not None
        assert result[0] == "take"

    def test_execution_take_signal_bucket(self):
        from api.middleware.rate_limit import _path_bucket  # noqa: PLC0415

        result = _path_bucket("/api/v1/execution/take-signal", "POST", False)
        assert result is not None
        assert result[0] == "take"

    def test_trades_confirm_bucket(self):
        from api.middleware.rate_limit import TRADE_WRITE_PER_MIN, _path_bucket  # noqa: PLC0415

        result = _path_bucket("/trades/confirm", "POST", False)
        assert result is not None
        assert result[0] == "trade_write"
        assert result[1] == TRADE_WRITE_PER_MIN

    def test_trades_close_bucket(self):
        from api.middleware.rate_limit import _path_bucket  # noqa: PLC0415

        result = _path_bucket("/trades/close", "POST", False)
        assert result is not None
        assert result[0] == "trade_write"

    def test_trades_skip_bucket(self):
        from api.middleware.rate_limit import _path_bucket  # noqa: PLC0415

        result = _path_bucket("/trades/skip", "POST", False)
        assert result is not None
        assert result[0] == "trade_write"

    def test_signals_skip_bucket(self):
        from api.middleware.rate_limit import _path_bucket  # noqa: PLC0415

        result = _path_bucket("/signals/skip", "POST", False)
        assert result is not None
        assert result[0] == "trade_write"

    def test_risk_calculate_bucket(self):
        from api.middleware.rate_limit import RISK_CALC_PER_MIN, _path_bucket  # noqa: PLC0415

        result = _path_bucket("/risk/calculate", "POST", False)
        assert result is not None
        assert result[0] == "risk_calc"
        assert result[1] == RISK_CALC_PER_MIN

    def test_account_create_bucket(self):
        from api.middleware.rate_limit import ACCOUNT_WRITE_PER_MIN, _path_bucket  # noqa: PLC0415

        result = _path_bucket("/accounts", "POST", False)
        assert result is not None
        assert result[0] == "account_write"
        assert result[1] == ACCOUNT_WRITE_PER_MIN

    def test_account_update_bucket(self):
        from api.middleware.rate_limit import _path_bucket  # noqa: PLC0415

        result = _path_bucket("/accounts/abc-123", "PUT", False)
        assert result is not None
        assert result[0] == "account_write"

    def test_account_delete_bucket(self):
        from api.middleware.rate_limit import _path_bucket  # noqa: PLC0415

        result = _path_bucket("/accounts/abc-123", "DELETE", False)
        assert result is not None
        assert result[0] == "account_write"

    def test_config_profiles_bucket(self):
        from api.middleware.rate_limit import CONFIG_WRITE_PER_MIN, _path_bucket  # noqa: PLC0415

        result = _path_bucket("/config/profiles/active", "POST", False)
        assert result is not None
        assert result[0] == "config_write"
        assert result[1] == CONFIG_WRITE_PER_MIN

    def test_redis_candle_delete_admin_bucket(self):
        from api.middleware.rate_limit import ADMIN_PER_MIN, _path_bucket  # noqa: PLC0415

        result = _path_bucket("/redis/candles", "DELETE", False)
        assert result is not None
        assert result[0] == "admin"
        assert result[1] == ADMIN_PER_MIN

    def test_news_lock_admin_bucket(self):
        from api.middleware.rate_limit import _path_bucket  # noqa: PLC0415

        result = _path_bucket("/calendar/news-lock/enable", "POST", False)
        assert result is not None
        assert result[0] == "admin"

    def test_ws_connect_bucket(self):
        from api.middleware.rate_limit import WS_CONNECT_PER_MIN, _path_bucket  # noqa: PLC0415

        result = _path_bucket("/ws/feed", "GET", True)
        assert result is not None
        assert result[0] == "ws_connect"
        assert result[1] == WS_CONNECT_PER_MIN

    def test_get_request_no_special_bucket(self):
        from api.middleware.rate_limit import _path_bucket  # noqa: PLC0415

        result = _path_bucket("/api/v1/signals", "GET", False)
        assert result is None  # Falls through to general HTTP bucket

    def test_ea_control_tight_limit(self):
        """EA control should be very tight (default 3/min)."""
        from api.middleware.rate_limit import EA_CONTROL_PER_MIN  # noqa: PLC0415

        assert EA_CONTROL_PER_MIN <= 5, "EA control should be tightly limited"


# =========================================================================
# Proxy trust / _client_ip tests
# =========================================================================


class TestClientIpExtraction:
    """Tests for _client_ip, _is_trusted_proxy, and Railway auto-detection."""

    def _make_request(self, client_host: str, headers: dict[str, str] | None = None) -> MagicMock:
        from fastapi import Request as _Request  # noqa: PLC0415

        req = MagicMock(spec=_Request)
        req.client = MagicMock()
        req.client.host = client_host
        req.headers = headers or {}
        return req

    def test_returns_source_ip_when_proxy_trust_disabled(self, monkeypatch):
        from api.middleware import rate_limit as rl  # noqa: PLC0415

        monkeypatch.setattr(rl, "TRUSTED_PROXY_ENABLED", False)
        req = self._make_request("1.2.3.4", {"x-forwarded-for": "5.6.7.8"})
        assert rl._client_ip(req) == "1.2.3.4"

    def test_returns_xff_when_source_is_trusted_exact(self, monkeypatch):
        from api.middleware import rate_limit as rl  # noqa: PLC0415

        monkeypatch.setattr(rl, "TRUSTED_PROXY_ENABLED", True)
        monkeypatch.setattr(rl, "_trusted_proxy_exact", {"127.0.0.1"})
        monkeypatch.setattr(rl, "_trusted_proxy_nets", [])
        monkeypatch.setattr(rl, "TRUST_ALL_PROXIES", False)
        req = self._make_request("127.0.0.1", {"x-forwarded-for": "203.0.113.50"})
        assert rl._client_ip(req) == "203.0.113.50"

    def test_returns_source_ip_when_source_not_trusted(self, monkeypatch):
        from api.middleware import rate_limit as rl  # noqa: PLC0415

        monkeypatch.setattr(rl, "TRUSTED_PROXY_ENABLED", True)
        monkeypatch.setattr(rl, "_trusted_proxy_exact", {"127.0.0.1"})
        monkeypatch.setattr(rl, "_trusted_proxy_nets", [])
        monkeypatch.setattr(rl, "TRUST_ALL_PROXIES", False)
        req = self._make_request("9.9.9.9", {"x-forwarded-for": "203.0.113.50"})
        assert rl._client_ip(req) == "9.9.9.9"

    def test_cidr_trust_railway_cgnat(self, monkeypatch):
        """100.64.x.x (Railway CGNAT) should be trusted via CIDR."""
        import ipaddress  # noqa: PLC0415

        from api.middleware import rate_limit as rl  # noqa: PLC0415

        monkeypatch.setattr(rl, "TRUSTED_PROXY_ENABLED", True)
        monkeypatch.setattr(rl, "_trusted_proxy_exact", set())
        monkeypatch.setattr(rl, "_trusted_proxy_nets", [ipaddress.ip_network("100.64.0.0/10")])
        monkeypatch.setattr(rl, "TRUST_ALL_PROXIES", False)
        req = self._make_request("100.64.0.10", {"x-forwarded-for": "203.0.113.99"})
        assert rl._client_ip(req) == "203.0.113.99"

    def test_multi_valued_xff_rightmost_untrusted(self, monkeypatch):
        """Multi-valued XFF should return rightmost non-trusted IP."""
        import ipaddress  # noqa: PLC0415

        from api.middleware import rate_limit as rl  # noqa: PLC0415

        monkeypatch.setattr(rl, "TRUSTED_PROXY_ENABLED", True)
        monkeypatch.setattr(rl, "_trusted_proxy_exact", {"10.0.0.1"})
        monkeypatch.setattr(rl, "_trusted_proxy_nets", [ipaddress.ip_network("100.64.0.0/10")])
        monkeypatch.setattr(rl, "TRUST_ALL_PROXIES", False)
        # client → edge(10.0.0.1) → internal(100.64.0.10) → app
        # XFF: "real_client, 10.0.0.1" from source 100.64.0.10
        req = self._make_request("100.64.0.10", {"x-forwarded-for": "198.51.100.5, 10.0.0.1"})
        assert rl._client_ip(req) == "198.51.100.5"

    def test_attacker_injected_xff_ignored(self, monkeypatch):
        """Attacker-injected IPs at left of XFF should not override real IP."""
        import ipaddress  # noqa: PLC0415

        from api.middleware import rate_limit as rl  # noqa: PLC0415

        monkeypatch.setattr(rl, "TRUSTED_PROXY_ENABLED", True)
        monkeypatch.setattr(rl, "_trusted_proxy_exact", set())
        monkeypatch.setattr(rl, "_trusted_proxy_nets", [ipaddress.ip_network("100.64.0.0/10")])
        monkeypatch.setattr(rl, "TRUST_ALL_PROXIES", False)
        # Attacker sends "X-Forwarded-For: 1.1.1.1", proxy appends real IP
        req = self._make_request("100.64.0.10", {"x-forwarded-for": "1.1.1.1, 198.51.100.5"})
        # 198.51.100.5 is the rightmost untrusted = real client IP
        assert rl._client_ip(req) == "198.51.100.5"

    def test_no_xff_returns_source(self, monkeypatch):
        from api.middleware import rate_limit as rl  # noqa: PLC0415

        monkeypatch.setattr(rl, "TRUSTED_PROXY_ENABLED", True)
        monkeypatch.setattr(rl, "_trusted_proxy_exact", {"127.0.0.1"})
        monkeypatch.setattr(rl, "_trusted_proxy_nets", [])
        monkeypatch.setattr(rl, "TRUST_ALL_PROXIES", False)
        req = self._make_request("127.0.0.1", {})
        assert rl._client_ip(req) == "127.0.0.1"

    def test_trust_all_proxies(self, monkeypatch):
        from api.middleware import rate_limit as rl  # noqa: PLC0415

        monkeypatch.setattr(rl, "TRUSTED_PROXY_ENABLED", True)
        monkeypatch.setattr(rl, "_trusted_proxy_exact", set())
        monkeypatch.setattr(rl, "_trusted_proxy_nets", [])
        monkeypatch.setattr(rl, "TRUST_ALL_PROXIES", True)
        req = self._make_request("99.99.99.99", {"x-forwarded-for": "42.42.42.42"})
        assert rl._client_ip(req) == "42.42.42.42"
