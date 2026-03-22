"""
Aqua Instant Pro Prop Firm Guard

Enforces Aqua Instant Pro-specific rules:
- Max daily drawdown (from profile.yaml rules)
- Max total drawdown (from profile.yaml rules)
- Max risk per trade — from strategy.yaml (0.4%) and profile rules
- Max 2 primary positions simultaneously (from strategy.yaml)
- Kill-switch proximity / emergency flatten
- Session, news, symbol, consecutive-loss, weekly-loss enforcement
- Soft-rule advisory generation via StrategyLoader

Supports both v1 (flat rules) and v2 (nested plans/phases) YAML formats.
Strategy integration via StrategyLoader (dependency injection).
"""

from __future__ import annotations

import datetime
from typing import Any

from loguru import logger

from propfirm_manager.profiles.base_guard import (
    BasePropFirmGuard,
    GuardResult,
)
from propfirm_manager.strategy_loader import SoftAdvisory, StrategyLoader


class AquaInstantProGuard(BasePropFirmGuard):
    """Aqua Instant Pro prop firm rule enforcement with strategy integration."""

    def __init__(
        self,
        rules: dict[str, Any] | None = None,
        strategy_loader: StrategyLoader | None = None,
    ) -> None:
        """
        Initialize guard with flat or v2-structured rules.

        Args:
            rules: Flat rules dict (v1) or dict that may contain nested
                   v2 structure. In v2, ``default_rules`` is extracted
                   and used as the effective flat rules.
            strategy_loader: Optional pre-loaded StrategyLoader; if None
                             the default profile strategy.yaml is loaded.
        """
        super().__init__(self._normalise(rules or {}))
        if strategy_loader is not None:
            self._strategy = strategy_loader
        else:
            try:
                self._strategy = StrategyLoader.load()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    f"AquaInstantProGuard: strategy_loader failed to load, "
                    f"falling back to profile-only rules: {exc}"
                )
                self._strategy = None  # type: ignore[assignment]

    @staticmethod
    def _normalise(rules: dict[str, Any]) -> dict[str, Any]:
        """Extract flat rules from v1 or v2 rule dict."""
        if "default_rules" in rules:
            return dict(rules["default_rules"])
        return rules

    def check(
        self,
        account_state: dict[str, Any],
        trade_risk: dict[str, Any],
    ) -> GuardResult:
        """
        Evaluate trade against Aqua Instant Pro rules (profile + strategy).

        Standard account_state / trade_risk interface (backward-compatible):

        account_state keys (all optional with safe defaults):
            daily_dd_percent: float       — current daily drawdown %
            total_dd_percent: float       — current total drawdown %
            open_trades: int              — current open trade count
            balance: float                — current account balance
            account_id: str               — for contextual logging
            consecutive_losses_today: int — consecutive losses this session
            weekly_loss_percent: float    — running weekly loss %
            floating_loss_pct_of_initial: float — floating loss % of initial balance
            daily_profit_percent: float   — today's realised profit %

        trade_risk keys (all optional with safe defaults):
            risk_percent: float           — proposed trade risk %
            daily_dd_after: float         — daily DD if trade is placed
            total_dd_after: float         — total DD if trade is placed
            total_open_risk_percent: float — combined open risk after trade
            symbol: str                   — trading symbol
            has_stop_loss: bool           — whether SL is set
            add_to_loser: bool            — whether adding to a loser
            martingale: bool              — whether martingale sizing
            session_time_local: str       — local time "HH:MM" (Asia/Jakarta)
            news_active: bool             — high-impact news blackout active
            same_direction_correlated: int — same-dir correlated count
            correlated_positions: int     — total correlated count

        Returns:
            GuardResult
        """
        account_id: str = str(account_state.get("account_id", "unknown"))
        open_trades: int = int(account_state.get("open_trades", 0))
        daily_dd_after: float = float(trade_risk.get("daily_dd_after", 0.0))
        total_dd_after: float = float(trade_risk.get("total_dd_after", 0.0))
        risk_percent: float = float(trade_risk.get("risk_percent", 0.0))

        # -- profile.yaml-based limits (backward-compatible) -----------------
        max_daily_dd: float = float(self.rules.get("max_daily_dd_percent", 5.0))
        max_total_dd: float = float(self.rules.get("max_total_dd_percent", 10.0))
        max_open: int = int(self.rules.get("max_open_trades", 2))

        # Enforce profile-level open-trade cap first (cheapest check)
        if open_trades >= max_open:
            return self._deny(
                "DENY_MAX_OPEN_TRADES",
                f"Max {max_open} open trade(s) allowed, currently {open_trades} open",
            )

        if daily_dd_after > max_daily_dd:
            return self._deny(
                "DENY_DAILY_DD",
                f"Daily DD would reach {daily_dd_after:.2f}%, max {max_daily_dd}%",
            )

        if total_dd_after > max_total_dd:
            return self._deny(
                "DENY_TOTAL_DD",
                f"Total DD would reach {total_dd_after:.2f}%, max {max_total_dd}%",
            )

        # -- strategy.yaml hard-rule enforcement -----------------------------
        if self._strategy is not None:
            session_time_local: datetime.time | None = None
            raw_time: str | None = trade_risk.get("session_time_local")
            if raw_time:
                try:
                    session_time_local = datetime.time.fromisoformat(raw_time)
                except ValueError:
                    logger.warning(
                        f"AquaInstantProGuard: invalid session_time_local '{raw_time}'; skipping session check"
                    )

            hard_result = self._strategy.check_hard_rules(
                account_id=account_id,
                risk_percent=risk_percent,
                total_open_risk_percent=float(trade_risk.get("total_open_risk_percent", risk_percent)),
                open_primary_positions=open_trades,
                correlated_positions=int(trade_risk.get("correlated_positions", 0)),
                same_direction_correlated=int(trade_risk.get("same_direction_correlated", 0)),
                has_stop_loss=bool(trade_risk.get("has_stop_loss", True)),
                consecutive_losses_today=int(account_state.get("consecutive_losses_today", 0)),
                weekly_loss_percent=float(account_state.get("weekly_loss_percent", 0.0)),
                symbol=str(trade_risk.get("symbol", "")),
                session_time_local=session_time_local,
                news_active=bool(trade_risk.get("news_active", False)),
                add_to_loser=bool(trade_risk.get("add_to_loser", False)),
                martingale=bool(trade_risk.get("martingale", False)),
                floating_loss_percent_of_initial=float(
                    account_state.get("floating_loss_pct_of_initial", 0.0)
                ),
                daily_profit_percent=float(account_state.get("daily_profit_percent", 0.0)),
            )

            if not hard_result.allowed and hard_result.primary_violation is not None:
                v = hard_result.primary_violation
                code = "DENY_" + v.rule.upper()
                return self._deny(code, v.detail)

        # -- profile-level risk-per-trade check (uses strategy cap if loaded) -
        max_risk_per_trade: float = float(
            self.rules.get(
                "max_risk_per_trade_percent",
                self._strategy.risk.get("risk_per_trade_percent", 1.0)
                if self._strategy is not None
                else 1.0,
            )
        )
        if risk_percent > max_risk_per_trade:
            return self._deny(
                "DENY_RISK_PER_TRADE",
                f"Risk {risk_percent:.2f}% exceeds max {max_risk_per_trade}%",
            )

        # -- warning thresholds (80% of DD limits) ---------------------------
        warn_daily_threshold = max_daily_dd * 0.8
        warn_total_threshold = max_total_dd * 0.8

        if daily_dd_after >= warn_daily_threshold:
            return self._warn(
                "WARN_HIGH_DAILY_DD",
                f"Daily DD would be {daily_dd_after:.2f}%, approaching limit of {max_daily_dd}%",
            )

        if total_dd_after >= warn_total_threshold:
            return self._warn(
                "WARN_HIGH_TOTAL_DD",
                f"Total DD would be {total_dd_after:.2f}%, approaching limit of {max_total_dd}%",
            )

        return self._allow()

    def get_soft_advisories(
        self,
        account_state: dict[str, Any],
        trade_context: dict[str, Any] | None = None,
    ) -> list[SoftAdvisory]:
        """Return soft-rule advisory messages for the current account/trade state.

        Args:
            account_state: Account state dict (same keys as check()).
            trade_context: Optional trade setup context for entry-model checks.

        Returns:
            List of SoftAdvisory items; empty if StrategyLoader unavailable.
        """
        if self._strategy is None:
            return []

        ctx = trade_context or {}
        return self._strategy.get_soft_advisories(
            account_id=str(account_state.get("account_id", "unknown")),
            is_pullback_entry=bool(ctx.get("is_pullback_entry", True)),
            has_confluence=bool(ctx.get("has_confluence", True)),
            timeframes_aligned=bool(ctx.get("timeframes_aligned", True)),
            entry_in_preferred_zone=bool(ctx.get("entry_in_preferred_zone", True)),
            is_breakout_retest=bool(ctx.get("is_breakout_retest", True)),
            sl_moved_to_breakeven=ctx.get("sl_moved_to_breakeven"),
            partial_tp_taken=ctx.get("partial_tp_taken"),
            journal_entry_exists=bool(ctx.get("journal_entry_exists", True)),
            weekly_review_done=bool(ctx.get("weekly_review_done", True)),
            floating_loss_percent_of_initial=float(
                account_state.get("floating_loss_pct_of_initial", 0.0)
            ),
            best_day_percent_of_total=float(
                account_state.get("best_day_percent_of_total", 0.0)
            ),
        )
