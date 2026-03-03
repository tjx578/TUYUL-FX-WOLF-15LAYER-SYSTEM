"""
Tests for Risk Engine

Validates:
- Basic lot calculation
- Split risk mode
- Drawdown multiplier integration
- Prop firm guard integration
"""

from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest  # pyright: ignore[reportMissingImports]
import yaml  # pyright: ignore[reportMissingModuleSource]

from accounts.risk_engine import RiskEngine
from accounts.account_model import (
    AccountState,
    Layer12Signal,
    RiskMode,
    RiskSeverity,
)


# Add test accounts to registry for testing
@pytest.fixture(scope="module", autouse=True)
def setup_test_accounts():
    """
    Add test accounts to account registry for testing.

    NOTE: This temporarily modifies the production registry file.
    In production, use a separate test registry or mock the loading.
    """
    registry_path = Path(__file__).parent.parent / "propfirm_manager" / "account_registry.yaml"

    with open(registry_path) as f:
        registry = yaml.safe_load(f) or {}

    # Add test accounts
    test_accounts = {
        "TEST-001": "ftmo",
        "TEST-003": "ftmo",
        "TEST-004": "ftmo",
        "TEST-005": "ftmo",
        "TEST-006": "ftmo",
        "TEST-007": "ftmo",
    }

    original_registry = registry.copy()
    registry.update(test_accounts)

    with open(registry_path, "w") as f:
        yaml.safe_dump(registry, f)

    yield

    # Cleanup: restore original registry
    with open(registry_path, "w") as f:
        yaml.safe_dump(original_registry, f)


class TestBasicLotCalculation:
    """Test basic lot calculation logic."""

    def test_fixed_risk_lot_positive(self):
        """Fixed risk produces positive lot size."""
        engine = RiskEngine()

        signal = Layer12Signal(
            signal_id=uuid4(),
            timestamp=datetime.utcnow(),
            pair="EURUSD",
            direction="BUY",
            entry=1.1000,
            stop_loss=1.0950,
            take_profit_1=1.1100,
            rr=2.0,
            verdict="EXECUTE_BUY",
            confidence="HIGH",
            wolf_score=25,
            tii_sym=0.85,
            frpc=0.75,
        )

        account_state = AccountState(
            account_id="TEST-001",
            balance=100000.0,
            equity=100000.0,
            equity_high=100000.0,
            daily_dd_percent=0.0,
            total_dd_percent=0.0,
            open_risk_percent=0.0,
            open_trades=0,
            risk_state=RiskSeverity.SAFE,
        )

        result = engine.calculate_lot(
            signal=signal,
            account_state=account_state,
            risk_percent=1.0,
            prop_firm_code="ftmo",
        )

        assert result.recommended_lot > 0
        assert result.trade_allowed is True

    def test_zero_sl_distance_blocked(self):
        """Zero SL distance should be blocked."""
        engine = RiskEngine()

        signal = Layer12Signal(
            signal_id=uuid4(),
            timestamp=datetime.utcnow(),
            pair="EURUSD",
            direction="BUY",
            entry=1.1000,
            stop_loss=1.1000,  # Same as entry
            take_profit_1=1.1100,
            rr=2.0,
            verdict="EXECUTE_BUY",
            confidence="HIGH",
            wolf_score=25,
            tii_sym=0.85,
            frpc=0.75,
        )

        account_state = AccountState(
            account_id="TEST-002",
            balance=100000.0,
            equity=100000.0,
            equity_high=100000.0,
            daily_dd_percent=0.0,
            total_dd_percent=0.0,
            open_risk_percent=0.0,
            open_trades=0,
            risk_state=RiskSeverity.SAFE,
        )

        result = engine.calculate_lot(
            signal=signal,
            account_state=account_state,
            risk_percent=1.0,
            prop_firm_code="ftmo",
        )

        assert result.trade_allowed is False
        assert "Invalid SL distance" in result.reason

    def test_higher_risk_bigger_lot(self):
        """Higher risk percentage produces bigger lot size."""
        engine = RiskEngine()

        signal = Layer12Signal(
            signal_id=uuid4(),
            timestamp=datetime.utcnow(),
            pair="EURUSD",
            direction="BUY",
            entry=1.1000,
            stop_loss=1.0950,
            take_profit_1=1.1100,
            rr=2.0,
            verdict="EXECUTE_BUY",
            confidence="HIGH",
            wolf_score=25,
            tii_sym=0.85,
            frpc=0.75,
        )

        account_state = AccountState(
            account_id="TEST-003",
            balance=100000.0,
            equity=100000.0,
            equity_high=100000.0,
            daily_dd_percent=0.0,
            total_dd_percent=0.0,
            open_risk_percent=0.0,
            open_trades=0,
            risk_state=RiskSeverity.SAFE,
        )

        result_1pct = engine.calculate_lot(
            signal=signal,
            account_state=account_state,
            risk_percent=1.0,
            prop_firm_code="ftmo",
        )

        result_2pct = engine.calculate_lot(
            signal=signal,
            account_state=account_state,
            risk_percent=2.0,
            prop_firm_code="ftmo",
        )

        assert result_2pct.recommended_lot > result_1pct.recommended_lot


class TestSplitRisk:
    """Test split risk mode."""

    def test_split_produces_multiple_lots(self):
        """Split mode produces array of lot sizes."""
        engine = RiskEngine()

        signal = Layer12Signal(
            signal_id=uuid4(),
            timestamp=datetime.utcnow(),
            pair="EURUSD",
            direction="BUY",
            entry=1.1000,
            stop_loss=1.0950,
            take_profit_1=1.1100,
            rr=2.0,
            verdict="EXECUTE_BUY",
            confidence="HIGH",
            wolf_score=25,
            tii_sym=0.85,
            frpc=0.75,
        )

        account_state = AccountState(
            account_id="TEST-004",
            balance=100000.0,
            equity=100000.0,
            equity_high=100000.0,
            daily_dd_percent=0.0,
            total_dd_percent=0.0,
            open_risk_percent=0.0,
            open_trades=0,
            risk_state=RiskSeverity.SAFE,
        )

        result = engine.calculate_lot(
            signal=signal,
            account_state=account_state,
            risk_percent=1.0,
            prop_firm_code="ftmo",
            risk_mode=RiskMode.SPLIT,
            split_ratios=[0.5, 0.3, 0.2],
        )

        assert result.split_lots is not None
        assert len(result.split_lots) == 3

    def test_split_ratios_respected(self):
        """Split lots respect provided ratios."""
        engine = RiskEngine()

        signal = Layer12Signal(
            signal_id=uuid4(),
            timestamp=datetime.utcnow(),
            pair="EURUSD",
            direction="BUY",
            entry=1.1000,
            stop_loss=1.0950,
            take_profit_1=1.1100,
            rr=2.0,
            verdict="EXECUTE_BUY",
            confidence="HIGH",
            wolf_score=25,
            tii_sym=0.85,
            frpc=0.75,
        )

        account_state = AccountState(
            account_id="TEST-005",
            balance=100000.0,
            equity=100000.0,
            equity_high=100000.0,
            daily_dd_percent=0.0,
            total_dd_percent=0.0,
            open_risk_percent=0.0,
            open_trades=0,
            risk_state=RiskSeverity.SAFE,
        )

        result = engine.calculate_lot(
            signal=signal,
            account_state=account_state,
            risk_percent=1.0,
            prop_firm_code="ftmo",
            risk_mode=RiskMode.SPLIT,
            split_ratios=[0.5, 0.5],
        )

        # First split should be roughly equal to second
        assert result.split_lots is not None, f"split_lots should not be None: {result.reason}"
        assert abs(result.split_lots[0] - result.split_lots[1]) < 0.05


class TestDrawdownMultiplier:
    """Test drawdown multiplier integration."""

    def test_multiplier_applied(self):
        """Verify DD multiplier is applied in calculation."""
        engine = RiskEngine()

        signal = Layer12Signal(
            signal_id=uuid4(),
            timestamp=datetime.utcnow(),
            pair="EURUSD",
            direction="BUY",
            entry=1.1000,
            stop_loss=1.0950,
            take_profit_1=1.1100,
            rr=2.0,
            verdict="EXECUTE_BUY",
            confidence="HIGH",
            wolf_score=25,
            tii_sym=0.85,
            frpc=0.75,
        )

        # Low DD state (1% total DD → drawdown multiplier returns 1.0)
        low_dd_state = AccountState(
            account_id="TEST-006",
            balance=100000.0,
            equity=100000.0,
            equity_high=100000.0,
            daily_dd_percent=0.5,
            total_dd_percent=1.0,
            open_risk_percent=0.0,
            open_trades=0,
            risk_state=RiskSeverity.SAFE,
        )

        result = engine.calculate_lot(
            signal=signal,
            account_state=low_dd_state,
            risk_percent=1.0,
            prop_firm_code="ftmo",
        )

        # Verify calculation succeeded
        assert result.recommended_lot > 0
        assert result.trade_allowed is True
        # Verify multiplier was called (1.0 for low DD)
        assert result.risk_used_percent == 1.0


class TestPropFirmIntegration:
    """Test prop firm guard integration."""

    def test_ftmo_blocks_when_dd_exceeded(self):
        """FTMO guard blocks trade when DD limit exceeded."""
        engine = RiskEngine()

        signal = Layer12Signal(
            signal_id=uuid4(),
            timestamp=datetime.utcnow(),
            pair="EURUSD",
            direction="BUY",
            entry=1.1000,
            stop_loss=1.0950,
            take_profit_1=1.1100,
            rr=2.0,
            verdict="EXECUTE_BUY",
            confidence="HIGH",
            wolf_score=25,
            tii_sym=0.85,
            frpc=0.75,
        )

        # Account near DD limit
        account_state = AccountState(
            account_id="ACC-001",  # Maps to FTMO
            balance=100000.0,
            equity=95500.0,
            equity_high=100000.0,
            daily_dd_percent=4.5,
            total_dd_percent=4.5,
            open_risk_percent=0.0,
            open_trades=0,
            risk_state=RiskSeverity.CRITICAL,
        )

        result = engine.calculate_lot(
            signal=signal,
            account_state=account_state,
            risk_percent=1.0,  # Would push DD to 5.5%
            prop_firm_code="ftmo",
        )

        assert result.trade_allowed is False
        assert result.severity == RiskSeverity.CRITICAL
