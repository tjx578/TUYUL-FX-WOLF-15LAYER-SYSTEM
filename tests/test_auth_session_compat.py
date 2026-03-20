"""
Integration tests for auth endpoints:

1. Compat ``/auth/session`` — always 200, ``authenticated`` flag.
2. Primary ``/api/auth/session`` — 401 or SessionUserResponse.
3. Login ``/api/auth/login`` — issues JWT + sets cookie.
4. Refresh ``/api/auth/refresh`` — re-issues JWT + updates cookie.
5. Logout ``/api/auth/logout`` — clears cookie.
6. Cookie-based auth on compat endpoint.
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
    _set_auth_secret(api_key=_TEST_API_KEY)
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
        assert body["expires_at"] is not None

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

    def test_cookie_based_auth(self, compat_client_with_apikey: TestClient):
        """Session cookie (no Authorization header) should authenticate."""
        from api.middleware.auth import COOKIE_NAME

        _set_auth_secret(api_key=_TEST_API_KEY)
        token = _make_token(sub="cookie_user", email="cookie@test.com", role="viewer")
        compat_client_with_apikey.cookies.set(COOKIE_NAME, token)
        resp = compat_client_with_apikey.get("/auth/session")
        compat_client_with_apikey.cookies.clear()
        assert resp.status_code == 200
        body = resp.json()
        assert body["authenticated"] is True
        assert body["user"]["user_id"] == "cookie_user"

    def test_bearer_takes_precedence_over_cookie(self, compat_client: TestClient):
        """Authorization header wins when both header and cookie are present."""
        from api.middleware.auth import COOKIE_NAME

        _set_auth_secret()
        header_token = _make_token(sub="header_user")
        cookie_token = _make_token(sub="cookie_user")
        compat_client.cookies.set(COOKIE_NAME, cookie_token)
        resp = compat_client.get(
            "/auth/session",
            headers={"Authorization": f"Bearer {header_token}"},
        )
        compat_client.cookies.clear()
        assert resp.status_code == 200
        assert resp.json()["user"]["user_id"] == "header_user"


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


# ============================================================================
# 3. Refresh endpoint — /api/auth/refresh
# ============================================================================


class TestAuthRefresh:
    """``POST /api/auth/refresh`` — re-issues JWT + updates cookie."""

    def test_refresh_with_valid_token(self, primary_client: TestClient):
        from api.middleware.auth import COOKIE_NAME

        _set_auth_secret(api_key=_TEST_API_KEY)
        token = _make_token(sub="usr_42", email="t@test.com", role="operator")
        resp = primary_client.post(
            "/api/auth/refresh",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "token" in body
        assert body["user_id"] == "usr_42"
        assert COOKIE_NAME in resp.cookies

    def test_refresh_without_token_returns_401(self, primary_client: TestClient):
        resp = primary_client.post("/api/auth/refresh")
        assert resp.status_code == 401


# ============================================================================
# 4. Login endpoint — POST /api/auth/login
# ============================================================================


class TestAuthLogin:
    """``POST /api/auth/login`` — validates API key, returns JWT + sets cookie."""

    @pytest.fixture()
    def login_client(self):
        _set_auth_secret(api_key=_TEST_API_KEY)
        from api.auth_router import router

        app = FastAPI()
        app.include_router(router)
        yield TestClient(app)
        _set_auth_secret(api_key="")

    def test_login_with_valid_api_key_returns_token_and_cookie(self, login_client: TestClient):
        resp = login_client.post(
            "/api/auth/login",
            json={"api_key": _TEST_API_KEY},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "token" in body
        assert body["user_id"] == "api_key_user"

        # Must set HttpOnly session cookie
        cookie_header = resp.headers.get("set-cookie", "")
        assert "wolf15_session=" in cookie_header
        assert "httponly" in cookie_header.lower()

    def test_login_with_invalid_key_returns_401(self, login_client: TestClient):
        resp = login_client.post(
            "/api/auth/login",
            json={"api_key": "wrong-key"},
        )
        assert resp.status_code == 401

    def test_login_with_empty_key_returns_422(self, login_client: TestClient):
        resp = login_client.post(
            "/api/auth/login",
            json={"api_key": ""},
        )
        assert resp.status_code == 422

    def test_login_with_valid_jwt_returns_new_token(self, login_client: TestClient):
        _set_auth_secret()
        existing_jwt = _make_token(sub="usr_99", email="jwt@test.com", role="admin")
        resp = login_client.post(
            "/api/auth/login",
            json={"api_key": existing_jwt},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["user_id"] == "usr_99"
        assert "wolf15_session=" in resp.headers.get("set-cookie", "")


# ============================================================================
# 5. Logout endpoint — POST /api/auth/logout
# ============================================================================


class TestAuthLogout:
    """``POST /api/auth/logout`` — clears session cookie."""

    @pytest.fixture()
    def logout_client(self):
        _set_auth_secret()
        from api.auth_router import router

        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_logout_clears_cookie(self, logout_client: TestClient):
        resp = logout_client.post("/api/auth/logout")
        assert resp.status_code == 200
        assert resp.json()["status"] == "logged_out"
        # Cookie should be cleared (max-age=0 or expires in the past)
        cookie_header = resp.headers.get("set-cookie", "")
        assert "wolf15_session=" in cookie_header


# ============================================================================
# 6. Cookie-based session auth
# ============================================================================


class TestCookieAuth:
    """Verify that session endpoints accept HttpOnly cookie as auth."""

    @pytest.fixture()
    def cookie_client(self):
        _set_auth_secret()
        from api.auth_router import router

        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_session_via_cookie_returns_user(self, cookie_client: TestClient):
        """GET /api/auth/session should accept the session cookie."""
        _set_auth_secret()
        from api.middleware.auth import COOKIE_NAME

        token = _make_token(sub="cookie_user", email="c@test.com", role="trader")
        cookie_client.cookies.set(COOKIE_NAME, token)

        resp = cookie_client.get("/api/auth/session")
        assert resp.status_code == 200
        body = resp.json()
        assert body["user_id"] == "cookie_user"
        assert body["role"] == "trader"

    def test_session_refreshes_cookie(self, cookie_client: TestClient):
        """GET /api/auth/session should refresh the session cookie on success."""
        _set_auth_secret()
        token = _make_token(sub="usr_1")
        resp = cookie_client.get(
            "/api/auth/session",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert "wolf15_session=" in resp.headers.get("set-cookie", "")

    def test_refresh_via_cookie(self, cookie_client: TestClient):
        """POST /api/auth/refresh should work with cookie-only auth."""
        _set_auth_secret()
        from api.middleware.auth import COOKIE_NAME

        token = _make_token(sub="cookie_user", email="c@test.com", role="admin")
        cookie_client.cookies.set(COOKIE_NAME, token)

        resp = cookie_client.post("/api/auth/refresh")
        assert resp.status_code == 200
        body = resp.json()
        assert "token" in body
        assert body["user_id"] == "cookie_user"
        assert "wolf15_session=" in resp.headers.get("set-cookie", "")


# ============================================================================
# 7. Compat endpoint — cookie fallback
# ============================================================================


class TestAuthCompatCookie:
    """``GET /auth/session`` — should also accept HttpOnly cookie."""

    @pytest.fixture()
    def compat_cookie_client(self):
        _set_auth_secret()
        from api.routes.auth_compat import router

        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_compat_session_via_cookie(self, compat_cookie_client: TestClient):
        _set_auth_secret()
        from api.middleware.auth import COOKIE_NAME

        token = _make_token(sub="compat_cookie", email="cc@test.com", role="viewer")
        compat_cookie_client.cookies.set(COOKIE_NAME, token)

        resp = compat_cookie_client.get("/auth/session")
        assert resp.status_code == 200
        body = resp.json()
        assert body["authenticated"] is True
        assert body["user"]["user_id"] == "compat_cookie"

    def test_compat_invalid_cookie_returns_unauthenticated(self, compat_cookie_client: TestClient):
        from api.middleware.auth import COOKIE_NAME

        compat_cookie_client.cookies.set(COOKIE_NAME, "garbage-token")

        resp = compat_cookie_client.get("/auth/session")
        assert resp.status_code == 200
        assert resp.json()["authenticated"] is False
