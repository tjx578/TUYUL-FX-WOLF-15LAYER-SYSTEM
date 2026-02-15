"""
Dashboard risk calculator — THE authority for lot sizing.
Receives: AnalysisRiskInput (from L12 verdict via position_sizing_bridge).
Provides: DashboardRiskOutput with actual lot size.

Constitutional: This module reads account state; analysis never does.
"""

from __future__ import annotations

import logging

from analysis.orchestrators.position_sizing_bridge import (
    AnalysisRiskInput,
    DashboardRiskOutput,
)

logger = logging.getLogger("tuyul.dashboard.risk")


class DashboardRiskCalculator:
    """
    Computes lot sizing based on:
    1. Real account state (balance, equity, floating P&L)
    2. Prop firm guard limits
    3. User-configured risk percent per trade

    THIS IS NOT ANALYSIS. No market direction logic allowed here.
    """

    # Standard pip values per 1 standard lot (USD account)
    # In production, should come from broker/MT5 symbol info
    DEFAULT_PIP_VALUES: dict[str, float] = {
        "EURUSD": 10.0, "GBPUSD": 10.0, "AUDUSD": 10.0,
        "NZDUSD": 10.0, "USDCHF": 10.0, "USDCAD": 7.5,
        "USDJPY": 6.7, "EURJPY": 6.7, "GBPJPY": 6.7,
        "EURGBP": 12.5, "XAUUSD": 10.0,
    }

    def __init__(
        self,
        prop_guard,
        default_risk_pct: float = 1.0,
        pip_value_lookup: dict[str, float] | None = None,
    ):
        self._guard = prop_guard
        self._default_risk_pct = default_risk_pct
        self._pip_values = pip_value_lookup or self.DEFAULT_PIP_VALUES

    def calculate(
        self,
        analysis_input: AnalysisRiskInput,
        account_balance: float,
        account_equity: float,
        floating_pnl: float,
        open_position_count: int,
        day_start_balance: float,
        risk_pct_override: float | None = None,
    ) -> DashboardRiskOutput:
        """
        THE main calculation. Returns binding risk recommendation.
        """
        risk_pct = risk_pct_override or self._default_risk_pct

        # Step 1: Calculate risk amount from real account
        risk_amount_usd = account_balance * (risk_pct / 100.0)

        # Step 2: Calculate lot size from risk amount + SL distance
        sl_pips = analysis_input.sl_pips
        if sl_pips <= 0:
            return DashboardRiskOutput.blocked(
                reason=f"Invalid SL distance: {sl_pips} pips"
            )

        pip_value = self._pip_values.get(analysis_input.symbol, 10.0)
        if pip_value <= 0:
            return DashboardRiskOutput.blocked(
                reason=f"Unknown pip value for {analysis_input.symbol}"
            )

        raw_lot = risk_amount_usd / (sl_pips * pip_value)

        # Step 3: Clamp to broker constraints
        min_lot = 0.01
        lot_step = 0.01
        clamped_lot = max(min_lot, round(int(raw_lot / lot_step) * lot_step, 2))

        # Step 4: Prop firm guard check
        account_state = {
            "balance": account_balance,
            "equity": account_equity,
            "floating_pnl": floating_pnl,
            "open_position_count": open_position_count,
            "day_start_balance": day_start_balance,
        }
        trade_risk = {
            "risk_amount": risk_amount_usd,
            "lot_size": clamped_lot,
            "sl_pips": sl_pips,
        }

        guard_result = self._guard.check(account_state, trade_risk)
        if not guard_result.get("allowed", False):
            return DashboardRiskOutput.blocked(
                reason=(
                    f"Prop firm guard: {guard_result.get('code', 'UNKNOWN')} "
                    f"— {guard_result.get('details', '')}"
                )
            )

        # Step 5: Compute max safe lot (conservative daily limit)
        daily_limit_usd = day_start_balance * 0.05  # 5% FTMO standard
        daily_used = max(0, day_start_balance - account_equity)
        daily_remaining = max(0, daily_limit_usd - daily_used)
        denominator = sl_pips * pip_value
        max_safe = daily_remaining / denominator if denominator > 0 else min_lot
        max_safe_lot = max(min_lot, round(int(max_safe / lot_step) * lot_step, 2))

        final_lot = min(clamped_lot, max_safe_lot)

        logger.info(
            "Risk calc: %s | balance=%.2f | risk=%.1f%% | "
            "SL=%.1f pips | lot=%.2f | max_safe=%.2f",
            analysis_input.symbol, account_balance, risk_pct,
            sl_pips, final_lot, max_safe_lot,
        )

        return DashboardRiskOutput(
            trade_allowed=True,
            recommended_lot=final_lot,
            max_safe_lot=max_safe_lot,
            risk_amount_usd=round(final_lot * sl_pips * pip_value, 2),
            risk_percent=risk_pct,
            reason="All checks passed",
        )
