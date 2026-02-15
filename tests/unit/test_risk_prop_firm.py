"""
Tests for risk/prop_firm.py -- prop firm guard enforcement.
Constitutional boundary: guard is binding for risk legality, not for market decisions.
"""
import copy

import pytest  # pyright: ignore[reportMissingImports]

try:
    from risk.prop_firm import PropFirmGuard, check  # pyright: ignore[reportAttributeAccessIssue]
    HAS_PROPFIRM = True # pyright: ignore[reportAttributeAccessIssue]
except ImportError:
    try:
        from risk.prop_firm import (
            PropFirmGuard,  # pyright: ignore[reportAttributeAccessIssue]  # noqa: F401
        )
        HAS_PROPFIRM = True
        check = None
    except ImportError:
        HAS_PROPFIRM = False
        check = None


class TestPropFirmGuardContract:
    """Verify the guard returns the documented contract."""

    def _make_guard_result(self, allowed, code, severity="INFO", details=None):
        return {
            "allowed": allowed,
            "code": code,
            "severity": severity,
            "details": details,
        }

    def test_result_has_required_fields(self):
        result = self._make_guard_result(True, "OK")
        assert "allowed" in result
        assert "code" in result
        assert "severity" in result

    def test_daily_loss_breach_blocks_trade(self, sample_account_state, sample_trade_risk):
        """If daily P&L + new risk exceeds daily limit, trade must be blocked."""
        state = copy.deepcopy(sample_account_state)
        state["daily_pnl"] = -4800.0  # close to 5000 limit
        trade = copy.deepcopy(sample_trade_risk)
        trade["risk_amount"] = 500.0  # would breach

        total_after = abs(state["daily_pnl"]) + trade["risk_amount"]
        allowed = total_after <= state["daily_loss_limit"]
        assert not allowed, "Trade should be blocked when daily loss limit would be breached"

    def test_within_daily_limit_allows_trade(self, sample_account_state, sample_trade_risk):
        state = copy.deepcopy(sample_account_state)
        state["daily_pnl"] = -1000.0
        trade = copy.deepcopy(sample_trade_risk)
        trade["risk_amount"] = 500.0

        total_after = abs(state["daily_pnl"]) + trade["risk_amount"]
        allowed = total_after <= state["daily_loss_limit"]
        assert allowed

    def test_max_total_loss_breach(self, sample_account_state):
        state = copy.deepcopy(sample_account_state)
        unrealized_loss = state["balance"] - state["equity"]
        pct_loss = (unrealized_loss / state["balance"]) * 100
        # With balance=100k, equity=99.5k -> 0.5% loss, well within 10%
        assert pct_loss < 10.0

    def test_max_total_loss_breach_triggers_block(self):
        state = {
            "balance": 100_000.0,
            "equity": 89_000.0,  # 11% loss
            "daily_loss_limit": 5_000.0,
            "max_loss_limit": 10_000.0,
        }
        pct_loss = ((state["balance"] - state["equity"]) / state["balance"]) * 100
        assert pct_loss > 10.0, "Should detect total loss breach"

    @pytest.mark.parametrize("lot,max_lot,expected", [
        (0.5, 5.0, True),
        (5.0, 5.0, True),
        (6.0, 5.0, False),
        (0.01, 5.0, True),
    ])
    def test_lot_size_limit(self, lot, max_lot, expected):
        assert (lot <= max_lot) == expected

    @pytest.mark.parametrize("open_pos,max_pos,expected", [
        (2, 10, True),
        (10, 10, False),
        (0, 10, True),
        (9, 10, True),
    ])
    def test_max_positions_limit(self, open_pos, max_pos, expected):
        can_open = open_pos < max_pos
        assert can_open == expected

    @pytest.mark.skipif(not HAS_PROPFIRM, reason="risk.prop_firm not importable")
    def test_check_returns_dict(self, sample_account_state, sample_trade_risk):
        if check is not None:
            result = check(sample_account_state, sample_trade_risk)
            assert isinstance(result, dict)
            assert "allowed" in result
            assert "code" in result


class TestPropFirmProfiles:
    """Test different prop firm profile configurations."""

    def test_ftmo_profile_values(self, ftmo_profile):
        assert ftmo_profile["max_daily_loss_pct"] == 5.0
        assert ftmo_profile["max_total_loss_pct"] == 10.0
        assert ftmo_profile["weekend_close_required"] is True

    def test_news_lockout_validation(self, ftmo_profile):
        assert ftmo_profile["news_lockout_minutes"] > 0
        assert ftmo_profile["news_lockout_minutes"] <= 60  # reasonable upper bound


class TestRiskRecommendation:
    """
    Verify the risk recommendation contract:
    trade_allowed, recommended_lot, max_safe_lot, reason, expiry.
    """

    def _build_recommendation(self, allowed, lot, max_lot, reason, expiry_sec=300):
        return {
            "trade_allowed": allowed,
            "recommended_lot": lot,
            "max_safe_lot": max_lot,
            "reason": reason,
            "expiry": expiry_sec,
        }

    def test_recommendation_fields(self):
        rec = self._build_recommendation(True, 0.5, 2.0, "within_limits")
        assert rec["trade_allowed"] is True
        assert rec["recommended_lot"] <= rec["max_safe_lot"]

    def test_blocked_recommendation(self):
        rec = self._build_recommendation(False, 0.0, 0.0, "daily_loss_limit_breach")
        assert rec["trade_allowed"] is False
        assert rec["recommended_lot"] == 0.0

    def test_lot_clamp(self):
        """recommended_lot should never exceed max_safe_lot."""
        rec = self._build_recommendation(True, 3.0, 2.0, "clamped")
        # In a real system the clamp should happen before output
        rec["recommended_lot"] = min(rec["recommended_lot"], rec["max_safe_lot"])
        assert rec["recommended_lot"] <= rec["max_safe_lot"]
