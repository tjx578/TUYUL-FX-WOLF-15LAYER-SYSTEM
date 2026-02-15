"""
Dashboard risk calculator — THE authority for lot sizing.
Receives: AnalysisRiskInput (from L12 verdict) + account state.
Returns: DashboardRiskOutput with actual lot size.

This is where hardcoded placeholders must be replaced.
"""

from __future__ import annotations

import logging

from typing import TYPE_CHECKING

from analysis.orchestrators.position_sizing_bridge import (
    AnalysisRiskInput,
    DashboardRiskOutput,
)

if TYPE_CHECKING:
    from risk.prop_firm import PropFirmGuard  # pyright: ignore[reportAttributeAccessIssue]

logger = logging.getLogger("tuyul.dashboard.risk")


class DashboardRiskCalculator:
    """
    Computes lot sizing based on:
    1. Real account state (balance, equity, floating P&L)
    2. Prop firm guard limits
    3. User-configured risk percent per trade

    THIS IS NOT ANALYSIS. No market direction logic allowed here.
    """

    def __init__(
        self,
        prop_guard: PropFirmGuard,
        default_risk_pct: float = 1.0,  # 1% per trade default
        pip_value_lookup: dict[str, float] | None = None,
    ):
        self._guard = prop_guard
        self._default_risk_pct = default_risk_pct
        # pip value per 1 standard lot, per symbol
        # e.g. {"EURUSD": 10.0, "GBPUSD": 10.0, "USDJPY": 6.7}
        self._pip_values = pip_value_lookup or self._default_pip_values()

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

        # Step 1: Calculate risk amount from account
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
                reason=f"Prop firm guard: {guard_result.get('code', 'UNKNOWN')} — {guard_result.get('details', '')}"
            )

        # Step 5: Compute max safe lot (conservative)
        daily_limit_usd = day_start_balance * 0.05  # 5% daily max (FTMO standard)
        daily_used = day_start_balance - account_equity  # includes floating
        daily_remaining = max(0, daily_limit_usd - daily_used)
        max_safe = daily_remaining / (sl_pips * pip_value) if sl_pips * pip_value > 0 else min_lot
        max_safe_lot = max(min_lot, round(int(max_safe / lot_step) * lot_step, 2))

        final_lot = min(clamped_lot, max_safe_lot)

        logger.info(
            f"Risk calc: {analysis_input.symbol} | "
            f"balance={account_balance} | risk={risk_pct}% | "
            f"SL={sl_pips:.1f}pips | lot={final_lot} | "
            f"max_safe={max_safe_lot}"
        )

        return DashboardRiskOutput(
            trade_allowed=True,
            recommended_lot=final_lot,
            max_safe_lot=max_safe_lot,
            risk_amount_usd=round(final_lot * sl_pips * pip_value, 2),
            risk_percent=risk_pct,
            reason="All checks passed",
        )

    @staticmethod
    def _default_pip_values() -> dict[str, float]:
        """
        Default pip values per 1 standard lot (USD account).
        In production, these should come from broker/MT5 symbol info.
        """
        return {
            "EURUSD": 10.0,
            "GBPUSD": 10.0,
            "AUDUSD": 10.0,
            "NZDUSD": 10.0,
            "USDCHF": 10.0,
            "USDCAD": 7.5,
            "USDJPY": 6.7,
            "EURJPY": 6.7,
            "GBPJPY": 6.7,
            "EURGBP": 12.5,
            "XAUUSD": 10.0,  # Gold — varies by broker
        }
