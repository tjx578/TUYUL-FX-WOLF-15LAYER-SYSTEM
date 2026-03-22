"""
Aqua Instant Pro Strategy Loader

Loads, validates, and exposes machine-readable strategy configuration
(strategy.yaml) and the hard/soft rule mapping (rule_mapping.yaml) for
the Aqua Instant Pro prop firm profile.

Responsibilities:
    - Parse and validate strategy YAML safely; raise descriptive errors.
    - Enforce hard rules during pre-trade checks.
    - Surface soft-rule outputs as advisory warnings / compliance alerts.
    - Log all decisions with contextual data (account_id, thresholds, timestamp).
    - Gracefully degrade when optional strategy metadata is absent.

Zone: propfirm_manager — consumed exclusively by AquaInstantProGuard and tests.
      No market-direction logic; no account-state writes.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

from risk.exceptions import PropFirmConfigError

# ---------------------------------------------------------------------------
# Profile-local paths
# ---------------------------------------------------------------------------
_PROFILE_DIR = Path(__file__).parent / "profiles" / "aquafunded" / "aqua_instant_pro"
_DEFAULT_STRATEGY_PATH = _PROFILE_DIR / "strategy.yaml"
_DEFAULT_RULE_MAPPING_PATH = _PROFILE_DIR / "rule_mapping.yaml"


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HardRuleViolation:
    """A single hard rule that was violated."""

    rule: str
    action: str
    detail: str


@dataclass(frozen=True)
class HardRuleResult:
    """Aggregate result of all hard-rule checks for one trade context."""

    allowed: bool
    violations: tuple[HardRuleViolation, ...]

    @property
    def primary_violation(self) -> HardRuleViolation | None:
        return self.violations[0] if self.violations else None


@dataclass(frozen=True)
class SoftAdvisory:
    """A single soft-rule advisory (warning or compliance note)."""

    rule: str
    advisory_type: str
    message: str


# ---------------------------------------------------------------------------
# Session window helper
# ---------------------------------------------------------------------------


def _time_in_window(now_local: datetime.time, start: str, end: str) -> bool:
    """Return True if *now_local* falls within [start, end) (HH:MM strings)."""
    start_t = datetime.time.fromisoformat(start)
    end_t = datetime.time.fromisoformat(end)
    if start_t <= end_t:
        return start_t <= now_local < end_t
    # Midnight-spanning window (not used currently, but handle for correctness)
    return now_local >= start_t or now_local < end_t


# ---------------------------------------------------------------------------
# StrategyLoader
# ---------------------------------------------------------------------------


class StrategyLoader:
    """Loads and validates the Aqua Instant Pro strategy and rule-mapping files.

    Inject via constructor for testability; production code uses ``load()``.

    Parameters
    ----------
    strategy_path:
        Path to ``strategy.yaml``. Defaults to the profile directory.
    rule_mapping_path:
        Path to ``rule_mapping.yaml``. Defaults to the profile directory.
    """

    def __init__(
        self,
        strategy_path: Path | None = None,
        rule_mapping_path: Path | None = None,
    ) -> None:
        self._strategy_path = strategy_path or _DEFAULT_STRATEGY_PATH
        self._rule_mapping_path = rule_mapping_path or _DEFAULT_RULE_MAPPING_PATH
        self._strategy: dict[str, Any] = {}
        self._rule_mapping: dict[str, Any] = {}
        self._loaded = False

    # ------------------------------------------------------------------
    # Public factory
    # ------------------------------------------------------------------

    @classmethod
    def load(
        cls,
        strategy_path: Path | None = None,
        rule_mapping_path: Path | None = None,
    ) -> StrategyLoader:
        """Create and immediately load a StrategyLoader instance.

        Args:
            strategy_path: Override default strategy.yaml path.
            rule_mapping_path: Override default rule_mapping.yaml path.

        Returns:
            Loaded StrategyLoader.

        Raises:
            PropFirmConfigError: If required files are missing or malformed.
        """
        instance = cls(strategy_path=strategy_path, rule_mapping_path=rule_mapping_path)
        instance._load_files()
        return instance

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def risk(self) -> dict[str, Any]:
        """Parsed risk_management section (empty dict on missing section)."""
        return dict(self._strategy.get("risk_management", {}))

    @property
    def profit_distribution(self) -> dict[str, Any]:
        """Parsed profit_distribution section."""
        return dict(self._strategy.get("profit_distribution", {}))

    @property
    def market_filters(self) -> dict[str, Any]:
        """Parsed market_filters section."""
        return dict(self._strategy.get("market_filters", {}))

    @property
    def discipline(self) -> dict[str, Any]:
        """Parsed discipline section."""
        return dict(self._strategy.get("discipline", {}))

    @property
    def account_constraints(self) -> dict[str, Any]:
        """Parsed account_constraints section."""
        return dict(self._strategy.get("account_constraints", {}))

    @property
    def advisory_thresholds(self) -> dict[str, Any]:
        """Parsed advisory_thresholds section."""
        return dict(self._strategy.get("advisory_thresholds", {}))

    @property
    def hard_rules(self) -> list[dict[str, Any]]:
        """List of hard-rule entries from rule_mapping.yaml."""
        return list(self._rule_mapping.get("hard_rules", []))

    @property
    def soft_rules(self) -> list[dict[str, Any]]:
        """List of soft-rule entries from rule_mapping.yaml."""
        return list(self._rule_mapping.get("soft_rules", []))

    # ------------------------------------------------------------------
    # Hard rule enforcement
    # ------------------------------------------------------------------

    def check_hard_rules(
        self,
        *,
        account_id: str = "unknown",
        risk_percent: float = 0.0,
        total_open_risk_percent: float = 0.0,
        open_primary_positions: int = 0,
        correlated_positions: int = 0,
        same_direction_correlated: int = 0,
        has_stop_loss: bool = True,
        consecutive_losses_today: int = 0,
        weekly_loss_percent: float = 0.0,
        symbol: str = "",
        session_time_local: datetime.time | None = None,
        news_active: bool = False,
        add_to_loser: bool = False,
        martingale: bool = False,
        floating_loss_percent_of_initial: float = 0.0,
        daily_profit_percent: float = 0.0,
    ) -> HardRuleResult:
        """Evaluate all hard rules for a proposed trade.

        Args:
            account_id: For logging context.
            risk_percent: Proposed trade risk as % of account balance.
            total_open_risk_percent: Combined open risk % if trade is placed.
            open_primary_positions: Current count of primary open positions.
            correlated_positions: Current correlated position count.
            same_direction_correlated: Same-direction correlated count.
            has_stop_loss: Whether the proposed trade has a stop-loss.
            consecutive_losses_today: Consecutive loss count this session.
            weekly_loss_percent: Running weekly loss as %.
            symbol: Proposed trading symbol (e.g. "EURUSD").
            session_time_local: Local time (Asia/Jakarta) for session check.
            news_active: True if a high-impact news blackout is in effect.
            add_to_loser: Whether the trade adds to an existing loser.
            martingale: Whether martingale sizing is being used.
            floating_loss_percent_of_initial: Current floating loss as % of initial balance.
            daily_profit_percent: Today's realised profit as % of balance.

        Returns:
            HardRuleResult — ``allowed=True`` only if zero violations.
        """
        if not self._loaded:
            self._load_files()

        rm = self.risk
        mf = self.market_filters
        pd = self.profit_distribution
        ac = self.account_constraints
        violations: list[HardRuleViolation] = []

        max_risk = float(rm.get("risk_per_trade_percent", 0.4))
        max_total = float(rm.get("max_total_open_risk_percent", 0.8))
        max_primary = int(rm.get("max_primary_positions", 2))
        max_correlated = int(rm.get("max_correlated_positions", 2))
        max_same_dir = int(rm.get("max_same_direction_correlated_positions", 1))
        max_consec = int(rm.get("max_consecutive_losses_per_day", 2))
        weekly_cap = float(rm.get("hard_weekly_loss_limit_percent", 2.0))
        kill_switch_pct = float(ac.get("kill_switch_floating_loss_percent", 2.0))
        daily_max_pct = float(pd.get("daily_target_max_percent", 1.0))
        allowed_symbols: list[str] = list(mf.get("allowed_symbols", []))

        # 1. Risk per trade
        if risk_percent > max_risk:
            violations.append(
                HardRuleViolation(
                    rule="risk_per_trade",
                    action="block_trade",
                    detail=f"Risk {risk_percent:.2f}% exceeds cap {max_risk}%",
                )
            )

        # 2. Total open risk
        if total_open_risk_percent > max_total:
            violations.append(
                HardRuleViolation(
                    rule="max_total_open_risk",
                    action="block_trade",
                    detail=f"Total open risk {total_open_risk_percent:.2f}% exceeds {max_total}%",
                )
            )

        # 3. Max primary positions
        if open_primary_positions >= max_primary:
            violations.append(
                HardRuleViolation(
                    rule="max_primary_positions",
                    action="block_trade",
                    detail=f"Open primary positions {open_primary_positions} >= max {max_primary}",
                )
            )

        # 4. Correlated exposure
        if correlated_positions >= max_correlated:
            violations.append(
                HardRuleViolation(
                    rule="correlated_exposure_cap",
                    action="block_trade",
                    detail=f"Correlated positions {correlated_positions} >= max {max_correlated}",
                )
            )
        if same_direction_correlated >= max_same_dir:
            violations.append(
                HardRuleViolation(
                    rule="correlated_exposure_cap",
                    action="block_trade",
                    detail=f"Same-direction correlated positions {same_direction_correlated} >= max {max_same_dir}",
                )
            )

        # 5. Mandatory stop-loss
        if not has_stop_loss:
            violations.append(
                HardRuleViolation(
                    rule="mandatory_stop_loss",
                    action="block_trade",
                    detail="Trade must have a stop-loss",
                )
            )

        # 6. Consecutive loss lockout
        if consecutive_losses_today >= max_consec:
            violations.append(
                HardRuleViolation(
                    rule="daily_consecutive_loss_lockout",
                    action="lock_session",
                    detail=f"Consecutive losses today ({consecutive_losses_today}) >= {max_consec}; stop trading",
                )
            )

        # 7. Weekly loss cap
        if weekly_loss_percent >= weekly_cap:
            violations.append(
                HardRuleViolation(
                    rule="weekly_loss_cap",
                    action="lock_session",
                    detail=f"Weekly loss {weekly_loss_percent:.2f}% >= cap {weekly_cap}%",
                )
            )

        # 8. Allowed symbols
        if allowed_symbols and symbol and symbol.upper() not in [s.upper() for s in allowed_symbols]:
            violations.append(
                HardRuleViolation(
                    rule="allowed_symbols",
                    action="block_trade",
                    detail=f"Symbol '{symbol}' not in allowed list: {allowed_symbols}",
                )
            )

        # 9. Session window
        if session_time_local is not None:
            sessions: list[dict[str, Any]] = mf.get("sessions", {}).get("windows", [])
            if sessions:
                in_session = any(_time_in_window(session_time_local, w["start"], w["end"]) for w in sessions)
                if not in_session:
                    violations.append(
                        HardRuleViolation(
                            rule="allowed_sessions",
                            action="block_trade",
                            detail=f"Current time {session_time_local} outside allowed trading windows",
                        )
                    )

        # 10. News blackout
        if news_active:
            violations.append(
                HardRuleViolation(
                    rule="news_blackout",
                    action="block_trade",
                    detail="High-impact news blackout is active; no new trades allowed",
                )
            )

        # 11. No add-to-loser
        if add_to_loser:
            violations.append(
                HardRuleViolation(
                    rule="no_add_to_loser",
                    action="block_trade",
                    detail="Adding to a losing position is prohibited",
                )
            )

        # 12. No martingale
        if martingale:
            violations.append(
                HardRuleViolation(
                    rule="no_martingale",
                    action="block_trade",
                    detail="Martingale position sizing is prohibited",
                )
            )

        # 13. Kill-switch proximity / emergency flatten
        if floating_loss_percent_of_initial >= kill_switch_pct:
            violations.append(
                HardRuleViolation(
                    rule="kill_switch_proximity",
                    action="emergency_flatten",
                    detail=(
                        f"Floating loss {floating_loss_percent_of_initial:.2f}% of initial balance "
                        f">= kill-switch threshold {kill_switch_pct}%"
                    ),
                )
            )

        # 14. Daily profit target stop
        if daily_profit_percent >= daily_max_pct:
            violations.append(
                HardRuleViolation(
                    rule="daily_profit_target_stop",
                    action="lock_session",
                    detail=(f"Daily profit {daily_profit_percent:.2f}% has reached target cap {daily_max_pct}%"),
                )
            )

        allowed = len(violations) == 0
        result = HardRuleResult(allowed=allowed, violations=tuple(violations))

        logger.info(
            f"AquaInstantPro hard-rule check | account={account_id} allowed={allowed} "
            f"violations={len(violations)} profile=aqua_instant_pro "
            f"ts={datetime.datetime.now(datetime.UTC).isoformat()}"
        )
        if violations:
            for v in violations:
                logger.warning(
                    f"HardRuleViolation | account={account_id} rule={v.rule} " f"action={v.action} detail={v.detail}"
                )

        return result

    # ------------------------------------------------------------------
    # Soft advisory generation
    # ------------------------------------------------------------------

    def get_soft_advisories(
        self,
        *,
        account_id: str = "unknown",
        is_pullback_entry: bool = True,
        has_confluence: bool = True,
        timeframes_aligned: bool = True,
        entry_in_preferred_zone: bool = True,
        is_breakout_retest: bool = True,
        sl_moved_to_breakeven: bool | None = None,
        partial_tp_taken: bool | None = None,
        journal_entry_exists: bool = True,
        weekly_review_done: bool = True,
        floating_loss_percent_of_initial: float = 0.0,
        best_day_percent_of_total: float = 0.0,
    ) -> list[SoftAdvisory]:
        """Evaluate soft rules and return advisory messages.

        Args:
            account_id: For logging context.
            is_pullback_entry: Whether the entry follows a pullback model.
            has_confluence: Whether at least one confirmation signal is present.
            timeframes_aligned: Whether H1 bias aligns with H4 trend.
            entry_in_preferred_zone: Whether entry targets Fib/S/R zones.
            is_breakout_retest: Whether a breakout entry uses a retest.
            sl_moved_to_breakeven: None when not yet applicable.
            partial_tp_taken: None when not yet applicable.
            journal_entry_exists: Whether the trade is journaled.
            weekly_review_done: Whether the weekly review was completed.
            floating_loss_percent_of_initial: Current floating loss %.
            best_day_percent_of_total: Best-day profit as % of total profit.

        Returns:
            List of SoftAdvisory items (empty if no advisories triggered).
        """
        if not self._loaded:
            self._load_files()

        advisories: list[SoftAdvisory] = []
        thresholds = self.advisory_thresholds
        ks_warn = float(thresholds.get("kill_switch_proximity_warning_percent", 1.5))
        best_day_warn = float(thresholds.get("best_day_consistency_warning_percent", 15.0))

        if not is_pullback_entry:
            advisories.append(
                SoftAdvisory(
                    rule="trend_pullback_preference",
                    advisory_type="warn_if_not_pullback",
                    message="Entry does not follow the preferred trend-pullback model",
                )
            )

        if not has_confluence:
            advisories.append(
                SoftAdvisory(
                    rule="confirmation_quality",
                    advisory_type="score_penalty_if_missing_confluence",
                    message="No confluence signal present (candlestick / RSI-14 / MACD)",
                )
            )

        if not timeframes_aligned:
            advisories.append(
                SoftAdvisory(
                    rule="timeframe_alignment",
                    advisory_type="warn_if_misaligned_timeframes",
                    message="H1 execution bias does not align with H4 trend direction",
                )
            )

        if not entry_in_preferred_zone:
            advisories.append(
                SoftAdvisory(
                    rule="preferred_entry_zones",
                    advisory_type="warn_if_entry_outside_preferred_zone",
                    message="Entry is outside preferred Fibonacci / S/R zones",
                )
            )

        if not is_breakout_retest:
            advisories.append(
                SoftAdvisory(
                    rule="breakout_retest_preference",
                    advisory_type="warn_if_pure_breakout_entry",
                    message="Pure breakout entry detected; prefer breakout-retest confirmation",
                )
            )

        if sl_moved_to_breakeven is False:
            advisories.append(
                SoftAdvisory(
                    rule="move_to_breakeven_discipline",
                    advisory_type="warn_if_sl_not_moved_to_be",
                    message="SL has not been moved to breakeven after RR 1:1 was reached",
                )
            )

        if partial_tp_taken is False:
            advisories.append(
                SoftAdvisory(
                    rule="partial_take_profit",
                    advisory_type="warn_if_no_partial_tp_taken",
                    message="No partial TP taken yet; consider scaling out at first target (RR 1:2)",
                )
            )

        if not journal_entry_exists:
            advisories.append(
                SoftAdvisory(
                    rule="journaling_compliance",
                    advisory_type="compliance_alert_if_missing_journal",
                    message="Trade is missing a journal entry; journaling is required",
                )
            )

        if not weekly_review_done:
            advisories.append(
                SoftAdvisory(
                    rule="weekly_review_compliance",
                    advisory_type="compliance_alert_if_missing_weekly_review",
                    message="Weekly performance review has not been completed",
                )
            )

        if floating_loss_percent_of_initial >= ks_warn:
            advisories.append(
                SoftAdvisory(
                    rule="kill_switch_proximity_warning",
                    advisory_type="warn_approaching_kill_switch",
                    message=(
                        f"Floating loss {floating_loss_percent_of_initial:.2f}% is approaching "
                        f"kill-switch threshold of {self.account_constraints.get('kill_switch_floating_loss_percent', 2.0)}%"
                    ),
                )
            )

        if best_day_percent_of_total >= best_day_warn:
            advisories.append(
                SoftAdvisory(
                    rule="consistency_best_day_warning",
                    advisory_type="warn_approaching_consistency_limit",
                    message=(
                        f"Best-day profit is {best_day_percent_of_total:.1f}% of total profit "
                        f"(hard limit: 20%); reduce position size to protect payout eligibility"
                    ),
                )
            )

        if advisories:
            logger.info(
                f"AquaInstantPro soft-rule advisories | account={account_id} count={len(advisories)} "
                f"profile=aqua_instant_pro ts={datetime.datetime.now(datetime.UTC).isoformat()}"
            )

        return advisories

    # ------------------------------------------------------------------
    # Internal loading
    # ------------------------------------------------------------------

    def _load_files(self) -> None:
        """Load and validate strategy.yaml and rule_mapping.yaml.

        Raises:
            PropFirmConfigError: If a required file is missing or malformed.
        """
        self._strategy = self._load_yaml(self._strategy_path, required=True)
        self._rule_mapping = self._load_yaml(self._rule_mapping_path, required=True)
        self._loaded = True
        logger.debug(
            f"StrategyLoader: loaded aqua_instant_pro strategy={self._strategy_path} "
            f"rule_mapping={self._rule_mapping_path}"
        )

    @staticmethod
    def _load_yaml(path: Path, *, required: bool) -> dict[str, Any]:
        """Load a YAML file and return a dict.

        Args:
            path: File path to load.
            required: If True, raise PropFirmConfigError when file is missing.

        Returns:
            Parsed YAML as dict; empty dict if optional file is missing.

        Raises:
            PropFirmConfigError: On missing (required) or malformed file.
        """
        if not path.exists():
            if required:
                raise PropFirmConfigError(
                    f"Required strategy config not found: {path}. "
                    "Ensure propfirm_manager/profiles/aquafunded/aqua_instant_pro/ contains strategy.yaml and rule_mapping.yaml."
                )
            logger.warning(f"Optional strategy file not found: {path}")
            return {}

        try:
            with open(path) as fh:
                data = yaml.safe_load(fh)
        except yaml.YAMLError as exc:
            raise PropFirmConfigError(f"Failed to parse strategy config {path}: {exc}") from exc

        if data is None:
            return {}
        if not isinstance(data, dict):
            raise PropFirmConfigError(f"Strategy config must be a YAML mapping, got {type(data).__name__}: {path}")
        return data
