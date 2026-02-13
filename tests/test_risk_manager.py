"""
Tests for Risk Management System

Tests all risk components:
- DrawdownMonitor (with mocked Redis)
- CircuitBreaker state transitions
- PositionSizer calculations
- RiskMultiplier adaptive scaling
- RiskManager facade
- Synthesis integration
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from risk.circuit_breaker import CircuitBreaker, CircuitBreakerState
from risk.drawdown import DrawdownMonitor
from risk.exceptions import (
    DrawdownLimitExceeded,
    InvalidPositionSize,
)
from risk.position_sizer import PositionSizer
from risk.risk_manager import RiskManager
from risk.risk_multiplier import RiskMultiplier

# ========== Fixtures ==========


@pytest.fixture
def mock_redis():
    """Mock Redis client."""
    redis_mock = MagicMock()
    redis_mock.get.return_value = None
    redis_mock.set.return_value = True
    return redis_mock


@pytest.fixture
def drawdown_monitor(mock_redis):
    """Create DrawdownMonitor with mocked Redis."""
    with patch("risk.drawdown.RedisClient") as MockRedis:
        MockRedis.return_value = mock_redis
        monitor = DrawdownMonitor(
            initial_balance=10000.0,
            max_daily_percent=0.03,
            max_weekly_percent=0.05,
            max_total_percent=0.10,
        )
        yield monitor


@pytest.fixture
def circuit_breaker(mock_redis):
    """Create CircuitBreaker with mocked Redis."""
    with patch("risk.circuit_breaker.RedisClient") as MockRedis:
        MockRedis.return_value = mock_redis
        breaker = CircuitBreaker(
            initial_balance=10000.0,
            daily_loss_threshold=0.03,
            consecutive_loss_limit=3,
            velocity_threshold=0.02,
            velocity_window_hours=1,
            cooldown_hours=4,
        )
        yield breaker


@pytest.fixture
def position_sizer():
    """Create PositionSizer."""
    return PositionSizer()


@pytest.fixture
def risk_multiplier():
    """Create RiskMultiplier."""
    return RiskMultiplier()


@pytest.fixture
def risk_manager(mock_redis):
    """Create RiskManager with mocked Redis."""
    # Reset singleton before test
    RiskManager.reset_instance()

    with patch("risk.drawdown.RedisClient") as MockRedis:
        MockRedis.return_value = mock_redis
        with patch("risk.circuit_breaker.RedisClient") as MockRedis2:
            MockRedis2.return_value = mock_redis
            manager = RiskManager.get_instance(initial_balance=10000.0)
            yield manager

    # Reset after test
    RiskManager.reset_instance()


# ========== DrawdownMonitor Tests ==========


def test_drawdown_monitor_initialization(drawdown_monitor):
    """Test DrawdownMonitor initializes correctly."""
    assert drawdown_monitor.max_daily_percent == 0.03
    assert drawdown_monitor.max_weekly_percent == 0.05
    assert drawdown_monitor.max_total_percent == 0.10


def test_drawdown_monitor_update_loss(drawdown_monitor):
    """Test DrawdownMonitor tracks losses."""
    # Update with losing trade
    drawdown_monitor.update(current_equity=9900.0, pnl=-100.0)

    snapshot = drawdown_monitor.get_snapshot()
    assert snapshot["daily_dd_amount"] == 100.0
    assert snapshot["weekly_dd_amount"] == 100.0
    assert snapshot["total_dd_amount"] == 100.0


def test_drawdown_monitor_update_profit(drawdown_monitor):
    """Test DrawdownMonitor with winning trade."""
    # Update with winning trade
    drawdown_monitor.update(current_equity=10100.0, pnl=100.0)

    snapshot = drawdown_monitor.get_snapshot()
    # Daily/weekly should not increase on profit
    assert snapshot["daily_dd_amount"] == 0.0
    assert snapshot["weekly_dd_amount"] == 0.0


def test_drawdown_monitor_peak_equity(drawdown_monitor):
    """Test DrawdownMonitor tracks peak equity."""
    # Make profit - should update peak
    drawdown_monitor.update(current_equity=10500.0, pnl=500.0)

    snapshot = drawdown_monitor.get_snapshot()
    assert snapshot["peak_equity"] == 10500.0


def test_drawdown_monitor_breach(drawdown_monitor):
    """Test DrawdownMonitor detects breaches."""
    # Breach daily limit (3% of 10000 = 300)
    drawdown_monitor.update(current_equity=9650.0, pnl=-350.0)

    assert drawdown_monitor.is_breached()

    with pytest.raises(DrawdownLimitExceeded):
        drawdown_monitor.check_and_raise()


def test_drawdown_monitor_redis_persistence(mock_redis):
    """Test DrawdownMonitor persists to Redis."""
    with patch("risk.drawdown.RedisClient") as MockRedis:
        MockRedis.return_value = mock_redis

        monitor = DrawdownMonitor(initial_balance=10000.0)
        monitor.update(current_equity=9900.0, pnl=-100.0)

        # Check Redis set was called
        assert mock_redis.set.called
        # Should persist daily, weekly, total, peak
        assert mock_redis.set.call_count >= 4


# ========== CircuitBreaker Tests ==========


def test_circuit_breaker_initialization(circuit_breaker):
    """Test CircuitBreaker initializes in CLOSED state."""
    assert circuit_breaker.get_state() == "CLOSED"
    assert circuit_breaker.is_trading_allowed()


def test_circuit_breaker_daily_loss_trigger(circuit_breaker):
    """Test CircuitBreaker opens on daily loss threshold."""
    # Record loss exceeding 3% threshold
    circuit_breaker.record_trade(pnl=-350.0, pair="EURUSD", daily_loss=350.0)

    assert circuit_breaker.get_state() == "OPEN"
    assert not circuit_breaker.is_trading_allowed()


def test_circuit_breaker_consecutive_losses(circuit_breaker):
    """Test CircuitBreaker opens on consecutive losses."""
    # Record 3 consecutive losses (threshold = 3)
    for i in range(3):
        daily_loss = (i + 1) * 50.0
        circuit_breaker.record_trade(
            pnl=-50.0,
            pair="EURUSD",
            daily_loss=daily_loss
        )
        circuit_breaker.record_trade(pnl=-50.0, pair="EURUSD", daily_loss=daily_loss)

    assert circuit_breaker.get_state() == "OPEN"
    assert not circuit_breaker.is_trading_allowed()


def test_circuit_breaker_recovery_probe_success(circuit_breaker):
    """Test CircuitBreaker recovers after successful probe."""
    # Force into OPEN state
    circuit_breaker._state = CircuitBreakerState.OPEN
    circuit_breaker._opened_at = datetime.now(UTC) - timedelta(hours=5)

    # Check auto-recovery to HALF_OPEN after cooldown
    assert circuit_breaker.is_trading_allowed()  # Triggers auto-recovery check
    assert circuit_breaker.get_state() == "HALF_OPEN"

    # Successful probe trade
    circuit_breaker.record_trade(pnl=100.0, pair="EURUSD", daily_loss=0.0)

    # Should be CLOSED now
    assert circuit_breaker.get_state() == "CLOSED"


def test_circuit_breaker_recovery_probe_failure(circuit_breaker):
    """Test CircuitBreaker returns to OPEN on failed probe."""
    # Force into HALF_OPEN state
    circuit_breaker._state = CircuitBreakerState.HALF_OPEN

    # Failed probe trade (loss)
    circuit_breaker.record_trade(pnl=-50.0, pair="EURUSD", daily_loss=50.0)

    # Should return to OPEN
    assert circuit_breaker.get_state() == "OPEN"


def test_circuit_breaker_redis_persistence(mock_redis):
    """Test CircuitBreaker persists state to Redis."""
    with patch("risk.circuit_breaker.RedisClient") as MockRedis:
        MockRedis.return_value = mock_redis

        breaker = CircuitBreaker(initial_balance=10000.0)
        breaker.record_trade(pnl=-350.0, pair="EURUSD", daily_loss=350.0)

        # Check Redis set was called
        assert mock_redis.set.called


# ========== PositionSizer Tests ==========


def test_position_sizer_eurusd(position_sizer):
    """Test PositionSizer calculates correctly for EURUSD."""
    result = position_sizer.calculate(
        account_balance=10000.0,
        entry_price=1.1000,
        stop_loss_price=1.0950,
        pair="EURUSD",
        risk_percent=0.01,  # 1%
        risk_multiplier=1.0,
    )

    assert "lot_size" in result
    assert result["lot_size"] > 0
    assert result["risk_amount"] == 100.0  # 1% of 10000
    assert abs(result["pips_at_risk"] - 50.0) < 0.01  # ~50 pips (floating point)


def test_position_sizer_xauusd(position_sizer):
    """Test PositionSizer calculates correctly for XAUUSD."""
    result = position_sizer.calculate(
        account_balance=10000.0,
        entry_price=2000.0,
        stop_loss_price=1990.0,
        pair="XAUUSD",
        risk_percent=0.01,  # 1%
        risk_multiplier=1.0,
    )

    assert "lot_size" in result
    assert result["lot_size"] > 0
    assert result["risk_amount"] == 100.0
    # XAUUSD: 10 pips @ $10/pip = $100 risk


def test_position_sizer_risk_multiplier(position_sizer):
    """Test PositionSizer applies risk multiplier."""
    result_full = position_sizer.calculate(
        account_balance=10000.0,
        entry_price=1.1000,
        stop_loss_price=1.0950,
        pair="EURUSD",
        risk_multiplier=1.0,
    )

    result_half = position_sizer.calculate(
        account_balance=10000.0,
        entry_price=1.1000,
        stop_loss_price=1.0950,
        pair="EURUSD",
        risk_multiplier=0.5,
    )

    # Half multiplier should result in smaller position
    assert result_half["lot_size"] < result_full["lot_size"]
    assert result_half["risk_amount"] < result_full["risk_amount"]


def test_position_sizer_min_lot_clamp(position_sizer):
    """Test PositionSizer clamps to minimum lot size."""
    result = position_sizer.calculate(
        account_balance=100.0,  # Very small balance
        entry_price=1.1000,
        stop_loss_price=1.0950,
        pair="EURUSD",
        risk_multiplier=1.0,
    )

    # Should be clamped to min (0.01)
    assert result["lot_size"] >= position_sizer.min_lot_size


def test_position_sizer_invalid_inputs(position_sizer):
    """Test PositionSizer rejects invalid inputs."""
    with pytest.raises(InvalidPositionSize):
        position_sizer.calculate(
            account_balance=-100.0,  # Invalid
            entry_price=1.1000,
            stop_loss_price=1.0950,
            pair="EURUSD",
        )


# ========== RiskMultiplier Tests ==========


def test_risk_multiplier_low_drawdown(risk_multiplier):
    """Test RiskMultiplier with low drawdown."""
    # Mock now_utc to a deterministic non-Friday time so the
    # friday-afternoon multiplier (0.6) does not interfere.
    _tue_10am = datetime(2026, 2, 10, 10, 0, 0)  # Tuesday 10:00 UTC
    with patch("risk.risk_multiplier.now_utc", return_value=_tue_10am):
        mult = risk_multiplier.calculate(drawdown_level=0.1, session="LONDON")
    assert mult == 1.0


def test_risk_multiplier_high_drawdown(risk_multiplier):
    """Test RiskMultiplier with high drawdown."""
    _tue_10am = datetime(2026, 2, 10, 10, 0, 0)  # Tuesday 10:00 UTC
    with patch("risk.risk_multiplier.now_utc", return_value=_tue_10am):
        mult = risk_multiplier.calculate(drawdown_level=0.9, session="LONDON")
    assert mult == 0.25


def test_risk_multiplier_vix_scaling(risk_multiplier):
    """Test RiskMultiplier with VIX input."""
    mult_low_vix = risk_multiplier.calculate(
        drawdown_level=0.1,
        vix_level=12.0
    )
    mult_high_vix = risk_multiplier.calculate(
        drawdown_level=0.1,
        vix_level=40.0
    )
    mult_low_vix = risk_multiplier.calculate(drawdown_level=0.1, vix_level=12.0)
    mult_high_vix = risk_multiplier.calculate(drawdown_level=0.1, vix_level=40.0)

    # High VIX should reduce multiplier
    assert mult_high_vix < mult_low_vix


def test_risk_multiplier_session_scaling(risk_multiplier):
    """Test RiskMultiplier with session input."""
    mult_london = risk_multiplier.calculate(
        drawdown_level=0.1,
        session="LONDON"
    )
    mult_off = risk_multiplier.calculate(
        drawdown_level=0.1,
        session="OFF_SESSION"
    )
    mult_london = risk_multiplier.calculate(drawdown_level=0.1, session="LONDON")
    mult_off = risk_multiplier.calculate(drawdown_level=0.1, session="OFF_SESSION")

    # Off-session should reduce multiplier
    assert mult_off < mult_london


def test_risk_multiplier_breakdown(risk_multiplier):
    """Test RiskMultiplier breakdown provides details."""
    breakdown = risk_multiplier.get_breakdown(
        drawdown_level=0.5,
        vix_level=20.0,
        session="LONDON",
    )

    assert "overall" in breakdown
    assert "components" in breakdown
    assert "drawdown" in breakdown["components"]
    assert "vix" in breakdown["components"]
    assert "session" in breakdown["components"]


# ========== RiskManager Tests ==========


def test_risk_manager_singleton(risk_manager):
    """Test RiskManager is a singleton."""
    # Get another instance
    instance2 = RiskManager.get_instance()

    # Should be same instance
    assert instance2 is risk_manager


def test_risk_manager_get_risk_snapshot(risk_manager):
    """Test RiskManager provides risk snapshot."""
    snapshot = risk_manager.get_risk_snapshot()

    assert "drawdown" in snapshot
    assert "circuit_breaker" in snapshot
    assert "risk_multiplier" in snapshot
    assert "balance" in snapshot


def test_risk_manager_record_trade(risk_manager):
    """Test RiskManager records trade results."""
    # Record a trade
    risk_manager.record_trade_result(
        pnl=-100.0,
        pair="EURUSD",
        current_equity=9900.0,
    )

    snapshot = risk_manager.get_risk_snapshot()

    # Should have updated drawdown
    assert snapshot["drawdown"]["daily_dd_amount"] == 100.0


def test_risk_manager_calculate_position(risk_manager):
    """Test RiskManager calculates positions."""
    position = risk_manager.calculate_position(
        entry_price=1.1000,
        stop_loss_price=1.0950,
        pair="EURUSD",
    )

    assert "lot_size" in position
    assert "risk_amount" in position
    assert position["lot_size"] > 0


def test_risk_manager_is_trading_allowed(risk_manager):
    """Test RiskManager checks trading allowed."""
    # Initially should be allowed
    assert risk_manager.is_trading_allowed(category="forex")


def test_risk_manager_trading_not_allowed_on_breach(risk_manager):
    """Test RiskManager blocks trading on drawdown breach."""
    # Cause a major loss
    risk_manager.record_trade_result(
        pnl=-1100.0,  # 11% loss, exceeds 10% max total
        pair="EURUSD",
        current_equity=8900.0,
    )

    # Should not allow trading
    assert not risk_manager.is_trading_allowed()


def test_risk_manager_prop_firm_compliance(risk_manager):
    """Test RiskManager checks prop firm compliance."""
    result = risk_manager.check_prop_firm_compliance({
        "risk_percent": 0.01,
        "rr_ratio": 2.5,
    })
    result = risk_manager.check_prop_firm_compliance(
        {
            "risk_percent": 0.01,
            "rr_ratio": 2.5,
        }
    )

    assert "compliant" in result
    assert "violations" in result


# ========== Synthesis Integration Tests ==========
# NOTE: These tests are deprecated. The new WolfConstitutionalPipeline
# has internal risk management that cannot be injected the same way.
# RiskManager integration is tested through the pipeline itself.


def test_synthesis_with_risk_manager():
    """Test synthesis integration with RiskManager (DEPRECATED - pipeline internal now)."""
    pytest.skip("RiskManager integration is now internal to WolfConstitutionalPipeline")


def test_synthesis_without_risk_manager():
    """Test synthesis works without RiskManager (DEPRECATED - pipeline internal now)."""
    pytest.skip("RiskManager integration is now internal to WolfConstitutionalPipeline")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
