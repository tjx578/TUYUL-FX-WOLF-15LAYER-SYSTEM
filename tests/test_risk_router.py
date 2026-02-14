"""
Tests for Risk Router API

Tests FastAPI endpoints:
- Profile management (save/get)
- Signal evaluation
- Trade lifecycle (close)
- Input validation
"""

from unittest.mock import MagicMock, patch

import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from risk.risk_router import router as risk_router

# ========== Fixtures ==========


@pytest.fixture
def mock_redis():
    """Mock Redis client with in-memory store."""
    store: dict[str, str] = {}
    redis_mock = MagicMock()
    redis_mock.get.side_effect = store.get
    redis_mock.set.side_effect = lambda key, value, ex=None: store.__setitem__(key, value)
    redis_mock.delete.side_effect = lambda key: store.pop(key, None)
    return redis_mock


@pytest.fixture
def app():
    """Create test FastAPI app with risk router."""
    test_app = FastAPI()
    test_app.include_router(risk_router)
    return test_app


@pytest.fixture
def client(app):
    """Create test client."""
    return TestClient(app)


# ========== Profile Endpoints ==========


def test_save_profile_fixed_mode(client, mock_redis):
    """Test saving FIXED mode profile."""
    with patch("risk.risk_profile.RedisClient") as MockRedis:
        MockRedis.return_value = mock_redis

        response = client.post(
            "/api/v1/risk/test_account/profile",
            json={
                "risk_per_trade": 1.5,
                "max_daily_dd": 6.0,
                "max_total_dd": 12.0,
                "max_open_trades": 2,
                "risk_mode": "FIXED",
                "split_ratio": [0.4, 0.6],
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "saved"
        assert data["profile"]["risk_mode"] == "FIXED"
        assert data["profile"]["risk_per_trade"] == 1.5


def test_save_profile_split_mode(client, mock_redis):
    """Test saving SPLIT mode profile."""
    with patch("risk.risk_profile.RedisClient") as MockRedis:
        MockRedis.return_value = mock_redis

        response = client.post(
            "/api/v1/risk/test_account/profile",
            json={
                "risk_per_trade": 2.0,
                "max_daily_dd": 8.0,
                "max_total_dd": 15.0,
                "max_open_trades": 3,
                "risk_mode": "SPLIT",
                "split_ratio": [0.5, 0.5],
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["profile"]["risk_mode"] == "SPLIT"
        assert data["profile"]["split_ratio"] == [0.5, 0.5]


def test_get_profile_default(client, mock_redis):
    """Test getting default profile when none exists."""
    with patch("risk.risk_profile.RedisClient") as MockRedis:
        MockRedis.return_value = mock_redis
        mock_redis.get.return_value = None

        response = client.get("/api/v1/risk/test_account/profile")

        assert response.status_code == 200
        data = response.json()
        assert data["risk_per_trade"] == 0.7  # Default value
        assert data["risk_mode"] == "FIXED"


def test_get_profile_saved(client, mock_redis):
    """Test getting saved profile."""
    with patch("risk.risk_profile.RedisClient") as MockRedis:
        store: dict[str, str] = {}
        mock_redis.get.side_effect = store.get
        mock_redis.set.side_effect = lambda key, value, ex=None: store.__setitem__(key, value)
        MockRedis.return_value = mock_redis

        # Save profile
        client.post(
            "/api/v1/risk/test_account/profile",
            json={
                "risk_per_trade": 2.5,
                "max_daily_dd": 7.0,
                "max_total_dd": 14.0,
                "max_open_trades": 4,
                "risk_mode": "SPLIT",
                "split_ratio": [0.3, 0.7],
            },
        )

        # Get profile
        response = client.get("/api/v1/risk/test_account/profile")

        assert response.status_code == 200
        data = response.json()
        assert data["risk_per_trade"] == 2.5
        assert data["max_open_trades"] == 4
        assert data["risk_mode"] == "SPLIT"


def test_save_profile_invalid_risk_mode(client, mock_redis):
    """Test saving profile with invalid risk_mode returns 422."""
    with patch("risk.risk_profile.RedisClient") as MockRedis:
        MockRedis.return_value = mock_redis

        response = client.post(
            "/api/v1/risk/test_account/profile",
            json={
                "risk_per_trade": 1.0,
                "max_daily_dd": 5.0,
                "max_total_dd": 10.0,
                "max_open_trades": 1,
                "risk_mode": "INVALID",
                "split_ratio": [0.4, 0.6],
            },
        )

        assert response.status_code == 422  # Validation error


def test_save_profile_risk_too_high(client, mock_redis):
    """Test saving profile with risk_per_trade too high returns 422."""
    with patch("risk.risk_profile.RedisClient") as MockRedis:
        MockRedis.return_value = mock_redis

        response = client.post(
            "/api/v1/risk/test_account/profile",
            json={
                "risk_per_trade": 10.0,  # Too high (max 5.0)
                "max_daily_dd": 5.0,
                "max_total_dd": 10.0,
                "max_open_trades": 1,
                "risk_mode": "FIXED",
                "split_ratio": [0.4, 0.6],
            },
        )

        assert response.status_code == 422


# ========== Evaluate Endpoint ==========


def test_evaluate_signal_allow(client, mock_redis):
    """Test evaluating signal returns ALLOW response."""
    with patch("risk.risk_profile.RedisClient") as MockRedis1:
        MockRedis1.return_value = mock_redis
        with patch("risk.open_risk_tracker.RedisClient") as MockRedis2:
            MockRedis2.return_value = mock_redis
            with patch("risk.drawdown.RedisClient") as MockRedis3:
                MockRedis3.return_value = mock_redis
                with patch("risk.circuit_breaker.RedisClient") as MockRedis4:
                    MockRedis4.return_value = mock_redis

                    # Reset RiskManager singleton
                    # Reset and re-initialize RiskManager singleton
                    from risk.risk_manager import RiskManager

                    RiskManager.reset_instance()
                    RiskManager.get_instance(initial_balance=10000.0)

                    response = client.post(
                        "/api/v1/risk/test_account/evaluate",
                        json={
                            "symbol": "EURUSD",
                            "direction": "BUY",
                            "entry_price": 1.0950,
                            "stop_loss": 1.0900,
                            "take_profit_1": 1.1000,
                            "take_profit_1": 1.1050,
                            "rr_ratio": 2.0,
                            "trade_id": "test_trade_1",
                        },
                    )

                    # Cleanup
                    RiskManager.reset_instance()

                    assert response.status_code == 200
                    data = response.json()
                    assert data["verdict"] == "ALLOW"
                    assert data["lots"] is not None
                    assert len(data["lots"]) >= 1
                    assert data["risk_amount"] > 0


def test_evaluate_signal_with_auto_register(client, mock_redis):
    """Test evaluating signal with auto_register flag."""
    with patch("risk.risk_profile.RedisClient") as MockRedis1:
        MockRedis1.return_value = mock_redis
        with patch("risk.open_risk_tracker.RedisClient") as MockRedis2:
            MockRedis2.return_value = mock_redis
            with patch("risk.drawdown.RedisClient") as MockRedis3:
                MockRedis3.return_value = mock_redis
                with patch("risk.circuit_breaker.RedisClient") as MockRedis4:
                    MockRedis4.return_value = mock_redis

                    from risk.risk_manager import RiskManager

                    RiskManager.reset_instance()
                    RiskManager.get_instance(initial_balance=10000.0)

                    response = client.post(
                        "/api/v1/risk/test_account/evaluate",
                        json={
                            "symbol": "EURUSD",
                            "direction": "BUY",
                            "entry_price": 1.0950,
                            "stop_loss": 1.0900,
                            "take_profit_1": 1.1000,
                            "take_profit_1": 1.1050,
                            "rr_ratio": 2.0,
                            "trade_id": "test_trade_1",
                            "auto_register": True,
                        },
                    )

                    RiskManager.reset_instance()

                    assert response.status_code == 200
                    data = response.json()
                    assert data["verdict"] == "ALLOW"
                    # Note: We can't easily verify registration without checking Redis,
                    # but the endpoint should handle it


# ========== Snapshot Endpoint ==========


def test_get_snapshot(client, mock_redis):
    """Test getting account snapshot."""
    with patch("risk.risk_profile.RedisClient") as MockRedis1:
        MockRedis1.return_value = mock_redis
        with patch("risk.open_risk_tracker.RedisClient") as MockRedis2:
            MockRedis2.return_value = mock_redis
            with patch("risk.drawdown.RedisClient") as MockRedis3:
                MockRedis3.return_value = mock_redis
                with patch("risk.circuit_breaker.RedisClient") as MockRedis4:
                    MockRedis4.return_value = mock_redis

                    from risk.risk_manager import RiskManager

                    RiskManager.reset_instance()
                    RiskManager.get_instance(initial_balance=10000.0)

                    response = client.get("/api/v1/risk/test_account/snapshot")

                    RiskManager.reset_instance()

                    assert response.status_code == 200
                    data = response.json()
                    assert "account_id" in data
                    assert "profile" in data
                    assert "risk" in data
                    assert "open_risk" in data
                    assert "trading_allowed" in data


# ========== Close Trade Endpoint ==========


def test_close_trade(client, mock_redis):
    """Test closing a trade."""
    with patch("risk.risk_profile.RedisClient") as MockRedis1:
        MockRedis1.return_value = mock_redis
        with patch("risk.open_risk_tracker.RedisClient") as MockRedis2:
            MockRedis2.return_value = mock_redis
            with patch("risk.drawdown.RedisClient") as MockRedis3:
                MockRedis3.return_value = mock_redis
                with patch("risk.circuit_breaker.RedisClient") as MockRedis4:
                    MockRedis4.return_value = mock_redis

                    from risk.risk_manager import RiskManager

                    RiskManager.reset_instance()
                    RiskManager.get_instance(initial_balance=10000.0)

                    response = client.post(
                        "/api/v1/risk/test_account/close",
                        json={
                            "trade_id": "test_trade_1",
                            "entry_number": 1,
                        },
                    )

                    RiskManager.reset_instance()

                    assert response.status_code == 200
                    data = response.json()
                    assert data["status"] == "closed"
                    assert data["trade_id"] == "test_trade_1"
                    assert data["entry_number"] == 1


# ========== Input Validation ==========


def test_evaluate_invalid_direction(client, mock_redis):
    """Test evaluating signal with invalid direction."""
    with patch("risk.risk_profile.RedisClient") as MockRedis:
        MockRedis.return_value = mock_redis

        response = client.post(
            "/api/v1/risk/test_account/evaluate",
            json={
                "symbol": "EURUSD",
                "direction": "INVALID",
                "entry_price": 1.0950,
                "stop_loss": 1.0900,
                "take_profit_1": 1.1000,
                "rr_ratio": 1.0,
                "trade_id": "test_trade_1",
            },
        )

        assert response.status_code == 422


def test_evaluate_missing_required_fields(client, mock_redis):
    """Test evaluating signal with missing required fields."""
    with patch("risk.risk_profile.RedisClient") as MockRedis:
        MockRedis.return_value = mock_redis

        response = client.post(
            "/api/v1/risk/test_account/evaluate",
            json={
                "symbol": "EURUSD",
                "direction": "BUY",
                # Missing other required fields
            },
        )

        assert response.status_code == 422


def test_save_profile_missing_fields(client, mock_redis):
    """Test saving profile with missing fields."""
    with patch("risk.risk_profile.RedisClient") as MockRedis:
        MockRedis.return_value = mock_redis

        response = client.post(
            "/api/v1/risk/test_account/profile",
            json={
                "risk_per_trade": 1.0,
                # Missing other required fields
            },
        )

        assert response.status_code == 422


def test_close_trade_invalid_entry_number(client, mock_redis):
    """Test closing trade with invalid entry_number."""
    with patch("risk.risk_profile.RedisClient") as MockRedis1:
        MockRedis1.return_value = mock_redis
        with patch("risk.open_risk_tracker.RedisClient") as MockRedis2:
            MockRedis2.return_value = mock_redis
            with patch("risk.drawdown.RedisClient") as MockRedis3:
                MockRedis3.return_value = mock_redis
                with patch("risk.circuit_breaker.RedisClient") as MockRedis4:
                    MockRedis4.return_value = mock_redis

                    response = client.post(
                        "/api/v1/risk/test_account/close",
                        json={
                            "trade_id": "test_trade_1",
                            "entry_number": 5,  # Out of range (1-2)
                        },
                    )

                    assert response.status_code == 422
