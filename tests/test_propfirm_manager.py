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
from propfirm_manager.profiles.aqua_instant_pro.guard import (
    AquaInstantProGuard,
)
from propfirm_manager.profiles.aquafunded.guard import AquafundedGuard
from propfirm_manager.profiles.ftmo.guard import FTMOGuard


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
        assert result.severity == "allow"

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
        assert result.severity == "deny"

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
        assert result.severity == "deny"

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
        assert result.severity == "warn"


class TestAquaInstantProGuard:
    """Test Aqua Instant Pro guard implementation."""

    def test_aqua_allows_safe_trade(self):
        """Aqua allows trade within limits (risk within strategy 0.4% cap)."""
        rules = {
            "max_daily_dd_percent": 5.0,
            "max_total_dd_percent": 10.0,
            "max_risk_per_trade_percent": 0.5,
            "max_open_trades": 1,
        }

        guard = AquaInstantProGuard(rules)

        account_state = {
            "daily_dd_percent": 0.5,
            "total_dd_percent": 1.0,
            "open_trades": 0,
            "balance": 100000,
        }

        # risk_percent 0.35 is within the strategy.yaml cap (0.4%)
        # symbol and session_time_local satisfy strategy hard rules
        trade_risk = {
            "risk_percent": 0.35,
            "daily_dd_after": 1.3,
            "total_dd_after": 1.8,
            "symbol": "EURUSD",
            "session_time_local": "15:00",  # London session
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


class TestAquafundedGuard:
    """Test Aqua Funded guard implementation."""

    _SAFE_ACCOUNT: dict = {
        "daily_dd_percent": 0.5,
        "total_dd_percent": 1.0,
        "open_trades": 0,
        "balance": 100_000,
    }
    _SAFE_TRADE: dict = {
        "risk_percent": 0.8,
        "daily_dd_after": 1.3,
        "total_dd_after": 1.8,
    }

    def test_allows_trade_with_empty_rules(self):
        """Guard allows trade when profile has no numeric risk limits."""
        guard = AquafundedGuard({})
        result = guard.check(self._SAFE_ACCOUNT, self._SAFE_TRADE)
        assert result.allowed is True
        assert result.code == "ALLOW"

    def test_allows_trade_with_none_rules(self):
        """Guard allows trade when rules is None."""
        guard = AquafundedGuard(None)
        result = guard.check(self._SAFE_ACCOUNT, self._SAFE_TRADE)
        assert result.allowed is True

    def test_allows_safe_trade_with_explicit_rules(self):
        """Guard allows trade within explicit numeric limits."""
        rules = {
            "max_daily_dd_percent": 5.0,
            "max_total_dd_percent": 10.0,
            "max_risk_per_trade_percent": 2.0,
            "max_open_trades": 3,
        }
        guard = AquafundedGuard(rules)
        result = guard.check(self._SAFE_ACCOUNT, self._SAFE_TRADE)
        assert result.allowed is True

    def test_denies_when_daily_dd_exceeded(self):
        """Guard denies when explicit daily DD limit is breached."""
        rules = {"max_daily_dd_percent": 5.0, "max_total_dd_percent": 10.0}
        guard = AquafundedGuard(rules)
        trade = {**self._SAFE_TRADE, "daily_dd_after": 5.5}
        result = guard.check(self._SAFE_ACCOUNT, trade)
        assert result.allowed is False
        assert result.code == "DENY_DAILY_DD"

    def test_denies_when_total_dd_exceeded(self):
        """Guard denies when explicit total DD limit is breached."""
        rules = {"max_daily_dd_percent": 5.0, "max_total_dd_percent": 10.0}
        guard = AquafundedGuard(rules)
        trade = {**self._SAFE_TRADE, "total_dd_after": 10.5}
        result = guard.check(self._SAFE_ACCOUNT, trade)
        assert result.allowed is False
        assert result.code == "DENY_TOTAL_DD"

    def test_denies_when_risk_per_trade_exceeded(self):
        """Guard denies when explicit risk-per-trade limit is breached."""
        rules = {"max_risk_per_trade_percent": 1.0}
        guard = AquafundedGuard(rules)
        trade = {**self._SAFE_TRADE, "risk_percent": 1.5}
        result = guard.check(self._SAFE_ACCOUNT, trade)
        assert result.allowed is False
        assert result.code == "DENY_RISK_PER_TRADE"

    def test_no_open_trade_cap_without_limit(self):
        """No open-trade denial when max_open_trades is not configured."""
        guard = AquafundedGuard({})
        account = {**self._SAFE_ACCOUNT, "open_trades": 999}
        result = guard.check(account, self._SAFE_TRADE)
        assert result.allowed is True

    def test_denies_open_trades_when_explicit_cap_set(self):
        """Guard denies when explicit open-trade cap is hit."""
        rules = {"max_open_trades": 1}
        guard = AquafundedGuard(rules)
        account = {**self._SAFE_ACCOUNT, "open_trades": 1}
        result = guard.check(account, self._SAFE_TRADE)
        assert result.allowed is False
        assert result.code == "DENY_MAX_OPEN_TRADES"

    def test_warns_approaching_daily_dd_with_finite_limit(self):
        """Guard warns when explicit DD limit is 80% approached."""
        rules = {"max_daily_dd_percent": 5.0, "max_total_dd_percent": 10.0}
        guard = AquafundedGuard(rules)
        trade = {**self._SAFE_TRADE, "daily_dd_after": 4.2}  # 84% of 5%
        result = guard.check(self._SAFE_ACCOUNT, trade)
        assert result.allowed is True
        assert result.code == "WARN_HIGH_DAILY_DD"

    def test_no_warn_with_permissive_defaults(self):
        """Guard does not warn for large DD values when defaults are used."""
        guard = AquafundedGuard({})
        trade = {**self._SAFE_TRADE, "daily_dd_after": 90.0, "total_dd_after": 95.0}
        result = guard.check(self._SAFE_ACCOUNT, trade)
        assert result.allowed is True
        assert result.code == "ALLOW"

    def test_normalise_extracts_default_rules(self):
        """_normalise extracts v2 default_rules correctly."""
        v2_rules = {
            "default_rules": {"max_daily_dd_percent": 4.0},
            "plans": {},
        }
        guard = AquafundedGuard(v2_rules)
        assert guard.rules == {"max_daily_dd_percent": 4.0}


class TestAquafundedProfileManager:
    """Test Aqua Funded profile loading via PropFirmManager."""

    @pytest.fixture(autouse=True)
    def _clear_aquafunded_cache(self):
        """Ensure each test starts with a fresh aquafunded manager."""
        PropFirmManager._profile_cache.pop("aquafunded", None)
        yield
        PropFirmManager._profile_cache.pop("aquafunded", None)

    def test_load_aquafunded_profile(self):
        """PropFirmManager loads aquafunded profile without error."""
        manager = PropFirmManager("aquafunded")
        assert manager.profile_name == "aquafunded"

    def test_aquafunded_guard_is_aquafunded_guard_type(self):
        """Guard instance is AquafundedGuard."""
        manager = PropFirmManager("aquafunded")
        assert isinstance(manager.guard, AquafundedGuard)

    def test_aquafunded_rules_are_empty_or_dict(self):
        """Rules for aquafunded resolve to a dict (may be empty)."""
        manager = PropFirmManager("aquafunded")
        assert isinstance(manager.rules, dict)

    def test_aquafunded_evaluate_trade_allows_safe_trade(self):
        """evaluate_trade allows a safe trade on the aquafunded profile."""
        manager = PropFirmManager("aquafunded")
        account_state = {
            "daily_dd_percent": 0.5,
            "total_dd_percent": 1.0,
            "open_trades": 0,
            "balance": 100_000,
        }
        trade_risk = {
            "risk_percent": 0.8,
            "daily_dd_after": 1.3,
            "total_dd_after": 1.8,
        }
        result = manager.evaluate_trade(account_state, trade_risk)
        assert result.allowed is True

    def test_for_account_acc003_returns_aquafunded(self):
        """ACC-003 maps to aquafunded in account registry."""
        manager = PropFirmManager.for_account("ACC-003")
        assert manager.profile_name == "aquafunded"
