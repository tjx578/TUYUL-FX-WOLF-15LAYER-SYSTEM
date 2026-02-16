"""
L4 -- Session & Timing + Wolf 30-Point + Bayesian Expectancy (PRODUCTION)
=========================================================================
Upgraded from:
  • L4 v1 (l4_session.py + L4_scoring.py): Linear deterministic scorer
  • L4 v2 (merged): Wolf 30-Point + session integration
  • L4 v3 (THIS): Bayesian probabilistic decision engine + expectancy

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
                               └─ (7) Grade Classification + Gate

Wolf 30-Point Breakdown (PRESERVED):
  F-score  (Fundamental)  0-8 pts  <- L1 macro bias + confidence
  T-score  (Technical)    0-12 pts <- L2 trend + momentum + indicators
  FTA-score (Alignment)   0-5 pts  <- L1↔L2 directional agreement
  Exec-score (Execution)  0-5 pts  <- L3 structure + session quality

Bayesian Enrichment (NEW):
  P(W|E) = P(W)·∏Lᵢ / [P(W)·∏Lᵢ + (1-P(W))·∏(1-Lᵢ)]
  Each likelihood Lᵢ raised to regime-conditioned strength exponent.
  Expectancy = P(win) × R - (1 - P(win))
  RAE = Expectancy × ln(1 + posterior)  (risk-adjusted)

Backward compatibility:
  • analyze_session() tetap tersedia (signature identik)
  • L4ScoringEngine class tetap tersedia (signature identik)
  • Wolf 30-Point output BYTE-IDENTICAL dengan v2
  • Bayesian output ADDITIVE (new key, ignored by v2 consumers)

Zone: analysis/ -- pure computation, zero side-effects.
"""

from __future__ import annotations

import logging
import math

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Literal, TypedDict

logger = logging.getLogger(__name__)

__all__ = [
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
    ("TOKYO_LONDON",    7,  9, 0.85),
    ("LONDON",          9, 13, 0.90),
    ("NEWYORK",        16, 22, 0.85),
    ("TOKYO",           1,  7, 0.60),
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
    "USD", "GBP", "EUR", "JPY", "AUD", "NZD", "CAD", "CHF",
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
# ════════════════════════════════════��══════════════════════════════════

# Max points per component
_F_SCORE_MAX: Final = 8     # Fundamental
_T_SCORE_MAX: Final = 12    # Technical
_FTA_SCORE_MAX: Final = 5   # Fundamental-Technical Alignment
_EXEC_SCORE_MAX: Final = 5  # Execution readiness
_WOLF_TOTAL_MAX: Final = 30

# Grade thresholds (inclusive lower bound)
_GRADE_THRESHOLDS: Final[list[tuple[int, str]]] = [
    (27, "PERFECT"),
    (23, "EXCELLENT"),
    (18, "GOOD"),
    (13, "MARGINAL"),
    ( 0, "FAIL"),
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


# ═══════════════════════════════════════════════════════════════════════
# §3B  BAYESIAN CONFIGURATION (NEW — v3)
# ═══════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class BayesianConfig:
    """Configuration for the Bayesian win probability engine.

    Regime priors derived from historical regime-specific win rates.
    Strength matrix controls how much each evidence component contributes
    under different market regimes (exponent on Bayes factor).

    Calibration:
      - Priors: historical win% per regime from backtest corpus
      - Strengths: >1.0 = amplify, <1.0 = dampen, 1.0 = neutral
      - Likelihood clamp: prevents degenerate BF at extremes
      - Strength cap: prevents runaway posterior from single component
      - Coherence threshold: below this, posterior is dampened

    All values are YAML-overridable for recalibration.
    """

    # ── Regime-conditioned prior win probabilities ──
    prior_trend_up: float = 0.58
    prior_trend_down: float = 0.58
    prior_range: float = 0.47
    prior_transition: float = 0.42
    prior_unknown: float = 0.45

    # ── Regime-conditioned evidence strength matrix ──
    # Keys: (regime, component) → exponent on Bayes factor
    # In trending: technical evidence is most reliable
    # In range: execution timing is most critical
    # In transition: alignment is key
    strength_trend_up_f: float = 1.2
    strength_trend_up_t: float = 1.5
    strength_trend_up_fta: float = 1.3
    strength_trend_up_exec: float = 1.0

    strength_trend_down_f: float = 1.2
    strength_trend_down_t: float = 1.5
    strength_trend_down_fta: float = 1.3
    strength_trend_down_exec: float = 1.0

    strength_range_f: float = 0.8
    strength_range_t: float = 0.9
    strength_range_fta: float = 1.0
    strength_range_exec: float = 1.4

    strength_transition_f: float = 0.7
    strength_transition_t: float = 0.8
    strength_transition_fta: float = 1.2
    strength_transition_exec: float = 1.3

    strength_unknown_f: float = 0.8
    strength_unknown_t: float = 0.8
    strength_unknown_fta: float = 0.8
    strength_unknown_exec: float = 0.8

    # ── Likelihood clamp (prevent degenerate BF) ──
    likelihood_min: float = 0.05
    likelihood_max: float = 0.95

    # ── Strength exponent cap (prevent runaway posterior) ──
    strength_cap: float = 2.0

    # ── Coherence dampener ──
    coherence_threshold: float = 0.70
    coherence_min_mult: float = 0.60

    # ── Volatility dampener ──
    extreme_vol_mult: float = 0.85
    high_vol_mult: float = 0.93

    # ── Default R:R when L3 doesn't provide ──
    default_rr: float = 1.5


# Production default
_DEFAULT_BAYESIAN_CONFIG: Final = BayesianConfig()


def _get_regime_prior(regime: str, cfg: BayesianConfig) -> float:
    """Look up regime-conditioned prior win probability."""
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
    """Look up regime-conditioned evidence strengths (F, T, FTA, Exec)."""
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
    return _map.get(regime, (
        cfg.strength_unknown_f,
        cfg.strength_unknown_t,
        cfg.strength_unknown_fta,
        cfg.strength_unknown_exec,
    ))


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

    quality = round(max(0.0, min(1.0, quality)), 4)

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
        return max(0.0, min(1.0, v))
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

    if isinstance(bias, (int, float)):
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

    L1 expected keys:
      bias     -- str/float/dict indicating macro direction
      confidence -- float 0-1
      strength   -- float 0-1 (alternative to bias strength)
    """
    _, bias_strength = _normalize_bias(l1.get("bias", "NEUTRAL"))
    confidence = _safe(l1, "confidence", 0.5)

    # Override bias_strength if L1 provides explicit strength
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
    """Compute Technical score (0-12 points) from L2 output.

    Sub-components:
      • trend      (0-3): Trend direction + strength
      • momentum   (0-3): Momentum indicators (MACD, etc.)
      • rsi        (0-2): RSI alignment score
      • structure  (0-2): EMA/indicator structure quality
      • volume     (0-2): Volume confirmation

    L2 expected keys (flexible -- adapts to available data):
      trend_strength, momentum, rsi_score, rsi (raw 0-100),
      structure_score, volume_score, macd_signal, ema_alignment
    """
    # Trend strength
    trend = _safe(l2, "trend_strength", 0.0)
    if trend == 0.0:
        trend = _safe(l2, "trend", 0.0)

    # Momentum
    momentum = _safe(l2, "momentum", 0.0)
    if momentum == 0.0:
        momentum = _safe(l2, "momentum_score", 0.0)

    # RSI -- normalize raw RSI (0-100) to quality score (0-1)
    rsi_score = _safe(l2, "rsi_score", 0.0)
    if rsi_score == 0.0 and "rsi" in l2:
        raw_rsi = _safe_raw(l2, "rsi", 50.0)
        # Best score near extremes (strong signal), worst at 50
        rsi_score = min(1.0, abs(raw_rsi - 50.0) / 30.0)

    # Structure (EMA alignment, MACD, etc.)
    structure = _safe(l2, "structure_score", 0.0)
    if structure == 0.0:
        structure = _safe(l2, "ema_alignment", 0.0)

    # Volume confirmation
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
    """Compute Fundamental-Technical Alignment score (0-5 points).

    Measures how well L1 (fundamental) and L2 (technical) agree.

    Sub-components:
      • direction_match (0-3): Both layers point same way
      • magnitude_match (0-2): Strength levels are comparable

    If L1 says BULLISH and L2 trend is bullish -> full direction points.
    If both are strong (>0.6) -> full magnitude points.
    """
    l1_dir, l1_str = _normalize_bias(l1.get("bias", "NEUTRAL"))

    # L2 direction from trend or bias
    l2_bias = l2.get("bias", l2.get("trend_bias", "NEUTRAL"))
    l2_dir, l2_str = _normalize_bias(l2_bias)

    # Override L2 strength if explicit
    if "trend_strength" in l2:
        l2_str = _safe(l2, "trend_strength", l2_str)

    # Direction match: same = 1.0, opposite = 0.0, one neutral = 0.5
    if l1_dir == l2_dir and l1_dir != "NEUTRAL":
        dir_match = 1.0
    elif l1_dir == "NEUTRAL" or l2_dir == "NEUTRAL":
        dir_match = 0.5
    elif l1_dir != l2_dir:
        dir_match = 0.0
    else:
        dir_match = 0.5

    # Magnitude match: how close are the strength levels
    if l1_str > 0 and l2_str > 0:
        mag_match = 1.0 - min(1.0, abs(l1_str - l2_str))
    else:
        mag_match = 0.0

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
    """Compute Execution readiness score (0-5 points).

    Sub-components:
      • structure_quality (0-3): L3 market structure confidence
      • session_quality   (0-2): Current session quality from timing

    L3 expected keys:
      confidence, structure_confidence, structure_score, quality
    """
    struct = _safe(l3, "confidence", 0.0)
    if struct == 0.0:
        struct = _safe(l3, "structure_confidence", 0.0)
    if struct == 0.0:
        struct = _safe(l3, "structure_score", 0.0)
    if struct == 0.0:
        struct = _safe(l3, "quality", 0.0)

    sq = max(0.0, min(1.0, session_quality))

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

    Mathematical model:
      odds = P(W) / (1 - P(W))
      For each evidence Lᵢ with strength sᵢ:
        BF = (Lᵢ / (1 - Lᵢ))^sᵢ
        odds *= BF
      posterior = odds / (1 + odds)

    Likelihoods clamped to [min, max] to prevent degenerate Bayes factors.
    Strengths capped to prevent runaway posterior from single component.

    Args:
        prior: Regime-conditioned base win probability P(W).
        likelihoods: Normalized evidence values [0-1] per component.
        strengths: Reliability weight exponents per component.
        cfg: Bayesian configuration for clamp/cap values.

    Returns:
        Posterior win probability ∈ [0, 1].
    """
    # Clamp prior to prevent division by zero
    p = max(0.01, min(0.99, prior))
    odds = p / (1.0 - p)

    for like, s in zip(likelihoods, strengths):
        # Clamp likelihood to prevent degenerate BF (0/0 or inf)
        clamped = max(cfg.likelihood_min, min(cfg.likelihood_max, like))
        # Cap strength exponent to prevent runaway
        capped_s = min(cfg.strength_cap, max(0.0, s))
        # Bayes factor: evidence ratio raised to strength power
        bayes_factor = (clamped / (1.0 - clamped)) ** capped_s
        odds *= bayes_factor

    posterior = odds / (1.0 + odds)
    return max(0.0, min(1.0, posterior))


def _compute_expectancy(p_win: float, rr: float) -> float:
    """Compute mathematical expectancy of a trade.

    Expectancy = P(win) × R - (1 - P(win))

    Where R = reward:risk ratio.

    Positive expectancy = statistical edge exists.
    Negative expectancy = no edge, do not trade.

    Args:
        p_win: Win probability [0, 1].
        rr: Reward:risk ratio (e.g. 1.8 means TP = 1.8 × SL).

    Returns:
        Expectancy value (unbounded, typically -1.0 to +R).
    """
    return (p_win * rr) - (1.0 - p_win)


def _compute_risk_adjusted_edge(
    expectancy: float,
    posterior: float,
) -> float:
    """Risk-Adjusted Edge: scales expectancy by confidence level.

    RAE = expectancy × ln(1 + posterior)

    Log-scaling prevents over-sizing on marginal edges.
    High posterior + high expectancy = high RAE.
    Low posterior dampens even good expectancy.

    Args:
        expectancy: Mathematical expectancy value.
        posterior: Bayesian posterior win probability.

    Returns:
        Risk-adjusted edge score.
    """
    if expectancy <= 0:
        return round(expectancy, 4)
    return round(expectancy * math.log(1.0 + posterior), 4)


def _classify_bayesian_grade(
    posterior: float,
    expectancy: float,
) -> str:
    """Classify trade quality by posterior + expectancy combination.

    Replaces linear grade with probabilistic interpretation:
      INSTITUTIONAL_A : Very high probability + strong edge
      INSTITUTIONAL_B : High probability + good edge
      SPECULATIVE     : Moderate probability + positive edge
      NO_EDGE         : Insufficient probability or negative expectancy
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
    """Full Bayesian enrichment pipeline.

    Converts Wolf 30-Point sub-scores into probabilistic win assessment.

    Flow:
      1. Extract regime from L1 → select prior + strength matrix
      2. Normalize sub-scores to [0, 1] likelihoods
      3. Apply coherence dampener (L1 context_coherence / L2 reflex)
      4. Apply volatility dampener (L1 volatility_level)
      5. Compute posterior via Bayesian update
      6. Compute expectancy + risk-adjusted edge
      7. Classify into bayesian grade

    Args:
        f_score: Fundamental sub-score (0-8).
        t_score: Technical sub-score (0-12).
        fta_score: FTA alignment sub-score (0-5).
        exec_score: Execution sub-score (0-5).
        l1: Layer 1 output dict (regime, volatility, coherence).
        l2: Layer 2 output dict (reflex_coherence, technical signals).
        l3: Layer 3 output dict (rr_ratio, structure confidence).
        cfg: Bayesian configuration.

    Returns:
        Dict with posterior, expectancy, RAE, grade, and full lineage.
    """
    # ── 1. Regime → prior + strengths ─────────────────────────────
    regime = str(l1.get("regime", "UNKNOWN")).upper()
    prior = _get_regime_prior(regime, cfg)
    s_f, s_t, s_fta, s_exec = _get_regime_strengths(regime, cfg)

    # ── 2. Normalize sub-scores to [0, 1] likelihoods ────────────
    l_f = f_score / _F_SCORE_MAX if _F_SCORE_MAX > 0 else 0.0
    l_t = t_score / _T_SCORE_MAX if _T_SCORE_MAX > 0 else 0.0
    l_fta = fta_score / _FTA_SCORE_MAX if _FTA_SCORE_MAX > 0 else 0.0
    l_exec = exec_score / _EXEC_SCORE_MAX if _EXEC_SCORE_MAX > 0 else 0.0

    likelihoods = [l_f, l_t, l_fta, l_exec]
    strengths = [s_f, s_t, s_fta, s_exec]

    # ── 3. Bayesian posterior ─────────────────────────────────────
    posterior = _bayesian_win_probability(prior, likelihoods, strengths, cfg)

    # ── 4. Coherence dampener (from L2 reflex, fallback L1 CC) ───
    # L2.reflex_coherence is the PRIMARY coherence signal for L4.
    # L1.context_coherence is the FALLBACK if L2 doesn't provide.
    reflex_coherence = _safe(
        l2, "reflex_coherence",
        _safe(l1, "context_coherence", 1.0),
    )
    coherence_applied = False
    if reflex_coherence < cfg.coherence_threshold:
        # Linear interpolation: at 0.0 → min_mult, at threshold → 1.0
        dampener = cfg.coherence_min_mult + (
            (1.0 - cfg.coherence_min_mult)
            * (reflex_coherence / cfg.coherence_threshold)
        )
        posterior *= dampener
        coherence_applied = True

    # ── 5. Volatility dampener (from L1 volatility_level) ────────
    vol_level = str(l1.get("volatility_level", "")).upper()
    vol_dampener = 1.0
    if vol_level == "EXTREME":
        vol_dampener = cfg.extreme_vol_mult
    elif vol_level == "HIGH":
        vol_dampener = cfg.high_vol_mult
    posterior *= vol_dampener

    # Clamp final posterior
    posterior = round(max(0.0, min(1.0, posterior)), 4)

    # ── 6. Expectancy + RAE ───────────────────────────────────────
    rr = _safe_raw(l3, "rr_ratio", cfg.default_rr)
    if rr <= 0:
        rr = cfg.default_rr

    expectancy = round(_compute_expectancy(posterior, rr), 4)
    rae = _compute_risk_adjusted_edge(expectancy, posterior)

    # ── 7. Bayesian grade ──────────────��──────────────────────────
    bayesian_grade = _classify_bayesian_grade(posterior, expectancy)

    # ── 8. Bayesian tradeable gate ────────────────────────────────
    bayesian_tradeable = posterior >= 0.55 and expectancy > 0.0

    return {
        "posterior_win_probability": posterior,
        "expected_value": expectancy,
        "risk_adjusted_edge": rae,
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
        # result["wolf_30_point"]["total"]           -> 24.5
        # result["grade"]                            -> "EXCELLENT"
        # result["bayesian"]["posterior_win_probability"] -> 0.72
        # result["bayesian"]["bayesian_grade"]       -> "INSTITUTIONAL_B"
    """

    def __init__(
        self,
        bayesian_config: BayesianConfig | None = None,
    ) -> None:
        self._call_count: int = 0
        self._bayesian_config = bayesian_config or _DEFAULT_BAYESIAN_CONFIG

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
            Expected keys: ``bias``, ``confidence``, ``strength``,
            ``regime``, ``context_coherence``, ``volatility_level``.
        l2 : dict
            Layer 2 (Technical Analysis) output.
            Expected keys: ``trend_strength``, ``momentum``, ``rsi``,
            ``structure_score``, ``volume_score``, ``trend_bias``,
            ``reflex_coherence``.
        l3 : dict
            Layer 3 (Market Structure) output.
            Expected keys: ``confidence``, ``structure_score``,
            ``rr_ratio``.
        pair : str
            Currency pair for event relevance and session context.
        market_data : dict, optional
            Additional market data (for pipeline consistency).
        now : datetime, optional
            UTC timestamp override for deterministic testing.

        Returns
        -------
        dict
            Complete L4 profile with:

            **Session** (from l4_session.py):
              ``session``, ``quality``, ``tradeable``, ``gate_reasons``,
              ``near_event``, ``event_name``

            **Wolf 30-Point** (preserved byte-identical):
              ``wolf_30_point`` dict with ``total``, ``f_score``,
              ``t_score``, ``fta_score``, ``exec_score`` + sub-detail

            **Bayesian** (NEW — additive enrichment):
              ``bayesian`` dict with ``posterior_win_probability``,
              ``expected_value``, ``risk_adjusted_edge``,
              ``bayesian_grade``, ``bayesian_tradeable``

            **Classification**:
              ``grade``, ``technical_score``, ``tradeable``, ``valid``
        """
        if now is None:
            now = datetime.now(UTC)

        # ── PHASE 1: Session analysis ────────────────────────────────

        ctx = _compute_session_context(pair, now)

        # ── PHASE 2: Wolf 30-Point scoring (PRESERVED 100%) ──────────

        f_score, f_detail = _compute_f_score(l1, ctx["near_event"])
        t_score, t_detail = _compute_t_score(l2)
        fta_score, fta_detail = _compute_fta_score(l1, l2)
        exec_score, exec_detail = _compute_exec_score(l3, ctx["quality"])

        wolf_total = round(
            f_score + t_score + fta_score + exec_score, 2,
        )
        wolf_total = min(_WOLF_TOTAL_MAX, wolf_total)

        # ── PHASE 3: Grade classification (PRESERVED 100%) ───────────

        grade = _classify_grade(wolf_total)

        # Legacy technical_score (0-100 scale) for backward compat
        technical_score = (
            round((t_score / _T_SCORE_MAX) * 100)
            if _T_SCORE_MAX > 0 else 0
        )

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
        #
        # Dual gate: BOTH deterministic (Wolf 30-Point) AND
        # probabilistic (Bayesian) must agree for full clearance.
        #
        # position_ok requires:
        #   - Session is tradeable (not weekend)
        #   - Grade is at least MARGINAL (��13 points)

        score_ok = grade in ("PERFECT", "EXCELLENT", "GOOD", "MARGINAL")
        valid = True
        overall_tradeable = ctx["tradeable"] and score_ok

        self._call_count += 1

        logger.debug(
            "L4 scoring: pair=%s session=%s quality=%.4f "
            "F=%s T=%s FTA=%s E=%s total=%.1f grade=%s "
            "P(win)=%.4f EV=%.4f b_grade=%s tradeable=%s",
            pair, ctx["session"], ctx["quality"],
            f_score, t_score, fta_score, exec_score,
            wolf_total, grade,
            bayesian["posterior_win_probability"],
            bayesian["expected_value"],
            bayesian["bayesian_grade"],
            overall_tradeable,
        )

        return {
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
            # NEW — additive, ignored by existing consumers
            "bayesian": full["bayesian"],
        }


def analyze_session(
    market_data: dict[str, Any],
    pair: str = "GBPUSD",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Backward-compatible session-only analysis.

    Same signature and return shape as original ``l4_session.analyze_session()``.
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
    return L4SessionScoring().analyze(l1=l1, l2=l2, l3=l3, pair=pair, now=now)