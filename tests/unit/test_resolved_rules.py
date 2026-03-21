"""Unit tests for ResolvedPropRules dataclass.

Validates immutability and required field presence.
"""

from __future__ import annotations

import dataclasses

import pytest

from propfirm_manager.resolved_rules import ResolvedPropRules


def _make_rules(**overrides: object) -> ResolvedPropRules:
    """Build a minimal valid ResolvedPropRules with sensible defaults."""
    defaults: dict[str, object] = {
        "firm_code": "test_firm",
        "firm_name": "Test Firm",
        "plan_code": "plan_100k",
        "plan_display_name": "Plan $100,000",
        "phase": "funded",
        "initial_balance": 100000.0,
        "currency": "USD",
        "max_daily_dd_percent": 5.0,
        "max_total_dd_percent": 10.0,
        "drawdown_mode": "FIXED",
        "profit_target_percent": 10.0,
        "consistency_rule_percent": 0.0,
        "min_trading_days": 0,
        "max_risk_per_trade_percent": 1.0,
        "max_open_trades": 1,
        "min_rr_required": 2.0,
        "news_restriction": False,
        "weekend_holding": True,
        "allow_scaling": False,
        "allow_split_risk": False,
    }
    defaults.update(overrides)
    return ResolvedPropRules(**defaults)  # type: ignore[arg-type]


class TestResolvedPropRulesImmutability:
    """ResolvedPropRules must be frozen (immutable)."""

    def test_is_frozen_dataclass(self):
        rules = _make_rules()
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            rules.max_daily_dd_percent = 99.0  # type: ignore[misc]

    def test_is_dataclass(self):
        rules = _make_rules()
        assert dataclasses.is_dataclass(rules)

    def test_frozen_flag_set(self):
        rules = _make_rules()
        # Verify frozen by attempting mutation through normal attribute access
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            rules.firm_code = "mutated"  # type: ignore[misc]


class TestResolvedPropRulesFields:
    """All required fields must be present and correctly typed."""

    def test_all_fields_present(self):
        rules = _make_rules()
        assert rules.firm_code == "test_firm"
        assert rules.firm_name == "Test Firm"
        assert rules.plan_code == "plan_100k"
        assert rules.plan_display_name == "Plan $100,000"
        assert rules.phase == "funded"
        assert rules.initial_balance == 100000.0
        assert rules.currency == "USD"
        assert rules.max_daily_dd_percent == 5.0
        assert rules.max_total_dd_percent == 10.0
        assert rules.drawdown_mode == "FIXED"
        assert rules.profit_target_percent == 10.0
        assert rules.consistency_rule_percent == 0.0
        assert rules.min_trading_days == 0
        assert rules.max_risk_per_trade_percent == 1.0
        assert rules.max_open_trades == 1
        assert rules.min_rr_required == 2.0
        assert rules.news_restriction is False
        assert rules.weekend_holding is True
        assert rules.allow_scaling is False
        assert rules.allow_split_risk is False

    def test_phase_stored_as_string(self):
        for phase in ("funded", "challenge", "verification"):
            rules = _make_rules(phase=phase)
            assert rules.phase == phase

    def test_drawdown_mode_stored_as_string(self):
        for mode in ("FIXED", "TRAILING", "SEMI_TRAILING"):
            rules = _make_rules(drawdown_mode=mode)
            assert rules.drawdown_mode == mode

    def test_boolean_fields(self):
        rules_with_news = _make_rules(news_restriction=True, weekend_holding=False)
        assert rules_with_news.news_restriction is True
        assert rules_with_news.weekend_holding is False

    def test_equality(self):
        r1 = _make_rules()
        r2 = _make_rules()
        assert r1 == r2

    def test_inequality_on_field_diff(self):
        r1 = _make_rules(max_daily_dd_percent=3.0)
        r2 = _make_rules(max_daily_dd_percent=5.0)
        assert r1 != r2
