"""
Tests for Prop Firm Manager

Validates:
- Profile loading
- Guard evaluation
- Account registry
- FTMO and Aqua rules
"""

import pytest

from propfirm_manager.profile_manager import PropFirmManager
from propfirm_manager.profiles.ftmo.guard import FTMOGuard
from propfirm_manager.profiles.aqua_instant_pro.guard import (
    AquaInstantProGuard,
)
from dashboard.backend.schemas import RiskSeverity


class TestFTMOGuard:
    """Test FTMO guard implementation."""

    def test_ftmo_allows_safe_trade(self):
        """FTMO allows trade within limits."""
        rules = {
            "max_daily_dd_percent": 5.0,
            "max_total_dd_percent": 10.0,
            "max_risk_per_trade_percent": 1.0,
            "max_open_trades": 1,
        }

        guard = FTMOGuard(rules)

        account_state = {
            "daily_dd_percent": 0.5,
            "total_dd_percent": 1.0,
            "open_trades": 0,
            "balance": 100000,
        }

        trade_risk = {
            "risk_percent": 0.8,
            "daily_dd_after": 1.3,
            "total_dd_after": 1.8,
        }

        result = guard.check(account_state, trade_risk)

        assert result.allowed is True
        assert result.code == "ALLOW"
        assert result.severity == RiskSeverity.SAFE

    def test_ftmo_denies_when_daily_dd_exceeded(self):
        """FTMO denies when daily DD limit would be exceeded."""
        rules = {
            "max_daily_dd_percent": 5.0,
            "max_total_dd_percent": 10.0,
            "max_risk_per_trade_percent": 1.0,
            "max_open_trades": 1,
        }

        guard = FTMOGuard(rules)

        account_state = {
            "daily_dd_percent": 3.0,
            "total_dd_percent": 5.0,
            "open_trades": 0,
            "balance": 100000,
        }

        trade_risk = {
            "risk_percent": 1.0,
            "daily_dd_after": 5.5,  # Exceeds 5% limit
            "total_dd_after": 6.0,
        }

        result = guard.check(account_state, trade_risk)

        assert result.allowed is False
        assert "DENY" in result.code
        assert "daily" in result.details.lower()
        assert result.severity == RiskSeverity.CRITICAL

    def test_ftmo_denies_when_max_open_trades_reached(self):
        """FTMO denies when max open trades reached."""
        rules = {
            "max_daily_dd_percent": 5.0,
            "max_total_dd_percent": 10.0,
            "max_risk_per_trade_percent": 1.0,
            "max_open_trades": 1,
        }

        guard = FTMOGuard(rules)

        account_state = {
            "daily_dd_percent": 0.5,
            "total_dd_percent": 1.0,
            "open_trades": 1,  # Already at max
            "balance": 100000,
        }

        trade_risk = {
            "risk_percent": 0.5,
            "daily_dd_after": 1.0,
            "total_dd_after": 1.5,
        }

        result = guard.check(account_state, trade_risk)

        assert result.allowed is False
        assert "OPEN_TRADES" in result.code
        assert result.severity == RiskSeverity.CRITICAL

    def test_ftmo_warns_at_80_percent_threshold(self):
        """FTMO warns when approaching DD limits (80%)."""
        rules = {
            "max_daily_dd_percent": 5.0,
            "max_total_dd_percent": 10.0,
            "max_risk_per_trade_percent": 1.0,
            "max_open_trades": 1,
        }

        guard = FTMOGuard(rules)

        account_state = {
            "daily_dd_percent": 2.0,
            "total_dd_percent": 5.0,
            "open_trades": 0,
            "balance": 100000,
        }

        trade_risk = {
            "risk_percent": 1.0,
            "daily_dd_after": 4.2,  # 84% of 5% limit
            "total_dd_after": 8.5,  # 85% of 10% limit
        }

        result = guard.check(account_state, trade_risk)

        assert result.allowed is True
        assert "WARN" in result.code
        assert result.severity == RiskSeverity.WARNING


class TestAquaInstantProGuard:
    """Test Aqua Instant Pro guard implementation."""

    def test_aqua_allows_safe_trade(self):
        """Aqua allows trade within limits."""
        rules = {
            "max_daily_dd_percent": 5.0,
            "max_total_dd_percent": 10.0,
            "max_risk_per_trade_percent": 1.0,
            "max_open_trades": 1,
        }

        guard = AquaInstantProGuard(rules)

        account_state = {
            "daily_dd_percent": 0.5,
            "total_dd_percent": 1.0,
            "open_trades": 0,
            "balance": 100000,
        }

        trade_risk = {
            "risk_percent": 0.8,
            "daily_dd_after": 1.3,
            "total_dd_after": 1.8,
        }

        result = guard.check(account_state, trade_risk)

        assert result.allowed is True


class TestProfileManager:
    """Test profile manager loading and caching."""

    def test_load_ftmo_profile(self):
        """Load FTMO profile successfully."""
        manager = PropFirmManager("ftmo")

        assert manager.profile_name == "ftmo"
        assert "max_daily_dd_percent" in manager.rules
        assert manager.rules["max_daily_dd_percent"] == 5.0

    def test_load_aqua_profile(self):
        """Load Aqua Instant Pro profile successfully."""
        manager = PropFirmManager("aqua_instant_pro")

        assert manager.profile_name == "aqua_instant_pro"
        assert "max_daily_dd_percent" in manager.rules
        assert manager.features["allow_weekend_holding"] is True

    def test_for_account_factory(self):
        """Factory method creates manager from account registry."""
        manager = PropFirmManager.for_account("ACC-001")

        assert manager.profile_name == "ftmo"

    def test_unknown_profile_raises_error(self):
        """Unknown profile raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            PropFirmManager("unknown_firm")

    def test_unknown_account_raises_error(self):
        """Unknown account ID raises ValueError."""
        with pytest.raises(ValueError):
            PropFirmManager.for_account("ACC-999")

    def test_profile_caching(self):
        """Profiles are cached to avoid repeated loads."""
        manager1 = PropFirmManager("ftmo")
        manager2 = PropFirmManager("ftmo")

        # Should return same cached instance
        assert manager1 is manager2

    def test_evaluate_trade_delegates_to_guard(self):
        """evaluate_trade delegates to guard.check()."""
        manager = PropFirmManager("ftmo")

        account_state = {
            "daily_dd_percent": 0.5,
            "total_dd_percent": 1.0,
            "open_trades": 0,
            "balance": 100000,
        }

        trade_risk = {
            "risk_percent": 0.5,
            "daily_dd_after": 1.0,
            "total_dd_after": 1.5,
        }

        result = manager.evaluate_trade(account_state, trade_risk)

        assert result.allowed is True
