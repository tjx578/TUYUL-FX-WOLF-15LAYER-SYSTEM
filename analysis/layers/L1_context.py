"""
🧭 L1 -- Context Layer (PRODUCTION v2)
----------------------------------------
Adaptive multi-asset regime detection via:
  - SMA 20/50 crossover with ATR-normalized thresholds (asset-agnostic)
  - ATR-14 for volatility classification (asset-adaptive percentile)
  - Session awareness (London/NY/Tokyo overlap)
  - Volume-weighted CSI (Contextual Strength Index) v2 (momentum-aware)
  - EMA-9 momentum layer (short-term directional bias)
  - Regime quality score (composite confidence metric)

Upgrade from v1:
  ✅ ATR-normalized regime threshold (replaces static 0.002)
  ✅ Asset-adaptive volatility classification (replaces fixed ATR% bands)
  ✅ Trend strength scaled by ATR (replaces spread×200)
  ✅ Enhanced CSI v2 with momentum component
  ✅ EMA-9 short-term momentum enrichment
  ✅ Regime quality composite (trend + vol + session + momentum)
  ✅ Multi-timeframe regime summary ready for downstream layers
  ✅ Dataclass-based AssetProfile for clean extensibility
  ✅ Input validation with ContextError exception
  ✅ Type-safe return contract via ContextResult dataclass

Zone: analysis/ -- pure read-only analysis, no execution side-effects.
"""

from __future__ import annotations

import logging
import math

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# ── Optional Engine Enrichment ────────────────────────────────────────────
# RegimeClassifier (Hurst-exponent) gives statistical regime confirmation
# as a secondary signal alongside the SMA-based primary detection.
try:
    from engines.regime_classifier_ml import (
        RegimeClassifier,  # pyright: ignore[reportMissingImports]
    )

    _regime_classifier: RegimeClassifier | None = RegimeClassifier()
except Exception:  # pragma: no cover
    _regime_classifier = None

__all__ = [
    "AssetProfile",
    "ContextError",
    "ContextResult",
    "L1ContextAnalyzer",
    "analyze_context",
]


# ═══════════════════════════════════════════════════════════════════════════
# §0  EXCEPTIONS
# ═══════════════════════════════════════════════════════════════════════════


class ContextError(Exception):
    """Raised for invalid L1 input data."""


# ═══════════════════════════════════════════════════════════════════════════
# §1  ASSET PROFILES (adaptive thresholds per instrument class)
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class AssetProfile:
    """Per-asset-class calibration for regime and volatility thresholds.

    Instead of a single static threshold (0.002), we derive thresholds
    from ATR-normalized spread.  The ``k_trend`` / ``k_transition``
    multipliers determine how many ATRs of SMA spread constitute
    a trend vs. transition.

    Attributes
    ----------
    k_trend : float
        ATR-normalized spread multiplier for TREND detection.
        regime = TREND when  |sma_spread| > k_trend * (ATR / price)
    k_transition : float
        ATR-normalized spread multiplier for TRANSITION detection.
        regime = TRANSITION when  |sma_spread| > k_transition * (ATR / price)
    vol_percentiles : tuple[float, float, float, float]
        (extreme, high, normal, low) thresholds as ATR%  — session-adjusted.
    trend_scale : float
        Replaces the hardcoded ``spread × 200``.
        trend_strength = min(1.0, |spread| / (k_trend * atr_frac) )
    """

    k_trend: float = 1.5
    k_transition: float = 0.4
    vol_percentiles: tuple[float, float, float, float] = (1.5, 0.8, 0.3, 0.1)
    trend_scale: float = 1.0  # normalizer — 1.0 = threshold = max strength


# Pre-built profiles for known asset classes.
# Missing symbols gracefully fall back to FX_PROFILE (the most conservative).
FX_PROFILE = AssetProfile(
    k_trend=1.5,
    k_transition=0.4,
    vol_percentiles=(1.5, 0.8, 0.3, 0.1),
)
METALS_PROFILE = AssetProfile(
    k_trend=1.2,
    k_transition=0.35,
    vol_percentiles=(3.0, 1.5, 0.6, 0.2),
)
CRYPTO_PROFILE = AssetProfile(
    k_trend=1.0,
    k_transition=0.3,
    vol_percentiles=(5.0, 2.5, 1.0, 0.4),
)
INDEX_PROFILE = AssetProfile(
    k_trend=1.3,
    k_transition=0.35,
    vol_percentiles=(2.5, 1.2, 0.5, 0.15),
)

_ASSET_CLASS_MAP: dict[str, AssetProfile] = {
    # Metals
    "XAUUSD": METALS_PROFILE,
    "XAGUSD": METALS_PROFILE,
    # Crypto
    "BTCUSD": CRYPTO_PROFILE,
    "ETHUSD": CRYPTO_PROFILE,
    # Indices
    "US30": INDEX_PROFILE,
    "US500": INDEX_PROFILE,
    "NAS100": INDEX_PROFILE,
}


def _get_asset_profile(pair: str) -> AssetProfile:
    """Resolve asset profile.  Falls back to FX for unknown symbols."""
    return _ASSET_CLASS_MAP.get(pair.upper(), FX_PROFILE)


# ═══════════════════════════════════════════════════════════════════════════
# §2  SESSION MODEL
# ═══════════════════════════════════════════════════════════════════════════

# Session definitions: (name, start_hour_utc, end_hour_utc, multiplier)
# Ordered by priority -- overlaps checked first.
SESSIONS = {
    "LONDON_NEWYORK_OVERLAP": (13, 16, 1.30),
    "TOKYO_LONDON_OVERLAP": (7, 9, 1.15),
    "LONDON": (7, 16, 1.10),
    "NEWYORK": (13, 22, 1.05),
    "TOKYO": (0, 9, 0.85),
    "SYDNEY": (22, 7, 0.70),
}

_MIN_BARS = 20


def _get_session(h: int) -> tuple[str, float]:
    """Return (session_name, multiplier) for a given UTC hour.

    Priority order: overlaps first, then single sessions, then Sydney fallback.
    """
    if 13 <= h < 16:
        return "LONDON_NEWYORK_OVERLAP", 1.30
    if 7 <= h < 9:
        return "TOKYO_LONDON_OVERLAP", 1.15
    if 9 <= h < 13:
        return "LONDON", 1.10
    if 16 <= h < 22:
        return "NEWYORK", 1.05
    if 0 <= h < 7:
        return "TOKYO", 0.85
    return "SYDNEY", 0.70


# ═══════════════════════════════════════════════════════════════════════════
# §3  CORE INDICATORS (pure functions)
# ═══════════════════════════════════════════════════════════════════════════


def _sma(data: list[float], n: int) -> float:
    """Simple moving average over the last *n* values of *data*."""
    if not data:
        return 0.0
    if len(data) < n:
        return sum(data) / len(data)
    return sum(data[-n:]) / n


def _ema(data: list[float], n: int) -> float:
    """Exponential moving average over the full series, return last value.

    Uses standard EMA formula:  EMA_t = α * price_t + (1-α) * EMA_{t-1}
    where α = 2 / (n+1).

    Falls back to SMA if data length < n.
    """
    if not data:
        return 0.0
    if len(data) < n:
        return sum(data) / len(data)
    alpha = 2.0 / (n + 1)
    ema_val = sum(data[:n]) / n  # seed with SMA
    for price in data[n:]:
        ema_val = alpha * price + (1.0 - alpha) * ema_val
    return ema_val


def _atr(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> float:
    """Average True Range over *period* bars (simple average, not smoothed)."""
    n = min(period, len(highs) - 1)
    if n < 1:
        return 0.0
    trs: list[float] = []
    for i in range(len(highs) - n, len(highs)):
        prev_close = closes[i - 1]
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - prev_close),
            abs(lows[i] - prev_close),
        )
        trs.append(tr)
    return sum(trs) / len(trs) if trs else 0.0


# ═══════════════════════════════════════════════════════════════════════════
# §4  REGIME DETECTION (ATR-normalized, asset-adaptive)
# ═══════════════════════════════════════════════════════════════════════════


def _classify_volatility(
    adj_atr_pct: float,
    profile: AssetProfile,
) -> str:
    """Map session-adjusted ATR% to volatility label using asset profile."""
    ext, high, normal, low = profile.vol_percentiles
    if adj_atr_pct > ext:
        return "EXTREME"
    if adj_atr_pct > high:
        return "HIGH"
    if adj_atr_pct > normal:
        return "NORMAL"
    if adj_atr_pct > low:
        return "LOW"
    return "DEAD"


def _detect_regime(
    spread: float,
    atr_frac: float,
    profile: AssetProfile,
) -> tuple[str, str]:
    """Return (regime, dominant_force) using ATR-normalized thresholds.

    Thresholds:
      TREND      when |spread| > k_trend      * atr_frac
      TRANSITION when |spread| > k_transition * atr_frac
      RANGE      otherwise

    Where atr_frac = ATR / price (dimensionless volatility measure).
    """
    trend_thresh = profile.k_trend * atr_frac
    trans_thresh = profile.k_transition * atr_frac

    # Guard: if ATR is zero/negligible fall back to static thresholds
    if atr_frac < 1e-9:
        trend_thresh = 0.002
        trans_thresh = 0.0005

    if spread > trend_thresh:
        return "TREND_UP", "BULLISH"
    if spread < -trend_thresh:
        return "TREND_DOWN", "BEARISH"
    if abs(spread) > trans_thresh:
        return "TRANSITION", "NEUTRAL"
    return "RANGE", "NEUTRAL"


def _compute_trend_strength(
    spread: float,
    atr_frac: float,
    profile: AssetProfile,
) -> float:
    """ATR-normalized trend strength [0.0, 1.0].

    At exactly the trend threshold → strength = 1.0 × profile.trend_scale.
    Linearly interpolated below that.  Capped at 1.0.
    """
    threshold = profile.k_trend * atr_frac
    if threshold < 1e-12:
        # Fallback: use legacy scaling when ATR data unavailable
        return min(1.0, abs(spread) * 200.0)
    raw = abs(spread) / threshold
    return min(1.0, raw * profile.trend_scale)


# ═══════════════════════════════════════════════════════════════════════════
# §5  ALIGNMENT & CSI
# ═══════════════════════════════════════════════════════════════════════════


def _compute_alignment(
    close: float,
    sma20: float,
    sma50: float,
    ema9: float,
    spread: float,
    regime: str,
) -> str:
    """Price-to-SMA alignment label (enriched with EMA-9 momentum)."""
    above20 = close > sma20
    above50 = close > sma50
    above_ema9 = close > ema9

    if above20 and above50 and above_ema9 and regime == "TREND_UP":
        return "STRONGLY_BULLISH"
    if not above20 and not above50 and not above_ema9 and regime == "TREND_DOWN":
        return "STRONGLY_BEARISH"
    if above20 and above_ema9 and spread > 0:
        return "BULLISH"
    if not above20 and not above_ema9 and spread < 0:
        return "BEARISH"
    return "NEUTRAL"


def _compute_momentum_bias(
    closes: list[float],
    ema9: float,
) -> tuple[str, float]:
    """Short-term momentum direction and magnitude.

    Returns (direction, magnitude) where magnitude ∈ [0, 1].
    """
    if not closes or ema9 == 0.0:
        return "NEUTRAL", 0.0
    price = closes[-1]
    deviation = (price - ema9) / ema9
    magnitude = min(1.0, abs(deviation) * 100)  # 1% deviation = full strength
    if deviation > 0.0001:
        return "BULLISH", round(magnitude, 4)
    if deviation < -0.0001:
        return "BEARISH", round(magnitude, 4)
    return "NEUTRAL", 0.0


def _compute_csi(
    trend_strength: float,
    volumes: list[float],
    session_mult: float,
    momentum_magnitude: float,
) -> float:
    """Contextual Strength Index v2 (0-1 range, momentum-enriched).

    CSI v2 = trend_strength × 0.35
           + volume_factor  × 0.25
           + session_factor × 0.20
           + momentum       × 0.20

    Volume factor: ratio of last volume to 20-bar average, capped at 1.0.
    Session factor: session multiplier normalized to [0, 1].
    Momentum: short-term EMA-9 deviation strength.
    """
    vol_factor = 0.5
    if volumes and len(volumes) >= 20:
        avg_v = sum(volumes[-20:]) / 20
        if avg_v > 0:
            vol_factor = min(1.0, (volumes[-1] / avg_v) / 2.0)

    csi = (
        trend_strength * 0.35
        + vol_factor * 0.25
        + (session_mult / 1.3) * 0.20
        + momentum_magnitude * 0.20
    )
    return round(min(1.0, csi), 4)


# ═══════════════════════════════════════════════════════════════════════════
# §6  REGIME QUALITY SCORE
# ═══════════════════════════════════════════════════════════════════════════


def _compute_regime_quality(
    trend_strength: float,
    vol_level: str,
    session_mult: float,
    momentum_magnitude: float,
    regime_agreement: bool | None,
) -> float:
    """Composite regime quality score [0.0, 1.0].

    Weights:
      - trend_strength:      0.30  (how decisive is the regime?)
      - volatility_penalty:  0.20  (EXTREME/DEAD penalize quality)
      - session_quality:     0.20  (overlaps are highest quality)
      - momentum_coherence:  0.15  (EMA-9 agrees with trend?)
      - hurst_agreement:     0.15  (SMA regime matches Hurst?)

    Higher = more reliable context for downstream layers.
    """
    # Volatility quality: NORMAL = best, EXTREME/DEAD = worst
    vol_quality_map = {
        "NORMAL": 1.0,
        "HIGH": 0.7,
        "LOW": 0.6,
        "EXTREME": 0.3,
        "DEAD": 0.2,
    }
    vol_q = vol_quality_map.get(vol_level, 0.5)

    sess_q = min(1.0, session_mult / 1.3)

    hurst_q = 0.5  # neutral default
    if regime_agreement is True:
        hurst_q = 1.0
    elif regime_agreement is False:
        hurst_q = 0.0

    quality = (
        trend_strength * 0.30
        + vol_q * 0.20
        + sess_q * 0.20
        + momentum_magnitude * 0.15
        + hurst_q * 0.15
    )
    return round(min(1.0, quality), 4)


# ═══════════════════════════════════════════════════════════════════════════
# §7  RESULT CONTRACT
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ContextResult:
    """Immutable L1 Context output contract.

    All downstream layers (L2-L12) consume this via ``to_dict()``.
    """

    regime: str
    dominant_force: str
    volatility_level: str
    regime_confidence: float
    csi: float
    market_alignment: str
    valid: bool
    session: str
    session_multiplier: float
    sma20: float
    sma50: float
    ema9: float
    sma_spread_pct: float
    atr: float
    atr_pct: float
    pair: str
    timestamp: str
    asset_class: str
    momentum_direction: str
    momentum_magnitude: float
    trend_strength: float
    regime_quality: float
    reason: str = ""

    # Optional Hurst enrichment fields
    hurst_regime: str | None = None
    hurst_confidence: float | None = None
    hurst_exponent: float | None = None
    hurst_volatility_state: str | None = None
    hurst_momentum: float | None = None
    regime_agreement: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for downstream layer consumption."""
        result = asdict(self)
        # Strip None Hurst fields when enrichment unavailable
        return {k: v for k, v in result.items() if v is not None}


# ═══════════════════════════════════════════════════════════════════════════
# §8  INPUT VALIDATION
# ═══════════════════════════════════════════════════════════════════════════


def _classify_asset(pair: str) -> str:
    """Return human-readable asset class label for output."""
    upper = pair.upper()
    if upper in ("XAUUSD", "XAGUSD"):
        return "METALS"
    if upper in ("BTCUSD", "ETHUSD"):
        return "CRYPTO"
    if upper in ("US30", "US500", "NAS100"):
        return "INDEX"
    return "FX"


def _validate_market_data(
    closes: list[float],
    highs: list[float],
    lows: list[float],
) -> None:
    """Validate market data integrity.

    Raises ContextError on invalid data.
    """
    if not closes:
        raise ContextError("closes data is empty")

    # Check for NaN/Inf in closes
    for i, c in enumerate(closes[-_MIN_BARS:]):
        if not math.isfinite(c):
            raise ContextError(
                f"closes[{len(closes) - _MIN_BARS + i}] = {c} is not finite"
            )
        if c <= 0:
            raise ContextError(
                f"closes[{len(closes) - _MIN_BARS + i}] = {c} must be positive"
            )

    if highs and lows:
        check_len = min(len(highs), len(lows), _MIN_BARS)
        for i in range(len(highs) - check_len, len(highs)):
            if highs[i] < lows[i]:
                raise ContextError(
                    f"high[{i}]={highs[i]} < low[{i}]={lows[i]}"
                )


# ═══════════════════════════════════════════════════════════════════════════
# §9  MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════


def analyze_context(
    market_data: dict[str, Any],
    pair: str = "GBPUSD",
    now: datetime | None = None,
) -> dict[str, Any]:
    """L1 Context -- PRODUCTION v2.

    Pure analysis function.  Returns regime, volatility, alignment, CSI,
    momentum, and regime quality.  No execution side-effects.

    Enhancements over v1:
      - ATR-normalized regime thresholds (asset-agnostic)
      - Asset-adaptive volatility classification
      - ATR-scaled trend strength (replaces spread×200)
      - EMA-9 short-term momentum layer
      - Regime quality composite score
      - ContextResult dataclass contract

    Parameters
    ----------
    market_data : dict
        Must contain ``closes`` (or ``close``) with ≥ 20 bars.
        Optionally ``highs``/``lows``/``volumes``.
    pair : str
        Currency pair / instrument label.
    now : datetime, optional
        Override for current UTC time (useful for testing).

    Returns
    -------
    dict[str, Any]
        Context analysis result.  Always includes ``valid`` key.

    Raises
    ------
    ContextError
        On data integrity issues (NaN, negative prices, high < low).
    """
    closes: list[float] = market_data.get(
        "closes", market_data.get("close", [])
    )
    highs: list[float] = market_data.get(
        "highs", market_data.get("high", [])
    )
    lows: list[float] = market_data.get(
        "lows", market_data.get("low", [])
    )
    volumes: list[float] = market_data.get(
        "volumes", market_data.get("volume", [])
    )

    if not closes or len(closes) < _MIN_BARS:
        return ContextResult(
            regime="UNKNOWN",
            dominant_force="NEUTRAL",
            volatility_level="UNKNOWN",
            regime_confidence=0.0,
            csi=0.0,
            market_alignment="NEUTRAL",
            valid=False,
            session="UNKNOWN",
            session_multiplier=0.0,
            sma20=0.0,
            sma50=0.0,
            ema9=0.0,
            sma_spread_pct=0.0,
            atr=0.0,
            atr_pct=0.0,
            pair=pair,
            timestamp=datetime.now(UTC).isoformat(),
            asset_class=_classify_asset(pair),
            momentum_direction="NEUTRAL",
            momentum_magnitude=0.0,
            trend_strength=0.0,
            regime_quality=0.0,
            reason=f"need {_MIN_BARS}+ bars, got {len(closes)}",
        ).to_dict()

    # Validate data integrity
    _validate_market_data(closes, highs, lows)

    if now is None:
        now = datetime.now(UTC)

    profile = _get_asset_profile(pair)
    session, sess_mult = _get_session(now.hour)

    # ── Moving Averages ───────────────────────────────────────────
    sma20 = _sma(closes, 20)
    sma50 = (
        _sma(closes, 50)
        if len(closes) >= 50
        else _sma(closes, len(closes))
    )
    ema9 = _ema(closes, 9)
    spread = (sma20 - sma50) / sma50 if sma50 != 0 else 0.0

    # ── ATR & Volatility ─────────────────────────────────────────
    atr_val = _atr(highs, lows, closes) if highs and lows else 0.0
    price = closes[-1]
    atr_pct = (atr_val / price * 100) if price != 0 else 0.0
    atr_frac = atr_val / price if price != 0 else 0.0  # dimensionless
    adj_atr = atr_pct * sess_mult
    vol_level = _classify_volatility(adj_atr, profile)

    # ── Regime (ATR-normalized) ───────────────────────────────────
    regime, dominant = _detect_regime(spread, atr_frac, profile)

    # ── Trend Strength (ATR-scaled) ──────────────────────────────
    trend_strength = _compute_trend_strength(spread, atr_frac, profile)

    # ── Confidence (trend × volatility penalty) ──────────────────
    vol_penalty = (
        max(0.0, 1.0 - adj_atr * 0.3)
        if vol_level in ("EXTREME", "HIGH")
        else 1.0
    )
    regime_conf = round(trend_strength * vol_penalty, 4)

    # ── Momentum (EMA-9) ─────────────────────────────────────────
    mom_dir, mom_mag = _compute_momentum_bias(closes, ema9)

    # ── CSI v2 ────────────────────────────────────────────────────
    csi = _compute_csi(trend_strength, volumes, sess_mult, mom_mag)

    # ── Alignment (enriched) ─────────────────────────────────────
    alignment = _compute_alignment(
        closes[-1], sma20, sma50, ema9, spread, regime
    )

    # ── Hurst Enrichment (optional) ──────────────────────────────
    hurst_regime: str | None = None
    hurst_conf: float | None = None
    hurst_exp: float | None = None
    hurst_vol_state: str | None = None
    hurst_mom: float | None = None
    regime_agreement: bool | None = None

    if _regime_classifier is not None:
        try:
            rc = _regime_classifier.classify(closes)
            hurst_regime = rc.regime
            hurst_conf = rc.confidence
            hurst_exp = rc.hurst_exponent
            hurst_vol_state = rc.volatility_state
            hurst_mom = rc.momentum
            _sma_trending = regime in ("TREND_UP", "TREND_DOWN")
            _hurst_trending = rc.regime == "TRENDING"
            regime_agreement = _sma_trending == _hurst_trending
        except Exception as exc:
            logger.debug("L1 Hurst enrichment skipped: %s", exc)

    # ── Regime Quality ────────────────────────────────────────────
    regime_quality = _compute_regime_quality(
        trend_strength, vol_level, sess_mult, mom_mag, regime_agreement
    )

    logger.debug(
        "L1 context v2: pair=%s regime=%s vol=%s csi=%.4f "
        "quality=%.4f session=%s asset=%s",
        pair,
        regime,
        vol_level,
        csi,
        regime_quality,
        session,
        _classify_asset(pair),
    )

    result = ContextResult(
        regime=regime,
        dominant_force=dominant,
        volatility_level=vol_level,
        regime_confidence=regime_conf,
        csi=csi,
        market_alignment=alignment,
        valid=True,
        session=session,
        session_multiplier=sess_mult,
        sma20=round(sma20, 5),
        sma50=round(sma50, 5),
        ema9=round(ema9, 5),
        sma_spread_pct=round(spread, 6),
        atr=round(atr_val, 6),
        atr_pct=round(atr_pct, 4),
        pair=pair,
        timestamp=now.isoformat(),
        asset_class=_classify_asset(pair),
        momentum_direction=mom_dir,
        momentum_magnitude=mom_mag,
        trend_strength=round(trend_strength, 4),
        regime_quality=regime_quality,
        hurst_regime=hurst_regime,
        hurst_confidence=hurst_conf,
        hurst_exponent=hurst_exp,
        hurst_volatility_state=hurst_vol_state,
        hurst_momentum=hurst_mom,
        regime_agreement=regime_agreement,
    )

    return result.to_dict()


# ═══════════════════════════════════════════════════════════════════════════
# §10  PIPELINE-COMPATIBLE CLASS WRAPPER
# ═══════════════════════════════════════════════════════════════════════════


class L1ContextAnalyzer:
    """Pipeline-compatible wrapper around :func:`analyze_context`.

    The Wolf Constitutional Pipeline (``wolf_constitutional_pipeline.py``)
    instantiates ``L1ContextAnalyzer()`` and calls ``.analyze(symbol)``.
    This class pulls OHLCV candle data from :class:`LiveContextBus` and
    delegates to the pure ``analyze_context()`` function.
    """

    def __init__(self) -> None:
        from context.live_context_bus import LiveContextBus  # noqa: PLC0415

        self._bus = LiveContextBus()

    def analyze(self, symbol: str) -> dict[str, Any]:
        """Run L1 context analysis for *symbol*.

        Pulls H1 candle history from LiveContextBus, assembles the
        market_data dict, and delegates to ``analyze_context()``.
        """
        candles = self._bus.get_candle_history(symbol, "H1", count=80)

        if not candles:
            return analyze_context({}, pair=symbol)

        closes = [float(c["close"]) for c in candles]
        highs = [float(c["high"]) for c in candles]
        lows = [float(c["low"]) for c in candles]
        volumes = [float(c.get("volume", 1.0)) for c in candles]

        market_data: dict[str, Any] = {
            "closes": closes,
            "highs": highs,
            "lows": lows,
            "volumes": volumes,
        }

        return analyze_context(market_data, pair=symbol)
