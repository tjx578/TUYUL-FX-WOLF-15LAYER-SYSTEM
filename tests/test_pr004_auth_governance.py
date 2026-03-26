"""PR-004 regression: auth & governance boundary enforcement.

Tests verify:
- risk_router has verify_token in dependencies (was CRITICAL bypass — GETs were open)
- risk_router dependencies include both verify_token AND enforce_write_policy
- write endpoints reject missing governance headers (runtime, accounts_router)
- CORS allow_headers include governance headers
- accounts_router router-level auth enforcement
"""

from __future__ import annotations

import ast
import pathlib
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
    from api.middleware.auth import create_token

    return create_token(sub="test_user", extra={"role": "trader"})


def _make_admin_token() -> str:
    from api.middleware.auth import create_token

    return create_token(sub="admin_user", extra={"role": "admin", "scopes": ["*"]})


def _set_auth_secret():
    import api.middleware.auth as auth_mod

    auth_mod.JWT_SECRET = _TEST_SECRET
    auth_mod.JWT_VERIFY_SECRETS = (_TEST_SECRET,)


# Pre-stub modules with broken import chains
_BROKEN_MODULES = [
    "execution.broker_executor",
    "execution.ea_manager",
    "execution.state_machine",
    "accounts.risk_engine",
]


def _ensure_stub(name: str) -> None:
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


# ---------------------------------------------------------------------------
# Helper: parse a router = APIRouter(...) call from source and return
# the list of dependency function names found in dependencies=[...].
# ---------------------------------------------------------------------------
def _extract_router_dependencies(source: str) -> list[str]:
    """Return dependency function names from the router's dependencies kwarg."""
    tree = ast.parse(source)
    deps: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not (isinstance(target, ast.Name) and target.id == "router"):
                continue
            if not isinstance(node.value, ast.Call):
                continue
            for kw in node.value.keywords:
                if kw.arg != "dependencies":
                    continue
                if not isinstance(kw.value, ast.List):
                    continue
                for elt in kw.value.elts:
                    # Depends(verify_token) → Call(func=Name('Depends'), args=[Name('verify_token')])
                    if isinstance(elt, ast.Call) and elt.args:
                        arg0 = elt.args[0]
                        if isinstance(arg0, ast.Name):
                            deps.append(arg0.id)
    return deps


# ============================================================================
# 1. risk_router — MUST have verify_token in dependencies (was CRITICAL bypass)
# ============================================================================


class TestRiskRouterAuthBoundary:
    """Static verification that risk_router.py enforces auth on ALL methods.

    Before PR-004, the router only had enforce_write_policy (returns None
    for GET), leaving 5 GET endpoints completely unauthenticated.
    """

    _SOURCE = pathlib.Path("risk/risk_router.py").read_text(encoding="utf-8")

    def test_imports_verify_token(self):
        tree = ast.parse(self._SOURCE)
        found = False
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and "auth" in node.module
                and any(alias.name == "verify_token" for alias in node.names)
            ):
                found = True
        assert found, "risk_router.py must import verify_token from auth module"

    def test_router_depends_verify_token(self):
        deps = _extract_router_dependencies(self._SOURCE)
        assert "verify_token" in deps, f"risk_router dependencies must include verify_token, found: {deps}"

    def test_router_depends_enforce_write_policy(self):
        deps = _extract_router_dependencies(self._SOURCE)
        assert "enforce_write_policy" in deps, (
            f"risk_router dependencies must include enforce_write_policy, found: {deps}"
        )

    def test_verify_token_listed_before_write_policy(self):
        """Auth check must run before governance check."""
        deps = _extract_router_dependencies(self._SOURCE)
        idx_auth = deps.index("verify_token") if "verify_token" in deps else -1
        idx_gov = deps.index("enforce_write_policy") if "enforce_write_policy" in deps else -1
        assert idx_auth >= 0 and idx_gov >= 0, f"Missing deps: {deps}"
        assert idx_auth < idx_gov, "verify_token must come before enforce_write_policy in dependencies"


# ============================================================================
# 2. Write governance enforcement — missing headers rejected (runtime test)
# ============================================================================


class TestWriteGovernanceEnforcement:
    """Verify write endpoints reject requests without governance headers."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        _set_auth_secret()
        with (
            patch("accounts.account_manager.AccountManager") as MockAM,
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

    def test_write_without_auth_returns_401(self):
        resp = self.client.post(
            "/api/v1/accounts",
            json={"account_name": "Test", "broker": "IC"},
        )
        assert resp.status_code == 401

    def test_write_with_auth_but_no_governance_headers_returns_403(self):
        _set_auth_secret()
        token = _make_admin_token()
        resp = self.client.post(
            "/api/v1/accounts",
            json={"account_name": "Test", "broker": "IC"},
            headers={"Authorization": f"Bearer {token}"},
        )
        # Missing X-Edit-Mode → governance rejects with 403
        assert resp.status_code == 403, f"Expected 403 but got {resp.status_code}: {resp.text}"

    def test_write_with_auth_and_governance_headers_passes_gate(self):
        """Full auth + governance headers should not be blocked by auth/governance."""
        _set_auth_secret()
        token = _make_admin_token()
        resp = self.client.post(
            "/api/v1/accounts",
            json={
                "account_name": "Test Account",
                "broker": "IC_Markets",
                "balance": 10000.0,
            },
            headers={
                "Authorization": f"Bearer {token}",
                "X-Edit-Mode": "ON",
                "X-Action-Reason": "TEST_CREATE",
            },
        )
        # Passes auth+governance — may fail on business logic, but NOT 401/403
        assert resp.status_code not in (401, 403)


# ============================================================================
# 3. CORS allow_headers include governance headers
# ============================================================================


class TestCORSGovernanceHeaders:
    """Verify app_factory includes governance headers in CORS config."""

    _SOURCE = pathlib.Path("api/app_factory.py").read_text(encoding="utf-8")

    @pytest.mark.parametrize("header", ["X-Edit-Mode", "X-Action-Reason", "X-Action-Pin"])
    def test_cors_includes_governance_header(self, header: str):
        assert f'"{header}"' in self._SOURCE, f"CORS allow_headers missing governance header: {header}"


# ============================================================================
# 4. accounts_router router-level auth
# ============================================================================


class TestAccountsRouterLevelAuth:
    """Verify accounts_router has router-level verify_token dependency."""

    _SOURCE = pathlib.Path("api/accounts_router.py").read_text(encoding="utf-8")

    def test_accounts_router_has_router_level_auth(self):
        deps = _extract_router_dependencies(self._SOURCE)
        assert "verify_token" in deps, f"accounts_router router must have verify_token in dependencies, found: {deps}"
