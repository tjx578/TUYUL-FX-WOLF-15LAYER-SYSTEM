"""
Tests for Dashboard Routes

Tests cover:
  - Account management (create, list, get)
  - Trade lifecycle (take signal, skip, confirm)
  - Active trades listing
  - Price endpoints
  - Journal metrics
"""

from __future__ import annotations

import fnmatch
import json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from accounts.account_model import RiskCalculationResult, RiskSeverity
from api.middleware.auth import verify_token
from api.middleware.governance import enforce_write_policy

# ── In-memory async Redis mock for test isolation ─────────────────────────────


class _FakeRedis:
    """Minimal async Redis mock that stores data in memory."""

    def __init__(self) -> None:
        self._str: dict[str, str] = {}
        self._hash: dict[str, dict[str, str]] = {}

    # -- string ops --
    async def get(self, key: str) -> str | None:
        return self._str.get(str(key))

    async def set(self, key: str, value: str, **kw: Any) -> bool:
        self._str[str(key)] = str(value)
        return True

    # -- hash ops --
    async def hset(self, key: str, mapping: dict[str, Any] | None = None, **kw: Any) -> int:
        k = str(key)
        if k not in self._hash:
            self._hash[k] = {}
        if mapping:
            self._hash[k].update({str(mk): str(mv) for mk, mv in mapping.items()})
        return len(mapping or {})

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self._hash.get(str(key), {}))

    # -- scan --
    async def scan_iter(self, match: str | None = None) -> Any:
        pattern = str(match or "*")
        seen: set[str] = set()
        for k in list(self._hash) + list(self._str):
            if k not in seen and fnmatch.fnmatch(k, pattern):
                seen.add(k)
                yield k

    # -- misc --
    async def delete(self, *keys: str) -> int:
        c = 0
        for key in keys:
            k = str(key)
            c += int(k in self._str) + int(k in self._hash)
            self._str.pop(k, None)
            self._hash.pop(k, None)
        return c

    async def eval(self, script: str, numkeys: int, *args: Any) -> Any:
        """Minimal eval stub — supports TRADE confirm transition."""
        if numkeys >= 1 and "INTENDED" in script:
            key = str(args[0])
            now = str(args[1]) if len(args) > 1 else ""
            raw = self._str.get(key)
            if not raw:
                return [0, "NOT_FOUND"]
            trade = json.loads(raw)
            if trade.get("status") != "INTENDED":
                return [0, trade.get("status", "UNKNOWN")]
            trade["status"] = "PENDING"
            trade["updated_at"] = now
            self._str[key] = json.dumps(trade)
            return [1, json.dumps(trade)]
        if numkeys >= 2 and "XADD" in script:
            # Outbox enqueue stub
            trade_key = str(args[0])
            if len(args) > 2:
                self._str[trade_key] = str(args[2])
            return "fake-stream-id"
        return None

    async def xadd(self, *a: Any, **kw: Any) -> str:
        return "fake-stream-id"

    async def publish(self, *a: Any, **kw: Any) -> int:
        return 1

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        pass

    async def close(self) -> None:
        pass


class _KillSwitchOff:
    def is_enabled(self) -> bool:
        return False

    def snapshot(self) -> dict[str, Any]:
        return {"enabled": False, "reason": "", "updated_at": ""}

    def evaluate_and_trip(self, *, metrics: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG002
        return self.snapshot()


_fake_redis = _FakeRedis()


async def _mock_get_client(*_a: Any, **_kw: Any) -> _FakeRedis:
    return _fake_redis


async def _mock_get_async_redis() -> _FakeRedis:
    return _fake_redis


def _stable_risk_result(*_a: Any, **_kw: Any) -> RiskCalculationResult:
    """Return a concrete risk result to avoid suite-level MagicMock leakage."""
    return RiskCalculationResult(
        trade_allowed=True,
        recommended_lot=0.1,
        max_safe_lot=0.1,
        risk_used_percent=1.0,
        daily_dd_after=0.0,
        total_dd_after=0.0,
        severity=RiskSeverity.SAFE,
        reason="test",
    )


class _StableRiskEngine:
    """Deterministic risk engine stub for route tests."""

    def calculate_lot(self, *args: Any, **kwargs: Any) -> RiskCalculationResult:  # noqa: ARG002
        return _stable_risk_result()


# ── App setup with auth overrides ─────────────────────────────────────────────

from api_server import app  # noqa: E402


def _mock_verify_token() -> dict[str, str]:
    return {"sub": "test_user", "auth_method": "test"}


async def _mock_write_policy() -> None:
    return None


@pytest.fixture(autouse=True)
def _override_auth_dependencies() -> Any:
    """Isolate dependency overrides to this test module's test scope."""
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[verify_token] = _mock_verify_token
    app.dependency_overrides[enforce_write_policy] = _mock_write_policy

    # Also override the exact route-bound dependency callables in case other
    # tests reloaded/mocked modules and changed function object identity.
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if not str(route.path).startswith("/api/v1/"):
            continue
        for dep in route.dependant.dependencies:
            call = getattr(dep, "call", None)
            if callable(call):
                app.dependency_overrides[call] = _mock_write_policy

    yield
    app.dependency_overrides.clear()
    app.dependency_overrides.update(previous)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _valid_account_payload(
    name: str = "Test Account",
    balance: float = 100000.0,
    **overrides: Any,
) -> dict[str, Any]:
    """Build a valid AccountUpsertRequest payload."""
    base: dict[str, Any] = {
        "account_name": name,
        "starting_balance": balance,
        "current_balance": balance,
        "equity": balance,
        "equity_high": balance,
        "reason": "test account creation",
    }
    base.update(overrides)
    return base


def _create_account(
    client: TestClient,
    name: str = "Test Account",
    balance: float = 100000.0,
    **kw: Any,
) -> tuple[str, dict[str, Any]]:
    """Create an account via API, return (account_id, response_data)."""
    resp = client.post("/api/v1/accounts", json=_valid_account_payload(name, balance, **kw))
    assert resp.status_code == 200, f"Account creation failed: {resp.text}"
    data = resp.json()
    return data["account_id"], data


def _take_signal(
    client: TestClient,
    account_id: str,
    pair: str = "EURUSD",
    signal_id: str = "SIG-EURUSD_1234567890",
) -> tuple[str, dict[str, Any]]:
    """Take a signal via API, return (trade_id, response_data)."""
    direction = "BUY"
    resp = client.post(
        "/api/v1/trades/take",
        json={
            "signal_id": signal_id,
            "account_id": account_id,
            "pair": pair,
            "direction": direction,
            "entry": 1.08500,
            "sl": 1.08000,
            "tp": 1.09500,
            "risk_percent": 2.0,
        },
    )
    assert resp.status_code == 200, f"Take signal failed: {resp.text}"
    data = resp.json()
    return data["trade_id"], data


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_state() -> Any:
    """Clear all in-memory caches and fake Redis between tests."""
    from dashboard.account_manager import AccountManager
    from dashboard.trade_ledger import TradeLedger

    AccountManager._memory_accounts.clear()
    TradeLedger._memory_trades.clear()
    _fake_redis._str.clear()
    _fake_redis._hash.clear()

    # Seed recent tick to prevent kill-switch from tripping
    _fake_redis._str["ctx:tick:latest"] = json.dumps({"timestamp": time.time()})

    import api.allocation_router as alloc
    from api.middleware import rate_limit as rl

    alloc._trade_ledger.clear()
    alloc._account_registry.clear()

    # Reset in-memory rate-limit buckets so tests don't leak 429 state.
    rl._http_store.reset()
    rl._ws_store.reset()
    rl._take_store.reset()
    rl._config_store.reset()
    rl._ws_connect_store.reset()
    rl._ea_control_store.reset()
    rl._account_write_store.reset()
    rl._trade_write_store.reset()
    rl._risk_calc_store.reset()
    rl._admin_store.reset()

    yield


@pytest.fixture(autouse=True)
def _patch_redis() -> Any:
    """Patch Redis client at the infrastructure level so ALL modules get the mock."""
    import infrastructure.redis_client as _rc

    # Mock the signal service to avoid sync Redis calls in SignalRegistry
    _mock_signal_svc = MagicMock()
    _mock_signal_svc.publish.side_effect = lambda payload: {
        "signal_id": payload.get("signal_id", "SIG-TEST"),
        "symbol": payload.get("symbol", "UNKNOWN"),
        "verdict": payload.get("verdict", "EXECUTE"),
        "confidence": payload.get("confidence", 0.8),
        **payload,
    }

    import api.allocation_router as _alloc_mod

    with (
        patch.object(_rc._manager, "get_client", new=AsyncMock(return_value=_fake_redis)),
        patch("api.allocation_router._kill_switch", new=_KillSwitchOff()),
        patch("api.allocation_router._ensure_live_producer", new=AsyncMock(return_value=None)),
        patch("api.allocation_router._runtime_take_precheck", new=AsyncMock(return_value=(True, None))),
        patch("api.allocation_router.RiskEngine", new=_StableRiskEngine),
        patch(
            "api.allocation_router._persist_trade_write_through",
            new=AsyncMock(return_value=True),
        ),
    ):
        # Inject mock signal service directly into the module global
        old_svc = _alloc_mod._signal_service
        _alloc_mod._signal_service = _mock_signal_svc
        try:
            yield
        finally:
            _alloc_mod._signal_service = old_svc


# ── Account tests ─────────────────────────────────────────────────────────────


def test_create_account(client: TestClient) -> None:
    """Test creating a new account."""
    response = client.post(
        "/api/v1/accounts",
        json=_valid_account_payload(
            "Test Account",
            100000.0,
            prop_firm=False,
            max_daily_dd_percent=4.0,
            max_total_dd_percent=8.0,
            max_concurrent_trades=3,
        ),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Test Account"
    assert data["prop_firm"] is False
    assert "account_id" in data
    assert data["account_id"].startswith("ACC-")


def test_list_accounts_empty(client: TestClient) -> None:
    """Test listing accounts when none exist."""
    response = client.get("/api/v1/accounts")

    assert response.status_code == 200
    data = response.json()
    # Response is {"count": N, "accounts": [...]}
    assert "accounts" in data
    assert isinstance(data["accounts"], list)


def test_list_accounts_with_data(client: TestClient) -> None:
    """Test listing accounts after creating some."""
    _create_account(client, "Account 1", 50000.0)
    _create_account(client, "Account 2", 100000.0)

    response = client.get("/api/v1/accounts")

    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 2
    assert len(data["accounts"]) == 2


def test_get_account(client: TestClient) -> None:
    """Test getting a specific account."""
    account_id, _ = _create_account(client, "Test Account", 100000.0)

    response = client.get(f"/api/v1/accounts/{account_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["account_id"] == account_id
    assert data["name"] == "Test Account"


def test_get_account_not_found(client: TestClient) -> None:
    """Test getting non-existent account."""
    response = client.get("/api/v1/accounts/ACC-nonexistent")

    assert response.status_code == 404


# ── Trade lifecycle tests ─────────────────────────────────────────────────────


def test_take_signal(client: TestClient) -> None:
    """Test taking a signal to create a trade."""
    account_id, _ = _create_account(client, "Trading Account", 100000.0)

    # Seed account in allocation_router's Redis lookup path
    _fake_redis._hash[f"ACCOUNT:{account_id}"] = {
        "balance": "100000",
        "equity": "100000",
        "equity_high": "100000",
        "compliance_mode": "1",
        "prop_firm_code": "ftmo",
        "max_concurrent_trades": "3",
    }

    trade_id, data = _take_signal(client, account_id)

    assert data["status"] == "INTENDED"
    assert "trade_id" in data


def test_skip_signal(client: TestClient) -> None:
    """Test skipping a signal."""
    response = client.post(
        "/api/v1/trades/skip",
        json={
            "signal_id": "SIG-GBPUSD_1234567890",
            "pair": "GBPUSD",
            "reason": "Too risky",
        },
    )

    assert response.status_code == 200
    data = response.json()
    # Actual response: {"logged": True, "entry_id": "...", "journal_type": "J2"}
    assert data["logged"] is True
    assert "entry_id" in data
    assert data["journal_type"] == "J2"


def test_confirm_order(client: TestClient) -> None:
    """Test confirming order placement."""
    account_id, _ = _create_account(client, "Trading Account", 100000.0)
    _fake_redis._hash[f"ACCOUNT:{account_id}"] = {
        "balance": "100000",
        "equity": "100000",
        "equity_high": "100000",
        "compliance_mode": "1",
        "prop_firm_code": "ftmo",
        "max_concurrent_trades": "3",
    }

    trade_id, _ = _take_signal(client, account_id)

    response = client.post(
        "/api/v1/trades/confirm",
        json={"trade_id": trade_id},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["trade_id"] == trade_id
    assert data["status"] == "PENDING"


def test_get_active_trades_empty(client: TestClient) -> None:
    """Test getting active trades when none exist."""
    response = client.get("/api/v1/trades/active")

    assert response.status_code == 200
    data = response.json()
    # Response is {"trades": [...], "count": N}
    assert data["count"] == 0
    assert isinstance(data["trades"], list)
    assert len(data["trades"]) == 0


def test_get_active_trades_with_data(client: TestClient) -> None:
    """Test getting active trades after creating some."""
    account_id, _ = _create_account(client, "Trading Account", 100000.0)
    _fake_redis._hash[f"ACCOUNT:{account_id}"] = {
        "balance": "100000",
        "equity": "100000",
        "equity_high": "100000",
        "compliance_mode": "1",
        "prop_firm_code": "ftmo",
        "max_concurrent_trades": "5",
    }

    _take_signal(client, account_id, "EURUSD", "SIG-EURUSD_1")
    _take_signal(client, account_id, "GBPUSD", "SIG-GBPUSD_2")

    response = client.get("/api/v1/trades/active")

    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 2
    assert len(data["trades"]) == 2


def test_get_trade(client: TestClient) -> None:
    """Test getting a specific trade."""
    account_id, _ = _create_account(client, "Trading Account", 100000.0)
    _fake_redis._hash[f"ACCOUNT:{account_id}"] = {
        "balance": "100000",
        "equity": "100000",
        "equity_high": "100000",
        "compliance_mode": "1",
        "prop_firm_code": "ftmo",
        "max_concurrent_trades": "3",
    }

    trade_id, _ = _take_signal(client, account_id)

    response = client.get(f"/api/v1/trades/{trade_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["trade_id"] == trade_id


def test_get_trade_not_found(client: TestClient) -> None:
    """Test getting non-existent trade."""
    response = client.get("/api/v1/trades/T-nonexistent")

    assert response.status_code == 404


# ── Price & Journal tests ─────────────────────────────────────────────────────


def test_get_prices_empty(client: TestClient) -> None:
    """Test getting prices when none cached."""
    response = client.get("/api/v1/prices")

    assert response.status_code == 200
    data = response.json()
    assert "prices" in data
    assert "count" in data


def test_journal_endpoints(client: TestClient) -> None:
    """Test journal endpoints are accessible."""
    response = client.get("/api/v1/journal/today")
    assert response.status_code == 200

    response = client.get("/api/v1/journal/weekly")
    assert response.status_code == 200

    response = client.get("/api/v1/journal/metrics")
    assert response.status_code == 200
    data = response.json()
    # Actual field names from _compute_metrics
    assert "rejection_rate" in data
    assert "total_trades" in data
