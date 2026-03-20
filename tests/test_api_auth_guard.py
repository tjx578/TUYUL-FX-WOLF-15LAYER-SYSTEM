"""Regression: auth enforcement on read endpoints.

Every read-only router must reject unauthenticated requests with 401,
and return 200 when a valid token is supplied.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Shared test JWT secret (>= 32 chars)
# ---------------------------------------------------------------------------
_TEST_SECRET = "test-jwt-secret-that-is-at-least-32-chars-long!"


def _make_token() -> str:
    """Issue a JWT using the real create_token helper."""
    from api.middleware.auth import create_token

    return create_token(sub="test_user")


def _set_auth_secret():
    """Ensure the auth module uses our test secret."""
    import api.middleware.auth as auth_mod

    auth_mod.JWT_SECRET = _TEST_SECRET
    auth_mod.JWT_VERIFY_SECRETS = (_TEST_SECRET,)


# ---------------------------------------------------------------------------
# Pre-stub modules with broken import chains (pre-existing SyntaxErrors).
# ---------------------------------------------------------------------------

_BROKEN_MODULES = [
    "execution.broker_executor",
    "execution.ea_manager",
    "execution.state_machine",
    "accounts.risk_engine",
]


def _ensure_stub(name: str) -> None:
    """Install a stub module if the real one can't be imported."""
    if name in sys.modules:
        return
    mod = types.ModuleType(name)
    for attr in (
        "EAManager",
        "ExecutionStateMachine",
        "BrokerExecutor",
        "ExecutionRequest",
        "ExecutionResult",
        "RiskEngine",
        "PropFirmManager",
        "BasePropFirmGuard",
        "GuardResult",
    ):
        setattr(mod, attr, MagicMock())
    sys.modules[name] = mod


for _m in _BROKEN_MODULES:
    _ensure_stub(_m)


# ============================================================================
# 1. accounts_router — GET /api/v1/accounts requires auth
# ============================================================================


class TestAccountsRouterAuth:
    @pytest.fixture(autouse=True)
    def _setup(self):
        _set_auth_secret()
        with (
            patch("dashboard.account_manager.AccountManager") as MockAM,  # noqa: N806
            patch("journal.audit_trail.AuditTrail"),
            patch("storage.redis_client.redis_client", MagicMock()),
            patch("accounts.prop_rule_engine.validate_prop_sovereignty", return_value=(True, "")),
        ):
            MockAM.return_value.list_accounts_async = AsyncMock(return_value=[])
            MockAM.return_value.list_accounts.return_value = []

            from api.accounts_router import router

            self.app = FastAPI()
            self.app.include_router(router)
            self.client = TestClient(self.app)
            yield

    def test_no_auth_returns_401(self):
        resp = self.client.get("/api/v1/accounts")
        assert resp.status_code == 401

    def test_valid_auth_returns_200(self):
        _set_auth_secret()
        token = _make_token()
        resp = self.client.get(
            "/api/v1/accounts",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200


# ============================================================================
# 2. l12_routes — GET /api/v1/verdict/all requires auth
# ============================================================================


class TestL12RoutesAuth:
    @pytest.fixture(autouse=True)
    def _setup(self):
        _set_auth_secret()
        with patch("config_loader.load_pairs", return_value=[]):
            from api.l12_routes import router

            self.app = FastAPI()
            self.app.include_router(router)
            self.client = TestClient(self.app)
            yield

    def test_no_auth_returns_401(self):
        resp = self.client.get("/api/v1/verdict/all")
        assert resp.status_code == 401

    def test_valid_auth_returns_200(self):
        _set_auth_secret()
        token = _make_token()
        with patch("api.l12_routes.get_verdict", return_value=None):
            resp = self.client.get(
                "/api/v1/verdict/all",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200


# ============================================================================
# 3. ea_router — GET /api/v1/ea/status requires auth
# ============================================================================


class TestEARouterAuth:
    @pytest.fixture(autouse=True)
    def _setup(self):
        _set_auth_secret()
        with (
            patch("journal.audit_trail.AuditTrail"),
            patch("storage.redis_client.redis_client", MagicMock()),
            patch("api.middleware.governance.enforce_write_policy", return_value=None),
        ):
            from api.ea_router import router

            self.app = FastAPI()
            self.app.include_router(router)
            self.client = TestClient(self.app)
            yield

    def test_no_auth_returns_401(self):
        resp = self.client.get("/api/v1/ea/status")
        assert resp.status_code == 401

    def test_valid_auth_returns_200(self):
        _set_auth_secret()
        token = _make_token()
        resp = self.client.get(
            "/api/v1/ea/status",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200


# ============================================================================
# 4. config_profile_router — GET /api/v1/config/profiles requires auth
# ============================================================================


class TestConfigProfileRouterAuth:
    @pytest.fixture(autouse=True)
    def _setup(self):
        _set_auth_secret()
        with (
            patch("config.profile_engine.ConfigProfileEngine") as MockEngine,  # noqa: N806
            patch("journal.audit_trail.AuditTrail"),
        ):
            MockEngine.return_value.get_active_profile.return_value = "default"
            MockEngine.return_value.list_profiles.return_value = []
            MockEngine.return_value.list_profile_records.return_value = []
            MockEngine.return_value.list_scoped_overrides.return_value = {}
            MockEngine.return_value.is_locked.return_value = False

            from api.config_profile_router import router

            self.app = FastAPI()
            self.app.include_router(router)
            self.client = TestClient(self.app)
            yield

    def test_no_auth_returns_401(self):
        resp = self.client.get("/api/v1/config/profiles")
        assert resp.status_code == 401

    def test_valid_auth_returns_200(self):
        _set_auth_secret()
        token = _make_token()
        resp = self.client.get(
            "/api/v1/config/profiles",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200


# ============================================================================
# 5. dashboard_routes — GET /api/v1/trades/{id} requires auth
# ============================================================================


class TestDashboardRoutesAuth:
    @pytest.fixture(autouse=True)
    def _setup(self):
        _set_auth_secret()
        with (
            patch("dashboard.trade_ledger.TradeLedger") as MockTL,  # noqa: N806
            patch("dashboard.price_feed.PriceFeed"),
        ):
            MockTL.return_value.get_trade.return_value = None
            MockTL.return_value.get_trade_async = AsyncMock(return_value=None)

            from api.dashboard_routes import router

            self.app = FastAPI()
            self.app.include_router(router)
            self.client = TestClient(self.app)
            yield

    def test_no_auth_returns_401(self):
        resp = self.client.get("/api/v1/trades/some-id")
        assert resp.status_code == 401

    def test_valid_auth_returns_404_for_missing_trade(self):
        """Auth passes but trade doesn't exist → 404."""
        _set_auth_secret()
        token = _make_token()
        resp = self.client.get(
            "/api/v1/trades/some-id",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404


# ============================================================================
# 6. Prices endpoint (auth required)
# ============================================================================


class TestPricesEndpointAuth:
    @pytest.fixture(autouse=True)
    def _setup(self):
        with (
            patch("dashboard.price_feed.PriceFeed") as MockPF,  # noqa: N806
            patch("dashboard.trade_ledger.TradeLedger"),
        ):
            mock_pf = MockPF.return_value
            mock_pf.get_all_prices.return_value = {}
            mock_pf.get_all_prices_async = AsyncMock(return_value={})

            from api import dashboard_routes
            from api.dashboard_routes import router

            # Patch the module-level instance directly (created at import time)
            with patch.object(dashboard_routes, "_price_feed", mock_pf):
                self.app = FastAPI()
                self.app.include_router(router)
                self.client = TestClient(self.app)
                yield

    def test_prices_without_auth_returns_401(self):
        resp = self.client.get("/api/v1/prices")
        assert resp.status_code == 401

    def test_prices_with_valid_auth_returns_200(self):
        _set_auth_secret()
        token = _make_token()
        resp = self.client.get(
            "/api/v1/prices",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
