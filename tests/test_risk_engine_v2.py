"""
Tests for Risk Engine v2

Comprehensive test coverage for RiskEngineV2:
- ALLOW flow (FIXED and SPLIT modes)
- DENY flows (circuit breaker, max trades, prop firm)
- Trade lifecycle (register, close)
- Account snapshot
- Multi-instrument support
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from risk.risk_engine_v2 import (
    RiskEngineV2,
    RiskEvalResult,
    RiskVerdict,
    SignalInput,
)
from risk.risk_manager import RiskManager
from risk.risk_profile import RiskMode, RiskProfile, save_risk_profile

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
def risk_manager(mock_redis):
    """Create RiskManager with mocked Redis."""
    RiskManager.reset_instance()

    with patch("risk.drawdown.RedisClient") as MockRedis1:
        MockRedis1.return_value = mock_redis
        with patch("risk.circuit_breaker.RedisClient") as MockRedis2:
            MockRedis2.return_value = mock_redis
            manager = RiskManager.get_instance(initial_balance=10000.0)
            yield manager

    RiskManager.reset_instance()


@pytest.fixture
def engine(mock_redis, risk_manager):
    """Create RiskEngineV2 with mocked Redis."""
    with patch("risk.risk_profile.RedisClient") as MockRedis1:
        MockRedis1.return_value = mock_redis
        with patch("risk.open_risk_tracker.RedisClient") as MockRedis2:
            MockRedis2.return_value = mock_redis
            yield RiskEngineV2("test_account", risk_manager=risk_manager)


@pytest.fixture
def buy_signal():
    """Sample BUY signal."""
    return SignalInput(
        symbol="EURUSD",
        direction="BUY",
        entry_price=1.0950,
        stop_loss=1.0900,
        take_profit_1=1.1050,
        rr_ratio=2.0,
        trade_id="test_trade_1",
    )


@pytest.fixture
def xauusd_signal():
    """Sample XAUUSD signal."""
    return SignalInput(
        symbol="XAUUSD",
        direction="BUY",
        entry_price=2000.0,
        stop_loss=1995.0,
        take_profit_1=2010.0,
        rr_ratio=2.0,
        trade_id="test_trade_xau",
    )


# ========== ALLOW Flow ==========


def test_evaluate_allow_basic_fixed_mode(mock_redis, engine, buy_signal):
    """Test basic ALLOW verdict in FIXED mode."""
    with patch("risk.risk_profile.RedisClient") as MockRedis:
        MockRedis.return_value = mock_redis

        result = engine.evaluate(buy_signal)

        assert result.verdict == RiskVerdict.ALLOW
        assert result.allowed
        assert result.deny_code is None
        assert result.lots is not None
        assert len(result.lots) == 1  # FIXED mode = 1 lot
        assert result.risk_amount > 0
        assert result.open_trades_after == 1


def test_evaluate_allow_xauusd(mock_redis, engine, xauusd_signal):
    """Test ALLOW verdict for XAUUSD instrument."""
    with patch("risk.risk_profile.RedisClient") as MockRedis:
        MockRedis.return_value = mock_redis

        result = engine.evaluate(xauusd_signal)

        assert result.verdict == RiskVerdict.ALLOW
        assert result.lots is not None
        assert len(result.lots) == 1


# ========== SPLIT Mode ==========


def test_evaluate_split_mode_returns_two_lots(mock_redis, engine, buy_signal):
    """Test SPLIT mode returns 2 lots."""
    with patch("risk.risk_profile.RedisClient") as MockRedis:
        MockRedis.return_value = mock_redis

        # Save SPLIT profile
        profile = RiskProfile(
            risk_per_trade=1.0,
            risk_mode=RiskMode.SPLIT,
            split_ratio=(0.4, 0.6),
        )
        save_risk_profile("test_account", profile)

        result = engine.evaluate(buy_signal)

        assert result.verdict == RiskVerdict.ALLOW
        assert result.lots is not None
        assert len(result.lots) == 2  # SPLIT mode = 2 lots
        assert result.lots[0]["entry_number"] == 1
        assert result.lots[1]["entry_number"] == 2


def test_evaluate_split_mode_40_60_allocation(mock_redis, engine, buy_signal):
    """Test SPLIT mode 40/60 risk allocation."""
    with patch("risk.risk_profile.RedisClient") as MockRedis:
        MockRedis.return_value = mock_redis

        profile = RiskProfile(
            risk_per_trade=1.0,
            risk_mode=RiskMode.SPLIT,
            split_ratio=(0.4, 0.6),
        )
        save_risk_profile("test_account", profile)

        result = engine.evaluate(buy_signal)

        assert result.verdict == RiskVerdict.ALLOW
        lot1_risk = result.lots[0]["risk_amount"]
        lot2_risk = result.lots[1]["risk_amount"]
        total_risk = lot1_risk + lot2_risk

        # Check allocation ratio (allow small floating point error)
        assert abs(lot1_risk / total_risk - 0.4) < 0.01
        assert abs(lot2_risk / total_risk - 0.6) < 0.01


def test_evaluate_split_mode_50_50_allocation(mock_redis, engine, buy_signal):
    """Test SPLIT mode 50/50 risk allocation."""
    with patch("risk.risk_profile.RedisClient") as MockRedis:
        MockRedis.return_value = mock_redis

        profile = RiskProfile(
            risk_per_trade=1.0,
            risk_mode=RiskMode.SPLIT,
            split_ratio=(0.5, 0.5),
        )
        save_risk_profile("test_account", profile)

        result = engine.evaluate(buy_signal)

        assert result.verdict == RiskVerdict.ALLOW
        lot1_risk = result.lots[0]["risk_amount"]
        lot2_risk = result.lots[1]["risk_amount"]

        # Check equal allocation
        assert abs(lot1_risk - lot2_risk) < 0.01


# ========== DENY Flows ==========


def test_evaluate_deny_circuit_breaker(mock_redis, engine, buy_signal, risk_manager):
    """Test DENY verdict when circuit breaker is OPEN."""
    with patch("risk.risk_profile.RedisClient") as MockRedis:
        MockRedis.return_value = mock_redis

        # Trigger circuit breaker with large loss
        risk_manager.record_trade_result(
            pnl=-500.0,
            pair="EURUSD",
            current_equity=9500.0,
        )

        result = engine.evaluate(buy_signal)

        assert result.verdict == RiskVerdict.DENY
        assert not result.allowed
        assert result.deny_code == "CIRCUIT_BREAKER"
        assert "Circuit breaker" in result.details["reason"]


def test_evaluate_deny_max_open_trades(mock_redis, engine, buy_signal):
    """Test DENY verdict when max open trades reached."""
    with patch("risk.risk_profile.RedisClient") as MockRedis1:
        MockRedis1.return_value = mock_redis
        with patch("risk.open_risk_tracker.RedisClient") as MockRedis2:
            MockRedis2.return_value = mock_redis

            # Set profile with max_open_trades = 1
            profile = RiskProfile(max_open_trades=1)
            save_risk_profile("test_account", profile)

            # First trade should be allowed
            result1 = engine.evaluate(buy_signal)
            assert result1.verdict == RiskVerdict.ALLOW

            # Register the trade
            engine.register_intended_trade(buy_signal, result1.lots)

            # Second trade should be denied
            signal2 = SignalInput(
                symbol="GBPUSD",
                direction="BUY",
                entry_price=1.2500,
                stop_loss=1.2450,
                take_profit_1=1.2600,
                rr_ratio=2.0,
                trade_id="test_trade_2",
            )
            result2 = engine.evaluate(signal2)

            assert result2.verdict == RiskVerdict.DENY
            assert result2.deny_code == "MAX_OPEN_TRADES"
            assert "max" in result2.details["reason"].lower()


def test_evaluate_allow_after_close(mock_redis, engine, buy_signal):
    """Test ALLOW verdict after closing a trade."""
    with patch("risk.risk_profile.RedisClient") as MockRedis1:
        MockRedis1.return_value = mock_redis
        with patch("risk.open_risk_tracker.RedisClient") as MockRedis2:
            MockRedis2.return_value = mock_redis

            # Set profile with max_open_trades = 1
            profile = RiskProfile(max_open_trades=1)
            save_risk_profile("test_account", profile)

            # First trade
            result1 = engine.evaluate(buy_signal)
            assert result1.verdict == RiskVerdict.ALLOW
            engine.register_intended_trade(buy_signal, result1.lots)

            # Close first trade
            engine.close_trade("test_trade_1")

            # Second trade should now be allowed
            signal2 = SignalInput(
                symbol="GBPUSD",
                direction="BUY",
                entry_price=1.2500,
                stop_loss=1.2450,
                take_profit_1=1.2600,
                rr_ratio=2.0,
                trade_id="test_trade_2",
            )
            result2 = engine.evaluate(signal2)

            assert result2.verdict == RiskVerdict.ALLOW


# ========== Trade Lifecycle ==========


def test_register_intended_trade_updates_tracker(mock_redis, engine, buy_signal):
    """Test register_intended_trade updates open risk tracker."""
    with patch("risk.risk_profile.RedisClient") as MockRedis1:
        MockRedis1.return_value = mock_redis
        with patch("risk.open_risk_tracker.RedisClient") as MockRedis2:
            MockRedis2.return_value = mock_redis

            result = engine.evaluate(buy_signal)
            engine.register_intended_trade(buy_signal, result.lots)

            snapshot = engine.get_account_snapshot()
            assert snapshot["open_risk"]["open_trade_count"] == 1
            assert snapshot["open_risk"]["open_risk_amount"] > 0


def test_close_trade_reduces_open_risk(mock_redis, engine, buy_signal):
    """Test close_trade reduces open risk."""
    with patch("risk.risk_profile.RedisClient") as MockRedis1:
        MockRedis1.return_value = mock_redis
        with patch("risk.open_risk_tracker.RedisClient") as MockRedis2:
            MockRedis2.return_value = mock_redis

            result = engine.evaluate(buy_signal)
            engine.register_intended_trade(buy_signal, result.lots)

            # Verify trade is open
            snapshot1 = engine.get_account_snapshot()
            assert snapshot1["open_risk"]["open_trade_count"] == 1

            # Close trade
            engine.close_trade("test_trade_1")

            # Verify trade is closed
            snapshot2 = engine.get_account_snapshot()
            assert snapshot2["open_risk"]["open_trade_count"] == 0
            assert snapshot2["open_risk"]["open_risk_amount"] == 0.0


def test_split_lifecycle_register_two_entries(mock_redis, engine, buy_signal):
    """Test SPLIT mode registers 2 entries."""
    with patch("risk.risk_profile.RedisClient") as MockRedis1:
        MockRedis1.return_value = mock_redis
        with patch("risk.open_risk_tracker.RedisClient") as MockRedis2:
            MockRedis2.return_value = mock_redis

            # Set SPLIT profile
            profile = RiskProfile(
                risk_per_trade=1.0,
                risk_mode=RiskMode.SPLIT,
                split_ratio=(0.4, 0.6),
            )
            save_risk_profile("test_account", profile)

            result = engine.evaluate(buy_signal)
            engine.register_intended_trade(buy_signal, result.lots)

            snapshot = engine.get_account_snapshot()
            assert snapshot["open_risk"]["open_entry_count"] == 2  # 2 entries
            assert snapshot["open_risk"]["open_trade_count"] == 1  # 1 trade


def test_split_lifecycle_close_both_entries(mock_redis, engine, buy_signal):
    """Test SPLIT mode closes both entries."""
    with patch("risk.risk_profile.RedisClient") as MockRedis1:
        MockRedis1.return_value = mock_redis
        with patch("risk.open_risk_tracker.RedisClient") as MockRedis2:
            MockRedis2.return_value = mock_redis

            # Set SPLIT profile
            profile = RiskProfile(
                risk_per_trade=1.0,
                risk_mode=RiskMode.SPLIT,
                split_ratio=(0.4, 0.6),
            )
            save_risk_profile("test_account", profile)

            result = engine.evaluate(buy_signal)
            engine.register_intended_trade(buy_signal, result.lots)

            # Close both entries
            engine.close_trade("test_trade_1", entry_number=1)
            engine.close_trade("test_trade_1", entry_number=2)

            snapshot = engine.get_account_snapshot()
            assert snapshot["open_risk"]["open_trade_count"] == 0
            assert snapshot["open_risk"]["open_entry_count"] == 0


# ========== Account Snapshot ==========


def test_get_account_snapshot_structure(mock_redis, engine):
    """Test account snapshot contains all required fields."""
    with patch("risk.risk_profile.RedisClient") as MockRedis1:
        MockRedis1.return_value = mock_redis
        with patch("risk.open_risk_tracker.RedisClient") as MockRedis2:
            MockRedis2.return_value = mock_redis

            snapshot = engine.get_account_snapshot()

            assert "account_id" in snapshot
            assert "profile" in snapshot
            assert "risk" in snapshot
            assert "open_risk" in snapshot
            assert "trading_allowed" in snapshot


def test_get_account_snapshot_profile_data(mock_redis, engine):
    """Test account snapshot contains profile data."""
    with patch("risk.risk_profile.RedisClient") as MockRedis1:
        MockRedis1.return_value = mock_redis
        with patch("risk.open_risk_tracker.RedisClient") as MockRedis2:
            MockRedis2.return_value = mock_redis

            profile = RiskProfile(risk_per_trade=2.0, max_open_trades=3)
            save_risk_profile("test_account", profile)

            snapshot = engine.get_account_snapshot()

            assert snapshot["profile"]["risk_per_trade"] == 2.0
            assert snapshot["profile"]["max_open_trades"] == 3


def test_get_account_snapshot_drawdown_info(mock_redis, engine, risk_manager):
    """Test account snapshot contains drawdown info."""
    with patch("risk.risk_profile.RedisClient") as MockRedis1:
        MockRedis1.return_value = mock_redis
        with patch("risk.open_risk_tracker.RedisClient") as MockRedis2:
            MockRedis2.return_value = mock_redis

            # Record a loss
            risk_manager.record_trade_result(
                pnl=-100.0,
                pair="EURUSD",
                current_equity=9900.0,
            )

            snapshot = engine.get_account_snapshot()

            assert "drawdown" in snapshot["risk"]
            assert snapshot["risk"]["drawdown"]["daily_dd_amount"] > 0


def test_get_account_snapshot_trading_allowed_flag(mock_redis, engine):
    """Test account snapshot contains trading_allowed flag."""
    with patch("risk.risk_profile.RedisClient") as MockRedis1:
        MockRedis1.return_value = mock_redis
        with patch("risk.open_risk_tracker.RedisClient") as MockRedis2:
            MockRedis2.return_value = mock_redis

            snapshot = engine.get_account_snapshot()

            assert isinstance(snapshot["trading_allowed"], bool)
            assert snapshot["trading_allowed"] is True  # Should be true initially


# ========== Dataclass Tests ==========


def test_risk_eval_result_dataclass():
    """Test RiskEvalResult dataclass."""
    result = RiskEvalResult(
        verdict=RiskVerdict.ALLOW,
        lots=[{"lot_size": 0.1}],
        risk_amount=50.0,
    )

    assert result.verdict == RiskVerdict.ALLOW
    assert result.allowed
    assert result.lots == [{"lot_size": 0.1}]
    assert result.risk_amount == 50.0


def test_risk_eval_result_deny():
    """Test RiskEvalResult DENY verdict."""
    result = RiskEvalResult(
        verdict=RiskVerdict.DENY,
        deny_code="TEST_DENY",
    )

    assert result.verdict == RiskVerdict.DENY
    assert not result.allowed
    assert result.deny_code == "TEST_DENY"


def test_signal_input_dataclass():
    """Test SignalInput dataclass."""
    signal = SignalInput(
        symbol="EURUSD",
        direction="BUY",
        entry_price=1.0950,
        stop_loss=1.0900,
        take_profit_1=1.1000,
        rr_ratio=1.0,
        trade_id="test_trade",
    )

    assert signal.symbol == "EURUSD"
    assert signal.direction == "BUY"
    assert signal.entry_price == 1.0950
    assert signal.sl_distance_2 is None  # Optional field


# ========== Parametrized Multi-Instrument ==========


@pytest.mark.parametrize(
    "symbol,entry,sl,tp",
    [
        ("EURUSD", 1.0950, 1.0900, 1.1050),
        ("GBPUSD", 1.2500, 1.2450, 1.2600),
        ("USDJPY", 150.00, 149.50, 151.00),
        ("XAUUSD", 2000.0, 1995.0, 2010.0),
        ("AUDUSD", 0.6500, 0.6450, 0.6600),
    ],
)
def test_evaluate_multi_instrument(mock_redis, engine, symbol, entry, sl, tp):
    """Test evaluate works for multiple instruments."""
    with patch("risk.risk_profile.RedisClient") as MockRedis:
        MockRedis.return_value = mock_redis

        signal = SignalInput(
            symbol=symbol,
            direction="BUY",
            entry_price=entry,
            stop_loss=sl,
            take_profit_1=tp,
            rr_ratio=2.0,
            trade_id=f"test_trade_{symbol}",
        )

        result = engine.evaluate(signal)

        assert result.verdict == RiskVerdict.ALLOW
        assert result.lots is not None
        assert len(result.lots) >= 1


# ========== Edge Cases ==========


def test_evaluate_projected_risk_stacking(mock_redis, engine):
    """Test projected risk stacks correctly with multiple trades."""
    with patch("risk.risk_profile.RedisClient") as MockRedis1:
        MockRedis1.return_value = mock_redis
        with patch("risk.open_risk_tracker.RedisClient") as MockRedis2:
            MockRedis2.return_value = mock_redis

            # Set profile allowing 2 trades
            profile = RiskProfile(max_open_trades=2)
            save_risk_profile("test_account", profile)

            # First trade
            signal1 = SignalInput(
                symbol="EURUSD",
                direction="BUY",
                entry_price=1.0950,
                stop_loss=1.0900,
                take_profit_1=1.1050,
                rr_ratio=2.0,
                trade_id="trade_1",
            )
            result1 = engine.evaluate(signal1)
            engine.register_intended_trade(signal1, result1.lots)

            # Second trade
            signal2 = SignalInput(
                symbol="GBPUSD",
                direction="BUY",
                entry_price=1.2500,
                stop_loss=1.2450,
                take_profit_1=1.2600,
                rr_ratio=2.0,
                trade_id="trade_2",
            )
            result2 = engine.evaluate(signal2)

            # Projected risk should be sum of both
            assert result2.open_risk_after > result1.open_risk_after


def test_evaluate_details_contain_profile(mock_redis, engine, buy_signal):
    """Test evaluation result details contain profile."""
    with patch("risk.risk_profile.RedisClient") as MockRedis:
        MockRedis.return_value = mock_redis

        result = engine.evaluate(buy_signal)

        assert result.details is not None
        assert "profile" in result.details
        assert "risk_snapshot" in result.details


def test_evaluate_deny_details_contain_reason(mock_redis, engine, buy_signal, risk_manager):
    """Test DENY result details contain reason."""
    with patch("risk.risk_profile.RedisClient") as MockRedis:
        MockRedis.return_value = mock_redis

        # Trigger circuit breaker
        risk_manager.record_trade_result(
            pnl=-500.0,
            pair="EURUSD",
            current_equity=9500.0,
        )

        result = engine.evaluate(buy_signal)

        assert result.verdict == RiskVerdict.DENY
        assert result.details is not None
        assert "reason" in result.details
