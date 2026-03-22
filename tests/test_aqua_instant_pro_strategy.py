"""
Tests for Aqua Instant Pro Strategy Integration

Validates:
- Loading and parsing strategy.yaml
- Loading and parsing rule_mapping.yaml
- Fallback behavior when files are missing or malformed
- Hard-rule enforcement (max positions, allowed symbols, sessions, news, losses, weekly cap)
- Soft-rule advisory output
- Updated AquaInstantProGuard integration
"""

from __future__ import annotations

import datetime
from pathlib import Path

import pytest

from propfirm_manager.profiles.aquafunded.aqua_instant_pro.guard import AquaInstantProGuard
from propfirm_manager.strategy_loader import (
    HardRuleResult,
    SoftAdvisory,
    StrategyLoader,
)
from risk.exceptions import PropFirmConfigError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

PROFILE_DIR = Path(__file__).parent.parent / "propfirm_manager" / "profiles" / "aquafunded" / "aqua_instant_pro"


@pytest.fixture()
def loader() -> StrategyLoader:
    """Default StrategyLoader using real profile files."""
    return StrategyLoader.load()


@pytest.fixture()
def guard(loader: StrategyLoader) -> AquaInstantProGuard:
    """AquaInstantProGuard with real strategy integration."""
    rules = {
        "max_daily_dd_percent": 5.0,
        "max_total_dd_percent": 10.0,
        "max_risk_per_trade_percent": 0.5,
        "max_open_trades": 2,
    }
    return AquaInstantProGuard(rules=rules, strategy_loader=loader)


_SAFE_ACCOUNT: dict = {
    "account_id": "ACC-TEST",
    "daily_dd_percent": 0.1,
    "total_dd_percent": 0.2,
    "open_trades": 0,
    "balance": 100_000,
    "consecutive_losses_today": 0,
    "weekly_loss_percent": 0.0,
    "floating_loss_pct_of_initial": 0.0,
    "daily_profit_percent": 0.0,
}

_SAFE_TRADE: dict = {
    "risk_percent": 0.3,
    "daily_dd_after": 0.4,
    "total_dd_after": 0.5,
    "total_open_risk_percent": 0.3,
    "symbol": "EURUSD",
    "has_stop_loss": True,
    "add_to_loser": False,
    "martingale": False,
    "session_time_local": "15:00",  # London session
    "news_active": False,
    "correlated_positions": 0,
    "same_direction_correlated": 0,
}


# ---------------------------------------------------------------------------
# Loading and parsing
# ---------------------------------------------------------------------------


class TestStrategyYamlLoading:
    """Strategy YAML loads and parses correctly."""

    def test_strategy_yaml_loads_successfully(self, loader: StrategyLoader) -> None:
        """strategy.yaml loads without error."""
        assert loader is not None
        assert loader.risk != {}

    def test_strategy_contains_risk_management(self, loader: StrategyLoader) -> None:
        """risk_management section is present and has key fields."""
        rm = loader.risk
        assert "risk_per_trade_percent" in rm
        assert rm["risk_per_trade_percent"] == pytest.approx(0.4)
        assert rm["max_primary_positions"] == 2
        assert rm["stop_loss_required"] is True

    def test_strategy_contains_account_constraints(self, loader: StrategyLoader) -> None:
        """account_constraints section contains kill-switch and trailing DD."""
        ac = loader.account_constraints
        assert ac["trailing_drawdown_percent"] == pytest.approx(4.0)
        assert ac["kill_switch_floating_loss_percent"] == pytest.approx(2.0)
        assert ac["payout_min_profitable_days"] == 5

    def test_strategy_contains_market_filters(self, loader: StrategyLoader) -> None:
        """market_filters section contains symbols, sessions and news filter."""
        mf = loader.market_filters
        assert "EURUSD" in mf["allowed_symbols"]
        assert "GBPUSD" in mf["allowed_symbols"]
        assert mf["news_filter"]["enabled"] is True
        assert mf["news_filter"]["blackout_minutes_before"] == 30

    def test_strategy_contains_profit_distribution(self, loader: StrategyLoader) -> None:
        """profit_distribution section is present."""
        pd = loader.profit_distribution
        assert pd["daily_target_min_percent"] == pytest.approx(0.5)
        assert pd["consistency_best_day_limit_percent"] == pytest.approx(20.0)

    def test_rule_mapping_loads_successfully(self, loader: StrategyLoader) -> None:
        """rule_mapping.yaml loads and contains hard and soft rules."""
        assert len(loader.hard_rules) > 0
        assert len(loader.soft_rules) > 0

    def test_hard_rules_have_required_fields(self, loader: StrategyLoader) -> None:
        """Each hard rule has name, description, and action."""
        for rule in loader.hard_rules:
            assert "name" in rule, f"Missing 'name' in hard rule: {rule}"
            assert "description" in rule, f"Missing 'description' in hard rule: {rule}"
            assert "action" in rule, f"Missing 'action' in hard rule: {rule}"

    def test_soft_rules_have_required_fields(self, loader: StrategyLoader) -> None:
        """Each soft rule has name, description, and advisory type."""
        for rule in loader.soft_rules:
            assert "name" in rule
            assert "advisory" in rule


# ---------------------------------------------------------------------------
# Fallback / error handling
# ---------------------------------------------------------------------------


class TestStrategyLoaderFallback:
    """Fallback behavior on missing or malformed files."""

    def test_missing_strategy_file_raises_config_error(self, tmp_path: Path) -> None:
        """Missing required strategy.yaml raises PropFirmConfigError."""
        fake_rm = tmp_path / "rule_mapping.yaml"
        fake_rm.write_text("hard_rules: []\nsoft_rules: []\n")
        with pytest.raises(PropFirmConfigError, match="strategy.yaml"):
            StrategyLoader.load(
                strategy_path=tmp_path / "nonexistent_strategy.yaml",
                rule_mapping_path=fake_rm,
            )

    def test_missing_rule_mapping_raises_config_error(self, tmp_path: Path) -> None:
        """Missing required rule_mapping.yaml raises PropFirmConfigError."""
        real_strategy = PROFILE_DIR / "strategy.yaml"
        with pytest.raises(PropFirmConfigError, match="rule_mapping.yaml"):
            StrategyLoader.load(
                strategy_path=real_strategy,
                rule_mapping_path=tmp_path / "nonexistent_rule_mapping.yaml",
            )

    def test_malformed_strategy_yaml_raises_config_error(self, tmp_path: Path) -> None:
        """Malformed YAML raises PropFirmConfigError with descriptive message."""
        bad = tmp_path / "strategy.yaml"
        bad.write_text("key: [unmatched bracket\n")
        rm = tmp_path / "rule_mapping.yaml"
        rm.write_text("hard_rules: []\nsoft_rules: []\n")
        with pytest.raises(PropFirmConfigError):
            StrategyLoader.load(strategy_path=bad, rule_mapping_path=rm)

    def test_non_mapping_yaml_raises_config_error(self, tmp_path: Path) -> None:
        """YAML that is a list (not a mapping) raises PropFirmConfigError."""
        bad = tmp_path / "strategy.yaml"
        bad.write_text("- item1\n- item2\n")
        rm = tmp_path / "rule_mapping.yaml"
        rm.write_text("hard_rules: []\nsoft_rules: []\n")
        with pytest.raises(PropFirmConfigError, match="mapping"):
            StrategyLoader.load(strategy_path=bad, rule_mapping_path=rm)

    def test_empty_yaml_returns_empty_sections(self, tmp_path: Path) -> None:
        """Empty YAML files degrade gracefully to empty dicts."""
        s = tmp_path / "strategy.yaml"
        s.write_text("")
        rm = tmp_path / "rule_mapping.yaml"
        rm.write_text("")
        loader = StrategyLoader.load(strategy_path=s, rule_mapping_path=rm)
        assert loader.risk == {}
        assert loader.hard_rules == []

    def test_guard_degrades_gracefully_if_strategy_unavailable(self, tmp_path: Path) -> None:
        """Guard falls back to profile-only rules if strategy files are missing."""
        # Point StrategyLoader to nonexistent files so it raises during load
        # Guard should catch the error and still work in degraded mode
        guard = AquaInstantProGuard.__new__(AquaInstantProGuard)
        BasePropFirmGuard = AquaInstantProGuard.__bases__[0]
        BasePropFirmGuard.__init__(guard, {"max_daily_dd_percent": 5.0, "max_total_dd_percent": 10.0})
        guard._strategy = None  # Simulate failed loader

        result = guard.check(_SAFE_ACCOUNT, _SAFE_TRADE)
        assert result.allowed is True


# ---------------------------------------------------------------------------
# Hard rule enforcement
# ---------------------------------------------------------------------------


class TestHardRuleMaxPrimaryPositions:
    """Max primary positions enforcement."""

    def test_blocks_when_max_positions_reached(self, loader: StrategyLoader) -> None:
        """Blocks trade when max_primary_positions (2) is already reached."""
        result = loader.check_hard_rules(
            risk_percent=0.3,
            open_primary_positions=2,
            symbol="EURUSD",
            session_time_local=datetime.time(15, 0),
        )
        assert not result.allowed
        assert any(v.rule == "max_primary_positions" for v in result.violations)

    def test_allows_when_positions_below_max(self, loader: StrategyLoader) -> None:
        """Allows trade when open_primary_positions is below cap."""
        result = loader.check_hard_rules(
            risk_percent=0.3,
            open_primary_positions=1,
            symbol="EURUSD",
            session_time_local=datetime.time(15, 0),
        )
        assert result.allowed


class TestHardRuleAllowedSymbols:
    """Allowed symbols enforcement."""

    @pytest.mark.parametrize("symbol", ["EURUSD", "GBPUSD"])
    def test_allows_permitted_symbols(self, loader: StrategyLoader, symbol: str) -> None:
        result = loader.check_hard_rules(
            risk_percent=0.3,
            symbol=symbol,
            session_time_local=datetime.time(15, 0),
        )
        assert result.allowed

    @pytest.mark.parametrize("symbol", ["USDJPY", "XAUUSD", "BTCUSD", "EURJPY"])
    def test_blocks_non_allowed_symbols(self, loader: StrategyLoader, symbol: str) -> None:
        result = loader.check_hard_rules(
            risk_percent=0.3,
            symbol=symbol,
            session_time_local=datetime.time(15, 0),
        )
        assert not result.allowed
        assert any(v.rule == "allowed_symbols" for v in result.violations)


class TestHardRuleAllowedSessions:
    """Session window enforcement."""

    @pytest.mark.parametrize("hhmm", ["14:00", "15:30", "17:59"])
    def test_allows_london_session(self, loader: StrategyLoader, hhmm: str) -> None:
        t = datetime.time.fromisoformat(hhmm)
        result = loader.check_hard_rules(risk_percent=0.3, symbol="EURUSD", session_time_local=t)
        assert result.allowed

    @pytest.mark.parametrize("hhmm", ["20:00", "21:30", "22:59"])
    def test_allows_new_york_session(self, loader: StrategyLoader, hhmm: str) -> None:
        t = datetime.time.fromisoformat(hhmm)
        result = loader.check_hard_rules(risk_percent=0.3, symbol="EURUSD", session_time_local=t)
        assert result.allowed

    @pytest.mark.parametrize("hhmm", ["00:00", "08:00", "12:00", "18:01", "19:59", "23:01"])
    def test_blocks_outside_sessions(self, loader: StrategyLoader, hhmm: str) -> None:
        t = datetime.time.fromisoformat(hhmm)
        result = loader.check_hard_rules(risk_percent=0.3, symbol="EURUSD", session_time_local=t)
        assert not result.allowed
        assert any(v.rule == "allowed_sessions" for v in result.violations)


class TestHardRuleNewsBlackout:
    """News blackout enforcement."""

    def test_blocks_when_news_active(self, loader: StrategyLoader) -> None:
        result = loader.check_hard_rules(
            risk_percent=0.3,
            symbol="EURUSD",
            session_time_local=datetime.time(15, 0),
            news_active=True,
        )
        assert not result.allowed
        assert any(v.rule == "news_blackout" for v in result.violations)

    def test_allows_when_no_news(self, loader: StrategyLoader) -> None:
        result = loader.check_hard_rules(
            risk_percent=0.3,
            symbol="EURUSD",
            session_time_local=datetime.time(15, 0),
            news_active=False,
        )
        assert result.allowed


class TestHardRuleConsecutiveLosses:
    """Consecutive daily loss lockout."""

    def test_blocks_after_two_consecutive_losses(self, loader: StrategyLoader) -> None:
        result = loader.check_hard_rules(
            risk_percent=0.3,
            symbol="EURUSD",
            session_time_local=datetime.time(15, 0),
            consecutive_losses_today=2,
        )
        assert not result.allowed
        assert any(v.rule == "daily_consecutive_loss_lockout" for v in result.violations)
        assert any(v.action == "lock_session" for v in result.violations)

    def test_allows_before_loss_limit(self, loader: StrategyLoader) -> None:
        result = loader.check_hard_rules(
            risk_percent=0.3,
            symbol="EURUSD",
            session_time_local=datetime.time(15, 0),
            consecutive_losses_today=1,
        )
        assert result.allowed


class TestHardRuleWeeklyLossCap:
    """Weekly loss cap enforcement."""

    def test_blocks_at_weekly_loss_cap(self, loader: StrategyLoader) -> None:
        result = loader.check_hard_rules(
            risk_percent=0.3,
            symbol="EURUSD",
            session_time_local=datetime.time(15, 0),
            weekly_loss_percent=2.0,
        )
        assert not result.allowed
        assert any(v.rule == "weekly_loss_cap" for v in result.violations)

    def test_allows_below_weekly_cap(self, loader: StrategyLoader) -> None:
        result = loader.check_hard_rules(
            risk_percent=0.3,
            symbol="EURUSD",
            session_time_local=datetime.time(15, 0),
            weekly_loss_percent=1.5,
        )
        assert result.allowed

    def test_blocks_above_weekly_cap(self, loader: StrategyLoader) -> None:
        result = loader.check_hard_rules(
            risk_percent=0.3,
            symbol="EURUSD",
            session_time_local=datetime.time(15, 0),
            weekly_loss_percent=2.5,
        )
        assert not result.allowed


class TestHardRuleKillSwitch:
    """Kill-switch proximity / emergency flatten."""

    def test_triggers_emergency_flatten_at_kill_switch(self, loader: StrategyLoader) -> None:
        result = loader.check_hard_rules(
            risk_percent=0.1,
            symbol="EURUSD",
            session_time_local=datetime.time(15, 0),
            floating_loss_percent_of_initial=2.0,
        )
        assert not result.allowed
        assert any(v.action == "emergency_flatten" for v in result.violations)

    def test_no_trigger_below_kill_switch(self, loader: StrategyLoader) -> None:
        result = loader.check_hard_rules(
            risk_percent=0.1,
            symbol="EURUSD",
            session_time_local=datetime.time(15, 0),
            floating_loss_percent_of_initial=1.0,
        )
        assert result.allowed


# ---------------------------------------------------------------------------
# Soft rule advisories
# ---------------------------------------------------------------------------


class TestSoftAdvisories:
    """Soft-rule advisory output."""

    def test_no_advisories_for_ideal_setup(self, loader: StrategyLoader) -> None:
        """Clean setup produces zero advisories."""
        advisories = loader.get_soft_advisories(
            is_pullback_entry=True,
            has_confluence=True,
            timeframes_aligned=True,
            entry_in_preferred_zone=True,
            is_breakout_retest=True,
            journal_entry_exists=True,
            weekly_review_done=True,
        )
        assert advisories == []

    def test_warns_non_pullback_entry(self, loader: StrategyLoader) -> None:
        advisories = loader.get_soft_advisories(is_pullback_entry=False)
        names = [a.rule for a in advisories]
        assert "trend_pullback_preference" in names

    def test_warns_missing_confluence(self, loader: StrategyLoader) -> None:
        advisories = loader.get_soft_advisories(has_confluence=False)
        names = [a.rule for a in advisories]
        assert "confirmation_quality" in names

    def test_warns_misaligned_timeframes(self, loader: StrategyLoader) -> None:
        advisories = loader.get_soft_advisories(timeframes_aligned=False)
        names = [a.rule for a in advisories]
        assert "timeframe_alignment" in names

    def test_warns_pure_breakout_entry(self, loader: StrategyLoader) -> None:
        advisories = loader.get_soft_advisories(is_breakout_retest=False)
        names = [a.rule for a in advisories]
        assert "breakout_retest_preference" in names

    def test_warns_sl_not_moved_to_breakeven(self, loader: StrategyLoader) -> None:
        advisories = loader.get_soft_advisories(sl_moved_to_breakeven=False)
        names = [a.rule for a in advisories]
        assert "move_to_breakeven_discipline" in names

    def test_no_advisory_when_sl_not_yet_applicable(self, loader: StrategyLoader) -> None:
        """sl_moved_to_breakeven=None means not applicable yet — no advisory."""
        advisories = loader.get_soft_advisories(sl_moved_to_breakeven=None)
        names = [a.rule for a in advisories]
        assert "move_to_breakeven_discipline" not in names

    def test_warns_missing_journal(self, loader: StrategyLoader) -> None:
        advisories = loader.get_soft_advisories(journal_entry_exists=False)
        names = [a.rule for a in advisories]
        assert "journaling_compliance" in names

    def test_warns_missing_weekly_review(self, loader: StrategyLoader) -> None:
        advisories = loader.get_soft_advisories(weekly_review_done=False)
        names = [a.rule for a in advisories]
        assert "weekly_review_compliance" in names

    def test_warns_approaching_kill_switch(self, loader: StrategyLoader) -> None:
        advisories = loader.get_soft_advisories(floating_loss_percent_of_initial=1.6)
        names = [a.rule for a in advisories]
        assert "kill_switch_proximity_warning" in names

    def test_no_ks_warning_below_threshold(self, loader: StrategyLoader) -> None:
        advisories = loader.get_soft_advisories(floating_loss_percent_of_initial=1.0)
        names = [a.rule for a in advisories]
        assert "kill_switch_proximity_warning" not in names

    def test_warns_approaching_consistency_limit(self, loader: StrategyLoader) -> None:
        advisories = loader.get_soft_advisories(best_day_percent_of_total=16.0)
        names = [a.rule for a in advisories]
        assert "consistency_best_day_warning" in names

    def test_returns_list_of_soft_advisory_instances(self, loader: StrategyLoader) -> None:
        """Every advisory is a SoftAdvisory dataclass."""
        advisories = loader.get_soft_advisories(
            is_pullback_entry=False,
            has_confluence=False,
        )
        assert all(isinstance(a, SoftAdvisory) for a in advisories)


# ---------------------------------------------------------------------------
# Guard integration (AquaInstantProGuard + StrategyLoader)
# ---------------------------------------------------------------------------


class TestAquaInstantProGuardStrategy:
    """End-to-end guard integration with StrategyLoader."""

    def test_guard_allows_clean_trade(self, guard: AquaInstantProGuard) -> None:
        result = guard.check(_SAFE_ACCOUNT, _SAFE_TRADE)
        assert result.allowed is True

    def test_guard_denies_disallowed_symbol(self, guard: AquaInstantProGuard) -> None:
        trade = {**_SAFE_TRADE, "symbol": "USDJPY"}
        result = guard.check(_SAFE_ACCOUNT, trade)
        assert result.allowed is False
        assert "ALLOWED_SYMBOLS" in result.code

    def test_guard_denies_outside_session(self, guard: AquaInstantProGuard) -> None:
        trade = {**_SAFE_TRADE, "session_time_local": "12:00"}
        result = guard.check(_SAFE_ACCOUNT, trade)
        assert result.allowed is False
        assert "ALLOWED_SESSIONS" in result.code

    def test_guard_denies_news_blackout(self, guard: AquaInstantProGuard) -> None:
        trade = {**_SAFE_TRADE, "news_active": True}
        result = guard.check(_SAFE_ACCOUNT, trade)
        assert result.allowed is False
        assert "NEWS_BLACKOUT" in result.code

    def test_guard_denies_after_consecutive_losses(self, guard: AquaInstantProGuard) -> None:
        account = {**_SAFE_ACCOUNT, "consecutive_losses_today": 2}
        result = guard.check(account, _SAFE_TRADE)
        assert result.allowed is False
        assert "CONSECUTIVE_LOSS" in result.code

    def test_guard_denies_over_weekly_loss_cap(self, guard: AquaInstantProGuard) -> None:
        account = {**_SAFE_ACCOUNT, "weekly_loss_percent": 2.0}
        result = guard.check(account, _SAFE_TRADE)
        assert result.allowed is False
        assert "WEEKLY_LOSS_CAP" in result.code

    def test_guard_emergency_flatten_at_kill_switch(self, guard: AquaInstantProGuard) -> None:
        account = {**_SAFE_ACCOUNT, "floating_loss_pct_of_initial": 2.0}
        result = guard.check(account, _SAFE_TRADE)
        assert result.allowed is False
        assert "KILL_SWITCH" in result.code

    def test_guard_denies_max_open_trades(self, guard: AquaInstantProGuard) -> None:
        account = {**_SAFE_ACCOUNT, "open_trades": 2}
        result = guard.check(account, _SAFE_TRADE)
        assert result.allowed is False
        assert "OPEN_TRADES" in result.code

    def test_guard_denies_excess_risk_per_trade(self, guard: AquaInstantProGuard) -> None:
        trade = {**_SAFE_TRADE, "risk_percent": 0.5}
        result = guard.check(_SAFE_ACCOUNT, trade)
        assert result.allowed is False
        assert "RISK_PER_TRADE" in result.code

    def test_guard_soft_advisories_returned(self, guard: AquaInstantProGuard) -> None:
        advisories = guard.get_soft_advisories(
            _SAFE_ACCOUNT,
            {"is_pullback_entry": False, "has_confluence": False},
        )
        assert len(advisories) >= 2

    def test_guard_soft_advisories_empty_for_clean_setup(self, guard: AquaInstantProGuard) -> None:
        advisories = guard.get_soft_advisories(_SAFE_ACCOUNT, {})
        assert advisories == []

    def test_guard_no_martingale(self, guard: AquaInstantProGuard) -> None:
        trade = {**_SAFE_TRADE, "martingale": True}
        result = guard.check(_SAFE_ACCOUNT, trade)
        assert result.allowed is False
        assert "MARTINGALE" in result.code

    def test_guard_no_add_to_loser(self, guard: AquaInstantProGuard) -> None:
        trade = {**_SAFE_TRADE, "add_to_loser": True}
        result = guard.check(_SAFE_ACCOUNT, trade)
        assert result.allowed is False
        assert "LOSER" in result.code

    def test_guard_backward_compatible_no_strategy_loader(self) -> None:
        """Guard works with strategy_loader=None (degraded mode)."""
        # Use a None strategy to force fallback; pass sentinel to avoid real load
        guard = AquaInstantProGuard(
            rules={
                "max_daily_dd_percent": 5.0,
                "max_total_dd_percent": 10.0,
                "max_risk_per_trade_percent": 1.0,
                "max_open_trades": 1,
            },
            strategy_loader=_NullStrategyLoader(),  # type: ignore[arg-type]
        )
        result = guard.check(
            {"open_trades": 0, "daily_dd_percent": 0.0, "total_dd_percent": 0.0},
            {"risk_percent": 0.5, "daily_dd_after": 1.0, "total_dd_after": 2.0},
        )
        assert result.allowed is True


# ---------------------------------------------------------------------------
# Helper stub — simulates a fully unavailable strategy loader
# ---------------------------------------------------------------------------


class _NullStrategyLoader:
    """Stub that returns 'allowed' for all hard-rule checks with no violations."""

    def check_hard_rules(self, **_kwargs: object) -> HardRuleResult:
        return HardRuleResult(allowed=True, violations=())

    @property
    def risk(self) -> dict:
        return {}
