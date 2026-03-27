"""
TUYUL FX Wolf-15 — Risk Engine (Dashboard Layer)
=================================================
BUG FIX [BUG-2]:
  RiskMultiplier and RiskEngine aliases are now defined AFTER the class body.
  Previously they were defined before the class, causing NameError on import.

REFACTOR [overlap-fix]:
  Removed local pip value table and helper functions.
  All pip lookups now delegate to config/pip_values.py (single source of truth),
  eliminating divergence from risk/risk_engine_v2.py.

  calculate_lot() now accepts typed schema objects and returns RiskCalculationResult,
  matching the contract expected by tests and dashboard consumers.

Lot formula:
  1. pip_value, pip_mult = get_pip_info(pair)          ← config/pip_values.py
  2. sl_pips  = abs(entry - sl) * pip_mult
  3. dd_mult  = dd_multiplier(daily_dd_percent)
  4. adj_risk = risk_percent * dd_mult
  5. risk_amt = equity * adj_risk / 100
  6. lot      = risk_amt / (sl_pips * pip_value)
  7. PropFirmManager.evaluate_trade()                  ← DD-based guard
"""

from __future__ import annotations

import logging
import math

from accounts.account_model import (
    AccountState,
    Layer12Signal,
    RiskCalculationResult,
    RiskMode,
    RiskSeverity,
)
from config.pip_values import DEFAULT_PIP_VALUE, PipLookupError, get_pip_info
from propfirm_manager.profile_manager import PropFirmManager

logger = logging.getLogger(__name__)


def _map_guard_severity(severity: str) -> RiskSeverity:
    """Convert prop-firm guard severity labels to dashboard RiskSeverity."""
    normalized = str(severity or "").strip().lower()
    if normalized == "deny":
        return RiskSeverity.CRITICAL
    if normalized == "warn":
        return RiskSeverity.WARNING
    return RiskSeverity.SAFE


# ─── Drawdown multiplier (adaptive risk reduction) ───────────────────────────


def dd_multiplier(daily_dd_percent: float) -> float:
    """
    Adaptive risk multiplier based on drawdown level.
    < 30%  → 1.00 (full risk)
    30-60% → 0.75 (reduce)
    60-80% → 0.50 (half)
    > 80%  → 0.25 (emergency)
    """
    if daily_dd_percent >= 80:
        return 0.25
    if daily_dd_percent >= 60:
        return 0.50
    if daily_dd_percent >= 30:
        return 0.75
    return 1.00


# ─── Main Risk Engine ─────────────────────────────────────────────────────────


class RiskMultiplierAggregator:
    """
    Dashboard lot-size calculator — single authority for position sizing.

    Uses config/pip_values.py as the sole pip data source so that the
    dashboard and risk/risk_engine_v2.py share identical pip values and
    cannot diverge.

    Constitutional rule: lot_size is ALWAYS derived here, never from EA or
    user input.
    """

    MIN_LOT: float = 0.01
    MAX_LOT: float = 100.0

    def calculate_lot(
        self,
        signal: Layer12Signal,
        account_state: AccountState,
        risk_percent: float,
        prop_firm_code: str,
        risk_mode: RiskMode = RiskMode.FIXED,
        split_ratios: list[float] | None = None,
    ) -> RiskCalculationResult:
        """
        Calculate recommended lot size from a Layer-12 signal and account state.

        Args:
            signal: Layer-12 signal supplying pair, entry, and stop_loss.
            account_state: Current account state snapshot.
            risk_percent: Risk per trade as a percentage (e.g. 1.0 = 1 %).
            prop_firm_code: Prop firm identifier for guard lookup (e.g. "ftmo").
            risk_mode: FIXED (single lot) or SPLIT (multiple legs).
            split_ratios: For SPLIT mode — ratios per leg, must sum to ~1.0.

        Returns:
            RiskCalculationResult
        """
        # ── 1. Pip data (single source of truth: config/pip_values.py) ───────
        try:
            pip_val, pip_mult = get_pip_info(signal.pair)
        except PipLookupError:
            pip_val = DEFAULT_PIP_VALUE
            pip_mult = 10_000.0

        # ── 2. SL distance ───────────────────────────────────────────────────
        sl_pips = abs(signal.entry - signal.stop_loss) * pip_mult
        if sl_pips < 1:
            return RiskCalculationResult(
                trade_allowed=False,
                recommended_lot=0.0,
                max_safe_lot=0.0,
                risk_used_percent=0.0,
                daily_dd_after=account_state.daily_dd_percent,
                total_dd_after=account_state.total_dd_percent,
                severity=RiskSeverity.CRITICAL,
                reason=f"Invalid SL distance: {sl_pips:.2f} pips",
            )

        # ── 3. Adjusted risk (DD multiplier) ─────────────────────────────────
        mult = dd_multiplier(account_state.daily_dd_percent)
        adj_risk_pct = risk_percent * mult

        # ── 4. Risk amount and lot size ───────────────────────────────────────
        risk_amount = account_state.equity * adj_risk_pct / 100.0
        raw_lot = risk_amount / (sl_pips * pip_val)
        lot = max(self.MIN_LOT, min(self.MAX_LOT, self._round_lot(raw_lot)))

        # ── 5. DD projections ─────────────────────────────────────────────────
        dd_after = account_state.daily_dd_percent + adj_risk_pct
        total_dd_after = account_state.total_dd_percent + adj_risk_pct

        # ── 6. Prop firm guard (DD-based limits) ──────────────────────────────
        try:
            mgr = PropFirmManager(prop_firm_code)
            guard = mgr.evaluate_trade(
                account_state={
                    "daily_dd_percent": account_state.daily_dd_percent,
                    "total_dd_percent": account_state.total_dd_percent,
                    "open_trades": account_state.open_trades,
                    "balance": account_state.balance,
                },
                trade_risk={
                    "daily_dd_after": dd_after,
                    "total_dd_after": total_dd_after,
                },
            )
            if not guard.allowed:
                return RiskCalculationResult(
                    trade_allowed=False,
                    recommended_lot=0.0,
                    max_safe_lot=0.0,
                    risk_used_percent=round(adj_risk_pct, 3),
                    daily_dd_after=round(dd_after, 3),
                    total_dd_after=round(total_dd_after, 3),
                    severity=_map_guard_severity(guard.severity),
                    reason=f"{guard.code}: {guard.details}",
                )
        except Exception as exc:
            logger.warning("PropFirmManager error for %s: %s", prop_firm_code, exc)

        # ── 7. Severity label ─────────────────────────────────────────────────
        severity = (
            RiskSeverity.CRITICAL if dd_after >= 4.0 else RiskSeverity.WARNING if dd_after >= 2.5 else RiskSeverity.SAFE
        )

        # ── 8. Split legs ─────────────────────────────────────────────────────
        split_lots = None
        if risk_mode == RiskMode.SPLIT and split_ratios:
            split_lots = [max(self.MIN_LOT, self._round_lot(lot * r)) for r in split_ratios]

        return RiskCalculationResult(
            trade_allowed=True,
            recommended_lot=lot,
            max_safe_lot=lot,
            risk_used_percent=round(adj_risk_pct, 3),
            daily_dd_after=round(dd_after, 3),
            total_dd_after=round(total_dd_after, 3),
            severity=severity,
            reason="APPROVED",
            split_lots=split_lots,
        )

    @staticmethod
    def _round_lot(lot: float) -> float:
        """Round to 0.01 lot step (floor, never round up for safety)."""
        return math.floor(lot * 100) / 100.0


# ── [BUG-2 FIX] Aliases defined AFTER class — no NameError on import ─────────
RiskMultiplier = RiskMultiplierAggregator
RiskEngine = RiskMultiplierAggregator
