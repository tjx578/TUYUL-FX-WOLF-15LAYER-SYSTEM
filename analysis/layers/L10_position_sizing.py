"""
L10 -- Position Sizing & Risk Geometry (PRODUCTION)
====================================================
Merged & upgraded from:
  • L10_position.py       (placeholder -> REPLACED with real computation)
  • l10_risk_geometry.py  (production geometry -> PRESERVED & extended)

Pipeline Flow:
  L6 risk gate ──┐
  L8 TII gate  ──┤
  L9 SMC entry ──┼──->  L10PositionAnalyzer.analyze()  ──->  lot_size
  Account state ─┘     │                                    entry/sl/tp
                        ├─ (1) Risk Geometry                direction
                        ├─ (2) FTA Confidence Adjustment    risk_amount
                        ├─ (3) Lot Size Computation         position_ok
                        └─ (4) Prop Firm Compliance         meta_state

Backward compatibility:
  • analyze_risk_geometry() tetap tersedia (signature identik)
  • L10PositionAnalyzer class tetap tersedia (signature diperluas)
  • Semua output field dari kedua file original tetap ada

Zone: analysis/ -- pure computation, zero side-effects.
"""

from __future__ import annotations

import logging
import math

from datetime import UTC, datetime
from typing import Any, Final

logger = logging.getLogger(__name__)

__all__ = ["L10PositionAnalyzer", "analyze_risk_geometry"]


# ═══════════════════════════════════════════════════════════════════════
# §1  PIP CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════

# Price-to-pip multipliers
#   Standard FX: 1 pip = 0.0001 -> multiplier 10_000
#   JPY pairs:   1 pip = 0.01   -> multiplier 100
#   XAUUSD:      1 pip = 0.10   -> multiplier 10
#   XAGUSD:      1 pip = 0.01   -> multiplier 100

_PIP_MULTIPLIERS: Final[dict[str, float]] = {
    "XAUUSD": 10.0,
    "XAGUSD": 100.0,
}
_PIP_MULT_JPY: Final = 100.0
_PIP_MULT_STANDARD: Final = 10_000.0

# Pip value per standard lot (1.0 lot), USD-denominated accounts.
# For non-USD accounts the caller must apply a conversion rate.

PIP_VALUES_USD: Final[dict[str, float]] = {
    # Majors
    "EURUSD": 10.0,   "GBPUSD": 10.0,   "AUDUSD": 10.0,
    "NZDUSD": 10.0,   "USDJPY": 6.67,   "USDCHF": 10.0,
    "USDCAD": 7.50,
    # Crosses
    "GBPJPY": 6.67,   "EURJPY": 6.67,   "EURGBP": 12.50,
    "AUDJPY": 6.67,   "NZDJPY": 6.67,   "CADJPY": 6.67,
    "CHFJPY": 6.67,   "EURAUD": 6.50,   "EURNZD": 6.00,
    "EURCAD": 7.50,   "GBPAUD": 6.50,   "GBPNZD": 6.00,
    "GBPCAD": 7.50,   "GBPCHF": 10.0,   "AUDNZD": 6.00,
    "AUDCAD": 7.50,   "NZDCAD": 7.50,
    # Metals
    "XAUUSD": 10.0,   # 100 oz × $0.10/pip = $10/pip per lot
    "XAGUSD": 50.0,   # 5000 oz × $0.01/pip = $50/pip per lot
}

_DEFAULT_PIP_VALUE: Final = 10.0


# ═══════════════════════════════════════════════════════════════════════
# §2  RISK CONSTANTS
# ═══════════════════════════════════════════════════════════════════════

# Risk fraction limits (absolute hard cap)
_MAX_RISK_PCT: Final = 5.0
_MIN_RISK_PCT: Final = 0.1
_DEFAULT_RISK_PCT: Final = 1.0

# R:R classification thresholds
_RR_EXCELLENT: Final = 3.0
_RR_GOOD: Final = 2.0
_RR_ACCEPTABLE: Final = 1.0
_RR_POOR: Final = 0.5

# Lot precision
_LOT_MIN: Final = 0.01
_LOT_MAX: Final = 10.0
_LOT_STEP: Final = 0.01

# FTA (Fundamental-Technical Alignment) confidence -> risk multiplier
# Higher confidence -> allows bigger position; lower -> defensive cut.
_FTA_BANDS: Final[list[tuple[float, float, float, str]]] = [
    # (min_conf, max_conf, multiplier, label)
    (0.90, 1.01, 1.20, "VERY_HIGH"),   # ≥90% -> 120% of base risk
    (0.75, 0.90, 1.00, "HIGH"),         # 75-89% -> 100% (baseline)
    (0.60, 0.75, 0.80, "MODERATE"),     # 60-74% -> 80%
    (0.40, 0.60, 0.60, "LOW"),          # 40-59% -> 60%
    (0.00, 0.40, 0.50, "VERY_LOW"),     # <40%   -> 50% (defensive)
]

# Prop firm compliance gates
_PROP_MAX_DAILY_DD_PCT: Final = 3.0
_PROP_MAX_TOTAL_DD_PCT: Final = 5.0
_PROP_MAX_POSITIONS: Final = 5
_PROP_MIN_RR: Final = 1.5


# ═══════════════════════════════════════════════════════════════════════
# §3  HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════

def _get_pip_multiplier(pair: str) -> float:
    """Price-difference -> pip conversion multiplier."""
    p = pair.upper()
    if p in _PIP_MULTIPLIERS:
        return _PIP_MULTIPLIERS[p]
    return _PIP_MULT_JPY if "JPY" in p else _PIP_MULT_STANDARD


def _get_pip_value(pair: str) -> tuple[float, bool]:
    """Return (pip_value_per_lot, is_approximate).

    ``is_approximate=True`` when using fallback default.
    """
    p = pair.upper()
    if p in PIP_VALUES_USD:
        return PIP_VALUES_USD[p], False
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
    """Infer LONG/SHORT from entry/SL/TP geometry.

    Returns ``None`` if any value is zero or geometry is ambiguous.
    """
    if entry <= 0 or sl <= 0 or tp <= 0:
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
    """Validate logical consistency of entry/SL/TP.  Return warnings."""
    w: list[str] = []

    if entry <= 0:
        w.append("ENTRY_ZERO_OR_NEGATIVE")
    if sl <= 0:
        w.append("SL_ZERO_OR_NEGATIVE")
    if tp <= 0:
        w.append("TP_ZERO_OR_NEGATIVE")

    if entry > 0 and sl > 0 and tp > 0:
        if direction is None:
            w.append("AMBIGUOUS_DIRECTION(entry/SL/TP inconsistent)")
        elif direction == "LONG":
            if sl >= entry:
                w.append("SL_ABOVE_ENTRY_FOR_LONG")
            if tp <= entry:
                w.append("TP_BELOW_ENTRY_FOR_LONG")
        elif direction == "SHORT":
            if sl <= entry:
                w.append("SL_BELOW_ENTRY_FOR_SHORT")
            if tp >= entry:
                w.append("TP_ABOVE_ENTRY_FOR_SHORT")

    return w


def _fta_multiplier(confidence: float) -> tuple[float, str]:
    """Map confidence (0-1) to (risk_multiplier, label).

    Uses the ``_FTA_BANDS`` table.  Clamps input to [0, 1].
    """
    c = max(0.0, min(1.0, confidence))
    for lo, hi, mult, label in _FTA_BANDS:
        if lo <= c < hi:
            return mult, label
    return _FTA_BANDS[-1][2], _FTA_BANDS[-1][3]


def _compute_lot_size(
    risk_amount: float,
    sl_pips: float,
    pip_value: float,
) -> float:
    """Core lot formula: ``lot = risk_amount / (sl_pips × pip_value)``.

    Always rounds DOWN to ``_LOT_STEP`` to never exceed intended risk.

    Example::

        $100 / (30 pips × $10/pip/lot) = 0.33 lots
    """
    if sl_pips <= 0 or pip_value <= 0:
        return _LOT_MIN

    raw = risk_amount / (sl_pips * pip_value)
    stepped = math.floor(raw / _LOT_STEP) * _LOT_STEP

    return max(_LOT_MIN, min(_LOT_MAX, round(stepped, 2)))


def _check_prop_compliance(
    effective_risk_pct: float,
    rr_ratio: float,
    open_positions: int,
    daily_dd_pct: float,
) -> list[str]:
    """Check prop firm risk rules.  Return list of violations (empty = OK)."""
    v: list[str] = []
    if effective_risk_pct > _PROP_MAX_DAILY_DD_PCT:
        v.append(
            f"PROP_DAILY_DD(risk {effective_risk_pct:.2f}% "
            f"> max {_PROP_MAX_DAILY_DD_PCT}%)"
        )
    if daily_dd_pct > _PROP_MAX_TOTAL_DD_PCT:
        v.append(
            f"PROP_TOTAL_DD(dd {daily_dd_pct:.2f}% "
            f"> max {_PROP_MAX_TOTAL_DD_PCT}%)"
        )
    if open_positions >= _PROP_MAX_POSITIONS:
        v.append(
            f"PROP_MAX_POSITIONS({open_positions} >= {_PROP_MAX_POSITIONS})"
        )
    if 0 < rr_ratio < _PROP_MIN_RR:
        v.append(f"PROP_MIN_RR(rr {rr_ratio:.2f} < min {_PROP_MIN_RR})")
    return v


# ═══════════════════════════════════════════════════════════════════════
# §4  MAIN ANALYZER CLASS
# ═══════════════════════════════════════════════════════════════════════

class L10PositionAnalyzer:
    """Layer 10: Position Sizing & Risk Geometry -- PRODUCTION.

    Single entry-point yang menggabungkan risk geometry analysis dengan
    position sizing computation, FTA confidence adjustment, dan prop
    firm compliance checks.

    Menggantikan:
      • L10_position.py (placeholder, return hardcoded)
      • l10_risk_geometry.py (geometry only, tanpa lot sizing)

    Usage::

        analyzer = L10PositionAnalyzer()
        result = analyzer.analyze(
            trade_params={
                "entry": 1.2650,
                "stop_loss": 1.2620,
                "take_profit": 1.2710,
            },
            account_balance=10_000.0,
            pair="GBPUSD",
            risk_data={"max_risk_pct": 1.0, "risk_multiplier": 1.0},
            confidence=0.78,
        )
        # result["lot_size"]   -> 0.33
        # result["risk_amount"] -> 100.0
        # result["rr_ratio"]   -> 2.0
        # result["rr_quality"] -> "GOOD"
    """

    def __init__(self) -> None:
        self._trade_count: int = 0

    def analyze(  # noqa: PLR0912
        self,
        trade_params: dict[str, Any],
        account_balance: float = 10_000.0,
        pair: str = "GBPUSD",
        risk_data: dict[str, Any] | None = None,
        confidence: float = 0.75,
        open_positions: int = 0,
        daily_dd_pct: float = 0.0,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Complete L10 pipeline: geometry -> sizing -> FTA -> compliance.

        Parameters
        ----------
        trade_params : dict
            Required keys: ``entry``, ``stop_loss``, ``take_profit``.
            Optional: ``direction`` (``"LONG"`` | ``"SHORT"``).
        account_balance : float
            Current account balance in USD.
        pair : str
            Currency pair (e.g. ``"GBPUSD"``, ``"XAUUSD"``).
        risk_data : dict, optional
            ``max_risk_pct`` (default 1.0), ``risk_multiplier`` (default 1.0).
        confidence : float
            Combined pipeline confidence (0.0-1.0) dari upstream layers.
            Drives FTA risk adjustment.
        open_positions : int
            Current open positions (prop firm gate).
        daily_dd_pct : float
            Current daily drawdown % (prop firm gate).
        now : datetime, optional
            UTC timestamp override for deterministic testing.

        Returns
        -------
        dict
            Complete position sizing profile.  Key fields:

            **Risk Geometry** (from l10_risk_geometry.py logic):
              ``sl_pips``, ``tp_pips``, ``rr_ratio``, ``rr_quality``,
              ``pip_value``, ``pip_multiplier``, ``direction``

            **Position Sizing** (was placeholder in L10_position.py):
              ``lot_size``, ``risk_amount``, ``adjusted_risk_pct``

            **FTA Adjustment** (was placeholder):
              ``fta_score``, ``fta_multiplier``, ``fta_label``

            **Decision**:
              ``position_ok``, ``meta_state``, ``valid``

            **Compliance**:
              ``prop_violations``, ``warnings``, ``degraded_fields``
        """
        if now is None:
            now = datetime.now(UTC)

        rd = risk_data or {}
        warnings: list[str] = []
        degraded: list[str] = []

        # ── PHASE 1: Parse trade parameters ──────────────────────────

        entry = float(trade_params.get("entry", 0.0))
        sl = float(trade_params.get("stop_loss", 0.0))
        tp = float(trade_params.get("take_profit", 0.0))

        explicit_dir = trade_params.get("direction")
        inferred_dir = _infer_direction(entry, sl, tp)

        if explicit_dir:
            direction: str | None = explicit_dir.upper()
            if inferred_dir and direction != inferred_dir:
                warnings.append(
                    f"DIRECTION_MISMATCH(explicit={direction}, "
                    f"inferred={inferred_dir})"
                )
        else:
            direction = inferred_dir

        # ── PHASE 2: Validate geometry ───────────────────────────────

        geom_warnings = _validate_geometry(entry, sl, tp, direction)
        warnings.extend(geom_warnings)

        # ── PHASE 3: Pip calculations ────────────────────────────────

        pip_mult = _get_pip_multiplier(pair)
        pip_value, pip_approx = _get_pip_value(pair)

        if pip_approx:
            degraded.append("pip_value_approximate")

        if entry > 0 and sl > 0:
            sl_pips = abs(entry - sl) * pip_mult
        else:
            sl_pips = 0.0
            warnings.append("CANNOT_COMPUTE_SL_PIPS(missing entry or SL)")

        if entry > 0 and tp > 0:
            tp_pips = abs(tp - entry) * pip_mult
        else:
            tp_pips = 0.0
            warnings.append("CANNOT_COMPUTE_TP_PIPS(missing entry or TP)")

        # ── PHASE 4: Risk-Reward ratio ───────────────────────────────

        rr_ratio = (tp_pips / sl_pips) if (sl_pips > 0 and tp_pips > 0) else 0.0
        rr_quality = _classify_rr(rr_ratio)

        # ── PHASE 5: Base risk fraction ──────────────────────────────

        max_risk_pct = float(rd.get("max_risk_pct", _DEFAULT_RISK_PCT))
        risk_multiplier = float(rd.get("risk_multiplier", 1.0))
        base_risk_pct = max_risk_pct * risk_multiplier

        if base_risk_pct > _MAX_RISK_PCT:
            warnings.append(
                f"RISK_CAPPED({base_risk_pct:.2f}% -> {_MAX_RISK_PCT}%)"
            )
            base_risk_pct = _MAX_RISK_PCT
        elif base_risk_pct < _MIN_RISK_PCT:
            warnings.append(
                f"RISK_BELOW_MIN({base_risk_pct:.2f}% < {_MIN_RISK_PCT}%)"
            )

        # ── PHASE 6: FTA confidence adjustment ──────────────────────
        #
        # Confidence dari upstream layers (L8 TII, L9 SMC) menentukan
        # seberapa agresif position sizing:
        #   ≥ 0.90  ->  1.20× (sangat yakin, posisi lebih besar)
        #   0.75-0.89 ->  1.00× (baseline, tidak ada adjustment)
        #   0.60-0.74 ->  0.80× (moderate, sedikit defensif)
        #   0.40-0.59 ->  0.60× (rendah, potong setengah)
        #   < 0.40  ->  0.50× (sangat rendah, minimal size)

        fta_mult, fta_label = _fta_multiplier(confidence)
        fta_score = round(confidence * 100.0, 1)

        adjusted_risk_pct = base_risk_pct * fta_mult
        adjusted_risk_pct = max(_MIN_RISK_PCT, min(_MAX_RISK_PCT, adjusted_risk_pct))

        # ── PHASE 7: Position sizing ─────────────────────────────────
        #
        # Formula: lot = risk_amount / (sl_pips × pip_value_per_lot)
        # Contoh:  $100 / (30 pips × $10/pip/lot) = 0.33 lot

        if account_balance <= 0:
            warnings.append("ACCOUNT_BALANCE_ZERO_OR_NEGATIVE")
            risk_amount = 0.0
            lot_size = _LOT_MIN
        else:
            risk_amount = round(
                account_balance * (adjusted_risk_pct / 100.0), 2
            )
            lot_size = _compute_lot_size(risk_amount, sl_pips, pip_value)

        # ── PHASE 8: Prop firm compliance ────────────────────────────

        prop_violations = _check_prop_compliance(
            adjusted_risk_pct, rr_ratio, open_positions, daily_dd_pct,
        )
        if prop_violations:
            warnings.extend(prop_violations)

        # ── PHASE 9: Final decision gates ────────────────────────────

        valid = sl_pips > 0 and direction is not None
        geometry_ok = valid and len(geom_warnings) == 0
        risk_ok = adjusted_risk_pct <= _MAX_RISK_PCT and rr_ratio >= _RR_ACCEPTABLE
        prop_ok = len(prop_violations) == 0
        position_ok = geometry_ok and risk_ok and prop_ok and account_balance > 0

        # Meta state assessment
        if position_ok and fta_label in ("VERY_HIGH", "HIGH"):
            meta_state = "OPTIMAL"
        elif position_ok:
            meta_state = "STABLE"
        elif valid and not risk_ok:
            meta_state = "RISK_DEGRADED"
        elif valid and not prop_ok:
            meta_state = "PROP_VIOLATION"
        else:
            meta_state = "INVALID"

        self._trade_count += 1

        logger.debug(
            "L10 sizing: pair=%s dir=%s sl=%.1f tp=%.1f rr=%.2f(%s) "
            "fta=%.1f(%s) risk=%.2f%% lot=%.2f ok=%s meta=%s",
            pair, direction, sl_pips, tp_pips, rr_ratio, rr_quality,
            fta_score, fta_label, adjusted_risk_pct, lot_size,
            position_ok, meta_state,
        )

        return {
            # ── Risk Geometry ──
            "sl_pips": round(sl_pips, 1),
            "tp_pips": round(tp_pips, 1),
            "rr_ratio": round(rr_ratio, 2),
            "rr_quality": rr_quality,
            "pip_value": pip_value,
            "pip_multiplier": pip_mult,
            "direction": direction,
            # ── Position Sizing ──
            "lot_size": lot_size,
            "risk_amount": risk_amount,
            "adjusted_risk_pct": round(adjusted_risk_pct, 2),
            # ── FTA Adjustment ──
            "fta_score": fta_score,
            "fta_multiplier": round(fta_mult, 2),
            "fta_label": fta_label,
            # ── Risk Parameters (audit echo) ──
            "base_risk_pct": round(max_risk_pct, 2),
            "risk_multiplier": round(risk_multiplier, 2),
            "effective_risk_pct": round(adjusted_risk_pct, 2),
            "account_balance": round(account_balance, 2),
            # ── Trade Parameters (audit echo) ──
            "entry": entry,
            "stop_loss": sl,
            "take_profit": tp,
            "pair": pair,
            # ── Decision ──
            "position_ok": position_ok,
            "meta_state": meta_state,
            "valid": valid,
            # ── Compliance ──
            "prop_violations": prop_violations,
            # ── Metadata ──
            "warnings": warnings,
            "degraded_fields": degraded,
            "timestamp": now.isoformat(),
        }


# ═══════════════════════════════════════════════════════════════════════
# §5  BACKWARD-COMPATIBLE STANDALONE FUNCTION
# ═══════════════════════════════════════════════════════════════════════

def analyze_risk_geometry(
    trade_params: dict[str, Any],
    risk_data: dict[str, Any] | None = None,
    pair: str = "GBPUSD",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Backward-compatible geometry-only analysis.

    Same signature and return shape as the original
    ``l10_risk_geometry.analyze_risk_geometry()``.  Delegates to
    ``L10PositionAnalyzer`` internally but returns only the geometry
    subset that existing callers expect.
    """
    full = L10PositionAnalyzer().analyze(
        trade_params=trade_params,
        pair=pair,
        risk_data=risk_data,
        now=now,
    )

    return {
        "sl_pips": full["sl_pips"],
        "tp_pips": full["tp_pips"],
        "rr_ratio": full["rr_ratio"],
        "rr_quality": full["rr_quality"],
        "pip_value": full["pip_value"],
        "pip_multiplier": full["pip_multiplier"],
        "direction": full["direction"],
        "max_risk_pct": full["base_risk_pct"],
        "risk_multiplier": full["risk_multiplier"],
        "effective_risk_pct": full["effective_risk_pct"],
        "entry": full["entry"],
        "stop_loss": full["stop_loss"],
        "take_profit": full["take_profit"],
        "pair": full["pair"],
        "valid": full["valid"],
        "warnings": full["warnings"],
        "degraded_fields": full["degraded_fields"],
        "timestamp": full["timestamp"],
    }
