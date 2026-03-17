"""
🔬 L8 -- TII Integrity Layer (PRODUCTION)
-------------------------------------------
Computes real Technical Integrity Index (TII) from:
  - Price-VWAP alignment
  - TRQ energy coherence
  - Bias strength confirmation
  - Multi-layer cross-validation (reflective + meta)

Also computes TWMS (Triple Wolf Momentum Score) for momentum confirmation.

TII gate threshold for EXECUTE: >= 0.60 (pipeline bridge uses 0.6).

Zone: analysis/ -- pure read-only analysis, no execution side-effects.
"""

import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "analyze_tii",
    "TIIGrade",
    "TIIInputs",
    "TIIResult",
    "classify_tii_grade",
    "compute_tii",
]

# ── TII Component Weights ───────────────────────────────────────────
_W_VWAP = 0.25
_W_ENERGY = 0.25
_W_BIAS = 0.20
_W_REFLECTIVE = 0.15
_W_META = 0.15

# ── TII Gate Threshold ──────────────────────────────────────────────
_TII_GATE_THRESHOLD = 0.60

# ── VWAP Alignment Thresholds (deviation fraction) ──────────────────
_VWAP_VERY_CLOSE = 0.001
_VWAP_CLOSE = 0.005
_VWAP_MODERATE = 0.010
_VWAP_FAR = 0.020

# ── Bias Strength Thresholds ────────────────────────────────────────
_BIAS_STRONG = 0.005
_BIAS_MODERATE = 0.002
_BIAS_WEAK = 0.001

# ── TWMS Thresholds ─────────────────────────────────────────────────
_MFI_EXTREME_HIGH = 70.0
_MFI_EXTREME_LOW = 30.0
_MFI_MILD_HIGH = 55.0
_MFI_MILD_LOW = 45.0

_CCI_EXTREME = 100.0
_CCI_MODERATE = 50.0

_RSI_STRONG_HIGH = 65.0
_RSI_STRONG_LOW = 35.0
_RSI_MILD_HIGH = 55.0
_RSI_MILD_LOW = 45.0

_MOMENTUM_THRESHOLD = 0.5

# ── Minimum bars for various computations ───────────────────────────
_MIN_BARS = 10
_MIN_BARS_VWAP_FALLBACK = 20
_MIN_BARS_BIAS_FALLBACK = 50

# ── Degraded mode meta-integrity penalty ────────────────────────────
_META_FULL_DATA = 0.95
_META_DEGRADED = 0.70


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp value to [lo, hi]."""
    return max(lo, min(hi, v))


def _score_vwap_alignment(price: float, vwap: float) -> float:
    """Score price-VWAP alignment (0.0-1.0).

    High scores when price is near VWAP (institutional fair value).
    Smooth decay for larger deviations.
    """
    if vwap == 0.0 or price == 0.0:
        return 0.0

    deviation = abs(price - vwap) / vwap

    if deviation < _VWAP_VERY_CLOSE:
        return 0.95
    if deviation < _VWAP_CLOSE:
        # Linear interpolation: 0.001->0.95, 0.005->0.80
        t = (deviation - _VWAP_VERY_CLOSE) / (_VWAP_CLOSE - _VWAP_VERY_CLOSE)
        return 0.95 - t * 0.15
    if deviation < _VWAP_MODERATE:
        t = (deviation - _VWAP_CLOSE) / (_VWAP_MODERATE - _VWAP_CLOSE)
        return 0.80 - t * 0.15
    if deviation < _VWAP_FAR:
        t = (deviation - _VWAP_MODERATE) / (_VWAP_FAR - _VWAP_MODERATE)
        return 0.65 - t * 0.15

    # Beyond 2% -- decay smoothly but floor at 0.1
    return max(0.10, 0.50 - (deviation - _VWAP_FAR) * 8)


def _score_energy_coherence(trq_energy: float) -> float:
    """Score TRQ field energy coherence (0.0-1.0).

    Uses tanh normalization for smooth mapping from raw energy.
    """
    energy_norm = math.tanh(trq_energy * 0.3)

    if energy_norm > 0.70:
        return 0.95
    if energy_norm > 0.40:
        t = (energy_norm - 0.40) / 0.30
        return 0.65 + t * 0.30
    if energy_norm > 0.20:
        t = (energy_norm - 0.20) / 0.20
        return 0.45 + t * 0.20
    if energy_norm > 0.05:
        t = (energy_norm - 0.05) / 0.15
        return 0.25 + t * 0.20

    return 0.20


def _score_bias_confirmation(bias_strength: float) -> float:
    """Score directional bias confirmation (0.0-1.0).

    Evaluates absolute bias -- direction is irrelevant for integrity.
    """
    bias_abs = abs(bias_strength)

    if bias_abs > _BIAS_STRONG:
        return 0.90
    if bias_abs > _BIAS_MODERATE:
        t = (bias_abs - _BIAS_MODERATE) / (_BIAS_STRONG - _BIAS_MODERATE)
        return 0.60 + t * 0.30
    if bias_abs > _BIAS_WEAK:
        t = (bias_abs - _BIAS_WEAK) / (_BIAS_MODERATE - _BIAS_WEAK)
        return 0.40 + t * 0.20

    return 0.30


def _classify_tii(tii: float) -> str:
    """Classify TII score into status label."""
    if tii >= 0.80:
        return "STRONG"
    if tii >= _TII_GATE_THRESHOLD:
        return "VALID"
    if tii >= 0.40:
        return "WEAK"
    return "INVALID"


def _compute_tii(
    price: float,
    vwap: float,
    trq_energy: float,
    bias_strength: float,
    reflective_intensity: float,
    meta_integrity: float,
) -> dict[str, Any]:
    """Compute TII (Technical Integrity Index).

    Components:
      1. VWAP Alignment     (25%): Price proximity to VWAP
      2. Energy Coherence   (25%): TRQ field energy validation
      3. Bias Confirmation  (20%): Directional bias strength
      4. Reflective Stability (15%): System self-consistency (L1 confidence)
      5. Meta Integrity     (15%): Data completeness / system health

    Returns dict with tii score, status, components, gate decision.
    """
    vwap_score = _score_vwap_alignment(price, vwap)
    energy_score = _score_energy_coherence(trq_energy)
    bias_score = _score_bias_confirmation(bias_strength)
    reflect_score = _clamp(reflective_intensity)
    meta_score = _clamp(meta_integrity)

    tii = round(
        _clamp(
            vwap_score * _W_VWAP
            + energy_score * _W_ENERGY
            + bias_score * _W_BIAS
            + reflect_score * _W_REFLECTIVE
            + meta_score * _W_META
        ),
        4,
    )

    status = _classify_tii(tii)
    gate_open = tii >= _TII_GATE_THRESHOLD

    return {
        "tii": tii,
        "tii_status": status,
        "gate_status": "OPEN" if gate_open else "CLOSED",
        "gate_passed": gate_open,
        "components": {
            "vwap_alignment": round(vwap_score, 4),
            "energy_coherence": round(energy_score, 4),
            "bias_confirmation": round(bias_score, 4),
            "reflective_stability": round(reflect_score, 4),
            "meta_integrity": round(meta_score, 4),
        },
    }


def _compute_twms(
    mfi: float = 50.0,
    cci: float = 0.0,
    rsi: float = 50.0,
    momentum: float = 0.0,
) -> dict[str, Any]:
    """Compute TWMS (Triple Wolf Momentum Score).

    Scores momentum conviction (not direction) from MFI, CCI, RSI,
    and raw momentum. Higher scores = stronger momentum signal,
    regardless of bull/bear direction.

    Returns dict with twms_score (0-1) and signal labels.
    """
    score = 0.0
    signals: list[str] = []

    # ── MFI (money flow) ──
    if mfi > _MFI_EXTREME_HIGH:
        score += 0.30
        signals.append("MFI_OVERBOUGHT")
    elif mfi < _MFI_EXTREME_LOW:
        score += 0.30
        signals.append("MFI_OVERSOLD")
    elif mfi > _MFI_MILD_HIGH:
        score += 0.15
        signals.append("MFI_BULLISH")
    elif mfi < _MFI_MILD_LOW:
        score += 0.15
        signals.append("MFI_BEARISH")

    # ── CCI (commodity channel) ──
    if abs(cci) > _CCI_EXTREME:
        score += 0.30
        signals.append(f"CCI_{'OVERBOUGHT' if cci > 0 else 'OVERSOLD'}")
    elif abs(cci) > _CCI_MODERATE:
        score += 0.15
        signals.append(f"CCI_{'BULLISH' if cci > 0 else 'BEARISH'}")

    # ── RSI ──
    if rsi > _RSI_STRONG_HIGH or rsi < _RSI_STRONG_LOW:
        score += 0.25
        signals.append(f"RSI_{'STRONG' if rsi > _RSI_STRONG_HIGH else 'WEAK'}")
    elif rsi > _RSI_MILD_HIGH or rsi < _RSI_MILD_LOW:
        score += 0.10
        signals.append(f"RSI_{'BULLISH' if rsi > _RSI_MILD_HIGH else 'BEARISH'}")

    # ── Momentum ──
    if abs(momentum) > _MOMENTUM_THRESHOLD:
        score += 0.15
        signals.append(f"MOM_{'UP' if momentum > 0 else 'DOWN'}")

    return {
        "twms_score": round(min(1.0, score), 4),
        "signals": signals,
    }


def _fallback_vwap(closes: list[float]) -> float:
    """Estimate VWAP from closes using linearly-increasing time weights.

    NOTE: This is a degraded approximation -- real VWAP requires volume data.
    The result is a time-weighted average price, not a true VWAP.
    """
    window = closes[-50:] if len(closes) >= 50 else closes
    n = len(window)
    if n == 0:
        return 0.0
    # Linearly increasing weights (recent bars weighted more)
    weights = [1.0 + i / n for i in range(n)]
    return sum(p * w for p, w in zip(window, weights, strict=False)) / sum(weights)


def _fallback_energy(closes: list[float]) -> float:
    """Estimate TRQ-like energy from price movement intensity.

    Uses average absolute bar-to-bar change normalized to price level.
    This maps to the 0–5 range that ``_score_energy_coherence`` expects
    (tanh(energy * 0.3) mapping).

    The ``_ENERGY_SCALE`` factor (500) is calibrated so that typical FX
    bar-to-bar moves (~0.1–0.5% of price) produce energy values in the
    1–4 range, matching the tanh input domain where differentiation is
    highest (tanh(0.3–1.5) ≈ 0.29–0.91).
    """
    recent = closes[-_MIN_BARS:]
    if len(recent) < 2:
        return 0.0
    price_level = recent[-1] if recent[-1] != 0 else 1.0
    diffs = [abs(recent[i] - recent[i - 1]) for i in range(1, len(recent))]
    avg_diff = sum(diffs) / len(diffs)
    _ENERGY_SCALE = 500  # Maps normalized diff to ~0-5 energy range  # noqa: N806
    return (avg_diff / price_level) * _ENERGY_SCALE


def _fallback_bias(closes: list[float]) -> float:
    """Estimate directional bias from SMA spread."""
    recent_avg = sum(closes[-10:]) / 10
    long_avg = sum(closes[-50:]) / 50
    if long_avg == 0:
        return 0.0
    return (recent_avg - long_avg) / long_avg


def analyze_tii(
    market_data: dict[str, Any],
    l3_data: dict[str, Any] | None = None,
    l1_data: dict[str, Any] | None = None,
    indicators: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """L8 TII + Integrity Analysis -- PRODUCTION.

    Pure analysis function.  Computes Technical Integrity Index and
    Triple Wolf Momentum Score.  No execution side-effects.

    Parameters
    ----------
    market_data : dict
        Must contain ``closes`` (or ``close``) with >= 10 bars.
    l3_data : dict, optional
        L3 output: ``vwap``, ``energy``, ``bias_strength``.
        If absent, L8 falls back to estimated values (degraded mode).
    l1_data : dict, optional
        L1 output: ``regime_confidence``.
    indicators : dict, optional
        Technical indicators: ``mfi``, ``cci``, ``rsi``, ``momentum``.
    now : datetime, optional
        UTC timestamp override (for deterministic testing).

    Returns
    -------
    dict
        TII profile with ``tii_sym``, ``tii_status``, ``integrity``,
        ``gate_status``, ``gate_passed``, ``valid``, etc.
    """
    closes: list[float] = market_data.get("closes", market_data.get("close", []))

    if not closes or len(closes) < _MIN_BARS:
        return {
            "tii_sym": 0.0,
            "tii_status": "INVALID",
            "integrity": 0.0,
            "twms_score": 0.0,
            "gate_status": "CLOSED",
            "gate_passed": False,
            "valid": False,
            "reason": f"need {_MIN_BARS}+ bars, got {len(closes) if closes else 0}",
        }

    if now is None:
        now = datetime.now(UTC)

    l3 = l3_data or {}
    ind = indicators or {}

    price = closes[-1]

    # ── Resolve inputs (with fallback tracking) ──
    degraded_fields: list[str] = []

    vwap = float(l3.get("vwap", 0.0))
    if vwap == 0.0 and len(closes) >= _MIN_BARS_VWAP_FALLBACK:
        vwap = _fallback_vwap(closes)
        degraded_fields.append("vwap")

    energy = float(l3.get("energy", 0.0))
    if energy == 0.0 and len(closes) >= _MIN_BARS:
        energy = _fallback_energy(closes)
        degraded_fields.append("energy")

    bias = float(l3.get("bias_strength", 0.0))
    if bias == 0.0 and len(closes) >= _MIN_BARS_BIAS_FALLBACK:
        bias = _fallback_bias(closes)
        degraded_fields.append("bias")

    # ── Reflective intensity from L1 ──
    reflect = float(l1_data.get("regime_confidence", 0.7)) if l1_data else 0.7
    if l1_data is None:
        degraded_fields.append("reflective")

    # ── Meta integrity: penalize if running in degraded mode ──
    if not degraded_fields:
        meta_integrity = _META_FULL_DATA
    else:
        # Each degraded field (vwap, energy, bias, reflective) reduces
        # meta-integrity by 6%. With max 4 fields degraded, worst case
        # is 0.70 - 0.24 = 0.46, floored at 0.40 to ensure the TII
        # component still contributes some signal rather than zero.
        _PENALTY_PER_FIELD = 0.06  # noqa: N806
        penalty = len(degraded_fields) * _PENALTY_PER_FIELD
        meta_integrity = max(0.4, _META_DEGRADED - penalty)
        logger.info(
            "L8 degraded mode: estimated fields=%s, meta_integrity=%.2f",
            degraded_fields,
            meta_integrity,
        )

    # ── TII computation ──
    tii_result = _compute_tii(
        price=price,
        vwap=vwap,
        trq_energy=energy,
        bias_strength=bias,
        reflective_intensity=reflect,
        meta_integrity=meta_integrity,
    )

    # ── TWMS computation ──
    twms = _compute_twms(
        mfi=float(ind.get("mfi", 50.0)),
        cci=float(ind.get("cci", 0.0)),
        rsi=float(ind.get("rsi", 50.0)),
        momentum=float(ind.get("momentum", 0.0)),
    )

    # ── Composite integrity score ──
    integrity = round(
        tii_result["tii"] * 0.60 + twms["twms_score"] * 0.40,
        4,
    )

    logger.debug(
        "L8 tii=%.4f status=%s gate=%s integrity=%.4f twms=%.4f degraded=%s",
        tii_result["tii"],
        tii_result["tii_status"],
        tii_result["gate_status"],
        integrity,
        twms["twms_score"],
        degraded_fields or "none",
    )

    # Map 0-1 TII to 0-100 scale for TIIGrade classification
    tii_pct = tii_result["tii"] * 100.0
    grade = classify_tii_grade(tii_pct)

    return {
        "tii_sym": tii_result["tii"],
        "tii_status": tii_result["tii_status"],
        "tii_grade": grade.value,
        "integrity": integrity,
        "twms_score": twms["twms_score"],
        "gate_status": tii_result["gate_status"],
        "gate_passed": tii_result["gate_passed"],
        "valid": True,
        "components": tii_result["components"],
        "twms_signals": twms["signals"],
        "computed_vwap": round(vwap, 5),
        "computed_energy": round(energy, 4),
        "computed_bias": round(bias, 6),
        "degraded_fields": degraded_fields,
        "meta_integrity": round(meta_integrity, 4),
        "timestamp": now.isoformat(),
    }


# ============================================================
# Structured TII API (used by tests/test_l8_tii.py)
# ============================================================


class TIIGrade(Enum):
    """Qualitative grade for a TII score."""

    PRISTINE = "PRISTINE"  # >= 90.0
    CLEAN = "CLEAN"  # >= 75.0
    ACCEPTABLE = "ACCEPTABLE"  # >= 55.0
    QUESTIONABLE = "QUESTIONABLE"  # >= 35.0
    COMPROMISED = "COMPROMISED"  # < 35.0


def classify_tii_grade(score: float) -> TIIGrade:
    """Convert a numeric TII score (0-100) to a TIIGrade."""
    if score >= 90.0:
        return TIIGrade.PRISTINE
    elif score >= 75.0:
        return TIIGrade.CLEAN
    elif score >= 55.0:
        return TIIGrade.ACCEPTABLE
    elif score >= 35.0:
        return TIIGrade.QUESTIONABLE
    else:
        return TIIGrade.COMPROMISED


@dataclass
class TIIInputs:
    """Structured inputs for the structured TII computation."""

    setup_clarity: float
    rule_compliance: float
    risk_reward_quality: float
    confluence_depth: float
    timing_alignment: float

    def __post_init__(self) -> None:
        for field_name in (
            "setup_clarity",
            "rule_compliance",
            "risk_reward_quality",
            "confluence_depth",
            "timing_alignment",
        ):
            val = getattr(self, field_name)
            if not (0.0 <= val <= 100.0):
                raise ValueError(f"{field_name} must be 0\u2013100, got {val}")


@dataclass(frozen=True)
class TIIResult:
    """Result of the structured TII computation."""

    symbol: str
    tii_score: float
    grade: TIIGrade
    pass_threshold: bool
    threshold_used: float
    weakest_dimension: str
    strongest_dimension: str
    metadata: dict[str, Any]


_DEFAULT_WEIGHTS: dict[str, float] = {
    "setup_clarity": 0.20,
    "rule_compliance": 0.25,
    "risk_reward_quality": 0.20,
    "confluence_depth": 0.20,
    "timing_alignment": 0.15,
}


def compute_tii(
    symbol: str,
    inputs: TIIInputs,
    threshold: float = 60.0,
    metadata: dict[str, Any] | None = None,
) -> TIIResult:
    """Compute TII score from structured inputs.

    Args:
        symbol: Trading pair symbol.
        inputs: TIIInputs dataclass with 5 dimension scores (0-100).
        threshold: Pass/fail threshold (default 60.0).
        metadata: Optional passthrough metadata dict.

    Returns:
        Frozen TIIResult with score, grade, pass/fail, and dimension analysis.
    """
    raw = {
        "setup_clarity": inputs.setup_clarity,
        "rule_compliance": inputs.rule_compliance,
        "risk_reward_quality": inputs.risk_reward_quality,
        "confluence_depth": inputs.confluence_depth,
        "timing_alignment": inputs.timing_alignment,
    }

    # Weighted score
    weighted_score = sum(raw[k] * _DEFAULT_WEIGHTS[k] for k in raw) / sum(_DEFAULT_WEIGHTS.values())

    # Rule-compliance penalty: traders with poor rule compliance (<50%)
    # cannot achieve a high TII regardless of other dimensions.
    # Formula: cap = 50 + 0.8 * compliance. At compliance=0 → cap=50,
    # at compliance=49 → cap=89.2. This creates a soft ceiling that
    # prevents gaming other dimensions to bypass compliance gaps.
    if inputs.rule_compliance < 50.0:
        max_allowed = 50.0 + inputs.rule_compliance * 0.8
        weighted_score = min(weighted_score, max_allowed)

    tii_score = round(min(100.0, max(0.0, weighted_score)), 4)
    grade = classify_tii_grade(tii_score)
    pass_threshold = tii_score >= threshold

    weakest = min(raw, key=lambda k: raw[k])
    strongest = max(raw, key=lambda k: raw[k])

    return TIIResult(
        symbol=symbol,
        tii_score=tii_score,
        grade=grade,
        pass_threshold=pass_threshold,
        threshold_used=threshold,
        weakest_dimension=weakest,
        strongest_dimension=strongest,
        metadata=metadata or {},
    )
