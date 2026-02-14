"""
Tests for Account Engine

Validates:
- Initial state
- Balance updates
- Trade open/close tracking
- Drawdown calculations
- Risk state transitions
"""

import pytest

from dashboard.backend.account_engine import AccountEngine
from dashboard.backend.schemas import RiskSeverity


class TestAccountEngineInitialization:
    """Test account engine initialization."""

    def test_initial_state_correct(self):
        """Initial state has correct values."""
        engine = AccountEngine.get_or_create(
            account_id="TEST-001",
            balance=100000.0,
            equity=100000.0,
            prop_firm_code="ftmo",
        )

        state = engine.get_state()

        assert state.account_id == "TEST-001"
        assert state.balance == 100000.0
        assert state.equity == 100000.0
        assert state.equity_high == 100000.0
        assert state.daily_dd_percent == 0.0
        assert state.total_dd_percent == 0.0
        assert state.open_trades == 0
        assert state.open_risk_percent == 0.0
        assert state.risk_state == RiskSeverity.SAFE

    def test_get_or_create_returns_same_instance(self):
        """get_or_create returns same instance for same account_id."""
        engine1 = AccountEngine.get_or_create(
            account_id="TEST-002",
            balance=50000.0,
            equity=50000.0,
            prop_firm_code="ftmo",
        )

        engine2 = AccountEngine.get_or_create(
            account_id="TEST-002",
            balance=60000.0,  # Different values
            equity=60000.0,
            prop_firm_code="aqua_instant_pro",
        )

        # Should return same instance (singleton per account_id)
        assert engine1 is engine2


class TestBalanceUpdate:
    """Test balance and equity updates."""

    def test_balance_update(self):
        """Balance update changes values."""
        engine = AccountEngine.get_or_create(
            account_id="TEST-003",
            balance=100000.0,
            equity=100000.0,
            prop_firm_code="ftmo",
        )

        engine.update_balance(105000.0, 105000.0)
        state = engine.get_state()

        assert state.balance == 105000.0
        assert state.equity == 105000.0
        assert state.equity_high == 105000.0

    def test_equity_high_watermark(self):
        """Equity high watermark tracks maximum equity."""
        engine = AccountEngine.get_or_create(
            account_id="TEST-004",
            balance=100000.0,
            equity=100000.0,
            prop_firm_code="ftmo",
        )

        # Increase equity
        engine.update_balance(100000.0, 110000.0)
        assert engine.get_state().equity_high == 110000.0

        # Decrease equity (high watermark should stay)
        engine.update_balance(100000.0, 105000.0)
        assert engine.get_state().equity_high == 110000.0


class TestTradeTracking:
    """Test trade open/close tracking."""

    def test_trade_open_increases_counters(self):
        """Opening trade increases open_trades and open_risk."""
        engine = AccountEngine.get_or_create(
            account_id="TEST-005",
            balance=100000.0,
            equity=100000.0,
            prop_firm_code="ftmo",
        )

        engine.record_trade_open(risk_amount=1000.0)
        state = engine.get_state()

        assert state.open_trades == 1
        assert state.open_risk_percent == 1.0  # 1000/100000 = 1%

    def test_trade_close_with_profit(self):
        """Closing trade with profit updates equity."""
        engine = AccountEngine.get_or_create(
            account_id="TEST-006",
            balance=100000.0,
            equity=100000.0,
            prop_firm_code="ftmo",
        )

        engine.record_trade_open(risk_amount=1000.0)
        engine.record_trade_close(pnl=500.0, risk_amount=1000.0)

        state = engine.get_state()

        assert state.equity == 100500.0
        assert state.equity_high == 100500.0
        assert state.open_trades == 0
        assert state.open_risk_percent == 0.0

    def test_trade_close_with_loss(self):
        """Closing trade with loss updates equity and DD."""
        engine = AccountEngine.get_or_create(
            account_id="TEST-007",
            balance=100000.0,
            equity=100000.0,
            prop_firm_code="ftmo",
        )

        # Set daily starting equity
        engine.reset_daily_dd()

        engine.record_trade_open(risk_amount=1000.0)
        engine.record_trade_close(pnl=-800.0, risk_amount=1000.0)

        state = engine.get_state()

        assert state.equity == 99200.0
        assert state.equity_high == 100000.0
        assert state.daily_dd_percent == pytest.approx(0.8, abs=0.01)
        assert state.total_dd_percent == pytest.approx(0.8, abs=0.01)


class TestDrawdownCalculations:
    """Test drawdown calculation logic."""

    def test_daily_dd_calculation(self):
        """Daily DD calculated from daily starting equity."""
        engine = AccountEngine.get_or_create(
            account_id="TEST-008",
            balance=100000.0,
            equity=100000.0,
            prop_firm_code="ftmo",
        )

        engine.reset_daily_dd()
        engine.update_balance(100000.0, 97000.0)

        state = engine.get_state()

        assert state.daily_dd_percent == pytest.approx(3.0, abs=0.01)

    def test_total_dd_from_equity_high(self):
        """Total DD calculated from equity high watermark."""
        engine = AccountEngine.get_or_create(
            account_id="TEST-009",
            balance=100000.0,
            equity=100000.0,
            prop_firm_code="ftmo",
        )

        # Increase to high
        engine.update_balance(100000.0, 110000.0)

        # Decrease (creates DD)
        engine.update_balance(100000.0, 105000.0)

        state = engine.get_state()

        assert state.equity_high == 110000.0
        assert state.total_dd_percent == pytest.approx(4.545, abs=0.01)

    def test_daily_dd_reset(self):
        """Daily DD reset clears daily tracking."""
        engine = AccountEngine.get_or_create(
            account_id="TEST-010",
            balance=100000.0,
            equity=100000.0,
            prop_firm_code="ftmo",
        )

        engine.reset_daily_dd()
        engine.update_balance(100000.0, 97000.0)

        assert engine.get_state().daily_dd_percent > 0

        # Reset for new day
        engine.reset_daily_dd()

        # DD should now be 0 (starting from current equity)
        assert engine.get_state().daily_dd_percent == 0.0


class TestRiskStateTransitions:
    """Test risk state severity transitions."""

    def test_safe_state_at_low_dd(self):
        """SAFE state when DD is low."""
        engine = AccountEngine.get_or_create(
            account_id="TEST-011",
            balance=100000.0,
            equity=100000.0,
            prop_firm_code="ftmo",
        )

        engine.reset_daily_dd()
        engine.update_balance(100000.0, 99000.0)  # 1% DD

        state = engine.get_state()

        assert state.risk_state == RiskSeverity.SAFE

    def test_warning_state_at_medium_dd(self):
        """WARNING state when DD approaches threshold."""
        engine = AccountEngine.get_or_create(
            account_id="TEST-012",
            balance=100000.0,
            equity=100000.0,
            prop_firm_code="ftmo",
        )

        engine.reset_daily_dd()
        engine.update_balance(100000.0, 96500.0)  # 3.5% DD (>80% of 4%)

        state = engine.get_state()

        assert state.risk_state == RiskSeverity.WARNING

    def test_critical_state_at_high_dd(self):
        """CRITICAL state when DD exceeds threshold."""
        engine = AccountEngine.get_or_create(
            account_id="TEST-013",
            balance=100000.0,
            equity=100000.0,
            prop_firm_code="ftmo",
        )

        engine.reset_daily_dd()
        engine.update_balance(100000.0, 95500.0)  # 4.5% DD (>4% critical)

        state = engine.get_state()

        assert state.risk_state == RiskSeverity.CRITICAL
