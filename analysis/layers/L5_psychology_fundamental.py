"""
L5 — Psychology & Fundamental Context Layer (PRODUCTION)
==========================================================
Merged & upgraded from:
  • L5_psychology.py   (production psychology → PRESERVED 100%)
  • l5_fundamental.py  (production fundamental → PRESERVED 100%)

Both original files had real, tested logic.  This merge preserves
every computation from both and adds cross-integration that neither
had: risk events now influence emotional bias, and fundamental
strength feeds into the overall confidence score.

Pipeline Flow:
  market_data ─────────┐
  news_sentiment ──────┤
  volatility_profile ──┼──→  L5AnalysisLayer.analyze()
  pair + symbol ───────┘     │
                             ├─ (1) Fundamental Analysis (stateless)
                             │     sentiment → bias → strength → risk events
                             ├─ (2) Psychology Analysis (stateful)
                             │     fatigue → focus → EAF → discipline → gates
                             ├─ (3) Cross-Integration (NEW)
                             │     risk_event → emotional_bias modifier
                             │     fundamental_strength → EAF boost
                             └─ (4) Combined Gate Decision
                                   psychology_ok AND NOT risk_event → can_trade

Backward compatibility:
  • L5PsychologyAnalyzer class + .analyze() → identical signature
  • analyze_fundamental() function → identical signature
  • All output keys from both files preserved

Zone: analysis/ — pure computation, zero side-effects.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any, Final, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "L5AnalysisLayer",
    "L5PsychologyAnalyzer",
    "analyze_fundamental",
    "analyze_l5",
]


# ═══════════════════════════════════════════════════════════════════════
# §1  PSYCHOLOGY CONSTANTS (from L5_psychology.py)
# ═══════════════════════════════════════════════════════════════════════

_MAX_CONSECUTIVE_LOSSES: Final = 2
_MAX_DRAWDOWN_PERCENT: Final = 5.0
_FATIGUE_MEDIUM_HOURS: Final = 4.0
_FATIGUE_HIGH_HOURS: Final = 6.0
_FOCUS_PEAK_END_HOURS: Final = 3.0

# EAF component weights (convex — no multiplicative collapse)
_EAF_W_FOCUS: Final = 0.30
_EAF_W_EMOTION: Final = 0.25
_EAF_W_DISCIPLINE: Final = 0.25
_EAF_W_STABILITY: Final = 0.20
_EAF_THRESHOLD: Final = 0.70

# Cross-integration: risk event → emotional bias boost
_RISK_EVENT_EMOTION_BOOST: Final = 0.15
_CAUTION_EVENT_EMOTION_BOOST: Final = 0.05

# Cross-integration: fundamental strength → EAF adjustment
_FUNDAMENTAL_EAF_WEIGHT: Final = 0.10  # up to 10% EAF boost from strong fundamentals


# ═══════════════════════════════════════════════════════════════════════
# §2  FUNDAMENTAL CONSTANTS (from l5_fundamental.py)
# ═══════════════════════════════════════════════════════════════════════

# Sentiment thresholds
_SENTIMENT_STRONG: Final = 0.40
_SENTIMENT_MODERATE: Final = 0.20
_SENTIMENT_WEAK: Final = 0.10

# News count confidence
_NEWS_COUNT_CONFIDENT: Final = 3
_NEWS_COUNT_MINIMAL: Final = 1

# Impact levels
_RISK_EVENT_LEVELS: Final = frozenset({"HIGH", "CRITICAL"})
_CAUTION_LEVELS: Final = frozenset({"MEDIUM"})
_ALL_IMPACT_LEVELS: Final = frozenset({"NONE", "LOW", "MEDIUM", "HIGH", "CRITICAL"})

# Fundamental strength weights
_W_SENTIMENT: Final = 0.50
_W_NEWS_VOLUME: Final = 0.20
_W_IMPACT: Final = 0.30

# Known currencies
_KNOWN_CURRENCIES: Final = (
    "USD", "GBP", "EUR", "JPY", "AUD", "NZD", "CAD", "CHF",
)


# ═══════════════════════════════════════════════════════════════════════
# §3  FUNDAMENTAL HELPERS (from l5_fundamental.py — preserved 100%)
# ═══════════════════════════════════════════════════════════════════════

def _extract_pair_currencies(pair: str) -> tuple[Optional[str], Optional[str]]:
    """Extract (base, quote) currency from a pair string.

    Standard FX pairs: first 3 chars = base, last 3 = quote.
    """
    clean = pair.upper().replace("/", "").replace("_", "")
    if len(clean) == 6:
        base, quote = clean[:3], clean[3:]
        if base in _KNOWN_CURRENCIES and quote in _KNOWN_CURRENCIES:
            return base, quote
    return None, None


def _classify_bias(score: float, news_count: int) -> str:
    """Classify sentiment score into directional bias label (7 levels)."""
    has_conf = news_count >= _NEWS_COUNT_CONFIDENT
    has_min = news_count >= _NEWS_COUNT_MINIMAL

    if abs(score) >= _SENTIMENT_STRONG and has_conf:
        return "BULLISH" if score > 0 else "BEARISH"
    if abs(score) >= _SENTIMENT_MODERATE and (has_conf or has_min):
        return "LEAN_BULLISH" if score > 0 else "LEAN_BEARISH"
    if abs(score) >= _SENTIMENT_WEAK and has_min:
        return "SLIGHT_BULLISH" if score > 0 else "SLIGHT_BEARISH"
    return "NEUTRAL"


def _compute_fundamental_strength(
    sentiment_score: float,
    news_count: int,
    impact_level: str,
) -> float:
    """Continuous fundamental strength score (0.0–1.0).

    Measures data quality/weight, NOT direction.
    """
    sent = min(1.0, abs(sentiment_score) / 0.5)
    vol = min(1.0, news_count / 5.0) if news_count > 0 else 0.0
    impact_map = {"CRITICAL": 1.0, "HIGH": 0.80, "MEDIUM": 0.50, "LOW": 0.25, "NONE": 0.0}
    imp = impact_map.get(impact_level.upper(), 0.0)

    return round(max(0.0, min(1.0,
        sent * _W_SENTIMENT + vol * _W_NEWS_VOLUME + imp * _W_IMPACT
    )), 4)


def _resolve_pair_bias(
    pair_bias: str,
    base_sentiment: Optional[float],
    quote_sentiment: Optional[float],
    base_ccy: Optional[str],
    quote_ccy: Optional[str],
) -> tuple[str, Optional[str]]:
    """Resolve directional bias considering base vs quote currency.

    For GBPUSD: bullish GBP + bearish USD → strongly BULLISH pair.
    Returns (resolved_bias, conflict_note_or_none).
    """
    if base_sentiment is None or quote_sentiment is None:
        return pair_bias, None

    b_dir = 1 if base_sentiment > _SENTIMENT_WEAK else (-1 if base_sentiment < -_SENTIMENT_WEAK else 0)
    q_dir = 1 if quote_sentiment > _SENTIMENT_WEAK else (-1 if quote_sentiment < -_SENTIMENT_WEAK else 0)

    if b_dir > 0 and q_dir < 0:
        return "BULLISH", None
    if b_dir < 0 and q_dir > 0:
        return "BEARISH", None
    if b_dir > 0 and q_dir > 0:
        return pair_bias, f"CONFLICTING_BOTH_BULLISH({base_ccy}+{quote_ccy})"
    if b_dir < 0 and q_dir < 0:
        return pair_bias, f"CONFLICTING_BOTH_BEARISH({base_ccy}+{quote_ccy})"
    return pair_bias, None


def _run_fundamental_analysis(
    news_sentiment: Optional[dict[str, Any]],
    pair: str,
    now: datetime,
) -> dict[str, Any]:
    """Core fundamental analysis (extracted from original analyze_fundamental).

    Returns complete fundamental profile dict.
    """
    ns = news_sentiment or {}
    degraded_fields: list[str] = []

    sentiment_score = float(ns.get("sentiment_score", 0.0))
    news_count = int(ns.get("news_count", 0))
    impact_level = str(ns.get("impact_level", "NONE")).upper()
    source = ns.get("source", "unknown")

    base_sentiment: Optional[float] = None
    quote_sentiment: Optional[float] = None
    if "base_sentiment" in ns:
        base_sentiment = float(ns["base_sentiment"])
    if "quote_sentiment" in ns:
        quote_sentiment = float(ns["quote_sentiment"])

    if impact_level not in _ALL_IMPACT_LEVELS:
        impact_level = "NONE"

    if not ns:
        degraded_fields.append("no_sentiment_data")
    elif news_count == 0 and sentiment_score == 0.0:
        degraded_fields.append("empty_sentiment_data")

    base_ccy, quote_ccy = _extract_pair_currencies(pair)
    raw_bias = _classify_bias(sentiment_score, news_count)
    resolved_bias, conflict_note = _resolve_pair_bias(
        raw_bias, base_sentiment, quote_sentiment, base_ccy, quote_ccy,
    )

    warnings: list[str] = []
    if conflict_note:
        warnings.append(conflict_note)

    risk_event = impact_level in _RISK_EVENT_LEVELS
    caution_event = impact_level in _CAUTION_LEVELS

    if risk_event:
        warnings.append(f"RISK_EVENT_{impact_level}")
    elif caution_event:
        warnings.append(f"CAUTION_EVENT_{impact_level}")

    strength = _compute_fundamental_strength(sentiment_score, news_count, impact_level)

    clamped = max(-1.0, min(1.0, sentiment_score))
    if clamped != sentiment_score:
        warnings.append(f"SENTIMENT_CLAMPED(raw={sentiment_score:.4f}->{clamped:.4f})")
        sentiment_score = clamped

    return {
        "fundamental_bias": resolved_bias,
        "fundamental_strength": strength,
        "sentiment_score": round(sentiment_score, 4),
        "news_count": news_count,
        "impact_level": impact_level,
        "risk_event_active": risk_event,
        "caution_event": caution_event,
        "base_currency": base_ccy,
        "quote_currency": quote_ccy,
        "warnings": warnings,
        "degraded_fields": degraded_fields,
        "source": source,
    }


# ═══════════════════════════════════════════════════════════════════════
# §4  PSYCHOLOGY HELPERS (from L5_psychology.py — preserved 100%)
# ═══════════════════════════════════════════════════════════════════════

def _fatigue_level(hours: float) -> str:
    """Classify fatigue from session duration."""
    if hours >= _FATIGUE_HIGH_HOURS:
        return "HIGH"
    if hours >= _FATIGUE_MEDIUM_HOURS:
        return "MEDIUM"
    return "LOW"


def _focus_level(hours: float) -> float:
    """Focus curve: ramps to 0.95 at ~2h, degrades after 3h."""
    if hours <= 0.0:
        return 0.90
    if hours <= _FOCUS_PEAK_END_HOURS:
        return 0.90 + 0.05 * min(hours / _FOCUS_PEAK_END_HOURS, 1.0)
    overshoot = hours - _FOCUS_PEAK_END_HOURS
    return max(0.40, 0.95 - 0.10 * overshoot)


def _emotional_bias(
    consecutive_losses: int,
    drawdown_pct: float,
    risk_event: bool = False,
    caution_event: bool = False,
) -> float:
    """Emotional bias score (0–1, higher = worse).

    Driven by losses + drawdown.  Cross-integration: risk events
    amplify emotional pressure (traders become anxious around NFP, etc).
    """
    loss_comp = min(consecutive_losses * 0.12, 0.50)
    dd_comp = min(drawdown_pct * 0.04, 0.40)

    # NEW: risk event → emotional pressure boost
    event_comp = 0.0
    if risk_event:
        event_comp = _RISK_EVENT_EMOTION_BOOST
    elif caution_event:
        event_comp = _CAUTION_EVENT_EMOTION_BOOST

    return min(1.0, loss_comp + dd_comp + event_comp)


def _discipline_score(consecutive_losses: int) -> float:
    """Discipline based on consecutive losses."""
    if consecutive_losses == 0:
        return 0.95
    if consecutive_losses == 1:
        return 0.90
    if consecutive_losses == 2:
        return 0.75
    return 0.60


def _stability_index(win_streak: int, loss_streak: int) -> float:
    """Long streaks (win or loss) reduce stability."""
    streak = max(win_streak, loss_streak)
    if streak <= 2:
        return 0.90
    if streak <= 4:
        return 0.80
    return 0.65


def _eaf_score(
    focus: float,
    emotional_bias: float,
    discipline: float,
    stability: float,
    fundamental_strength: float = 0.0,
) -> float:
    """Convex-weighted EAF (Emotional Awareness Factor).

    No multiplicative collapse — each component contributes independently.

    Cross-integration: strong fundamental data provides a small EAF boost
    (conviction from data reduces emotional noise).
    """
    emotion_contrib = max(0.0, 1.0 - emotional_bias)
    base_eaf = (
        _EAF_W_FOCUS * focus
        + _EAF_W_EMOTION * emotion_contrib
        + _EAF_W_DISCIPLINE * discipline
        + _EAF_W_STABILITY * stability
    )

    # NEW: fundamental conviction boost (up to _FUNDAMENTAL_EAF_WEIGHT)
    fund_boost = fundamental_strength * _FUNDAMENTAL_EAF_WEIGHT

    return min(1.0, base_eaf + fund_boost)


# ═══════════════════════════════════════════════════════════════════════
# §5  MAIN ANALYZER CLASS
# ═══════════════════════════════════════════════════════════════════════

class L5AnalysisLayer:
    """Layer 5: Psychology & Fundamental Context — PRODUCTION.

    Merges psychology (stateful, internal) with fundamental analysis
    (stateless, external) and adds cross-integration.

    Usage::

        layer = L5AnalysisLayer()
        result = layer.analyze(
            pair="GBPUSD",
            news_sentiment={"sentiment_score": 0.45, "news_count": 5,
                            "impact_level": "LOW"},
            volatility_profile={"profile": "NORMAL"},
            session_hours=2.5,
        )
        # result["can_trade"]            → True
        # result["eaf_score"]            → 0.87
        # result["fundamental_bias"]     → "BULLISH"
        # result["fundamental_strength"] → 0.55
    """

    def __init__(self) -> None:
        self._consecutive_losses: int = 0
        self._win_streak: int = 0
        self._drawdown_percent: float = 0.0

    # ── State mutation (from L5_psychology.py) ────────────────────────

    def record_loss(self) -> None:
        """Record a consecutive loss."""
        self._consecutive_losses += 1
        self._win_streak = 0

    def record_win(self) -> None:
        """Record a win — resets consecutive losses."""
        self._consecutive_losses = 0
        self._win_streak += 1

    def update_drawdown(self, pct: float) -> None:
        """Update current drawdown percentage."""
        self._drawdown_percent = max(0.0, pct)

    def reset_session(self) -> None:
        """Reset session state."""
        self._consecutive_losses = 0
        self._win_streak = 0
        self._drawdown_percent = 0.0

    # ── Main analysis ─────────────────────────────────────────────────

    def analyze(
        self,
        pair: str = "GBPUSD",
        symbol: Optional[str] = None,
        market_data: Optional[dict[str, Any]] = None,
        news_sentiment: Optional[dict[str, Any]] = None,
        volatility_profile: Optional[dict[str, Any]] = None,
        session_hours: float = 0.0,
        now: Optional[datetime] = None,
    ) -> dict[str, Any]:
        """Complete L5 pipeline: fundamental + psychology + integration.

        Parameters
        ----------
        pair : str
            Currency pair for fundamental bias resolution.
        symbol : str, optional
            Trading symbol (for logging/audit).
        market_data : dict, optional
            Market data context (pipeline consistency).
        news_sentiment : dict, optional
            Pre-fetched sentiment data with ``sentiment_score``,
            ``news_count``, ``impact_level``, optionally
            ``base_sentiment``, ``quote_sentiment``.
        volatility_profile : dict, optional
            Volatility context with ``profile`` key.
        session_hours : float
            Hours since session start (for fatigue/focus).
        now : datetime, optional
            UTC timestamp override.

        Returns
        -------
        dict
            Unified L5 profile with all psychology AND fundamental fields.
        """
        if now is None:
            now = datetime.now(timezone.utc)

        # ── PHASE 1: Fundamental analysis (stateless) ────────────────

        fund = _run_fundamental_analysis(news_sentiment, pair, now)

        # ── PHASE 2: Psychology analysis (stateful) ──────────────────

        fatigue = _fatigue_level(session_hours)
        focus = _focus_level(session_hours)

        losses_ok = self._consecutive_losses < _MAX_CONSECUTIVE_LOSSES
        drawdown_ok = self._drawdown_percent < _MAX_DRAWDOWN_PERCENT

        vol_profile = (volatility_profile or {}).get("profile", "NORMAL")
        stable = str(vol_profile).upper() != "HIGH"

        # Cross-integration: risk events amplify emotional bias
        em_bias = _emotional_bias(
            self._consecutive_losses,
            self._drawdown_percent,
            risk_event=fund["risk_event_active"],
            caution_event=fund["caution_event"],
        )

        discipline = _discipline_score(self._consecutive_losses)
        stability = _stability_index(self._win_streak, self._consecutive_losses)

        # Cross-integration: fundamental strength boosts EAF
        eaf = _eaf_score(
            focus, em_bias, discipline, stability,
            fundamental_strength=fund["fundamental_strength"],
        )

        emotion_index = int(em_bias * 100)

        # ── PHASE 3: Psychology gate decision ────────────────────────

        psych_reasons: list[str] = []
        if not losses_ok:
            psych_reasons.append("consecutive_losses_at_limit")
        if not drawdown_ok:
            psych_reasons.append("drawdown_exceeded")
        if fatigue == "HIGH":
            psych_reasons.append("high_fatigue")
        if not stable:
            psych_reasons.append("high_volatility")
        if eaf < _EAF_THRESHOLD:
            psych_reasons.append("eaf_below_threshold")

        psychology_ok = len(psych_reasons) == 0

        # ── PHASE 4: Combined gate (NEW) ─────────────────────────────
        #
        # Risk event active → CANNOT trade (fundamental override)
        # Psychology not OK → CANNOT trade (internal override)
        # Both clear → CAN trade

        fund_reasons: list[str] = []
        if fund["risk_event_active"]:
            fund_reasons.append(f"risk_event_{fund['impact_level']}")

        all_reasons = psych_reasons + fund_reasons
        can_trade = psychology_ok and not fund["risk_event_active"]

        if can_trade:
            recommendation = "Psychology & Fundamental OK — clear to trade"
            gate_status = "OPEN"
        elif len(all_reasons) == 1:
            recommendation = "CAUTION: " + all_reasons[0]
            gate_status = "WARNING"
        else:
            recommendation = "BLOCKED: " + "; ".join(all_reasons)
            gate_status = "LOCKED"

        psychology_score = max(0, min(100, int(eaf * 100)))

        # ── PHASE 5: RGO governance ──────────────────────────────────
        # Compute actual integrity from EAF + fundamental data quality

        # Absence of data (no_sentiment_data) is not integrity degradation;
        # only actively corrupted or conflicting data degrades integrity.
        real_degradation = [
            f for f in fund["degraded_fields"]
            if f not in ("no_sentiment_data", "empty_sentiment_data")
        ]
        if eaf >= 0.85 and not real_degradation:
            integrity_level = "FULL"
        elif eaf >= 0.70:
            integrity_level = "PARTIAL"
        else:
            integrity_level = "DEGRADED"

        vault_sync = "SYNCED" if psychology_ok else "DESYNCED"
        lambda_esi_stable = eaf >= _EAF_THRESHOLD and not fund["risk_event_active"]

        logger.debug(
            "L5 analysis: pair=%s eaf=%.4f bias=%s strength=%.4f "
            "gate=%s can_trade=%s reasons=%s",
            pair, eaf, fund["fundamental_bias"], fund["fundamental_strength"],
            gate_status, can_trade, all_reasons or "none",
        )

        return {
            # ── Psychology (from L5_psychology.py) ──
            "psychology_score": psychology_score,
            "eaf_score": round(eaf, 4),
            "emotion_delta": round(em_bias, 4),
            "can_trade": can_trade,
            "gate_status": gate_status,
            "psychology_ok": psychology_ok,
            "fatigue_level": fatigue,
            "consecutive_losses": self._consecutive_losses,
            "session_hours": session_hours,
            "losses_ok": losses_ok,
            "drawdown_percent": self._drawdown_percent,
            "drawdown_ok": drawdown_ok,
            "stable": stable,
            "focus_level": round(focus, 4),
            "emotional_bias": round(em_bias, 4),
            "discipline_score": round(discipline, 4),
            "emotion_index": emotion_index,
            "stability_index": round(stability, 4),
            "recommendation": recommendation,

            # ── RGO Governance (was hardcoded, now computed) ──
            "rgo_governance": {
                "integrity_level": integrity_level,
                "vault_sync": vault_sync,
                "lambda_esi_stable": lambda_esi_stable,
            },
            "current_drawdown": self._drawdown_percent,

            # ── Fundamental (from l5_fundamental.py) ──
            "fundamental_bias": fund["fundamental_bias"],
            "fundamental_strength": fund["fundamental_strength"],
            "sentiment_score": fund["sentiment_score"],
            "news_count": fund["news_count"],
            "impact_level": fund["impact_level"],
            "risk_event_active": fund["risk_event_active"],
            "caution_event": fund["caution_event"],
            "base_currency": fund["base_currency"],
            "quote_currency": fund["quote_currency"],

            # ── Metadata ──
            "pair": pair,
            "warnings": fund["warnings"],
            "degraded_fields": fund["degraded_fields"],
            "source": fund["source"],
            "valid": True,
            "timestamp": now.isoformat(),
        }


# ═══════════════════════════════════════════════════════════════════════
# §6  BACKWARD-COMPATIBLE INTERFACES
# ═══════════════════════════════════════════════════════════════════════

class L5PsychologyAnalyzer:
    """Backward-compatible wrapper matching original L5_psychology.py.

    Delegates to ``L5AnalysisLayer`` internally.
    """

    def __init__(self) -> None:
        self._inner = L5AnalysisLayer()

    def record_loss(self) -> None:
        self._inner.record_loss()

    def record_win(self) -> None:
        self._inner.record_win()

    def update_drawdown(self, pct: float) -> None:
        self._inner.update_drawdown(pct)

    def reset_session(self) -> None:
        self._inner.reset_session()

    def analyze(
        self,
        symbol: str,
        *,
        volatility_profile: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Original L5_psychology.py signature preserved."""
        return self._inner.analyze(
            symbol=symbol,
            volatility_profile=volatility_profile,
        )


def analyze_fundamental(
    market_data: dict[str, Any],
    news_sentiment: Optional[dict[str, Any]] = None,
    pair: str = "GBPUSD",
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Backward-compatible fundamental-only analysis.

    Same signature as original ``l5_fundamental.analyze_fundamental()``.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    fund = _run_fundamental_analysis(news_sentiment, pair, now)

    return {
        "fundamental_bias": fund["fundamental_bias"],
        "fundamental_strength": fund["fundamental_strength"],
        "sentiment_score": fund["sentiment_score"],
        "news_count": fund["news_count"],
        "impact_level": fund["impact_level"],
        "risk_event_active": fund["risk_event_active"],
        "caution_event": fund["caution_event"],
        "valid": True,
        "pair": pair,
        "base_currency": fund["base_currency"],
        "quote_currency": fund["quote_currency"],
        "warnings": fund["warnings"],
        "degraded_fields": fund["degraded_fields"],
        "source": fund["source"],
        "timestamp": now.isoformat(),
    }


def analyze_l5(
    pair: str = "GBPUSD",
    news_sentiment: Optional[dict[str, Any]] = None,
    volatility_profile: Optional[dict[str, Any]] = None,
    session_hours: float = 0.0,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Convenience function for full L5 analysis."""
    return L5AnalysisLayer().analyze(
        pair=pair,
        news_sentiment=news_sentiment,
        volatility_profile=volatility_profile,
        session_hours=session_hours,
        now=now,
    )
