"""
Integration tests for the ``/auth/session`` compat endpoint and the
primary ``/api/auth/session`` endpoint.

Verifies:
  - ``/auth/session`` returns 200 regardless of auth state.
  - Authenticated calls return ``{ authenticated: true, user, expires_at }``.
  - Unauthenticated calls return ``{ authenticated: false, user: null, expires_at: null }``.
  - Invalid tokens return ``{ authenticated: false, ... }`` (no 401).
  - The primary ``/api/auth/session`` returns 401 for missing/invalid tokens.
  - Response shape is consistent (``authenticated``, ``user``, ``expires_at``).
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Test JWT secret (>= 32 chars)
# ---------------------------------------------------------------------------
_TEST_SECRET = "test-jwt-secret-that-is-at-least-32-chars-long!"
_TEST_API_KEY = "my-static-api-key-for-tests"


def _set_auth_secret(*, api_key: str = "") -> None:
    """Point the auth module at a known test secret."""
    import api.middleware.auth as auth_mod

    auth_mod.JWT_SECRET = _TEST_SECRET
    auth_mod.JWT_VERIFY_SECRETS = (_TEST_SECRET,)
    auth_mod.API_KEY = api_key


def _make_token(sub: str = "test_user", **extra: str) -> str:
    from api.middleware.auth import create_token

    return create_token(sub=sub, extra=extra or None)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def compat_client():
    """TestClient mounting only the compat ``/auth`` router."""
    _set_auth_secret()
    from api.routes.auth_compat import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture()
def primary_client():
    """TestClient mounting the primary ``/api/auth`` router."""
    _set_auth_secret()
    from api.auth_router import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture()
def compat_client_with_apikey():
    """TestClient with a configured static API key."""
    _set_auth_secret(api_key=_TEST_API_KEY)
    from api.routes.auth_compat import router

    app = FastAPI()
    app.include_router(router)
    yield TestClient(app)
    # Reset API_KEY so other tests aren't affected
    _set_auth_secret(api_key="")


# ============================================================================
# 1. Compat endpoint — /auth/session
# ============================================================================


class TestAuthSessionCompat:
    """``GET /auth/session`` — always 200, ``authenticated`` flag in body."""

    def test_no_auth_returns_200_unauthenticated(self, compat_client: TestClient):
        resp = compat_client.get("/auth/session")
        assert resp.status_code == 200
        body = resp.json()
        assert body["authenticated"] is False
        assert body["user"] is None
        assert body["expires_at"] is None

    def test_valid_jwt_returns_authenticated(self, compat_client: TestClient):
        _set_auth_secret()
        token = _make_token(
            sub="usr_42",
            email="test@example.com",
            role="operator",
            name="Test User",
        )
        resp = compat_client.get(
            "/auth/session",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["authenticated"] is True
        assert body["user"]["user_id"] == "usr_42"
        assert body["user"]["email"] == "test@example.com"
        assert body["user"]["role"] == "operator"
        assert body["user"]["name"] == "Test User"
        assert body["expires_at"] is not None  # ISO timestamp from JWT exp

    def test_invalid_token_returns_unauthenticated(self, compat_client: TestClient):
        resp = compat_client.get(
            "/auth/session",
            headers={"Authorization": "Bearer totally-invalid-token"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["authenticated"] is False
        assert body["user"] is None

    def test_api_key_auth_returns_authenticated(self, compat_client_with_apikey: TestClient):
        resp = compat_client_with_apikey.get(
            "/auth/session",
            headers={"Authorization": f"Bearer {_TEST_API_KEY}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["authenticated"] is True
        assert body["user"]["user_id"] == "api_key_user"

    def test_response_shape_keys(self, compat_client: TestClient):
        """Every response must have exactly { authenticated, user, expires_at }."""
        _set_auth_secret()
        token = _make_token()
        for headers in [
            {},
            {"Authorization": f"Bearer {token}"},
            {"Authorization": "Bearer bad"},
        ]:
            resp = compat_client.get("/auth/session", headers=headers)
            body = resp.json()
            assert set(body.keys()) == {"authenticated", "user", "expires_at"}

    def test_no_bearer_prefix_returns_unauthenticated(self, compat_client: TestClient):
        resp = compat_client.get(
            "/auth/session",
            headers={"Authorization": "Basic abc123"},
        )
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is False


# ============================================================================
# 2. Primary endpoint — /api/auth/session
# ============================================================================


class TestAuthSessionPrimary:
    """``GET /api/auth/session`` — returns 401 or SessionUserResponse."""

    def test_no_auth_returns_401(self, primary_client: TestClient):
        resp = primary_client.get("/api/auth/session")
        assert resp.status_code == 401

    def test_invalid_token_returns_401(self, primary_client: TestClient):
        resp = primary_client.get(
            "/api/auth/session",
            headers={"Authorization": "Bearer bad-token"},
        )
        assert resp.status_code == 401

    def test_valid_jwt_returns_session_user(self, primary_client: TestClient):
        _set_auth_secret()
        token = _make_token(
            sub="usr_42",
            email="test@example.com",
            role="operator",
            name="Test User",
        )
        resp = primary_client.get(
            "/api/auth/session",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["user_id"] == "usr_42"
        assert body["email"] == "test@example.com"
        assert body["role"] == "operator"
        assert body["name"] == "Test User"
