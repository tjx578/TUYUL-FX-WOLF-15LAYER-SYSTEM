"""
🔬 L8 -- TII Integrity Layer (PRODUCTION)
============================================
Technical Integrity Index + Triple Wolf Momentum Score.

**Canonical TII computation lives in ``analysis.l8_tii``.**
This module provides:
  - ``L8TIIIntegrityAnalyzer`` — class-based pipeline-compatible API
  - ``analyze_tii`` — standalone function (delegates to canonical impl)

Sources (optional enhancement):
    core_reflective_unified.py -> AdaptiveTIIThresholds
    core_quantum_unified.py    -> ConfidenceMultiplier

Gate Logic:
    IF TII < gate_threshold (default 0.60) -> CLOSED -> HOLD
    Integrity = TII * 0.60 + TWMS * 0.40

Zone: analysis/ -- pure computation, zero side-effects.
"""  # noqa: N999

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, Final

# ── Canonical imports from analysis.l8_tii (single source of truth) ──
from analysis.l8_tii import (
    _clamp,
    _classify_tii,
    _compute_tii,
    _compute_twms,
    classify_tii_grade,
)

logger = logging.getLogger(__name__)

__all__ = ["L8TIIIntegrityAnalyzer", "analyze_tii"]

# ═══════════════════════════════════════════════════════════════════════
# §1  CONSTANTS
# ═══════════════════════════════════════════════════════════════════════

DEFAULT_GATE_THRESHOLD: Final[float] = 0.60

# Integrity blend weights
_W_TII_INTEGRITY: Final[float] = 0.60
_W_TWMS_INTEGRITY: Final[float] = 0.40

# Fallback lookbacks (used by L8TIIIntegrityAnalyzer only)
_VWAP_LOOKBACK: Final[int] = 50
_ENERGY_LOOKBACK: Final[int] = 20
_BIAS_SHORT: Final[int] = 10
_BIAS_LONG: Final[int] = 50

# ═══════════════════════════════════════════════════════════════════════
# §2  OPTIONAL CORE MODULE INTEGRATION
# ═══════════════════════════════════════════════════════════════════════

_core_reflective = None
_ConfidenceMultiplier = None

try:
    import core.core_reflective_unified as _core_reflective
    from core.core_quantum_unified import ConfidenceMultiplier as _ConfidenceMultiplier
except ImportError:
    pass  # Standalone mode -- all computation is self-contained


# ═══════════════════════════════════════════════════════════════════════
# §3  FALLBACK ESTIMATORS (when L3 data is missing)
# ═══════════════════════════════════════════════════════════════════════


def _estimate_vwap(closes: list[float]) -> float:
    """Estimate VWAP from closes using linearly-increasing weights."""
    if not closes or len(closes) < 5:
        return 0.0
    window = closes[-_VWAP_LOOKBACK:]
    weights = [1.0 + i / len(window) for i in range(len(window))]
    return sum(p * w for p, w in zip(window, weights, strict=False)) / sum(weights)


def _estimate_energy(closes: list[float]) -> float:
    """Estimate TRQ energy from recent price volatility.

    Scale factor 1000 maps typical FX bar-to-bar moves to the ~0–10
    energy range; the canonical ``_fallback_energy`` in ``l8_tii``
    uses 500 for a 0–5 range, but this wrapper is only used when the
    canonical path is bypassed.
    """
    if not closes or len(closes) < 3:
        return 0.0
    recent = closes[-_ENERGY_LOOKBACK:]
    diffs = [abs(recent[i] - recent[i - 1]) for i in range(1, len(recent))]
    _ENERGY_SCALE = 1000  # Broader range than canonical (500) for fallback  # noqa: N806
    return (sum(diffs) / len(diffs)) * _ENERGY_SCALE if diffs else 0.0


def _estimate_bias(closes: list[float]) -> float:
    """Estimate directional bias from short vs long SMA."""
    if not closes or len(closes) < _BIAS_LONG:
        return 0.0
    short_avg = sum(closes[-_BIAS_SHORT:]) / _BIAS_SHORT
    long_avg = sum(closes[-_BIAS_LONG:]) / _BIAS_LONG
    return (short_avg - long_avg) / long_avg if long_avg != 0.0 else 0.0


# ═══════════════════════════════════════════════════════════════════════
# §7  STANDALONE FUNCTION API
# ═══════════════════════════════════════════════════════════════════════


def analyze_tii(
    market_data: dict[str, Any],
    l3_data: dict[str, Any] | None = None,
    l1_data: dict[str, Any] | None = None,
    indicators: dict[str, Any] | None = None,
    *,
    gate_threshold: float = DEFAULT_GATE_THRESHOLD,
) -> dict[str, Any]:
    """L8 TII + Integrity Analysis -- standalone entry point.

    Args:
        market_data: Dict with ``closes`` (or ``close``) list.
        l3_data: L3 output (``vwap``, ``energy``, ``bias_strength``).
        l1_data: L1 output (``regime_confidence``).
        indicators: Dict with ``mfi``, ``cci``, ``rsi``, ``momentum``.
        gate_threshold: TII threshold for gate pass (default 0.60).

    Returns:
        Full L8 result dict.
    """
    closes = market_data.get("closes", market_data.get("close", []))
    l3 = l3_data or {}
    ind = indicators or {}

    price = float(closes[-1]) if closes else 0.0
    vwap = float(l3.get("vwap", 0.0))
    energy = float(l3.get("energy", 0.0))
    bias = float(l3.get("bias_strength", 0.0))

    # Fallbacks when L3 data is absent
    if vwap == 0.0 and closes and len(closes) >= 20:
        vwap = _estimate_vwap(closes)
    if energy == 0.0 and closes and len(closes) >= 3:
        energy = _estimate_energy(closes)
    if bias == 0.0 and closes and len(closes) >= _BIAS_LONG:
        bias = _estimate_bias(closes)

    reflect = float(l1_data.get("regime_confidence", 0.7)) if l1_data else 0.7

    # ── TII ──
    tii_result = _compute_tii(
        price=price,
        vwap=vwap,
        trq_energy=energy,
        bias_strength=bias,
        reflective_intensity=reflect,
        meta_integrity=0.97,
    )

    # ── TWMS ──
    twms = _compute_twms(
        mfi=float(ind.get("mfi", 50)),
        cci=float(ind.get("cci", 0)),
        rsi=float(ind.get("rsi", 50)),
        momentum=float(ind.get("momentum", 0)),
    )

    # ── Integrity (blended) ──
    integrity = round(
        tii_result["tii"] * _W_TII_INTEGRITY + twms["twms_score"] * _W_TWMS_INTEGRITY,
        4,
    )

    # ── Gate ──
    gate_passed = tii_result["tii"] >= gate_threshold

    # ── TII Grade (0-1 → 0-100 scale for grading) ──
    tii_grade = classify_tii_grade(tii_result["tii"] * 100.0)

    return {
        "tii_sym": tii_result["tii"],
        "tii_status": tii_result["tii_status"],
        "tii_grade": tii_grade.value,
        "integrity": integrity,
        "twms_score": twms["twms_score"],
        "gate_status": "OPEN" if gate_passed else "CLOSED",
        "gate_passed": gate_passed,
        "valid": True,
        "components": tii_result["components"],
        "twms_signals": twms["signals"],
        "computed_vwap": round(vwap, 5),
        "computed_energy": round(energy, 4),
        "computed_bias": round(bias, 6),
        "timestamp": datetime.now(UTC).isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════
# §8  CLASS-BASED API (pipeline compatible)
# ═══════════════════════════════════════════════════════════════════════


class L8TIIIntegrityAnalyzer:
    """Layer 8: TII Integrity Analyzer -- PRODUCTION.

    Class-based API for pipeline integration. Wraps :func:`analyze_tii`
    and optionally leverages core modules when available.

    Usage::

        analyzer = L8TIIIntegrityAnalyzer()
        result = analyzer.analyze(layer_outputs)
    """

    def __init__(self, gate_threshold: float = DEFAULT_GATE_THRESHOLD) -> None:
        self._gate_threshold = gate_threshold
        self._tii_thresholds = None
        self._confidence_mult = None

    def _try_load_core(self) -> None:
        """Attempt to load optional core modules for enhanced scoring."""
        if self._tii_thresholds is not None:
            return
        try:
            if _core_reflective is not None and _ConfidenceMultiplier is not None:
                self._tii_thresholds = _core_reflective.AdaptiveTIIThresholds()  # pyright: ignore[reportAttributeAccessIssue]
                self._confidence_mult = _ConfidenceMultiplier()
                logger.debug("[L8] Core modules loaded for enhanced TII")
        except Exception as exc:
            logger.warning("[L8] Core modules unavailable, using standalone: %s", exc)

    def analyze(self, layer_outputs: dict[str, Any]) -> dict[str, Any]:
        """Compute TII and validate integrity.

        Args:
            layer_outputs: Dict with keys like ``market_data``, ``l1``, ``l3``,
                ``indicators``, or flattened fields (``closes``, ``vwap``, etc.).

        Returns:
            Full L8 result dict with ``tii_sym``, ``tii_status``, ``integrity``,
            ``twms_score``, ``gate_status``, ``gate_passed``, ``valid``.
        """
        self._try_load_core()

        # ── Extract sub-dicts from pipeline output ──
        market_data = layer_outputs.get("market_data", {})
        if not market_data:
            # Fallback: treat layer_outputs itself as market data source
            market_data = {
                "closes": layer_outputs.get("closes", layer_outputs.get("close", [])),
            }

        l3_data = layer_outputs.get("l3", layer_outputs.get("L3", {}))
        l1_data = layer_outputs.get("l1", layer_outputs.get("L1", {}))
        indicators = layer_outputs.get("indicators", {})

        # ── Core module enhancement (if available) ──
        core_adjustment = 0.0
        if self._confidence_mult is not None:
            try:
                frpc = float(layer_outputs.get("frpc", 0.0))
                tii_raw = float(layer_outputs.get("tii_score", 0.0))
                if frpc > 0 and tii_raw > 0:
                    cm = self._confidence_mult.calculate(frpc, tii_raw)
                    # Dampen the raw multiplier delta to a small TII adjustment
                    # (±0.05). This keeps core enhancement as a tiebreaker without
                    # dominating the 5-component TII model.
                    _CORE_DAMPEN = 0.05  # noqa: N806
                    core_adjustment = (cm.multiplier - 1.0) * _CORE_DAMPEN
                    logger.debug("[L8] Core confidence adjustment: %.4f", core_adjustment)
            except Exception as exc:
                logger.debug("[L8] Core adjustment skipped: %s", exc)

        # ── Delegate to pure computation ──
        result = analyze_tii(
            market_data=market_data,
            l3_data=l3_data,
            l1_data=l1_data,
            indicators=indicators,
            gate_threshold=self._gate_threshold,
        )

        # ── Apply core enhancement if available ──
        if core_adjustment != 0.0:
            adjusted_tii = _clamp(result["tii_sym"] + core_adjustment)
            result["tii_sym"] = round(adjusted_tii, 4)
            result["tii_status"] = _classify_tii(adjusted_tii)
            result["gate_passed"] = adjusted_tii >= self._gate_threshold
            result["gate_status"] = "OPEN" if result["gate_passed"] else "CLOSED"
            result["integrity"] = round(
                adjusted_tii * _W_TII_INTEGRITY + result["twms_score"] * _W_TWMS_INTEGRITY,
                4,
            )
            result["core_enhanced"] = True

        return result
