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

import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest  # pyright: ignore[reportMissingImports]

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


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
        from dashboard.backend.auth import create_token, decode_token  # noqa: PLC0415

        token = create_token(sub="test_user")
        payload = decode_token(token)

        assert payload is not None
        assert payload["sub"] == "test_user"
        assert "iat" in payload
        assert "exp" in payload

    def test_decode_invalid_token_returns_none(self):
        from dashboard.backend.auth import decode_token  # noqa: PLC0415

        assert decode_token("not.a.valid.jwt") is None
        assert decode_token("garbage") is None
        assert decode_token("") is None

    def test_decode_tampered_signature_returns_none(self):
        from dashboard.backend.auth import create_token, decode_token  # noqa: PLC0415

        token = create_token(sub="user")
        parts = token.split(".")
        # Tamper with signature
        parts[2] = parts[2][:-4] + "XXXX"
        tampered = ".".join(parts)
        assert decode_token(tampered) is None

    def test_decode_expired_token_returns_none(self):
        import json  # noqa: PLC0415

        from dashboard.backend.auth import (  # noqa: PLC0415
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

        from dashboard.backend.auth import decode_token  # noqa: PLC0415

        assert decode_token(expired_token) is None

    def test_create_token_with_extra_claims(self):
        from dashboard.backend.auth import create_token, decode_token  # noqa: PLC0415

        token = create_token(sub="svc", extra={"role": "admin", "account": "123"})
        payload = decode_token(token)

        assert payload is not None
        assert payload["role"] == "admin"
        assert payload["account"] == "123"

    def test_decode_accepts_legacy_secret_during_migration(self):
        import json  # noqa: PLC0415

        from dashboard.backend import auth as dashboard_auth  # noqa: PLC0415

        now = int(time.time())
        header_b64 = dashboard_auth._b64url_encode(  # noqa: SLF001
            json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode()
        )
        payload_b64 = dashboard_auth._b64url_encode(  # noqa: SLF001
            json.dumps({"sub": "legacy_user", "iat": now, "exp": now + 60}, separators=(",", ":")).encode()
        )
        legacy_sig = dashboard_auth._sign(header_b64, payload_b64, "legacy-secret")  # noqa: SLF001
        token = f"{header_b64}.{payload_b64}.{legacy_sig}"

        with patch.object(dashboard_auth, "JWT_SECRET", "dashboard-secret"), patch.object(
            dashboard_auth,
            "JWT_VERIFY_SECRETS",
            ("dashboard-secret", "legacy-secret"),
        ):
            payload = dashboard_auth.decode_token(token)

        assert payload is not None
        assert payload["sub"] == "legacy_user"

    def test_decode_accepts_pyjwt_encoded_token(self):
        jwt = pytest.importorskip("jwt")

        from dashboard.backend import auth as dashboard_auth  # noqa: PLC0415

        shared_secret = "shared-secret-at-least-32-bytes-long"
        now = int(time.time())
        token = jwt.encode(
            {"sub": "pyjwt_user", "iat": now, "exp": now + 60},
            shared_secret,
            algorithm="HS256",
        )

        with patch.object(dashboard_auth, "JWT_SECRET", shared_secret), patch.object(
            dashboard_auth,
            "JWT_VERIFY_SECRETS",
            (shared_secret,),
        ):
            payload = dashboard_auth.decode_token(token)

        assert payload is not None
        assert payload["sub"] == "pyjwt_user"

    def test_custom_token_is_decodable_by_pyjwt(self):
        jwt = pytest.importorskip("jwt")

        from dashboard.backend import auth as dashboard_auth  # noqa: PLC0415

        shared_secret = "shared-secret-at-least-32-bytes-long"
        with patch.object(dashboard_auth, "JWT_SECRET", shared_secret), patch.object(
            dashboard_auth,
            "JWT_VERIFY_SECRETS",
            (shared_secret,),
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
        with patch("dashboard.backend.auth.API_KEY", "my-secret-key-123"):
            from dashboard.backend.auth import validate_api_key  # noqa: PLC0415

            assert validate_api_key("my-secret-key-123") is True

    def test_validate_with_wrong_key(self):
        with patch("dashboard.backend.auth.API_KEY", "my-secret-key-123"):
            from dashboard.backend.auth import validate_api_key  # noqa: PLC0415

            assert validate_api_key("wrong-key") is False

    def test_validate_with_empty_configured_key(self):
        with patch("dashboard.backend.auth.API_KEY", ""):
            from dashboard.backend.auth import validate_api_key  # noqa: PLC0415

            # If no API key is configured, always reject
            assert validate_api_key("anything") is False


# =========================================================================
# verify_token HTTP dependency tests
# =========================================================================


class TestVerifyToken:
    """Tests for the HTTP Bearer token verification dependency."""

    def test_missing_header_raises_401(self):
        from fastapi import HTTPException  # pyright: ignore[reportMissingImports] # noqa: PLC0415

        from dashboard.backend.auth import verify_token  # noqa: PLC0415

        with pytest.raises(HTTPException) as exc_info:
            verify_token(authorization=None) # pyright: ignore[reportArgumentType]
        assert exc_info.value.status_code == 401

    def test_invalid_scheme_raises_401(self):
        from fastapi import HTTPException  # pyright: ignore[reportMissingImports] # noqa: PLC0415

        from dashboard.backend.auth import verify_token  # noqa: PLC0415

        with pytest.raises(HTTPException) as exc_info:
            verify_token(authorization="Basic dXNlcjpwYXNz")
        assert exc_info.value.status_code == 401

    def test_valid_jwt_returns_payload(self):
        from dashboard.backend.auth import create_token, verify_token  # noqa: PLC0415

        token = create_token(sub="dashboard")
        result = verify_token(authorization=f"Bearer {token}")
        assert result["sub"] == "dashboard"

    def test_valid_api_key_returns_payload(self):
        with patch("dashboard.backend.auth.API_KEY", "test-api-key"):
            from dashboard.backend.auth import verify_token  # noqa: PLC0415

            result = verify_token(authorization="Bearer test-api-key")
            assert result["sub"] == "api_key_user"

    def test_invalid_token_raises_401(self):
        from fastapi import HTTPException  # pyright: ignore[reportMissingImports] # noqa: PLC0415

        from dashboard.backend.auth import verify_token  # noqa: PLC0415

        with pytest.raises(HTTPException) as exc_info:
            verify_token(authorization="Bearer invalid-garbage")
        assert exc_info.value.status_code == 401


# =========================================================================
# WebSocket authentication tests
# =========================================================================


class TestWSAuth:
    """Tests for WebSocket query-param authentication."""

    @pytest.mark.asyncio
    async def test_ws_no_token_closes_connection(self):
        from api.middleware.ws_auth import ws_authenticate  # noqa: PLC0415

        ws = AsyncMock(spec=["query_params", "close", "state"])
        ws.query_params = {}  # No token
        ws.close = AsyncMock()

        result = await ws_authenticate(ws)

        assert result is False
        ws.close.assert_awaited_once()
        # Check close code is 4401
        call_args = ws.close.call_args
        assert call_args.kwargs.get("code") == 4401 or (
            call_args.args and call_args.args[0] == 4401
        )

    @pytest.mark.asyncio
    async def test_ws_invalid_token_closes_connection(self):
        from api.middleware.ws_auth import ws_authenticate  # noqa: PLC0415

        ws = AsyncMock(spec=["query_params", "close", "state"])
        ws.query_params = {"token": "invalid-garbage"}
        ws.close = AsyncMock()

        result = await ws_authenticate(ws)

        assert result is False
        ws.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ws_valid_jwt_authenticates(self):
        from api.middleware.ws_auth import ws_authenticate  # noqa: PLC0415
        from dashboard.backend.auth import create_token  # noqa: PLC0415

        token = create_token(sub="ws_test_user")
        ws = AsyncMock(spec=["query_params", "close", "state"])
        ws.query_params = {"token": token}
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

            ws = AsyncMock(spec=["query_params", "close", "state"])
            ws.query_params = {"token": "valid-api-key"}
            ws.state = MagicMock()

            result = await ws_authenticate(ws)

            assert result is True
            assert ws.state.user == "api_key_user"

    @pytest.mark.asyncio
    async def test_ws_accepts_pyjwt_token_with_shared_secret(self):
        jwt = pytest.importorskip("jwt")

        from api.middleware.ws_auth import ws_authenticate  # noqa: PLC0415
        from dashboard.backend import auth as dashboard_auth  # noqa: PLC0415

        shared_secret = "shared-secret-at-least-32-bytes-long"
        now = int(time.time())
        token = jwt.encode(
            {"sub": "ws_pyjwt_user", "iat": now, "exp": now + 60},
            shared_secret,
            algorithm="HS256",
        )

        ws = AsyncMock(spec=["query_params", "close", "state"])
        ws.query_params = {"token": token}
        ws.state = MagicMock()
        ws.close = AsyncMock()

        with patch.object(dashboard_auth, "JWT_SECRET", shared_secret), patch.object(
            dashboard_auth,
            "JWT_VERIFY_SECRETS",
            (shared_secret,),
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
        import fastapi  # type: ignore # noqa: PLC0415
        from fastapi.testclient import (  # noqa: PLC0415 # pyright: ignore[reportMissingImports]
            TestClient,  # pyright: ignore[reportMissingImports]
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
        import fastapi  # pyright: ignore[reportMissingImports] # noqa: PLC0415
        from fastapi.testclient import (  # noqa: PLC0415 # pyright: ignore[reportMissingImports]
            TestClient,  # pyright: ignore[reportMissingImports]
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

    def test_burst_triggers_429(self):
        """Exceeding burst limit should return 429."""
        import fastapi  # pyright: ignore[reportMissingImports] # noqa: PLC0415
        from fastapi.testclient import (  # noqa: PLC0415 # pyright: ignore[reportMissingImports]
            TestClient,  # pyright: ignore[reportMissingImports]
        )

        from api.middleware.rate_limit import (  # noqa: PLC0415
            RateLimitMiddleware,
            _http_store,
        )

        # Reset state
        _http_store.reset()

        app = fastapi.FastAPI()
        app.add_middleware(RateLimitMiddleware)

        @app.get("/api/v1/test")
        async def _test():
            return {"ok": True}

        client = TestClient(app)

        # Flood with requests up to and beyond the limit
        # Default: 120 + 20 burst = 140
        hit_429 = False
        for _ in range(160):
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
