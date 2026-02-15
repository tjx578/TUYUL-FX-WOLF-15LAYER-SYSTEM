"""
Bridge between L12 verdict and Dashboard risk calculation.
Analysis provides: entry, SL, TP, direction.
Dashboard provides: account state → lot_size, risk_amount.

This module DOES NOT compute lot size. It packages what analysis knows
and leaves the sizing decision to dashboard/risk zone.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AnalysisRiskInput:
    """What analysis CAN provide — no account state here."""
    symbol: str
    direction: str  # "BUY" or "SELL"
    entry_price: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float | None = None
    risk_reward_ratio: float = 0.0

    @property
    def sl_distance(self) -> float:
        return abs(self.entry_price - self.stop_loss)

    @property
    def sl_pips(self) -> float:
        """SL distance in pips (5-digit FX pricing)."""
        return self.sl_distance * 10_000


@dataclass(frozen=True)
class DashboardRiskOutput:
    """What dashboard MUST provide — computed from account state + prop firm guard."""
    trade_allowed: bool
    recommended_lot: float
    max_safe_lot: float
    risk_amount_usd: float
    risk_percent: float
    reason: str
    expiry_seconds: float = 300.0

    @staticmethod
    def blocked(reason: str) -> DashboardRiskOutput:
        return DashboardRiskOutput(
            trade_allowed=False,
            recommended_lot=0.0,
            max_safe_lot=0.0,
            risk_amount_usd=0.0,
            risk_percent=0.0,
            reason=reason,
        )


def package_for_dashboard(
    symbol: str,
    direction: str,
    entry_price: float,
    stop_loss: float,
    take_profit_1: float,
    take_profit_2: float | None = None,
) -> AnalysisRiskInput:
    """
    Package analysis output for dashboard risk calculation.

    NOTE: This function deliberately does NOT include lot_size or risk_amount.
    Those are dashboard/risk-zone responsibilities per constitutional rules.
    """
    rr = 0.0
    sl_dist = abs(entry_price - stop_loss)
    if sl_dist > 0:
        rr = abs(take_profit_1 - entry_price) / sl_dist

    return AnalysisRiskInput(
        symbol=symbol,
        direction=direction,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit_1=take_profit_1,
        take_profit_2=take_profit_2,
        risk_reward_ratio=round(rr, 2),
    )
