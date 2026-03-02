"""
Tests for Dashboard Routes

Tests cover:
  - Trade creation (take signal)
  - Trade status updates (confirm, close)
  - Account management
  - Price endpoints
"""

import pytest  # pyright: ignore[reportMissingImports]

from fastapi.testclient import TestClient  # pyright: ignore[reportMissingImports]

from api_server import app
from accounts.account_manager import AccountManager
from api.auth import verify_token
from journal.trade_ledger import TradeLedger


def _mock_verify_token():
    """Override auth dependency for tests -- returns a dummy payload."""
    return {"sub": "test_user", "auth_method": "test"}


# Override auth dependency so test requests are authenticated
app.dependency_overrides[verify_token] = _mock_verify_token


@pytest.fixture
def client():
    """Create test client for API with auth overridden."""
    return TestClient(app)


@pytest.fixture(autouse=True)
def clear_caches():
    """Clear service caches before each test."""
    # Clear account manager cache
    account_mgr = AccountManager()
    account_mgr._cache.clear()

    # Clear trade ledger cache
    trade_ledger = TradeLedger()
    trade_ledger._cache.clear()

    yield


def test_create_account(client):
    """Test creating a new account."""
    response = client.post(
        "/api/v1/accounts",
        json={
            "name": "Test Account",
            "balance": 100000.0,
            "prop_firm": False,
            "max_daily_dd_percent": 4.0,
            "max_total_dd_percent": 8.0,
            "max_concurrent_trades": 3,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Test Account"
    assert data["balance"] == 100000.0
    assert data["prop_firm"] is False
    assert "account_id" in data
    assert data["account_id"].startswith("ACC-")


def test_list_accounts_empty(client):
    """Test listing accounts when none exist."""
    response = client.get("/api/v1/accounts")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_list_accounts_with_data(client):
    """Test listing accounts after creating some."""
    # Create two accounts
    client.post(
        "/api/v1/accounts",
        json={
            "name": "Account 1",
            "balance": 50000.0,
        },
    )
    client.post(
        "/api/v1/accounts",
        json={
            "name": "Account 2",
            "balance": 100000.0,
        },
    )

    # List accounts
    response = client.get("/api/v1/accounts")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2


def test_get_account(client):
    """Test getting a specific account."""
    # Create account
    create_response = client.post(
        "/api/v1/accounts",
        json={
            "name": "Test Account",
            "balance": 100000.0,
        },
    )
    account_id = create_response.json()["account_id"]

    # Get account
    response = client.get(f"/api/v1/accounts/{account_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["account_id"] == account_id
    assert data["name"] == "Test Account"


def test_get_account_not_found(client):
    """Test getting non-existent account."""
    response = client.get("/api/v1/accounts/ACC-nonexistent")

    assert response.status_code == 404


def test_take_signal(client):
    """Test taking a signal to create a trade."""
    # Create account first
    account_response = client.post(
        "/api/v1/accounts",
        json={
            "name": "Trading Account",
            "balance": 100000.0,
        },
    )
    account_id = account_response.json()["account_id"]

    # Take signal
    response = client.post(
        "/api/v1/trades/take",
        json={
            "signal_id": "SIG-EURUSD_1234567890",
            "account_id": account_id,
            "pair": "EURUSD",
            "direction": "BUY",
            "entry": 1.08500,
            "sl": 1.08000,
            "tp": 1.09500,
            "risk_percent": 2.0,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["signal_id"] == "SIG-EURUSD_1234567890"
    assert data["account_id"] == account_id
    assert data["pair"] == "EURUSD"
    assert data["direction"] == "BUY"
    assert data["status"] == "INTENDED"
    assert "trade_id" in data
    assert data["trade_id"].startswith("T-")


def test_skip_signal(client):
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
    assert data["status"] == "skipped"
    assert data["signal_id"] == "SIG-GBPUSD_1234567890"
    assert data["reason"] == "Too risky"


def test_confirm_order(client):
    """Test confirming order placement."""
    # Create account
    account_response = client.post(
        "/api/v1/accounts",
        json={
            "name": "Trading Account",
            "balance": 100000.0,
        },
    )
    account_id = account_response.json()["account_id"]

    # Take signal
    trade_response = client.post(
        "/api/v1/trades/take",
        json={
            "signal_id": "SIG-EURUSD_1234567890",
            "account_id": account_id,
            "pair": "EURUSD",
            "direction": "BUY",
            "entry": 1.08500,
            "sl": 1.08000,
            "tp": 1.09500,
            "risk_percent": 2.0,
        },
    )
    trade_id = trade_response.json()["trade_id"]

    # Confirm order
    response = client.post(
        "/api/v1/trades/confirm",
        json={
            "trade_id": trade_id,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["trade_id"] == trade_id
    assert data["status"] == "PENDING"


def test_get_active_trades_empty(client):
    """Test getting active trades when none exist."""
    response = client.get("/api/v1/trades/active")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 0


def test_get_active_trades_with_data(client):
    """Test getting active trades after creating some."""
    # Create account
    account_response = client.post(
        "/api/v1/accounts",
        json={
            "name": "Trading Account",
            "balance": 100000.0,
        },
    )
    account_id = account_response.json()["account_id"]

    # Create two trades
    client.post(
        "/api/v1/trades/take",
        json={
            "signal_id": "SIG-EURUSD_1",
            "account_id": account_id,
            "pair": "EURUSD",
            "direction": "BUY",
            "entry": 1.08500,
            "sl": 1.08000,
            "tp": 1.09500,
            "risk_percent": 2.0,
        },
    )

    client.post(
        "/api/v1/trades/take",
        json={
            "signal_id": "SIG-GBPUSD_2",
            "account_id": account_id,
            "pair": "GBPUSD",
            "direction": "SELL",
            "entry": 1.25500,
            "sl": 1.26000,
            "tp": 1.24500,
            "risk_percent": 1.5,
        },
    )

    # Get active trades
    response = client.get("/api/v1/trades/active")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2


def test_get_trade(client):
    """Test getting a specific trade."""
    # Create account and trade
    account_response = client.post(
        "/api/v1/accounts",
        json={
            "name": "Trading Account",
            "balance": 100000.0,
        },
    )
    account_id = account_response.json()["account_id"]

    trade_response = client.post(
        "/api/v1/trades/take",
        json={
            "signal_id": "SIG-EURUSD_1234567890",
            "account_id": account_id,
            "pair": "EURUSD",
            "direction": "BUY",
            "entry": 1.08500,
            "sl": 1.08000,
            "tp": 1.09500,
            "risk_percent": 2.0,
        },
    )
    trade_id = trade_response.json()["trade_id"]

    # Get trade
    response = client.get(f"/api/v1/trades/{trade_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["trade_id"] == trade_id


def test_get_trade_not_found(client):
    """Test getting non-existent trade."""
    response = client.get("/api/v1/trades/T-nonexistent")

    assert response.status_code == 404


def test_get_prices_empty(client):
    """Test getting prices when none cached."""
    response = client.get("/api/v1/prices")

    assert response.status_code == 200
    data = response.json()
    assert "prices" in data
    assert "count" in data


def test_journal_endpoints(client):
    """Test journal endpoints are accessible."""
    # Today
    response = client.get("/api/v1/journal/today")
    assert response.status_code == 200

    # Weekly
    response = client.get("/api/v1/journal/weekly")
    assert response.status_code == 200

    # Metrics
    response = client.get("/api/v1/journal/metrics")
    assert response.status_code == 200
    data = response.json()
    assert "rejection_accuracy_pct" in data
    assert "total_decisions" in data
