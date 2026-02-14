"""
📰 L5 — Fundamental Context Layer (PRODUCTION)
-------------------------------------------------
Provides fundamental awareness and risk event context.
Consumes pre-fetched news sentiment and economic calendar data.

Responsibilities:
  - Derive directional fundamental bias from sentiment data
  - Currency-aware bias (base vs quote when available)
  - Risk event flagging (high-impact news suppression)
  - Continuous fundamental strength score for downstream weighting
  - Degraded-mode tracking when data is absent

Zone: analysis/ — pure read-only analysis, no execution side-effects.
"""

import logging

from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["analyze_fundamental"]

# ── Sentiment Thresholds ────────────────────────────────────────────
_SENTIMENT_STRONG = 0.40
_SENTIMENT_MODERATE = 0.20
_SENTIMENT_WEAK = 0.10

# ── News Count Thresholds ───────────────────────────────────────────
# Minimum articles to trust a sentiment signal
_NEWS_COUNT_CONFIDENT = 3
_NEWS_COUNT_MINIMAL = 1

# ── Impact Levels (ordered by severity) ──────────────────────────────
_RISK_EVENT_LEVELS = frozenset({"HIGH", "CRITICAL"})
_CAUTION_LEVELS = frozenset({"MEDIUM"})
_ALL_IMPACT_LEVELS = frozenset({"NONE", "LOW", "MEDIUM", "HIGH", "CRITICAL"})

# ── Fundamental Strength Weights ─────────────────────────────────────
_W_SENTIMENT = 0.50
_W_NEWS_VOLUME = 0.20
_W_IMPACT = 0.30

# ── Known Currencies ────────────────────────────────────────────────
_KNOWN_CURRENCIES = ("USD", "GBP", "EUR", "JPY", "AUD", "NZD", "CAD", "CHF")


def _extract_pair_currencies(pair: str) -> tuple[str | None, str | None]:
    """Extract (base, quote) currency from a pair string.

    Standard FX pairs: first 3 chars = base, last 3 = quote.
    Returns (None, None) if pair format is unrecognized.
    """
    clean = pair.upper().replace("/", "").replace("_", "")
    if len(clean) == 6:
        base, quote = clean[:3], clean[3:]
        if base in _KNOWN_CURRENCIES and quote in _KNOWN_CURRENCIES:
            return base, quote
    return None, None


def _classify_bias(score: float, news_count: int) -> str:
    """Classify sentiment score into a directional bias label.

    Requires minimum news count for confidence.
    """
    has_confidence = news_count >= _NEWS_COUNT_CONFIDENT
    has_minimal = news_count >= _NEWS_COUNT_MINIMAL

    if abs(score) >= _SENTIMENT_STRONG and has_confidence:
        return "BULLISH" if score > 0 else "BEARISH"
    if abs(score) >= _SENTIMENT_MODERATE and has_confidence:
        return "LEAN_BULLISH" if score > 0 else "LEAN_BEARISH"
    if abs(score) >= _SENTIMENT_MODERATE and has_minimal:
        return "LEAN_BULLISH" if score > 0 else "LEAN_BEARISH"
    if abs(score) >= _SENTIMENT_WEAK and has_minimal:
        return "SLIGHT_BULLISH" if score > 0 else "SLIGHT_BEARISH"
    return "NEUTRAL"


def _compute_fundamental_strength(
    sentiment_score: float,
    news_count: int,
    impact_level: str,
) -> float:
    """Compute a continuous fundamental strength score (0.0–1.0).

    Higher = more actionable fundamental data available.
    This is NOT directional — it measures data quality and weight.
    """
    # Sentiment magnitude component (0–1)
    sent_component = min(1.0, abs(sentiment_score) / 0.5)

    # News volume component (0–1)
    vol_component = min(1.0, news_count / 5.0) if news_count > 0 else 0.0

    # Impact component (0–1)
    impact_map = {
        "CRITICAL": 1.0,
        "HIGH": 0.80,
        "MEDIUM": 0.50,
        "LOW": 0.25,
        "NONE": 0.0,
    }
    impact_component = impact_map.get(impact_level.upper(), 0.0)

    strength = (
        sent_component * _W_SENTIMENT
        + vol_component * _W_NEWS_VOLUME
        + impact_component * _W_IMPACT
    )
    return round(max(0.0, min(1.0, strength)), 4)


def _resolve_pair_bias(
    pair_bias: str,
    base_sentiment: float | None,
    quote_sentiment: float | None,
    base_ccy: str | None,
    quote_ccy: str | None,
) -> tuple[str, str | None]:
    """Resolve directional bias considering base vs quote currency sentiment.

    If per-currency sentiment is available, a pair like GBPUSD is:
      - BULLISH if GBP sentiment > 0 and/or USD sentiment < 0
      - BEARISH if GBP sentiment < 0 and/or USD sentiment > 0

    Returns (resolved_bias, conflict_note_or_none).
    """
    if base_sentiment is None or quote_sentiment is None:
        return pair_bias, None

    # Both currencies have sentiment data
    # For GBPUSD: buy = long GBP, short USD
    #   bullish base + bearish quote → strongly bullish pair
    #   bearish base + bullish quote → strongly bearish pair
    #   same direction → conflicting/neutral
    base_dir = 1 if base_sentiment > _SENTIMENT_WEAK else (-1 if base_sentiment < -_SENTIMENT_WEAK else 0)
    quote_dir = 1 if quote_sentiment > _SENTIMENT_WEAK else (-1 if quote_sentiment < -_SENTIMENT_WEAK else 0)

    if base_dir > 0 and quote_dir < 0:
        return "BULLISH", None  # aligned: long base, short quote
    if base_dir < 0 and quote_dir > 0:
        return "BEARISH", None  # aligned: short base, long quote
    if base_dir > 0 and quote_dir > 0:
        return pair_bias, f"CONFLICTING_BOTH_BULLISH({base_ccy}+{quote_ccy})"
    if base_dir < 0 and quote_dir < 0:
        return pair_bias, f"CONFLICTING_BOTH_BEARISH({base_ccy}+{quote_ccy})"

    return pair_bias, None


def analyze_fundamental(
    market_data: dict[str, Any],
    news_sentiment: dict[str, Any] | None = None,
    pair: str = "GBPUSD",
    now: datetime | None = None,
) -> dict[str, Any]:
    """L5 Fundamental Context — PRODUCTION.

    Pure analysis function.  Produces fundamental bias, strength score,
    and risk event flags from pre-fetched news/sentiment data.
    No execution side-effects.

    Parameters
    ----------
    market_data : dict
        Market data context (accepted for pipeline consistency;
        L5 currently uses it only for optional price context).
    news_sentiment : dict, optional
        Pre-fetched sentiment data.  Expected keys:

        - ``sentiment_score`` (float, -1.0 to 1.0): overall sentiment
        - ``news_count`` (int): number of relevant articles
        - ``impact_level`` (str): "NONE"|"LOW"|"MEDIUM"|"HIGH"|"CRITICAL"
        - ``base_sentiment`` (float, optional): base currency sentiment
        - ``quote_sentiment`` (float, optional): quote currency sentiment
        - ``source`` (str, optional): data source identifier

        If absent or empty, L5 runs in degraded mode with neutral output.
    pair : str
        Currency pair for currency-specific bias resolution.
    now : datetime, optional
        UTC timestamp override (for deterministic testing).

    Returns
    -------
    dict
        Fundamental profile with ``fundamental_bias``, ``fundamental_strength``,
        ``risk_event_active``, ``valid``, etc.
    """
    if now is None:
        now = datetime.now(UTC)

    ns = news_sentiment or {}
    degraded_fields: list[str] = []

    # ── Extract inputs ──
    sentiment_score = float(ns.get("sentiment_score", 0.0))
    news_count = int(ns.get("news_count", 0))
    impact_level = str(ns.get("impact_level", "NONE")).upper()
    source = ns.get("source", "unknown")

    base_sentiment: float | None = None
    quote_sentiment: float | None = None
    if "base_sentiment" in ns:
        base_sentiment = float(ns["base_sentiment"])
    if "quote_sentiment" in ns:
        quote_sentiment = float(ns["quote_sentiment"])

    # ── Validate impact level ──
    if impact_level not in _ALL_IMPACT_LEVELS:
        logger.warning("L5: unknown impact_level '%s', defaulting to NONE", impact_level)
        impact_level = "NONE"

    # ── Degraded mode detection ──
    if not ns:
        degraded_fields.append("no_sentiment_data")
    elif news_count == 0 and sentiment_score == 0.0:
        degraded_fields.append("empty_sentiment_data")

    # ── Parse pair currencies ──
    base_ccy, quote_ccy = _extract_pair_currencies(pair)

    # ── Classify bias ──
    raw_bias = _classify_bias(sentiment_score, news_count)

    # ── Resolve pair-specific bias ──
    resolved_bias, conflict_note = _resolve_pair_bias(
        raw_bias, base_sentiment, quote_sentiment, base_ccy, quote_ccy,
    )

    warnings: list[str] = []
    if conflict_note:
        warnings.append(conflict_note)

    # ── Risk event flag ──
    risk_event = impact_level in _RISK_EVENT_LEVELS
    caution_event = impact_level in _CAUTION_LEVELS

    if risk_event:
        warnings.append(f"RISK_EVENT_{impact_level}")
    elif caution_event:
        warnings.append(f"CAUTION_EVENT_{impact_level}")

    # ── Fundamental strength (continuous score) ──
    strength = _compute_fundamental_strength(sentiment_score, news_count, impact_level)

    # ── Clamp sentiment to expected range ──
    clamped_sentiment = max(-1.0, min(1.0, sentiment_score))
    if clamped_sentiment != sentiment_score:
        warnings.append(
            f"SENTIMENT_CLAMPED(raw={sentiment_score:.4f}→{clamped_sentiment:.4f})"
        )
        sentiment_score = clamped_sentiment

    logger.debug(
        "L5 fundamental: pair=%s bias=%s strength=%.4f risk_event=%s degraded=%s",
        pair, resolved_bias, strength, risk_event, degraded_fields or "none",
    )

    return {
        "fundamental_bias": resolved_bias,
        "fundamental_strength": strength,
        "sentiment_score": round(sentiment_score, 4),
        "news_count": news_count,
        "impact_level": impact_level,
        "risk_event_active": risk_event,
        "caution_event": caution_event,
        "valid": True,
        # Extended detail
        "pair": pair,
        "base_currency": base_ccy,
        "quote_currency": quote_ccy,
        "warnings": warnings,
        "degraded_fields": degraded_fields,
        "source": source,
        "timestamp": now.isoformat(),
    }
