"""Unit tests for PropFirmRuleResolver.

Validates rule resolution, plan/phase merging, fallback behaviour, error
handling, enumeration helpers, and instance-level caching.
"""

from __future__ import annotations

import pytest

from propfirm_manager.resolved_rules import ResolvedPropRules
from propfirm_manager.rule_resolver import PropFirmRuleResolver


@pytest.fixture()
def resolver() -> PropFirmRuleResolver:
    """Fresh resolver per test (no shared cache)."""
    return PropFirmRuleResolver()


# ---------------------------------------------------------------------------
# Aqua Instant Pro — funded plan resolution
# ---------------------------------------------------------------------------


class TestAquaInstantProResolution:
    def test_pro_100k_funded_returns_resolved_rules(self, resolver: PropFirmRuleResolver):
        rules = resolver.resolve("aqua_instant_pro", "pro_100k", "funded")
        assert isinstance(rules, ResolvedPropRules)

    def test_pro_100k_funded_correct_dd_limits(self, resolver: PropFirmRuleResolver):
        rules = resolver.resolve("aqua_instant_pro", "pro_100k", "funded")
        # Phase-specific funded rules override defaults
        assert rules.max_daily_dd_percent == pytest.approx(3.0)
        assert rules.max_total_dd_percent == pytest.approx(6.0)

    def test_pro_100k_funded_trailing_mode(self, resolver: PropFirmRuleResolver):
        rules = resolver.resolve("aqua_instant_pro", "pro_100k", "funded")
        assert rules.drawdown_mode == "TRAILING"

    def test_pro_100k_funded_consistency_rule(self, resolver: PropFirmRuleResolver):
        rules = resolver.resolve("aqua_instant_pro", "pro_100k", "funded")
        assert rules.consistency_rule_percent == pytest.approx(15.0)

    def test_pro_100k_funded_min_trading_days(self, resolver: PropFirmRuleResolver):
        rules = resolver.resolve("aqua_instant_pro", "pro_100k", "funded")
        assert rules.min_trading_days == 3

    def test_pro_100k_funded_risk_per_trade(self, resolver: PropFirmRuleResolver):
        rules = resolver.resolve("aqua_instant_pro", "pro_100k", "funded")
        assert rules.max_risk_per_trade_percent == pytest.approx(0.5)

    def test_pro_100k_funded_initial_balance(self, resolver: PropFirmRuleResolver):
        rules = resolver.resolve("aqua_instant_pro", "pro_100k", "funded")
        assert rules.initial_balance == pytest.approx(100_000.0)

    def test_pro_100k_funded_weekend_holding_allowed(self, resolver: PropFirmRuleResolver):
        rules = resolver.resolve("aqua_instant_pro", "pro_100k", "funded")
        assert rules.weekend_holding is True

    def test_pro_100k_funded_news_restriction_false(self, resolver: PropFirmRuleResolver):
        rules = resolver.resolve("aqua_instant_pro", "pro_100k", "funded")
        assert rules.news_restriction is False

    def test_pro_50k_matches_pro_100k_rules(self, resolver: PropFirmRuleResolver):
        """Pro 50k and 100k funded rules are identical per spec."""
        rules_100k = resolver.resolve("aqua_instant_pro", "pro_100k", "funded")
        rules_50k = resolver.resolve("aqua_instant_pro", "pro_50k", "funded")
        assert rules_100k.max_daily_dd_percent == rules_50k.max_daily_dd_percent
        assert rules_100k.max_total_dd_percent == rules_50k.max_total_dd_percent


# ---------------------------------------------------------------------------
# FTMO — multi-phase resolution
# ---------------------------------------------------------------------------


class TestFTMOResolution:
    def test_challenge_100k_challenge_phase(self, resolver: PropFirmRuleResolver):
        rules = resolver.resolve("ftmo", "challenge_100k", "challenge")
        assert isinstance(rules, ResolvedPropRules)
        assert rules.max_daily_dd_percent == pytest.approx(5.0)
        assert rules.profit_target_percent == pytest.approx(10.0)
        assert rules.min_trading_days == 4

    def test_challenge_100k_verification_phase(self, resolver: PropFirmRuleResolver):
        rules = resolver.resolve("ftmo", "challenge_100k", "verification")
        # Verification has lower profit target than challenge
        assert rules.profit_target_percent == pytest.approx(5.0)
        assert rules.min_trading_days == 4

    def test_challenge_100k_funded_phase(self, resolver: PropFirmRuleResolver):
        rules = resolver.resolve("ftmo", "challenge_100k", "funded")
        # Funded has no profit target requirement
        assert rules.profit_target_percent == pytest.approx(0.0)
        assert rules.min_trading_days == 0

    def test_challenge_vs_funded_different_profit_target(self, resolver: PropFirmRuleResolver):
        challenge = resolver.resolve("ftmo", "challenge_100k", "challenge")
        funded = resolver.resolve("ftmo", "challenge_100k", "funded")
        assert challenge.profit_target_percent != funded.profit_target_percent

    def test_ftmo_news_restriction_true(self, resolver: PropFirmRuleResolver):
        rules = resolver.resolve("ftmo", "challenge_100k", "funded")
        assert rules.news_restriction is True

    def test_ftmo_weekend_holding_false(self, resolver: PropFirmRuleResolver):
        rules = resolver.resolve("ftmo", "challenge_100k", "funded")
        assert rules.weekend_holding is False

    def test_ftmo_drawdown_mode_fixed(self, resolver: PropFirmRuleResolver):
        rules = resolver.resolve("ftmo", "challenge_100k", "funded")
        assert rules.drawdown_mode == "FIXED"

    def test_ftmo_allow_scaling_false(self, resolver: PropFirmRuleResolver):
        rules = resolver.resolve("ftmo", "challenge_100k", "funded")
        assert rules.allow_scaling is False

    def test_ftmo_allow_split_risk_false(self, resolver: PropFirmRuleResolver):
        rules = resolver.resolve("ftmo", "challenge_100k", "funded")
        assert rules.allow_split_risk is False


# ---------------------------------------------------------------------------
# Fallback to default_rules
# ---------------------------------------------------------------------------


class TestDefaultRulesFallback:
    def test_unknown_plan_falls_back_to_defaults(self, resolver: PropFirmRuleResolver):
        """When plan_code is not in the YAML, default_rules govern."""
        rules = resolver.resolve("aqua_instant_pro", "unknown_plan", "funded")
        # Default daily DD for aqua is 5.0
        assert rules.max_daily_dd_percent == pytest.approx(5.0)

    def test_unknown_phase_falls_back_to_defaults(self, resolver: PropFirmRuleResolver):
        """When phase is not in the plan, default_rules govern."""
        rules = resolver.resolve("aqua_instant_pro", "pro_100k", "unknown_phase")
        # Default daily DD for aqua is 5.0
        assert rules.max_daily_dd_percent == pytest.approx(5.0)

    def test_unknown_plan_and_phase_falls_back_to_defaults(self, resolver: PropFirmRuleResolver):
        rules = resolver.resolve("ftmo", "unknown_plan", "unknown_phase")
        assert rules.max_daily_dd_percent == pytest.approx(5.0)
        assert rules.max_total_dd_percent == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestResolverErrors:
    def test_missing_firm_raises_file_not_found(self, resolver: PropFirmRuleResolver):
        with pytest.raises(FileNotFoundError, match="not found"):
            resolver.resolve("non_existent_firm", "plan", "funded")

    def test_empty_firm_code_raises_value_error(self, resolver: PropFirmRuleResolver):
        with pytest.raises(ValueError, match="firm_code"):
            resolver.resolve("", "plan", "funded")

    def test_whitespace_firm_code_raises_value_error(self, resolver: PropFirmRuleResolver):
        with pytest.raises(ValueError, match="firm_code"):
            resolver.resolve("   ", "plan", "funded")


# ---------------------------------------------------------------------------
# Enumeration helpers
# ---------------------------------------------------------------------------


class TestEnumerationHelpers:
    def test_list_firms_returns_known_firms(self, resolver: PropFirmRuleResolver):
        firms = resolver.list_firms()
        assert "aqua_instant_pro" in firms
        assert "ftmo" in firms

    def test_list_firms_returns_sorted_list(self, resolver: PropFirmRuleResolver):
        firms = resolver.list_firms()
        assert firms == sorted(firms)

    def test_list_plans_aqua(self, resolver: PropFirmRuleResolver):
        plans = resolver.list_plans("aqua_instant_pro")
        assert "pro_100k" in plans
        assert "pro_50k" in plans
        assert "pro_25k" in plans

    def test_list_plans_ftmo(self, resolver: PropFirmRuleResolver):
        plans = resolver.list_plans("ftmo")
        assert "challenge_100k" in plans

    def test_list_plans_unknown_firm_raises(self, resolver: PropFirmRuleResolver):
        with pytest.raises(FileNotFoundError):
            resolver.list_plans("unknown_firm")

    def test_list_phases_aqua_pro_100k(self, resolver: PropFirmRuleResolver):
        phases = resolver.list_phases("aqua_instant_pro", "pro_100k")
        assert "funded" in phases

    def test_list_phases_ftmo_challenge_100k(self, resolver: PropFirmRuleResolver):
        phases = resolver.list_phases("ftmo", "challenge_100k")
        assert "challenge" in phases
        assert "verification" in phases
        assert "funded" in phases

    def test_list_phases_unknown_plan_returns_empty(self, resolver: PropFirmRuleResolver):
        phases = resolver.list_phases("ftmo", "nonexistent_plan")
        assert phases == []


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------


class TestResolverCaching:
    def test_second_resolve_uses_cache(self, resolver: PropFirmRuleResolver):
        """Repeated resolve calls should hit the internal YAML cache."""
        _ = resolver.resolve("ftmo", "challenge_100k", "funded")
        assert "ftmo" in resolver._cache

    def test_cache_populated_after_list_firms(self, resolver: PropFirmRuleResolver):
        """list_plans loads the YAML and caches it."""
        resolver.list_plans("aqua_instant_pro")
        assert "aqua_instant_pro" in resolver._cache

    def test_separate_instances_have_independent_caches(self):
        r1 = PropFirmRuleResolver()
        r2 = PropFirmRuleResolver()
        r1.resolve("ftmo", "challenge_100k", "funded")
        # r2 has not loaded anything yet
        assert "ftmo" not in r2._cache


# ---------------------------------------------------------------------------
# resolve_for_account
# ---------------------------------------------------------------------------


class TestResolveForAccount:
    def _make_account_state(
        self,
        *,
        prop_firm_code: str = "aqua_instant_pro",
        balance: float = 100_000.0,
        phase_mode: str = "FUNDED",
    ) -> object:
        """Build a minimal account state using a simple dataclass."""
        import dataclasses

        @dataclasses.dataclass
        class _MinimalAccountState:
            prop_firm_code: str
            balance: float
            phase_mode: str

        return _MinimalAccountState(
            prop_firm_code=prop_firm_code,
            balance=balance,
            phase_mode=phase_mode,
        )

    def test_resolve_for_aqua_100k_funded(self, resolver: PropFirmRuleResolver):
        state = self._make_account_state(balance=100_000.0, phase_mode="FUNDED")
        rules = resolver.resolve_for_account(state)
        assert isinstance(rules, ResolvedPropRules)
        assert rules.firm_code == "aqua_instant_pro"

    def test_resolve_for_ftmo_challenge(self, resolver: PropFirmRuleResolver):
        state = self._make_account_state(
            prop_firm_code="ftmo",
            balance=100_000.0,
            phase_mode="CHALLENGE",
        )
        rules = resolver.resolve_for_account(state)
        assert rules.firm_code == "ftmo"
        assert rules.phase == "challenge"

    def test_resolve_for_smaller_balance_picks_best_plan(self, resolver: PropFirmRuleResolver):
        """Balance of 25k should pick pro_25k plan."""
        state = self._make_account_state(balance=25_000.0, phase_mode="FUNDED")
        rules = resolver.resolve_for_account(state)
        assert rules.plan_code == "pro_25k"

    def test_resolve_for_missing_firm_raises(self, resolver: PropFirmRuleResolver):
        state = self._make_account_state(prop_firm_code="ghost_firm")
        with pytest.raises(FileNotFoundError):
            resolver.resolve_for_account(state)
