"""
🛡️ L6 — Risk Layer (PRODUCTION)
----------------------------------
Pure analysis layer: market-risk and trade-risk scoring.

Responsibilities (analysis zone — NO execution side-effects):
  - Drawdown-tier classification
  - Volatility-adjusted risk multiplier
  - Consecutive-loss scaling
  - LRCE (Layered Risk Containment Envelope) — *market-side only*
  - Circuit-breaker awareness (reads flag, does NOT enforce)

What L6 does NOT do (delegated to risk/ and dashboard/):
  - Prop firm compliance enforcement → [prop_firm.py](http://_vscodecontentref_/8)
  - Account balance/equity decisions  → dashboard
  - Position sizing                   → dashboard

Zone: analysis/ — pure read-only assessment, no execution side-effects.
"""

import logging

from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["analyze_risk"]


# ── Drawdown Tiers ───────────────────────────────────────────────────
# Maps drawdown % ceilings to risk multiplier and status label.
# Evaluated in order; first match wins.

DD_TIERS: list[tuple[str, float, float, str]] = [
    # (level_name, max_dd_pct, risk_mult, status)
    ("LEVEL_0", 1.0,  1.00, "ACCEPTABLE"),
    ("LEVEL_1", 2.0,  0.75, "CAUTION"),
    ("LEVEL_2", 3.0,  0.50, "WARNING"),
    ("LEVEL_3", 5.0,  0.25, "CRITICAL"),
    ("LEVEL_4", 10.0, 0.00, "LOCKOUT"),
]

# Volatility → risk multiplier adjustments
_VOL_ADJUSTMENTS: dict[str, float] = {
    "EXTREME": 0.50,
    "HIGH":    0.75,
    "NORMAL":  1.00,
    "LOW":     1.10,
    "DEAD":    0.80,  # Low vol can precede sudden breakouts
}

# Consecutive-loss thresholds
_CONSEC_LOSS_SEVERE = 3
_CONSEC_LOSS_MODERATE = 2
_CONSEC_LOSS_SEVERE_MULT = 0.50
_CONSEC_LOSS_MODERATE_MULT = 0.75

# LRCE bounds
_LRCE_BASE_RISK_PCT = 1.0
_LRCE_MAX_RISK_PCT = 2.0
_LRCE_MIN_RISK_PCT = 0.0

# Minimum RR for analysis-level flagging
_MIN_RR_RATIO = 1.5


def _classify_drawdown(current_dd_pct: float) -> tuple[str, float, str]:
    """Classify absolute drawdown % into a tier.

    Returns (level_name, risk_multiplier, status_label).
    """
    abs_dd = abs(current_dd_pct)
    for level, max_dd, mult, status in DD_TIERS:
        if abs_dd <= max_dd:
            return level, mult, status
    return "LEVEL_4", 0.0, "LOCKOUT"


def _volatility_adjustment(vol_level: str) -> float:
    """Return the volatility-based risk multiplier."""
    return _VOL_ADJUSTMENTS.get(vol_level, 1.0)


def _consecutive_loss_multiplier(consec_losses: int) -> tuple[float, str | None]:
    """Return (multiplier, warning_or_none) for consecutive losses."""
    if consec_losses >= _CONSEC_LOSS_SEVERE:
        return _CONSEC_LOSS_SEVERE_MULT, f"CONSECUTIVE_LOSSES_{consec_losses}"
    if consec_losses >= _CONSEC_LOSS_MODERATE:
        return _CONSEC_LOSS_MODERATE_MULT, None
    return 1.0, None


def _calc_lrce(
    dd_risk_mult: float,
    open_positions: int,
    max_positions: int,
) -> float:
    """LRCE — Layered Risk Containment Envelope (market-side).

    Returns the max allowed risk % for the next trade based on:
      - Drawdown-adjusted risk multiplier
      - Open-position load factor

    NOTE: Account-level factors (balance, equity) are intentionally excluded.
    Position sizing from LRCE output is the dashboard's responsibility.
    """
    position_factor = max(0.2, 1.0 - (open_positions / max(1, max_positions)))
    lrce = _LRCE_BASE_RISK_PCT * dd_risk_mult * position_factor
    return round(
        max(_LRCE_MIN_RISK_PCT, min(_LRCE_MAX_RISK_PCT, lrce)),
        4,
    )


def analyze_risk(
    market_data: dict[str, Any],
    account_state: dict[str, Any] | None = None,
    trade_params: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """L6 Risk Assessment — PRODUCTION.

    Pure analysis function.  Produces a risk profile consumed downstream
    by Layer-12 (constitution) and dashboard (for prop-firm enforcement).
    No execution side-effects.

    Parameters
    ----------
    market_data : dict
        Should include ``volatility_level`` (from L1).
    account_state : dict, optional
        Lightweight state for drawdown-tier classification:
        ``drawdown_pct``, ``daily_pnl_pct``, ``open_positions``,
        ``consecutive_losses``, ``circuit_breaker_active``.
        NOTE: L6 uses these read-only for risk *scoring* — actual
        enforcement is in `[prop_firm.py](http://_vscodecontentref_/9)`.
    trade_params : dict, optional
        Proposed trade: ``risk_pct``, ``rr_ratio``.
    now : datetime, optional
        UTC timestamp override (for deterministic testing).

    Returns
    -------
    dict
        Risk profile with ``risk_status``, ``risk_ok``, ``lrce``, etc.
    """
    acc = account_state or {}
    trade = trade_params or {}

    if now is None:
        now = datetime.now(UTC)

    # ── Read inputs (read-only, no enforcement) ──
    dd_pct = float(acc.get("drawdown_pct", 0.0))
    daily_pnl_pct = float(acc.get("daily_pnl_pct", 0.0))
    open_pos = int(acc.get("open_positions", 0))
    max_positions = int(acc.get("max_open_positions", 5))
    consec_losses = int(acc.get("consecutive_losses", 0))
    circuit_breaker = bool(acc.get("circuit_breaker_active", False))

    risk_pct = float(trade.get("risk_pct", 1.0))
    rr_ratio = float(trade.get("rr_ratio", 2.0))
    vol_level = str(market_data.get("volatility_level", "NORMAL"))

    warnings: list[str] = []

    # ── 1. Drawdown tier ──
    dd_level, risk_mult, risk_status = _classify_drawdown(dd_pct)

    # ── 2. Circuit breaker (read flag, flag it — enforcement is dashboard's job) ──
    if circuit_breaker:
        risk_status = "LOCKOUT"
        risk_mult = 0.0
        warnings.append("CIRCUIT_BREAKER_ACTIVE")

    # ── 3. Consecutive-loss scaling ──
    cl_mult, cl_warning = _consecutive_loss_multiplier(consec_losses)
    risk_mult *= cl_mult
    if cl_warning:
        warnings.append(cl_warning)

    # ── 4. Volatility adjustment ──
    vol_adj = _volatility_adjustment(vol_level)
    risk_mult *= vol_adj

    # ── 5. LRCE (market-side envelope) ──
    lrce = _calc_lrce(risk_mult, open_pos, max_positions)

    # ── 6. Trade-parameter flags (advisory — not enforcement) ──
    if risk_pct > lrce * 1.1:  # requested risk exceeds envelope by >10%
        warnings.append(
            f"RISK_EXCEEDS_LRCE(requested={risk_pct:.2f}%>lrce={lrce:.2f}%)"
        )

    if rr_ratio < _MIN_RR_RATIO:
        warnings.append(f"LOW_RR_RATIO({rr_ratio:.2f}<{_MIN_RR_RATIO})")

    # Daily drawdown flag (negative PnL only — positive PnL is fine)
    if daily_pnl_pct < 0 and abs(daily_pnl_pct) > 2.5:
        warnings.append(f"DAILY_DD_ELEVATED({daily_pnl_pct:.2f}%)")

    if open_pos >= max_positions:
        warnings.append(f"POSITION_LOAD_FULL({open_pos}/{max_positions})")

    # ── 7. Risk-OK (analysis opinion — Layer-12 makes actual decision) ──
    risk_ok = (
        risk_status not in ("LOCKOUT", "CRITICAL")
        and not circuit_breaker
        and risk_pct <= lrce * 1.1
    )

    # Force LOCKOUT to always fail
    if risk_status == "LOCKOUT":
        risk_ok = False

    logger.debug(
        "L6 risk: dd_level=%s status=%s mult=%.4f lrce=%.4f risk_ok=%s warnings=%s",
        dd_level, risk_status, risk_mult, lrce, risk_ok, warnings,
    )

    return {
        # Core risk profile (consumed by Layer-12)
        "risk_status": risk_status,
        "risk_ok": risk_ok,
        "drawdown_level": dd_level,
        "risk_multiplier": round(risk_mult, 4),
        "lrce": lrce,
        "valid": True,
        # Advisory details
        "warnings": warnings,
        "vol_adjustment": vol_adj,
        "consecutive_losses": consec_losses,
        "open_positions": open_pos,
        "rr_ratio": rr_ratio,
        "requested_risk_pct": risk_pct,
        "timestamp": now.isoformat(),
    }
