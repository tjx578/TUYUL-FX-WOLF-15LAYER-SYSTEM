"""
🔬 L8 -- TII Integrity Layer (PRODUCTION)
============================================
Technical Integrity Index + Triple Wolf Momentum Score.

Sources (optional enhancement):
    core_reflective_unified.py -> AdaptiveTIIThresholds
    core_quantum_unified.py    -> ConfidenceMultiplier

Computes real TII from:
  - Price-VWAP alignment      (25%)
  - TRQ energy coherence       (25%)
  - Bias strength confirmation  (20%)
  - Reflective stability        (15%)
  - Meta integrity              (15%)

Gate Logic:
    IF TII < gate_threshold (default 0.60) -> CLOSED -> HOLD
    Integrity = TII * 0.60 + TWMS * 0.40

Produces:
    - tii_sym (float)          -> target ≥ 0.60
    - tii_status (str)         -> STRONG | VALID | WEAK | INVALID
    - integrity (float)        -> combined TII + TWMS
    - twms_score (float)       -> 0.0-1.0
    - gate_status (str)        -> OPEN | CLOSED
    - gate_passed (bool)
    - valid (bool)
    - components (dict)        -> per-component breakdown
    - twms_signals (list)      -> active momentum signals

Zone: analysis/ -- pure computation, zero side-effects.
"""

from __future__ import annotations

import logging
import math

from datetime import UTC, datetime
from typing import Any, Final

logger = logging.getLogger(__name__)

__all__ = ["L8TIIIntegrityAnalyzer", "analyze_tii"] # type: ignore

# ═══════════════════════════════════════════════════════════════════════
# §1  CONSTANTS
# ═══════════════════════════════════════════════════════════════════════

DEFAULT_GATE_THRESHOLD: Final[float] = 0.60

# TII component weights (must sum to 1.0)
_W_VWAP: Final[float] = 0.25
_W_ENERGY: Final[float] = 0.25
_W_BIAS: Final[float] = 0.20
_W_REFLECT: Final[float] = 0.15
_W_META: Final[float] = 0.15

# Integrity blend weights
_W_TII_INTEGRITY: Final[float] = 0.60
_W_TWMS_INTEGRITY: Final[float] = 0.40

# VWAP fallback lookback
_VWAP_LOOKBACK: Final[int] = 50
_ENERGY_LOOKBACK: Final[int] = 10
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
# §3  PURE COMPUTATION HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp value to [lo, hi]."""
    return max(lo, min(hi, v))


def _score_vwap_alignment(price: float, vwap: float) -> float:
    """Score price-VWAP alignment (0.0-1.0).

    High score when price is near VWAP or has clear directional separation.
    """
    if vwap <= 0.0 or price <= 0.0:
        return 0.0
    deviation = abs(price - vwap) / vwap
    if deviation < 0.001:
        return 0.95
    if deviation < 0.005:
        return 0.85
    if deviation < 0.010:
        return 0.70
    if deviation < 0.020:
        return 0.55
    return max(0.20, 0.50 - deviation * 10)


def _score_energy_coherence(trq_energy: float) -> float:
    """Score TRQ field energy coherence (0.0-1.0)."""
    norm = math.tanh(trq_energy * 0.3)
    if norm > 0.70:
        return 0.95
    if norm > 0.40:
        return 0.75
    if norm > 0.20:
        return 0.55
    if norm > 0.05:
        return 0.40
    return 0.20


def _score_bias_confirmation(bias_strength: float) -> float:
    """Score directional bias strength (0.0-1.0)."""
    b = abs(bias_strength)
    if b > 0.005:
        return 0.90
    if b > 0.002:
        return 0.70
    if b > 0.001:
        return 0.50
    return 0.30


def _classify_tii(tii: float) -> str:
    """Classify TII score into status label."""
    if tii >= 0.80:
        return "STRONG"
    if tii >= 0.60:
        return "VALID"
    if tii >= 0.40:
        return "WEAK"
    return "INVALID"


# ═══════════════════════════════════════════════════════════════════════
# §4  TII COMPUTATION
# ═══════════════════════════════════════════════════════════════════════

def _compute_tii(
    price: float,
    vwap: float,
    trq_energy: float,
    bias_strength: float,
    reflective_intensity: float = 0.85,
    meta_integrity: float = 0.97,
) -> dict[str, Any]:
    """Compute Technical Integrity Index from 5 weighted components.

    Args:
        price: Current price.
        vwap: Volume-weighted average price.
        trq_energy: TRQ field energy value.
        bias_strength: Directional bias (signed).
        reflective_intensity: System self-consistency (0-1).
        meta_integrity: Overall system health (0-1).

    Returns:
        Dict with tii, tii_status, components.
    """
    vwap_score = _score_vwap_alignment(price, vwap)
    energy_score = _score_energy_coherence(trq_energy)
    bias_score = _score_bias_confirmation(bias_strength)
    reflect_score = _clamp(reflective_intensity)
    meta_score = _clamp(meta_integrity)

    tii = round(_clamp(
        vwap_score * _W_VWAP
        + energy_score * _W_ENERGY
        + bias_score * _W_BIAS
        + reflect_score * _W_REFLECT
        + meta_score * _W_META
    ), 4)

    return {
        "tii": tii,
        "tii_status": _classify_tii(tii),
        "components": {
            "vwap_alignment": round(vwap_score, 4),
            "energy_coherence": round(energy_score, 4),
            "bias_confirmation": round(bias_score, 4),
            "reflective_stability": round(reflect_score, 4),
            "meta_integrity": round(meta_score, 4),
        },
    }


# ═══════════════════════════════════════════════════════════════════════
# §5  TWMS COMPUTATION
# ═══════════════════════════════════════════════════════════════════════

def _compute_twms(
    mfi: float = 50.0,
    cci: float = 0.0,
    rsi: float = 50.0,
    momentum: float = 0.0,
) -> dict[str, Any]:
    """Compute Triple Wolf Momentum Score.

    Scores MFI, CCI, RSI, and momentum direction into a 0-1 composite.
    """
    score = 0.0
    signals: list[str] = []

    # MFI scoring (max +0.30)
    if mfi > 70:
        score += 0.30
        signals.append("MFI_OVERBOUGHT")
    elif mfi < 30:
        score += 0.30
        signals.append("MFI_OVERSOLD")
    elif mfi > 55:
        score += 0.15
        signals.append("MFI_BULLISH")
    elif mfi < 45:
        score += 0.15
        signals.append("MFI_BEARISH")

    # CCI scoring (max +0.30)
    if abs(cci) > 100:
        score += 0.30
        signals.append(f"CCI_{'OVERBOUGHT' if cci > 0 else 'OVERSOLD'}")
    elif abs(cci) > 50:
        score += 0.15
        signals.append(f"CCI_{'BULLISH' if cci > 0 else 'BEARISH'}")

    # RSI scoring (max +0.25)
    if rsi > 65 or rsi < 35:
        score += 0.25
        signals.append(f"RSI_{'STRONG' if rsi > 65 else 'WEAK'}")
    elif rsi > 55 or rsi < 45:
        score += 0.10
        signals.append(f"RSI_{'BULLISH' if rsi > 55 else 'BEARISH'}")

    # Momentum scoring (max +0.15)
    if abs(momentum) > 0.5:
        score += 0.15
        signals.append(f"MOM_{'UP' if momentum > 0 else 'DOWN'}")

    return {
        "twms_score": round(min(1.0, score), 4),
        "signals": signals,
    }


# ═══════════════════════════════════════════════════════════════════════
# §6  FALLBACK ESTIMATORS (when L3 data is missing)
# ═══════════════════════════════════════════════════════════════════════

def _estimate_vwap(closes: list[float]) -> float:
    """Estimate VWAP from closes using linearly-increasing weights."""
    if not closes or len(closes) < 5:
        return 0.0
    window = closes[-_VWAP_LOOKBACK:]
    weights = [1.0 + i / len(window) for i in range(len(window))]
    return sum(p * w for p, w in zip(window, weights, strict=False)) / sum(weights)


def _estimate_energy(closes: list[float]) -> float:
    """Estimate TRQ energy from recent price volatility."""
    if not closes or len(closes) < 3:
        return 0.0
    recent = closes[-_ENERGY_LOOKBACK:]
    diffs = [abs(recent[i] - recent[i - 1]) for i in range(1, len(recent))]
    return (sum(diffs) / len(diffs)) * 1000 if diffs else 0.0


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
        tii_result["tii"] * _W_TII_INTEGRITY
        + twms["twms_score"] * _W_TWMS_INTEGRITY,
        4,
    )

    # ── Gate ──
    gate_passed = tii_result["tii"] >= gate_threshold

    return {
        "tii_sym": tii_result["tii"],
        "tii_status": tii_result["tii_status"],
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
                self._tii_thresholds = _core_reflective.AdaptiveTIIThresholds() # pyright: ignore[reportAttributeAccessIssue]
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
                "closes": layer_outputs.get("closes",
                           layer_outputs.get("close", [])),
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
                    core_adjustment = (cm - 1.0) * 0.05  # pyright: ignore[reportOperatorIssue] # Small adjustment
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
                adjusted_tii * _W_TII_INTEGRITY
                + result["twms_score"] * _W_TWMS_INTEGRITY,
                4,
            )
            result["core_enhanced"] = True

        return result
