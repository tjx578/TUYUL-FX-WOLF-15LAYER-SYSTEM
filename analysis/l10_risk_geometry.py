"""
📐 L10 — Risk Geometry Layer (PRODUCTION)
--------------------------------------------
Computes trade risk geometry: SL/TP distances, R:R ratio,
pip value lookup, and risk fraction validation.

This is the ANALYSIS portion of position sizing.
It does NOT consume account balance or produce lot sizes.
Actual position sizing lives in risk/position_sizer.py
(dashboard/risk authority).

Zone: analysis/ — pure read-only analysis, no execution side-effects.
"""

import logging

from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["analyze_risk_geometry"]

# ── Pip Multipliers ──────────────────────────────────────────────────
# Maps pair patterns to the multiplier that converts price difference → pips.
# Standard FX: 1 pip = 0.0001 → multiplier 10_000
# JPY pairs:   1 pip = 0.01   → multiplier 100
# XAUUSD:      1 pip = 0.10   → multiplier 10
# XAGUSD:      1 pip = 0.01   → multiplier 100
_PIP_MULTIPLIERS: dict[str, float] = {
    "XAUUSD": 10.0,
    "XAGUSD": 100.0,
}
_PIP_MULT_JPY = 100.0
_PIP_MULT_STANDARD = 10_000.0

# ── Pip Values (per standard lot, USD-denominated accounts) ──────────
# NOTE: These are approximate and valid only for USD-denominated accounts.
# For non-USD accounts, the position sizer must apply a conversion rate.
PIP_VALUES_USD: dict[str, float] = {
    "EURUSD": 10.0,
    "GBPUSD": 10.0,
    "AUDUSD": 10.0,
    "NZDUSD": 10.0,
    "USDJPY": 6.67,
    "USDCHF": 10.0,
    "USDCAD": 7.50,
    "GBPJPY": 6.67,
    "EURJPY": 6.67,
    "EURGBP": 12.50,
    "XAUUSD": 10.0,   # per 1 lot (100 oz), $0.10 move = $10
    "XAGUSD": 50.0,   # per 1 lot (5000 oz), $0.01 move = $50
}

_DEFAULT_PIP_VALUE = 10.0

# ── Risk Fraction Limits ────────────────────────────────────────────
_MAX_RISK_PCT = 5.0    # Absolute ceiling — even analysis flags above this
_MIN_RISK_PCT = 0.1    # Below this is unusable

# ── R:R Thresholds ──────────────────────────────────────────────────
_RR_EXCELLENT = 3.0
_RR_GOOD = 2.0
_RR_ACCEPTABLE = 1.0
_RR_POOR = 0.5


def _get_pip_multiplier(pair: str) -> float:
    """Return the price-to-pip multiplier for a given pair."""
    pair_upper = pair.upper()
    if pair_upper in _PIP_MULTIPLIERS:
        return _PIP_MULTIPLIERS[pair_upper]
    if "JPY" in pair_upper:
        return _PIP_MULT_JPY
    return _PIP_MULT_STANDARD


def _get_pip_value(pair: str) -> tuple[float, bool]:
    """Return (pip_value_per_lot, is_approximate).

    is_approximate is True when using the default fallback.
    """
    pair_upper = pair.upper()
    if pair_upper in PIP_VALUES_USD:
        return PIP_VALUES_USD[pair_upper], False
    return _DEFAULT_PIP_VALUE, True


def _classify_rr(rr: float) -> str:
    """Classify risk-reward ratio quality."""
    if rr >= _RR_EXCELLENT:
        return "EXCELLENT"
    if rr >= _RR_GOOD:
        return "GOOD"
    if rr >= _RR_ACCEPTABLE:
        return "ACCEPTABLE"
    if rr >= _RR_POOR:
        return "POOR"
    return "UNACCEPTABLE"


def _infer_direction(entry: float, sl: float, tp: float) -> str | None:
    """Infer trade direction from entry/SL/TP geometry.

    Returns "LONG", "SHORT", or None if ambiguous.
    """
    if entry == 0 or sl == 0 or tp == 0:
        return None
    if sl < entry < tp:
        return "LONG"
    if tp < entry < sl:
        return "SHORT"
    return None


def _validate_geometry(
    entry: float,
    sl: float,
    tp: float,
    direction: str | None,
) -> list[str]:
    """Validate logical consistency of entry/SL/TP. Return list of warnings."""
    warnings: list[str] = []

    if entry <= 0:
        warnings.append("ENTRY_ZERO_OR_NEGATIVE")
    if sl <= 0:
        warnings.append("SL_ZERO_OR_NEGATIVE")
    if tp <= 0:
        warnings.append("TP_ZERO_OR_NEGATIVE")

    if entry > 0 and sl > 0 and tp > 0:
        if direction is None:
            warnings.append("AMBIGUOUS_DIRECTION(entry/SL/TP inconsistent)")
        if direction == "LONG":
            if sl >= entry:
                warnings.append("SL_ABOVE_ENTRY_FOR_LONG")
            if tp <= entry:
                warnings.append("TP_BELOW_ENTRY_FOR_LONG")
        elif direction == "SHORT":
            if sl <= entry:
                warnings.append("SL_BELOW_ENTRY_FOR_SHORT")
            if tp >= entry:
                warnings.append("TP_ABOVE_ENTRY_FOR_SHORT")

    return warnings


def analyze_risk_geometry(
    trade_params: dict[str, Any],
    risk_data: dict[str, Any] | None = None,
    pair: str = "GBPUSD",
    now: datetime | None = None,
) -> dict[str, Any]:
    """L10 Risk Geometry — PRODUCTION.

    Pure analysis function.  Computes SL/TP distances in pips,
    risk-reward ratio, pip value lookup, and risk fraction validation.

    Does NOT consume account balance or produce lot sizes.
    Position sizing is dashboard/risk authority (see risk/position_sizer.py).

    Parameters
    ----------
    trade_params : dict
        Must contain ``entry``, ``stop_loss``, ``take_profit``.
        Optionally ``direction`` ("LONG"|"SHORT") — inferred if absent.
    risk_data : dict, optional
        Risk parameters: ``max_risk_pct``, ``risk_multiplier``.
        Used for risk fraction validation only (not lot computation).
    pair : str
        Currency pair for pip multiplier and pip value lookup.
    now : datetime, optional
        UTC timestamp override (for deterministic testing).

    Returns
    -------
    dict
        Risk geometry profile with ``sl_pips``, ``tp_pips``, ``rr_ratio``,
        ``rr_quality``, ``pip_value``, ``pip_multiplier``, ``direction``,
        ``risk_fraction``, ``valid``, etc.

        Downstream consumers (risk/position_sizer.py) use ``sl_pips``,
        ``pip_value``, and ``risk_fraction`` to compute lot sizes
        with account state.
    """
    if now is None:
        now = datetime.now(UTC)

    rd = risk_data or {}
    warnings: list[str] = []
    degraded_fields: list[str] = []

    # ── Extract trade parameters ──
    entry = float(trade_params.get("entry", 0.0))
    sl = float(trade_params.get("stop_loss", 0.0))
    tp = float(trade_params.get("take_profit", 0.0))

    # ── Direction ──
    explicit_direction = trade_params.get("direction")
    inferred_direction = _infer_direction(entry, sl, tp)

    if explicit_direction:
        direction = explicit_direction.upper()
        if inferred_direction and direction != inferred_direction:
            warnings.append(
                f"DIRECTION_MISMATCH(explicit={direction}, "
                f"inferred={inferred_direction})"
            )
    else:
        direction = inferred_direction

    # ── Validate geometry ──
    geom_warnings = _validate_geometry(entry, sl, tp, direction)
    warnings.extend(geom_warnings)

    # ── Pip calculations ──
    pip_mult = _get_pip_multiplier(pair)
    pip_value, pip_value_approx = _get_pip_value(pair)

    if pip_value_approx:
        degraded_fields.append("pip_value_approximate")

    # SL distance in pips
    if entry > 0 and sl > 0:
        sl_pips = abs(entry - sl) * pip_mult
    else:
        sl_pips = 0.0
        warnings.append("CANNOT_COMPUTE_SL_PIPS(missing entry or SL)")

    # TP distance in pips
    if entry > 0 and tp > 0:
        tp_pips = abs(tp - entry) * pip_mult
    else:
        tp_pips = 0.0
        warnings.append("CANNOT_COMPUTE_TP_PIPS(missing entry or TP)")

    # ── Risk-Reward Ratio ──
    if sl_pips > 0 and tp_pips > 0:
        rr_ratio = tp_pips / sl_pips
    else:
        rr_ratio = 0.0

    rr_quality = _classify_rr(rr_ratio)

    # ── Risk fraction validation ──
    max_risk_pct = float(rd.get("max_risk_pct", 1.0))
    risk_multiplier = float(rd.get("risk_multiplier", 1.0))
    effective_risk_pct = max_risk_pct * risk_multiplier

    risk_warnings: list[str] = []
    if effective_risk_pct > _MAX_RISK_PCT:
        risk_warnings.append(
            f"RISK_PCT_EXCEEDS_CEILING({effective_risk_pct:.2f}%>{_MAX_RISK_PCT}%)"
        )
        effective_risk_pct = _MAX_RISK_PCT
    elif effective_risk_pct < _MIN_RISK_PCT:
        risk_warnings.append(
            f"RISK_PCT_BELOW_MINIMUM({effective_risk_pct:.2f}%<{_MIN_RISK_PCT}%)"
        )
    warnings.extend(risk_warnings)

    valid = sl_pips > 0  # Minimum requirement: computable SL distance

    logger.debug(
        "L10 geometry: pair=%s dir=%s sl_pips=%.1f tp_pips=%.1f "
        "rr=%.2f(%s) risk_pct=%.2f%% valid=%s",
        pair, direction, sl_pips, tp_pips, rr_ratio, rr_quality,
        effective_risk_pct, valid,
    )

    return {
        # ── Core geometry (consumed by risk/position_sizer.py) ──
        "sl_pips": round(sl_pips, 1),
        "tp_pips": round(tp_pips, 1),
        "rr_ratio": round(rr_ratio, 2),
        "rr_quality": rr_quality,
        "pip_value": pip_value,
        "pip_multiplier": pip_mult,
        "direction": direction,
        # ── Risk fraction (analysis-side validation only) ──
        "max_risk_pct": round(max_risk_pct, 2),
        "risk_multiplier": round(risk_multiplier, 2),
        "effective_risk_pct": round(effective_risk_pct, 2),
        # ── Trade params echo (for downstream audit) ──
        "entry": entry,
        "stop_loss": sl,
        "take_profit": tp,
        "pair": pair,
        # ── Metadata ──
        "valid": valid,
        "warnings": warnings,
        "degraded_fields": degraded_fields,
        "timestamp": now.isoformat(),
    }
