"""
L4 -- Session & Timing + Wolf 30-Point + Bayesian Expectancy (PRODUCTION)
=========================================================================
Upgraded from:
  • L4 v1 (l4_session.py + L4_scoring.py): Linear deterministic scorer
  • L4 v2 (merged): Wolf 30-Point + session integration
  • L4 v3 (THIS): Bayesian probabilistic decision engine + expectancy

Mathematical Model (see docs/L4_PRO_MATH.md):
  P_final = σ(log O₀ + Σαᵢ·log(Lᵢ/(1-Lᵢ))) · CoherenceDampener · VolAdj
  Expectancy = P_final·(R+1) - 1
  RAE = Expectancy × ln(1 + P_final)
  CI = 1 - H_posterior / ln(2)

Architecture:
  Linear Weighted Sum  →  Bayesian Evidence Integration
  Grade Label          →  Expected Value Estimator
  Static Weights       →  Regime-Conditioned Strength Matrix
  Scoring Layer        →  Probabilistic Decision Engine

Pipeline Flow:
  L1 macro/fundamental ──┐
  L2 technical analysis ─┤
  L3 market structure   ─┼──->  L4SessionScoring.analyze()
  pair + timestamp      ─┘     │
                               ├─ (1) Session Identification
                               ├─ (2) Quality Modifiers (weekend/news/etc)
                               ├─ (3) Wolf 30-Point Scoring (L1+L2+L3)
                               ├─ (4) Bayesian Win Probability
                               ├─ (5) Expectancy + Risk-Adjusted Edge
                               ├─ (6) Regime-Conditioned Dampeners
                               ├─ (7) Posterior Entropy + Confidence Index
                               └─ (8) Grade Classification + Gate

Wolf 30-Point Breakdown (PRESERVED):
  F-score  (Fundamental)  0-8 pts  <- L1 macro bias + confidence
  T-score  (Technical)    0-12 pts <- L2 trend + momentum + indicators
  FTA-score (Alignment)   0-5 pts  <- L1↔L2 directional agreement
  Exec-score (Execution)  0-5 pts  <- L3 structure + session quality

Bayesian Enrichment (NEW):
  P(W|E) = P(W)·∏Lᵢ / [P(W)·∏Lᵢ + (1-P(W))·∏(1-Lᵢ)]
  Each likelihood Lᵢ raised to regime-conditioned strength exponent.
  Stability constraint: Σαᵢ ∈ [2.8, 5.2], each αᵢ ∈ [0.5, 2.0]
  CI = 1 - H(P_final) / ln(2)

Backward compatibility:
  • analyze_session() tetap tersedia (signature identik)
  • L4ScoringEngine class tetap tersedia (signature identik)
  • Wolf 30-Point output BYTE-IDENTICAL dengan v2
  • Bayesian output ADDITIVE (new key, ignored by v2 consumers)

Zone: analysis/ -- pure computation, zero side-effects.
"""  # noqa: N999

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Literal, TypedDict

from core.core_fusion._utils import _clamp01

logger = logging.getLogger(__name__)

__all__ = [
    "BayesianConfig",
    "L4ScoringEngine",
    "L4SessionScoring",
    "analyze_session",
    "analyze_session_scoring",
]


# ═══════════════════════════════════════════════════════════════════════
# §1  SESSION CONFIGURATION (from l4_session.py -- preserved 100%)
# ═══════════════════════════════════════════════════════════════════════

# (session_name, start_hour_utc, end_hour_utc, base_quality)
# Ordered by priority: overlaps first, then single sessions.
_SESSIONS: Final[list[tuple[str, int, int, float]]] = [
    ("LONDON_NEWYORK", 13, 16, 1.00),
    ("TOKYO_LONDON", 7, 9, 0.85),
    ("LONDON", 9, 13, 0.90),
    ("NEWYORK", 16, 22, 0.85),
    ("TOKYO", 1, 7, 0.60),
]
_SYDNEY_QUALITY: Final = 0.40

# Quality modifiers
_WEEKEND_QUALITY: Final = 0.0
_FRIDAY_CLOSE_MULT: Final = 0.30
_FRIDAY_CLOSE_START_HOUR: Final = 21
_SUNDAY_OPEN_MULT: Final = 0.50
_SUNDAY_OPEN_END_HOUR: Final = 1
_OFF_HOURS_MULT: Final = 0.50
_EVENT_BUFFER_MULT: Final = 0.30

# Known currencies for event relevance
_KNOWN_CURRENCIES: Final = (
    "USD",
    "GBP",
    "EUR",
    "JPY",
    "AUD",
    "NZD",
    "CAD",
    "CHF",
)


# ═══════════════════════════════════════════════════════════════════════
# §2  HIGH-IMPACT EVENTS (from l4_session.py -- preserved 100%)
# ═══════════════════════════════════════════════════════════════════════


class _HighImpactEvent(TypedDict):
    day: int
    hour: int
    minute: int
    buffer_min: int
    pair_impact: list[str]
    recurring: Literal["monthly_first_friday", "scheduled", "weekly"]


HIGH_IMPACT_EVENTS: Final[dict[str, _HighImpactEvent]] = {
    "NFP": {
        "day": 4,
        "hour": 13,
        "minute": 30,
        "buffer_min": 30,
        "pair_impact": ["USD"],
        "recurring": "monthly_first_friday",
    },
    "FOMC": {
        "day": 2,
        "hour": 19,
        "minute": 0,
        "buffer_min": 60,
        "pair_impact": ["USD"],
        "recurring": "scheduled",
    },
    "BOE": {
        "day": 3,
        "hour": 12,
        "minute": 0,
        "buffer_min": 30,
        "pair_impact": ["GBP"],
        "recurring": "scheduled",
    },
    "ECB": {
        "day": 3,
        "hour": 13,
        "minute": 45,
        "buffer_min": 30,
        "pair_impact": ["EUR"],
        "recurring": "scheduled",
    },
    "BOJ": {
        "day": 3,
        "hour": 3,
        "minute": 0,
        "buffer_min": 30,
        "pair_impact": ["JPY"],
        "recurring": "scheduled",
    },
    "RBA": {
        "day": 1,
        "hour": 4,
        "minute": 30,
        "buffer_min": 30,
        "pair_impact": ["AUD"],
        "recurring": "scheduled",
    },
    "RBNZ": {
        "day": 2,
        "hour": 1,
        "minute": 0,
        "buffer_min": 30,
        "pair_impact": ["NZD"],
        "recurring": "scheduled",
    },
}


# ═══════════════════════════════════════════════════════════════════════
# §3  WOLF 30-POINT SCORING CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════

# Max points per component
_F_SCORE_MAX: Final = 8  # Fundamental
_T_SCORE_MAX: Final = 12  # Technical
_FTA_SCORE_MAX: Final = 5  # Fundamental-Technical Alignment
_EXEC_SCORE_MAX: Final = 5  # Execution readiness
_WOLF_TOTAL_MAX: Final = 30

# Grade thresholds (inclusive lower bound)
_GRADE_THRESHOLDS: Final[list[tuple[int, str]]] = [
    (27, "PERFECT"),
    (23, "EXCELLENT"),
    (18, "GOOD"),
    (13, "MARGINAL"),
    (0, "FAIL"),
]

# F-score sub-weights (within 8 points)
_F_WEIGHT_BIAS_STRENGTH: Final = 3.0
_F_WEIGHT_CONFIDENCE: Final = 3.0
_F_WEIGHT_EVENT_CLEAR: Final = 2.0

# T-score sub-weights (within 12 points)
_T_WEIGHT_TREND: Final = 3.0
_T_WEIGHT_MOMENTUM: Final = 3.0
_T_WEIGHT_RSI: Final = 2.0
_T_WEIGHT_STRUCTURE: Final = 2.0
_T_WEIGHT_VOLUME: Final = 2.0

# FTA-score sub-weights (within 5 points)
_FTA_WEIGHT_DIRECTION: Final = 3.0
_FTA_WEIGHT_MAGNITUDE: Final = 2.0

# Exec-score sub-weights (within 5 points)
_EXEC_WEIGHT_STRUCTURE: Final = 3.0
_EXEC_WEIGHT_SESSION: Final = 2.0


# ════════��══════════════════════════════════════════════════════════════
# §3B  BAYESIAN CONFIGURATION (NEW — v3)
# ═══════════════════════════════════════════════════════════════════════

# Stability constraint bounds (Math Spec §XV)
_STRENGTH_SUM_MIN: Final = 2.8
_STRENGTH_SUM_MAX: Final = 5.2
_STRENGTH_INDIVIDUAL_MIN: Final = 0.5
_STRENGTH_INDIVIDUAL_MAX: Final = 2.0

# Numerical guard
_EPS: Final = 1e-9


@dataclass(frozen=True)
class BayesianConfig:
    """Configuration for the Bayesian win probability engine.

    Regime priors derived from historical regime-specific win rates.
    Strength matrix controls how much each evidence component contributes
    under different market regimes (exponent on Bayes factor).

    Stability constraints (Math Spec §XV):
      - Per-regime: Σαᵢ ∈ [2.8, 5.2]
      - Individual: 0.5 ≤ αᵢ ≤ 2.0
    Validated at construction via __post_init__.

    All values are YAML-overridable for recalibration.
    """

    # ── Regime-conditioned prior win probabilities (§II) ──
    prior_trend_up: float = 0.58
    prior_trend_down: float = 0.58
    prior_range: float = 0.47
    prior_transition: float = 0.42
    prior_unknown: float = 0.45

    # ── Regime-conditioned evidence strength matrix (§IV) ──
    # TREND_UP: technical most reliable
    strength_trend_up_f: float = 1.2
    strength_trend_up_t: float = 1.5
    strength_trend_up_fta: float = 1.3
    strength_trend_up_exec: float = 1.0

    # TREND_DOWN: mirror of TREND_UP
    strength_trend_down_f: float = 1.2
    strength_trend_down_t: float = 1.5
    strength_trend_down_fta: float = 1.3
    strength_trend_down_exec: float = 1.0

    # RANGE: execution timing most critical
    strength_range_f: float = 0.8
    strength_range_t: float = 0.9
    strength_range_fta: float = 1.0
    strength_range_exec: float = 1.4

    # TRANSITION: alignment is key
    strength_transition_f: float = 0.7
    strength_transition_t: float = 0.8
    strength_transition_fta: float = 1.2
    strength_transition_exec: float = 1.3

    # UNKNOWN: conservative uniform
    strength_unknown_f: float = 0.8
    strength_unknown_t: float = 0.8
    strength_unknown_fta: float = 0.8
    strength_unknown_exec: float = 0.8

    # ── Likelihood clamp (prevent degenerate BF) (§IV) ──
    likelihood_min: float = 0.05
    likelihood_max: float = 0.95

    # ── Strength exponent cap (§XV individual bound) ──
    strength_cap: float = 2.0

    # ── Coherence dampener (§VI) ──
    coherence_threshold: float = 0.70
    coherence_min_mult: float = 0.60

    # ── Volatility dampener (§VII) ──
    extreme_vol_mult: float = 0.85
    high_vol_mult: float = 0.93

    # ── Default R:R when L3 doesn't provide (§VIII) ──
    default_rr: float = 1.5

    def __post_init__(self) -> None:
        """Validate stability constraints (Math Spec §XV).

        Ensures:
          - Each regime's strength sum ∈ [2.8, 5.2]
          - Each individual strength ∈ [0.5, 2.0]
          - Prior probabilities ∈ (0, 1)
          - Likelihood bounds valid
        """
        regimes = {
            "TREND_UP": (
                self.strength_trend_up_f,
                self.strength_trend_up_t,
                self.strength_trend_up_fta,
                self.strength_trend_up_exec,
            ),
            "TREND_DOWN": (
                self.strength_trend_down_f,
                self.strength_trend_down_t,
                self.strength_trend_down_fta,
                self.strength_trend_down_exec,
            ),
            "RANGE": (
                self.strength_range_f,
                self.strength_range_t,
                self.strength_range_fta,
                self.strength_range_exec,
            ),
            "TRANSITION": (
                self.strength_transition_f,
                self.strength_transition_t,
                self.strength_transition_fta,
                self.strength_transition_exec,
            ),
            "UNKNOWN": (
                self.strength_unknown_f,
                self.strength_unknown_t,
                self.strength_unknown_fta,
                self.strength_unknown_exec,
            ),
        }

        for regime_name, strengths in regimes.items():
            s_sum = sum(strengths)
            if not (_STRENGTH_SUM_MIN <= s_sum <= _STRENGTH_SUM_MAX):
                raise ValueError(
                    f"BayesianConfig: {regime_name} Σαᵢ={s_sum:.2f} violates [{_STRENGTH_SUM_MIN}, {_STRENGTH_SUM_MAX}]"
                )
            for i, s in enumerate(strengths):
                if not (_STRENGTH_INDIVIDUAL_MIN <= s <= _STRENGTH_INDIVIDUAL_MAX):
                    raise ValueError(
                        f"BayesianConfig: {regime_name} α[{i}]={s:.2f} "  # noqa: RUF001
                        f"violates [{_STRENGTH_INDIVIDUAL_MIN}, "
                        f"{_STRENGTH_INDIVIDUAL_MAX}]"
                    )

        for name, prior in [
            ("prior_trend_up", self.prior_trend_up),
            ("prior_trend_down", self.prior_trend_down),
            ("prior_range", self.prior_range),
            ("prior_transition", self.prior_transition),
            ("prior_unknown", self.prior_unknown),
        ]:
            if not (0.0 < prior < 1.0):
                raise ValueError(f"BayesianConfig: {name}={prior} must be in (0, 1)")

        if not (0.0 < self.likelihood_min < self.likelihood_max < 1.0):
            raise ValueError(
                f"BayesianConfig: likelihood bounds invalid: min={self.likelihood_min}, max={self.likelihood_max}"
            )


# Production default
_DEFAULT_BAYESIAN_CONFIG: Final = BayesianConfig()


def _get_regime_prior(regime: str, cfg: BayesianConfig) -> float:
    """Look up regime-conditioned prior win probability (§II)."""
    _map: dict[str, float] = {
        "TREND_UP": cfg.prior_trend_up,
        "TREND_DOWN": cfg.prior_trend_down,
        "RANGE": cfg.prior_range,
        "TRANSITION": cfg.prior_transition,
    }
    return _map.get(regime, cfg.prior_unknown)


def _get_regime_strengths(
    regime: str,
    cfg: BayesianConfig,
) -> tuple[float, float, float, float]:
    """Look up regime-conditioned evidence strengths (§IV).

    Returns (α_F, α_T, α_FTA, α_Exec).
    """
    _map: dict[str, tuple[float, float, float, float]] = {
        "TREND_UP": (
            cfg.strength_trend_up_f,
            cfg.strength_trend_up_t,
            cfg.strength_trend_up_fta,
            cfg.strength_trend_up_exec,
        ),
        "TREND_DOWN": (
            cfg.strength_trend_down_f,
            cfg.strength_trend_down_t,
            cfg.strength_trend_down_fta,
            cfg.strength_trend_down_exec,
        ),
        "RANGE": (
            cfg.strength_range_f,
            cfg.strength_range_t,
            cfg.strength_range_fta,
            cfg.strength_range_exec,
        ),
        "TRANSITION": (
            cfg.strength_transition_f,
            cfg.strength_transition_t,
            cfg.strength_transition_fta,
            cfg.strength_transition_exec,
        ),
    }
    return _map.get(
        regime,
        (
            cfg.strength_unknown_f,
            cfg.strength_unknown_t,
            cfg.strength_unknown_fta,
            cfg.strength_unknown_exec,
        ),
    )


# ═══════════════════════════════════════════════════════════════════════
# §4  SESSION HELPER FUNCTIONS (from l4_session.py -- preserved 100%)
# ═══════════════════════════════════════════════════════════════════════


def _identify_session(h: int) -> tuple[str, float]:
    """Return (session_name, base_quality) for a UTC hour."""
    for name, start, end, quality in _SESSIONS:
        if start <= h < end:
            return name, quality
    return "SYDNEY", _SYDNEY_QUALITY


def _extract_currencies(pair: str) -> list[str]:
    """Extract known currency codes from a pair string."""
    p = pair.upper().replace("/", "").replace("_", "")
    return [ccy for ccy in _KNOWN_CURRENCIES if ccy in p]


def _is_near_event(
    now: datetime,
    pair_currencies: list[str],
) -> tuple[bool, str | None]:
    """Check if current time is within a high-impact event buffer.

    Uses minute-level precision.  Returns (is_near, event_name_or_none).

    NOTE: Events marked 'scheduled' (FOMC, BOE, ECB, etc.) fire on every
    matching weekday.  For production, integrate a real economic calendar.
    NFP uses a first-Friday-of-month heuristic.
    """
    dow = now.weekday()
    for name, ev in HIGH_IMPACT_EVENTS.items():
        if dow != ev["day"]:
            continue

        if ev.get("recurring") == "monthly_first_friday" and now.day > 7:
            continue

        if not any(c in ev["pair_impact"] for c in pair_currencies):
            continue

        event_time = now.replace(
            hour=ev["hour"],
            minute=ev.get("minute", 0),
            second=0,
            microsecond=0,
        )
        delta = abs((now - event_time).total_seconds()) / 60.0
        if delta <= ev["buffer_min"]:
            return True, name

    return False, None


def _compute_session_context(
    pair: str,
    now: datetime,
) -> dict[str, Any]:
    """Compute full session context (extracted from original analyze_session).

    Returns dict with session identification, quality, gates, events.
    """
    h = now.hour
    dow = now.weekday()

    session, quality = _identify_session(h)

    tradeable = True
    gate_reasons: list[str] = []

    # Weekend gate
    if dow >= 5:
        tradeable = False
        quality = _WEEKEND_QUALITY
        gate_reasons.append("WEEKEND")
    else:
        if dow == 4 and h >= _FRIDAY_CLOSE_START_HOUR:
            quality *= _FRIDAY_CLOSE_MULT
            gate_reasons.append("FRIDAY_CLOSE")

        if dow == 0 and h < _SUNDAY_OPEN_END_HOUR:
            quality *= _SUNDAY_OPEN_MULT
            gate_reasons.append("SUNDAY_OPEN")

        if session == "SYDNEY":
            quality *= _OFF_HOURS_MULT
            gate_reasons.append("OFF_HOURS")

    # Event buffer
    pair_ccys = _extract_currencies(pair)
    near_event, event_name = _is_near_event(now, pair_ccys)

    if near_event:
        quality *= _EVENT_BUFFER_MULT
        gate_reasons.append(f"EVENT_BUFFER_{event_name}")

    quality = round(_clamp01(quality), 4)

    if not gate_reasons:
        gate_reasons.append("OK")

    return {
        "session": session,
        "quality": quality,
        "tradeable": tradeable,
        "gate_reasons": gate_reasons,
        "near_event": near_event,
        "event_name": event_name,
        "hour_utc": h,
        "day_of_week": dow,
    }


# ═══════════════════════════════════════════════════════════════════════
# §5  WOLF 30-POINT SCORING FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════


def _safe(d: dict[str, Any], key: str, default: float = 0.0) -> float:
    """Safely extract a float from a dict, clamping to [0, 1]."""
    try:
        v = float(d.get(key, default))
        if not math.isfinite(v):
            return default
        return _clamp01(v)
    except (TypeError, ValueError):
        return default


def _safe_raw(d: dict[str, Any], key: str, default: float = 0.0) -> float:
    """Safely extract a float without clamping."""
    try:
        v = float(d.get(key, default))
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def _normalize_bias(bias: Any) -> tuple[str, float]:
    """Normalize bias from various L1/L2 formats to (direction, strength).

    Accepts:
      - str: "BULLISH", "BEARISH", "NEUTRAL", "Bullish", etc.
      - float: positive = bullish, negative = bearish
      - dict: {"direction": ..., "strength": ...}

    Returns (direction, strength) where direction is BULLISH/BEARISH/NEUTRAL
    and strength is 0.0-1.0.
    """
    if isinstance(bias, dict):
        d = str(bias.get("direction", "NEUTRAL")).upper()
        s = _safe(bias, "strength", 0.5)
        return d, s

    if isinstance(bias, int | float):
        if bias > 0.05:
            return "BULLISH", min(1.0, abs(bias))
        if bias < -0.05:
            return "BEARISH", min(1.0, abs(bias))
        return "NEUTRAL", 0.0

    s = str(bias).upper().strip()
    if "BULL" in s:
        return "BULLISH", 0.7
    if "BEAR" in s:
        return "BEARISH", 0.7
    return "NEUTRAL", 0.0


def _compute_f_score(
    l1: dict[str, Any],
    near_event: bool,
) -> tuple[float, dict[str, Any]]:
    """Compute Fundamental score (0-8 points) from L1 output.

    Sub-components:
      • bias_strength (0-3): How decisive the macro bias is
      • confidence    (0-3): Fundamental analysis confidence
      • event_clear   (0-2): No high-impact event in buffer zone
    """
    _, bias_strength = _normalize_bias(l1.get("bias", "NEUTRAL"))
    confidence = _safe(l1, "confidence", 0.5)

    if "strength" in l1:
        bias_strength = _safe(l1, "strength", bias_strength)

    event_clear = 0.0 if near_event else 1.0

    pts_bias = round(bias_strength * _F_WEIGHT_BIAS_STRENGTH, 2)
    pts_conf = round(confidence * _F_WEIGHT_CONFIDENCE, 2)
    pts_event = round(event_clear * _F_WEIGHT_EVENT_CLEAR, 2)

    total = min(_F_SCORE_MAX, pts_bias + pts_conf + pts_event)

    detail = {
        "bias_strength": round(bias_strength, 3),
        "confidence": round(confidence, 3),
        "event_clear": event_clear,
        "pts_bias": pts_bias,
        "pts_conf": pts_conf,
        "pts_event": pts_event,
    }
    return round(total, 2), detail


def _compute_t_score(l2: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    """Compute Technical score (0-12 points) from L2 output."""
    trend = _safe(l2, "trend_strength", 0.0)
    if trend == 0.0:
        trend = _safe(l2, "trend", 0.0)

    momentum = _safe(l2, "momentum", 0.0)
    if momentum == 0.0:
        momentum = _safe(l2, "momentum_score", 0.0)

    rsi_score = _safe(l2, "rsi_score", 0.0)
    if rsi_score == 0.0 and "rsi" in l2:
        raw_rsi = _safe_raw(l2, "rsi", 50.0)
        rsi_score = min(1.0, abs(raw_rsi - 50.0) / 30.0)

    structure = _safe(l2, "structure_score", 0.0)
    if structure == 0.0:
        structure = _safe(l2, "ema_alignment", 0.0)

    volume = _safe(l2, "volume_score", 0.0)
    if volume == 0.0:
        volume = _safe(l2, "volume_confirmation", 0.0)

    pts_trend = round(trend * _T_WEIGHT_TREND, 2)
    pts_mom = round(momentum * _T_WEIGHT_MOMENTUM, 2)
    pts_rsi = round(rsi_score * _T_WEIGHT_RSI, 2)
    pts_struct = round(structure * _T_WEIGHT_STRUCTURE, 2)
    pts_vol = round(volume * _T_WEIGHT_VOLUME, 2)

    total = min(
        _T_SCORE_MAX,
        pts_trend + pts_mom + pts_rsi + pts_struct + pts_vol,
    )

    detail = {
        "trend": round(trend, 3),
        "momentum": round(momentum, 3),
        "rsi_score": round(rsi_score, 3),
        "structure": round(structure, 3),
        "volume": round(volume, 3),
        "pts_trend": pts_trend,
        "pts_momentum": pts_mom,
        "pts_rsi": pts_rsi,
        "pts_structure": pts_struct,
        "pts_volume": pts_vol,
    }
    return round(total, 2), detail


def _compute_fta_score(
    l1: dict[str, Any],
    l2: dict[str, Any],
) -> tuple[float, dict[str, Any]]:
    """Compute Fundamental-Technical Alignment score (0-5 points)."""
    l1_dir, l1_str = _normalize_bias(l1.get("bias", "NEUTRAL"))

    l2_bias = l2.get("bias", l2.get("trend_bias", "NEUTRAL"))
    l2_dir, l2_str = _normalize_bias(l2_bias)

    if "trend_strength" in l2:
        l2_str = _safe(l2, "trend_strength", l2_str)

    if l1_dir == l2_dir and l1_dir != "NEUTRAL":
        dir_match = 1.0
    elif l1_dir == "NEUTRAL" or l2_dir == "NEUTRAL":
        dir_match = 0.5
    elif l1_dir != l2_dir:
        dir_match = 0.0
    else:
        dir_match = 0.5

    mag_match = 1.0 - min(1.0, abs(l1_str - l2_str)) if l1_str > 0 and l2_str > 0 else 0.0

    pts_dir = round(dir_match * _FTA_WEIGHT_DIRECTION, 2)
    pts_mag = round(mag_match * _FTA_WEIGHT_MAGNITUDE, 2)

    total = min(_FTA_SCORE_MAX, pts_dir + pts_mag)

    detail = {
        "l1_direction": l1_dir,
        "l1_strength": round(l1_str, 3),
        "l2_direction": l2_dir,
        "l2_strength": round(l2_str, 3),
        "direction_match": round(dir_match, 3),
        "magnitude_match": round(mag_match, 3),
        "pts_direction": pts_dir,
        "pts_magnitude": pts_mag,
    }
    return round(total, 2), detail


def _compute_exec_score(
    l3: dict[str, Any],
    session_quality: float,
) -> tuple[float, dict[str, Any]]:
    """Compute Execution readiness score (0-5 points)."""
    struct = _safe(l3, "confidence", 0.0)
    if struct == 0.0:
        struct = _safe(l3, "structure_confidence", 0.0)
    if struct == 0.0:
        struct = _safe(l3, "structure_score", 0.0)
    if struct == 0.0:
        struct = _safe(l3, "quality", 0.0)

    sq = _clamp01(session_quality)

    pts_struct = round(struct * _EXEC_WEIGHT_STRUCTURE, 2)
    pts_session = round(sq * _EXEC_WEIGHT_SESSION, 2)

    total = min(_EXEC_SCORE_MAX, pts_struct + pts_session)

    detail = {
        "structure_quality": round(struct, 3),
        "session_quality": round(sq, 3),
        "pts_structure": pts_struct,
        "pts_session": pts_session,
    }
    return round(total, 2), detail


def _classify_grade(total: float) -> str:
    """Classify Wolf 30-Point total into grade."""
    t = int(total)
    for threshold, grade in _GRADE_THRESHOLDS:
        if t >= threshold:
            return grade
    return "FAIL"


# ═══════════════════════════════════════════════════════════════════════
# §5B  BAYESIAN WIN PROBABILITY ENGINE (NEW — v3)
# ═══════════════════════════════════════════════════════════════════════


def _bayesian_win_probability(
    prior: float,
    likelihoods: list[float],
    strengths: list[float],
    cfg: BayesianConfig,
) -> float:
    """Compute posterior win probability via Bayesian evidence integration.

    Mathematical model (§IV-V):
      O₀ = P₀ / (1 - P₀)
      For each evidence Lᵢ with strength αᵢ:
        BFᵢ = (Lᵢ / (1 - Lᵢ))^αᵢ
        O_post = O₀ · ∏BFᵢ
      P(W|E) = O_post / (1 + O_post)

    Likelihoods clamped to [min, max] to prevent degenerate Bayes factors.
    Strengths capped to prevent runaway posterior from single component.

    Args:
        prior: Regime-conditioned base win probability P₀.
        likelihoods: Normalized evidence values [0-1] per component.
        strengths: Reliability weight exponents per component.
        cfg: Bayesian configuration for clamp/cap values.

    Returns:
        Posterior win probability ∈ [0, 1].
    """
    p = max(0.01, min(0.99, prior))
    odds = p / (1.0 - p)

    for like, s in zip(likelihoods, strengths, strict=False):
        clamped = max(cfg.likelihood_min, min(cfg.likelihood_max, like))
        capped_s = min(cfg.strength_cap, max(0.0, s))
        bayes_factor = (clamped / (1.0 - clamped)) ** capped_s
        odds *= bayes_factor

    posterior = odds / (1.0 + odds)
    return _clamp01(posterior)


def _compute_expectancy(p_win: float, rr: float) -> float:
    """Compute mathematical expectancy of a trade (§VIII).

    E = P_win · (R + 1) - 1  ≡  P_win · R - (1 - P_win)

    Positive expectancy = statistical edge exists.

    Args:
        p_win: Win probability [0, 1].
        rr: Reward:risk ratio (e.g. 1.8 = TP is 1.8× SL).

    Returns:
        Expectancy value (typically -1.0 to +R).
    """
    return (p_win * rr) - (1.0 - p_win)


def _compute_risk_adjusted_edge(
    expectancy: float,
    posterior: float,
) -> float:
    """Risk-Adjusted Edge: scales expectancy by confidence level.

    RAE = expectancy × ln(1 + posterior)

    Log-scaling prevents over-sizing on marginal edges.
    Note: full math spec §IX uses E × P × (1-RoR) but RoR from L7
    is not available at L4 execution time. ln(1+P) approximates
    the confidence-weighted dampening without L7 dependency.

    Args:
        expectancy: Mathematical expectancy value.
        posterior: Bayesian posterior win probability.

    Returns:
        Risk-adjusted edge score.
    """
    if expectancy <= 0:
        return round(expectancy, 4)
    return round(expectancy * math.log(1.0 + posterior), 4)


def _compute_posterior_entropy(posterior: float) -> float:
    """Shannon entropy of posterior distribution (§XI).

    H = -P·ln(P) - (1-P)·ln(1-P)

    Output ∈ [0, ln(2)] ≈ [0, 0.6931].
    Clamped to [ε, 1-ε] to prevent log(0).
    """
    p = max(_EPS, min(1.0 - _EPS, posterior))
    q = 1.0 - p
    return -(p * math.log(p) + q * math.log(q))


def _compute_confidence_index(posterior: float) -> float:
    """Confidence Index: CI = 1 - H / ln(2) (§XI).

    CI = 1.0 when posterior is certain (P=0 or P=1).
    CI = 0.0 when maximum uncertainty (P=0.5).
    Output ∈ [0, 1].
    """
    h = _compute_posterior_entropy(posterior)
    return round(1.0 - h / math.log(2.0), 4)


def _classify_bayesian_grade(
    posterior: float,
    expectancy: float,
) -> str:
    """Classify trade quality by posterior + expectancy (§XIV).

    Grade mapping:
      INSTITUTIONAL_A : P ≥ 0.75 AND E > 0.5  (best setups)
      INSTITUTIONAL_B : P ≥ 0.65 AND E > 0.3  (good setups)
      SPECULATIVE     : P ≥ 0.55 AND E > 0.0  (marginal edge)
      NO_EDGE         : everything else
    """
    if posterior >= 0.75 and expectancy > 0.5:
        return "INSTITUTIONAL_A"
    if posterior >= 0.65 and expectancy > 0.3:
        return "INSTITUTIONAL_B"
    if posterior >= 0.55 and expectancy > 0.0:
        return "SPECULATIVE"
    return "NO_EDGE"


def _compute_bayesian_enrichment(
    f_score: float,
    t_score: float,
    fta_score: float,
    exec_score: float,
    l1: dict[str, Any],
    l2: dict[str, Any],
    l3: dict[str, Any],
    cfg: BayesianConfig,
) -> dict[str, Any]:
    """Full Bayesian enrichment pipeline (§II-§XV).

    Converts Wolf 30-Point sub-scores into probabilistic win assessment.

    Flow:
      1. Extract regime from L1 → select prior + strength matrix (§II, §IV)
      2. Normalize sub-scores to [0, 1] likelihoods (§III)
      3. Compute raw posterior via Bayesian update (§V)
      4. Apply coherence dampener: L2.reflex → L1.CC fallback (§VI)
      5. Apply volatility dampener from L1.volatility_level (§VII)
      6. Compute expectancy + risk-adjusted edge (§VIII, §IX)
      7. Compute posterior entropy + confidence index (§XI)
      8. Classify into bayesian grade (§XIV)

    Args:
        f_score: Fundamental sub-score (0-8).
        t_score: Technical sub-score (0-12).
        fta_score: FTA alignment sub-score (0-5).
        exec_score: Execution sub-score (0-5).
        l1: Layer 1 output (regime, volatility, context_coherence).
        l2: Layer 2 output (reflex_coherence, technical signals).
        l3: Layer 3 output (rr_ratio, structure confidence).
        cfg: Bayesian configuration.

    Returns:
        Dict with posterior, expectancy, RAE, CI, grade, and lineage.
    """
    # ── 1. Regime → prior + strengths (§II, §IV) ─────────────────
    regime = str(l1.get("regime", "UNKNOWN")).upper()
    prior = _get_regime_prior(regime, cfg)
    s_f, s_t, s_fta, s_exec = _get_regime_strengths(regime, cfg)

    # ── 2. Normalize sub-scores to [0, 1] likelihoods (§III) ─────
    l_f = f_score / _F_SCORE_MAX if _F_SCORE_MAX > 0 else 0.0
    l_t = t_score / _T_SCORE_MAX if _T_SCORE_MAX > 0 else 0.0
    l_fta = fta_score / _FTA_SCORE_MAX if _FTA_SCORE_MAX > 0 else 0.0
    l_exec = exec_score / _EXEC_SCORE_MAX if _EXEC_SCORE_MAX > 0 else 0.0

    likelihoods = [l_f, l_t, l_fta, l_exec]
    strengths = [s_f, s_t, s_fta, s_exec]

    # ── 3. Bayesian posterior (§V) ────────────────────────────────
    posterior = _bayesian_win_probability(
        prior,
        likelihoods,
        strengths,
        cfg,
    )

    # ── 4. Coherence dampener (§VI) ──────────────────────────────
    # PRIMARY: L2.reflex_coherence (technical signal coherence)
    # FALLBACK: L1.context_coherence (regime certainty from entropy)
    reflex_coherence = _safe(
        l2,
        "reflex_coherence",
        _safe(l1, "context_coherence", 1.0),
    )
    coherence_applied = False
    if reflex_coherence < cfg.coherence_threshold:
        dampener = cfg.coherence_min_mult + (
            (1.0 - cfg.coherence_min_mult) * (reflex_coherence / cfg.coherence_threshold)
        )
        posterior *= dampener
        coherence_applied = True

    # ── 5. Volatility dampener (§VII) ────────────────────────────
    vol_level = str(l1.get("volatility_level", "")).upper()
    vol_dampener = 1.0
    if vol_level == "EXTREME":
        vol_dampener = cfg.extreme_vol_mult
    elif vol_level == "HIGH":
        vol_dampener = cfg.high_vol_mult
    posterior *= vol_dampener

    # Clamp final posterior
    posterior = round(_clamp01(posterior), 4)

    # ── 6. Expectancy + RAE (§VIII, §IX) ─────────────────────────
    rr = _safe_raw(l3, "rr_ratio", cfg.default_rr)
    if rr <= 0:
        rr = cfg.default_rr

    expectancy = round(_compute_expectancy(posterior, rr), 4)
    rae = _compute_risk_adjusted_edge(expectancy, posterior)

    # ── 7. Posterior entropy + confidence index (§XI) ─────────────
    posterior_entropy = round(_compute_posterior_entropy(posterior), 4)
    confidence_index = _compute_confidence_index(posterior)

    # ── 8. Bayesian grade (§XIV) ──────────────────────────────────
    bayesian_grade = _classify_bayesian_grade(posterior, expectancy)

    # ── 9. Bayesian tradeable gate (§X) ──────────────────────────
    # Note: full §X requires Edge_adj > 0.15 + L7 RoR, which is
    # not available at L4. We use simplified gate here; L12 verdict
    # engine applies the full constitutional gate with L7 data.
    bayesian_tradeable = posterior >= 0.55 and expectancy > 0.0

    return {
        "posterior_win_probability": posterior,
        "expected_value": expectancy,
        "risk_adjusted_edge": rae,
        "posterior_entropy": posterior_entropy,
        "confidence_index": confidence_index,
        "regime_prior": round(prior, 4),
        "regime_used": regime,
        "rr_ratio": round(rr, 2),
        "bayesian_grade": bayesian_grade,
        "bayesian_tradeable": bayesian_tradeable,
        "confidence_lineage": {
            "F": round(l_f, 4),
            "T": round(l_t, 4),
            "FTA": round(l_fta, 4),
            "EXEC": round(l_exec, 4),
        },
        "regime_strengths": {
            "F": round(s_f, 2),
            "T": round(s_t, 2),
            "FTA": round(s_fta, 2),
            "EXEC": round(s_exec, 2),
        },
        "dampeners": {
            "coherence_value": round(reflex_coherence, 4),
            "coherence_applied": coherence_applied,
            "volatility_level": vol_level,
            "volatility_mult": round(vol_dampener, 4),
        },
    }


# ═══════════════════════════════════════════════════════════════════════
# §6  MAIN ANALYZER CLASS
# ═══════════════════════════════════════════════════════════════════════


class L4SessionScoring:
    """Layer 4: Session + Wolf 30-Point + Bayesian Expectancy — PRODUCTION.

    Merges session/timing analysis with confluence scoring and Bayesian
    probabilistic enrichment into a single L4 pipeline.

    Upgrade path:
      v1: l4_session.py (timing only)
      v2: Wolf 30-Point deterministic scorer
      v3 (THIS): Bayesian probabilistic decision engine

    Usage::

        analyzer = L4SessionScoring()
        result = analyzer.analyze(
            l1={"bias": "BULLISH", "confidence": 0.82, "strength": 0.75,
                "regime": "TREND_UP", "context_coherence": 0.91,
                "volatility_level": "NORMAL"},
            l2={"trend_strength": 0.80, "momentum": 0.70, "rsi": 62,
                "structure_score": 0.65, "volume_score": 0.55,
                "trend_bias": "BULLISH", "reflex_coherence": 0.88},
            l3={"confidence": 0.78, "rr_ratio": 1.8},
            pair="GBPUSD",
        )
        # result["wolf_30_point"]["total"]                   -> 24.5
        # result["grade"]                                    -> "EXCELLENT"
        # result["bayesian"]["posterior_win_probability"]     -> 0.72
        # result["bayesian"]["bayesian_grade"]               -> "INSTITUTIONAL_B"
        # result["bayesian"]["confidence_index"]             -> 0.83
    """

    def __init__(
        self,
        bayesian_config: BayesianConfig | None = None,
        *,
        l3_output: dict[str, Any] | None = None,
    ) -> None:
        self._call_count: int = 0
        self._bayesian_config = bayesian_config or _DEFAULT_BAYESIAN_CONFIG
        self._l3_output: dict[str, Any] | None = l3_output

    def set_l3_output(self, l3_output: dict[str, Any]) -> None:
        """Inject L3 constitutional output for upstream legality check."""
        self._l3_output = l3_output

    def analyze(
        self,
        l1: dict[str, Any],
        l2: dict[str, Any],
        l3: dict[str, Any],
        pair: str = "GBPUSD",
        market_data: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Complete L4 pipeline: session + scoring + Bayesian enrichment.

        Parameters
        ----------
        l1 : dict
            Layer 1 (Fundamental/Macro) output.
            Expected: ``bias``, ``confidence``, ``strength``,
            ``regime``, ``context_coherence``, ``volatility_level``.
        l2 : dict
            Layer 2 (Technical Analysis) output.
            Expected: ``trend_strength``, ``momentum``, ``rsi``,
            ``structure_score``, ``volume_score``, ``trend_bias``,
            ``reflex_coherence``.
        l3 : dict
            Layer 3 (Market Structure) output.
            Expected: ``confidence``, ``structure_score``, ``rr_ratio``.
        pair : str
            Currency pair for event relevance and session context.
        market_data : dict, optional
            Additional market data (for pipeline consistency).
        now : datetime, optional
            UTC timestamp override for deterministic testing.

        Returns
        -------
        dict
            Complete L4 profile with session, Wolf 30-Point (preserved),
            Bayesian enrichment (new), and classification.
        """
        if now is None:
            now = datetime.now(UTC)

        # ── PHASE 1: Session analysis ────────────────────────────────

        ctx = _compute_session_context(pair, now)

        # ── PHASE 2: Wolf 30-Point scoring (PRESERVED 100%) ──────────

        f_score, f_detail = _compute_f_score(l1, ctx["near_event"])
        t_score, t_detail = _compute_t_score(l2)
        fta_score, fta_detail = _compute_fta_score(l1, l2)
        exec_score, exec_detail = _compute_exec_score(
            l3,
            ctx["quality"],
        )

        wolf_total = round(
            f_score + t_score + fta_score + exec_score,
            2,
        )
        wolf_total = min(_WOLF_TOTAL_MAX, wolf_total)

        # ── PHASE 3: Grade classification (PRESERVED 100%) ───────────

        grade = _classify_grade(wolf_total)

        technical_score = round((t_score / _T_SCORE_MAX) * 100) if _T_SCORE_MAX > 0 else 0

        # ── PHASE 4: Bayesian enrichment (NEW) ───────────────────────

        bayesian = _compute_bayesian_enrichment(
            f_score=f_score,
            t_score=t_score,
            fta_score=fta_score,
            exec_score=exec_score,
            l1=l1,
            l2=l2,
            l3=l3,
            cfg=self._bayesian_config,
        )

        # ── PHASE 5: Integration gate ────────────────────────────────

        score_ok = grade in ("PERFECT", "EXCELLENT", "GOOD", "MARGINAL")
        valid = True
        overall_tradeable = ctx["tradeable"] and score_ok

        self._call_count += 1

        logger.debug(
            "L4 v3: pair=%s session=%s quality=%.4f "
            "F=%s T=%s FTA=%s E=%s total=%.1f grade=%s "
            "P(win)=%.4f EV=%.4f CI=%.4f b_grade=%s tradeable=%s",
            pair,
            ctx["session"],
            ctx["quality"],
            f_score,
            t_score,
            fta_score,
            exec_score,
            wolf_total,
            grade,
            bayesian["posterior_win_probability"],
            bayesian["expected_value"],
            bayesian["confidence_index"],
            bayesian["bayesian_grade"],
            overall_tradeable,
        )

        raw_result = {
            # ── Session (from l4_session.py) ──
            "session": ctx["session"],
            "quality": ctx["quality"],
            "tradeable": overall_tradeable,
            "gate_reasons": ctx["gate_reasons"],
            "near_event": ctx["near_event"],
            "event_name": ctx["event_name"],
            "hour_utc": ctx["hour_utc"],
            "day_of_week": ctx["day_of_week"],
            # ── Wolf 30-Point (PRESERVED byte-identical) ──
            "wolf_30_point": {
                "total": wolf_total,
                "f_score": f_score,
                "t_score": t_score,
                "fta_score": fta_score,
                "exec_score": exec_score,
                "max_possible": _WOLF_TOTAL_MAX,
                "f_detail": f_detail,
                "t_detail": t_detail,
                "fta_detail": fta_detail,
                "exec_detail": exec_detail,
            },
            # ── Bayesian Enrichment (NEW — additive) ──
            "bayesian": bayesian,
            # ── Classification ──
            "grade": grade,
            "technical_score": technical_score,
            # ── Metadata ──
            "pair": pair,
            "valid": valid,
            "timestamp": now.isoformat(),
        }
        return self._apply_constitutional(raw_result, pair)

    # ── Constitutional Governance Wrapper ────────────────────────────
    def _apply_constitutional(
        self, raw_result: dict[str, Any], symbol: str
    ) -> dict[str, Any]:
        """Wrap raw L4 output with constitutional governance envelope.

        Follows the same pattern as L2 / L3 constitutional wrappers:
        lazy-import governor → build inputs → evaluate → merge → map valid.
        """
        try:
            from analysis.layers.L4_constitutional import L4ConstitutionalGovernor

            gov = L4ConstitutionalGovernor()

            l3_output = self._l3_output or {}

            envelope = gov.evaluate(
                l3_output=l3_output,
                l4_analysis=raw_result,
                symbol=symbol,
            )

            raw_result["constitutional"] = envelope
            raw_result["continuation_allowed"] = envelope.get(
                "continuation_allowed", True
            )

            # Map constitutional status → valid flag
            status = envelope.get("status", "PASS")
            if status == "FAIL":
                raw_result["valid"] = False
            elif status == "WARN":
                # WARN degrades but does not block
                pass

            logger.debug(
                "L4 constitutional: symbol=%s status=%s continuation=%s",
                symbol,
                status,
                envelope.get("continuation_allowed", True),
            )

        except Exception as exc:
            logger.warning(
                "L4 constitutional governor failed — raw result preserved: %s",
                exc,
            )
            raw_result["constitutional"] = {"error": str(exc)}
            raw_result["continuation_allowed"] = True

        return raw_result


# ═══════════════════════════════════════════════════════════════════════
# §7  BACKWARD-COMPATIBLE INTERFACES
# ═══════════════════════════════════════════════════════════════════════


class L4ScoringEngine:
    """Backward-compatible wrapper matching original L4_scoring.py signature.

    Delegates to ``L4SessionScoring`` internally.
    Pipeline calls ``L4ScoringEngine().score(l1, l2, l3)`` — unchanged.
    """

    def __init__(self) -> None:
        self._inner = L4SessionScoring()

    def set_l3_output(self, l3_output: dict[str, Any]) -> None:
        """Propagate L3 constitutional output to inner engine."""
        self._inner.set_l3_output(l3_output)

    def score(
        self,
        l1: dict[str, Any],
        l2: dict[str, Any],
        l3: dict[str, Any],
    ) -> dict[str, Any]:
        """Compute Wolf 30-Point score from L1-L3 outputs.

        Returns dict matching original L4_scoring.py output shape
        PLUS additive ``bayesian`` key (ignored by v2 consumers).
        """
        full = self._inner.analyze(l1=l1, l2=l2, l3=l3)

        return {
            "wolf_30_point": {
                "total": full["wolf_30_point"]["total"],
                "f_score": full["wolf_30_point"]["f_score"],
                "t_score": full["wolf_30_point"]["t_score"],
                "fta_score": full["wolf_30_point"]["fta_score"],
                "exec_score": full["wolf_30_point"]["exec_score"],
            },
            "grade": full["grade"],
            "technical_score": full["technical_score"],
            "valid": full["valid"],
            "bayesian": full["bayesian"],
        }


def analyze_session(
    market_data: dict[str, Any],
    pair: str = "GBPUSD",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Backward-compatible session-only analysis.

    Same signature and return shape as original
    ``l4_session.analyze_session()``.
    """
    if now is None:
        now = datetime.now(UTC)

    ctx = _compute_session_context(pair, now)

    return {
        "session": ctx["session"],
        "quality": ctx["quality"],
        "tradeable": ctx["tradeable"],
        "gate_reasons": ctx["gate_reasons"],
        "near_event": ctx["near_event"],
        "event_name": ctx["event_name"],
        "hour_utc": ctx["hour_utc"],
        "day_of_week": ctx["day_of_week"],
        "pair": pair,
        "valid": True,
        "timestamp": now.isoformat(),
    }


def analyze_session_scoring(
    l1: dict[str, Any],
    l2: dict[str, Any],
    l3: dict[str, Any],
    pair: str = "GBPUSD",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Convenience function for full L4 analysis without class instantiation."""
    return L4SessionScoring().analyze(
        l1=l1,
        l2=l2,
        l3=l3,
        pair=pair,
        now=now,
    )
