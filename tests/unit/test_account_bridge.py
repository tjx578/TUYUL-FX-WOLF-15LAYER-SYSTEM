"""Unit tests for populate_account_risk_state bridge function.

Validates that resolved prop firm rules are correctly mapped to
AccountRiskState fields.
"""

from __future__ import annotations

import pytest

from accounts.account_repository import AccountRiskState
from propfirm_manager.account_bridge import populate_account_risk_state
from propfirm_manager.resolved_rules import ResolvedPropRules


def _make_rules(**overrides: object) -> ResolvedPropRules:
    """Build a minimal valid ResolvedPropRules for bridge tests."""
    defaults: dict[str, object] = {
        "firm_code": "aqua_instant_pro",
        "firm_name": "Aqua Instant Pro",
        "plan_code": "pro_100k",
        "plan_display_name": "Pro $100,000",
        "phase": "funded",
        "initial_balance": 100_000.0,
        "currency": "USD",
        "max_daily_dd_percent": 3.0,
        "max_total_dd_percent": 6.0,
        "drawdown_mode": "TRAILING",
        "profit_target_percent": 10.0,
        "consistency_rule_percent": 15.0,
        "min_trading_days": 3,
        "max_risk_per_trade_percent": 0.5,
        "max_open_trades": 1,
        "min_rr_required": 2.0,
        "news_restriction": False,
        "weekend_holding": True,
        "allow_scaling": True,
        "allow_split_risk": True,
    }
    defaults.update(overrides)
    return ResolvedPropRules(**defaults)  # type: ignore[arg-type]


class TestPopulateAccountRiskState:
    """Core field mapping validation."""

    def test_returns_account_risk_state(self):
        rules = _make_rules()
        result = populate_account_risk_state(
            resolved_rules=rules,
            account_id="ACC-001",
            balance=100_000.0,
            equity=99_500.0,
        )
        assert isinstance(result, AccountRiskState)

    def test_account_id_mapped(self):
        rules = _make_rules()
        result = populate_account_risk_state(rules, "ACC-XYZ", 100_000.0, 100_000.0)
        assert result.account_id == "ACC-XYZ"

    def test_firm_code_mapped(self):
        rules = _make_rules(firm_code="ftmo")
        result = populate_account_risk_state(rules, "ACC-001", 100_000.0, 100_000.0)
        assert result.prop_firm_code == "ftmo"

    def test_balance_and_equity_mapped(self):
        rules = _make_rules()
        result = populate_account_risk_state(rules, "ACC-001", 95_000.0, 94_500.0)
        assert result.balance == pytest.approx(95_000.0)
        assert result.equity == pytest.approx(94_500.0)

    def test_max_daily_loss_percent_mapped(self):
        rules = _make_rules(max_daily_dd_percent=3.0)
        result = populate_account_risk_state(rules, "ACC-001", 100_000.0, 100_000.0)
        assert result.max_daily_loss_percent == pytest.approx(3.0)

    def test_max_total_loss_percent_mapped(self):
        rules = _make_rules(max_total_dd_percent=6.0)
        result = populate_account_risk_state(rules, "ACC-001", 100_000.0, 100_000.0)
        assert result.max_total_loss_percent == pytest.approx(6.0)

    def test_consistency_limit_mapped(self):
        rules = _make_rules(consistency_rule_percent=15.0)
        result = populate_account_risk_state(rules, "ACC-001", 100_000.0, 100_000.0)
        assert result.consistency_limit_percent == pytest.approx(15.0)

    def test_phase_mode_mapped_and_uppercased(self):
        rules = _make_rules(phase="funded")
        result = populate_account_risk_state(rules, "ACC-001", 100_000.0, 100_000.0)
        assert result.phase_mode == "FUNDED"

    def test_phase_challenge_uppercased(self):
        rules = _make_rules(phase="challenge")
        result = populate_account_risk_state(rules, "ACC-001", 100_000.0, 100_000.0)
        assert result.phase_mode == "CHALLENGE"

    def test_max_concurrent_trades_mapped(self):
        rules = _make_rules(max_open_trades=5)
        result = populate_account_risk_state(rules, "ACC-001", 100_000.0, 100_000.0)
        assert result.max_concurrent_trades == 5

    def test_news_lock_mapped_from_news_restriction(self):
        rules_no_news = _make_rules(news_restriction=False)
        rules_news = _make_rules(news_restriction=True)
        assert populate_account_risk_state(rules_no_news, "A", 1.0, 1.0).news_lock is False
        assert populate_account_risk_state(rules_news, "A", 1.0, 1.0).news_lock is True


class TestBaseRiskCapping:
    """base_risk_percent must be capped at max_risk_per_trade_percent."""

    def test_base_risk_capped_at_max(self):
        rules = _make_rules(max_risk_per_trade_percent=0.5)
        result = populate_account_risk_state(rules, "ACC-001", 100_000.0, 100_000.0, base_risk_percent=2.0)
        assert result.base_risk_percent == pytest.approx(0.5)

    def test_base_risk_not_capped_when_below_max(self):
        rules = _make_rules(max_risk_per_trade_percent=1.0)
        result = populate_account_risk_state(rules, "ACC-001", 100_000.0, 100_000.0, base_risk_percent=0.5)
        assert result.base_risk_percent == pytest.approx(0.5)

    def test_base_risk_equal_to_max_passes_through(self):
        rules = _make_rules(max_risk_per_trade_percent=1.0)
        result = populate_account_risk_state(rules, "ACC-001", 100_000.0, 100_000.0, base_risk_percent=1.0)
        assert result.base_risk_percent == pytest.approx(1.0)


class TestOptionalFields:
    """Optional keyword arguments are correctly forwarded."""

    def test_daily_loss_used_passed_through(self):
        rules = _make_rules()
        result = populate_account_risk_state(rules, "ACC-001", 100_000.0, 100_000.0, daily_loss_used_percent=1.5)
        assert result.daily_loss_used_percent == pytest.approx(1.5)

    def test_total_loss_used_passed_through(self):
        rules = _make_rules()
        result = populate_account_risk_state(rules, "ACC-001", 100_000.0, 100_000.0, total_loss_used_percent=3.0)
        assert result.total_loss_used_percent == pytest.approx(3.0)

    def test_open_trades_count_passed_through(self):
        rules = _make_rules()
        result = populate_account_risk_state(rules, "ACC-001", 100_000.0, 100_000.0, open_trades_count=1)
        assert result.open_trades_count == 1

    def test_account_locked_flag(self):
        rules = _make_rules()
        result = populate_account_risk_state(rules, "ACC-001", 100_000.0, 100_000.0, account_locked=True)
        assert result.account_locked is True

    def test_circuit_breaker_flag(self):
        rules = _make_rules()
        result = populate_account_risk_state(rules, "ACC-001", 100_000.0, 100_000.0, circuit_breaker_open=True)
        assert result.circuit_breaker_open is True


class TestDifferentFirmsAndPhases:
    """Bridge works correctly across different firms and phases."""

    def test_ftmo_challenge_phase_mapped(self):
        rules = _make_rules(
            firm_code="ftmo",
            phase="challenge",
            max_daily_dd_percent=5.0,
            max_total_dd_percent=10.0,
            consistency_rule_percent=0.0,
            news_restriction=True,
            max_open_trades=10,
        )
        result = populate_account_risk_state(rules, "MT5-12345", 100_000.0, 100_000.0)
        assert result.prop_firm_code == "ftmo"
        assert result.phase_mode == "CHALLENGE"
        assert result.max_daily_loss_percent == pytest.approx(5.0)
        assert result.news_lock is True
        assert result.max_concurrent_trades == 10

    def test_result_is_immutable(self):
        """AccountRiskState is frozen; mutation must raise."""
        import dataclasses

        rules = _make_rules()
        result = populate_account_risk_state(rules, "ACC-001", 100_000.0, 100_000.0)
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            result.balance = 99999.0  # type: ignore[misc]
