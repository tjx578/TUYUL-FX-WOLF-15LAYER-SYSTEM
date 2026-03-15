"""
🧭 L1 -- Context Layer (PRODUCTION v3 — Probabilistic Regime)
--------------------------------------------------------------
Probabilistic regime detection via 4-feature logistic model:

  X_L1 = [S, A, H, Vz]

  S  = (EMA₂₀ - EMA₅₀) / Price     — Normalized trend spread
  A  = ATR₁₄ / Price                — Normalized volatility
  H  = Hurst exponent (returns)     — Persistence measure [0, 1]
  Vz = Z-score(ATR, lookback=50)    — Volatility regime shift

  P_trend = σ(w₁·S + w₂·A + w₃·H + w₄·Vz + b₀)

  Regime = TREND_UP/DOWN  if P > 0.65
           TRANSITION      if 0.45 < P ≤ 0.65
           RANGE            if P ≤ 0.45

  Context Coherence (Shannon Entropy):
    CC = 1 - H_regime / ln(2)   where H_regime = -Σ pᵢ ln(pᵢ)

Upgrade path:
  v1 (original): Static SMA spread threshold 0.002, no asset adaptation
  v2 (ATR-norm): ATR-normalized thresholds, AssetProfile per-class
  v3 (THIS):     Probabilistic logistic model, Shannon entropy coherence,
                 Hurst as core feature, Z-score volatility percentile,
                 inherently asset-agnostic via price-normalized features

Zone: analysis/ -- pure read-only analysis, no execution side-effects.
"""  # noqa: N999

from __future__ import annotations

import logging
import math
import statistics
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# ── Optional Engine Enrichment ────────────────────────────────────────────
try:
    from engines.regime_classifier_ml import (
        RegimeClassifier,
    )

    _regime_classifier: RegimeClassifier | None = RegimeClassifier()
except Exception:  # pragma: no cover
    _regime_classifier = None

__all__ = [
    "ContextError",
    "ContextResult",
    "L1ContextAnalyzer",
    "LogisticWeights",
    "analyze_context",
]


# ═══════════════════════════════════════════════════════════════════════════
# §0  EXCEPTIONS
# ═══════════════════════════════════════════════════════════════════════════


class ContextError(Exception):
    """Raised for invalid L1 input data."""


# ═══════════════════════════════════════════════════════════════════════════
# §1  LOGISTIC REGIME MODEL — CONFIGURABLE WEIGHTS
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class LogisticWeights:
    """Weights for the logistic regime probability model.

    P_trend = σ(w_spread·S + w_atr·A + w_hurst·H + w_zscore·Vz + bias)

    Derivation (see analysis doc):
      - w_spread = 8.0  → primary trend indicator, highest importance
      - w_atr    = 3.0  → volatility context (trend needs volatility)
      - w_hurst  = 4.0  → statistical persistence confirmation
      - w_zscore = 1.5  → volatility regime shift detector
      - bias     = -2.0 → centers sigmoid so H=0.5, S=0, Vz=0 → P≈0.5

    All weights are YAML-overridable for backtesting calibration.

    Regime thresholds:
      - trend_threshold     = 0.65 → P > 0.65 = TREND
      - transition_threshold = 0.45 → 0.45 < P ≤ 0.65 = TRANSITION
    """

    w_spread: float = 8.0
    w_atr: float = 3.0
    w_hurst: float = 4.0
    w_zscore: float = 1.5
    bias: float = -2.0
    trend_threshold: float = 0.65
    transition_threshold: float = 0.45
    hurst_fallback: float = 0.5


# Default production weights
DEFAULT_WEIGHTS = LogisticWeights()


# ═══════════════════════════════════════════════════════════════════════════
# §2  SESSION MODEL
# ═══════════════════════════════════════════════════════════════════════════

SESSIONS = {
    "LONDON_NEWYORK_OVERLAP": (13, 16, 1.30),
    "TOKYO_LONDON_OVERLAP": (7, 9, 1.15),
    "LONDON": (7, 16, 1.10),
    "NEWYORK": (13, 22, 1.05),
    "TOKYO": (0, 9, 0.85),
    "SYDNEY": (22, 7, 0.70),
}

_MIN_BARS = 20
_ZSCORE_LOOKBACK = 50
_EPS = 1e-9  # clamp guard for log(0)


def _get_session(h: int) -> tuple[str, float]:
    """Return (session_name, multiplier) for a given UTC hour."""
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


def _ema(data: list[float], n: int) -> float:
    """Exponential moving average over the full series, return last value.

    Uses standard EMA formula:  EMA_t = α·price_t + (1-α)·EMA_{t-1}
    where α = 2 / (n+1).  Falls back to SMA if len(data) < n.
    """
    if not data:
        return 0.0
    if len(data) < n:
        return sum(data) / len(data)
    alpha = 2.0 / (n + 1)
    ema_val = sum(data[:n]) / n
    for price in data[n:]:
        ema_val = alpha * price + (1.0 - alpha) * ema_val
    return ema_val


def _atr(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> float:
    """Average True Range over *period* bars (simple average)."""
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


def _atr_series(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> list[float]:
    """Compute rolling ATR series for Z-score calculation.

    Returns one ATR value per bar (from index=period onward).
    Bars before sufficient history return 0.0.
    """
    series: list[float] = []
    for end in range(period + 1, len(highs) + 1):
        trs: list[float] = []
        for i in range(end - period, end):
            if i == 0:
                trs.append(highs[i] - lows[i])
            else:
                prev_close = closes[i - 1]
                tr = max(
                    highs[i] - lows[i],
                    abs(highs[i] - prev_close),
                    abs(lows[i] - prev_close),
                )
                trs.append(tr)
        series.append(sum(trs) / len(trs) if trs else 0.0)
    return series


# ═══════════════════════════════════════════════════════════════════════════
# §4  FEATURE EXTRACTION — X_L1 = [S, A, H, Vz]
# ═══════════════════════════════════════════════════════════════════════════


def _sigmoid(x: float) -> float:
    """Numerically stable sigmoid σ(x) = 1 / (1 + e⁻ˣ)."""
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    ex = math.exp(x)
    return ex / (1.0 + ex)


def _compute_spread(closes: list[float]) -> float:
    """S = (EMA₂₀ - EMA₅₀) / Price.  Dimensionless trend measure."""
    price = closes[-1]
    if price == 0.0:
        return 0.0
    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50) if len(closes) >= 50 else _ema(closes, len(closes))
    return (ema20 - ema50) / price


def _compute_atr_frac(
    highs: list[float],
    lows: list[float],
    closes: list[float],
) -> float:
    """A = ATR₁₄ / Price.  Dimensionless volatility measure."""
    price = closes[-1]
    if price == 0.0 or not highs or not lows:
        return 0.0
    return _atr(highs, lows, closes) / price


def _compute_hurst(closes: list[float]) -> float | None:
    """Compute Hurst exponent via RegimeClassifier engine.

    Returns None if engine unavailable or computation fails.
    Uses the engine from engines/regime_classifier_ml.py which
    implements proper R/S analysis with log-regression.
    """
    if _regime_classifier is None:
        return None
    try:
        rc = _regime_classifier.classify(closes)
        return rc.hurst_exponent
    except Exception:
        return None


def _compute_zscore(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    lookback: int = _ZSCORE_LOOKBACK,
) -> float:
    """Vz = Z-Score(ATR_current, μ_ATR, σ_ATR) over lookback period.

    Vz = (ATR_now - mean(ATR_series)) / max(stdev(ATR_series), ε)

    Returns 0.0 if insufficient data for Z-score computation.
    """
    if not highs or not lows or len(highs) < 15:
        return 0.0

    series = _atr_series(highs, lows, closes)
    if len(series) < 2:
        return 0.0

    # Take last `lookback` ATR values
    window = series[-lookback:] if len(series) >= lookback else series
    current_atr = window[-1]

    mean_atr = statistics.mean(window)
    stdev_atr = statistics.stdev(window) if len(window) > 1 else 0.0

    if stdev_atr < _EPS:
        return 0.0
    return (current_atr - mean_atr) / stdev_atr


def _compute_volatility_percentile(vz: float) -> float:
    """Convert Z-score to percentile via standard normal CDF approximation.

    Uses Abramowitz & Stegun approximation (error < 1.5e-7).
    Output ∈ [0, 1] representing where current ATR sits in historical distribution.
    """
    return 0.5 * (1.0 + math.erf(vz / math.sqrt(2.0)))


# ═══════════════════════════════════════════════════════════════════════════
# §5  LOGISTIC REGIME PROBABILITY + ENTROPY
# ═══════════════════════════════════════════════════════════════════════════


def _compute_regime_probability(
    s: float,
    a: float,
    h: float,
    vz: float,
    w: LogisticWeights,
) -> float:
    """P_trend = σ(w₁·S + w₂·A + w₃·H + w₄·Vz + b₀).

    Args:
        s: EMA spread (normalized).
        a: ATR fraction (normalized).
        h: Hurst exponent [0, 1].
        vz: ATR Z-score.
        w: Logistic weight configuration.

    Returns:
        Regime probability ∈ [0, 1].
    """
    z = w.w_spread * s + w.w_atr * a + w.w_hurst * h + w.w_zscore * vz + w.bias
    return _sigmoid(z)


def _classify_regime(
    p_trend: float,
    s: float,
    w: LogisticWeights,
) -> tuple[str, str]:
    """Classify regime and direction from probability + spread sign.

    Returns (regime_label, dominant_force).
    Direction derived from sign(S): positive = UP/BULLISH, negative = DOWN/BEARISH.
    """
    if p_trend > w.trend_threshold:
        if s > 0:
            return "TREND_UP", "BULLISH"
        return "TREND_DOWN", "BEARISH"
    if p_trend > w.transition_threshold:
        return "TRANSITION", "NEUTRAL"
    return "RANGE", "NEUTRAL"


def _compute_entropy(p_trend: float) -> float:
    """Shannon entropy H_regime = -Σ pᵢ·ln(pᵢ) for binary distribution.

    Input is clamped to [ε, 1-ε] to prevent log(0).
    Output ∈ [0, ln(2)] ≈ [0, 0.6931].
    """
    p = max(_EPS, min(1.0 - _EPS, p_trend))
    q = 1.0 - p
    return -(p * math.log(p) + q * math.log(q))


def _compute_context_coherence(p_trend: float) -> float:
    """Context Coherence: CC = 1 - H_regime / ln(2).

    CC = 1.0 when regime is certain (P=0 or P=1).
    CC = 0.0 when maximum uncertainty (P=0.5).
    Output ∈ [0, 1].
    """
    h = _compute_entropy(p_trend)
    return 1.0 - h / math.log(2.0)


# ═══════════════════════════════════════════════════════════════════════════
# §6  SESSION-ADJUSTED VOLATILITY CLASSIFICATION
# ═══════════════════════════════════════════════════════════════════════════


def _classify_volatility_by_percentile(vol_pct: float) -> str:
    """Map volatility percentile [0,1] to label.

    Percentile-based (not fixed ATR%) → inherently asset-agnostic.
    """
    if vol_pct > 0.95:
        return "EXTREME"
    if vol_pct > 0.75:
        return "HIGH"
    if vol_pct > 0.25:
        return "NORMAL"
    if vol_pct > 0.05:
        return "LOW"
    return "DEAD"


# ═══════════════════════════════════════════════════════════════════════════
# §7  ALIGNMENT & CSI v3
# ═══════════════════════════════════════════════════════════════════════════


def _compute_alignment(
    close: float,
    ema20: float,
    ema50: float,
    ema9: float,
    s: float,
    regime: str,
) -> str:
    """Price-to-EMA alignment label (enriched with EMA-9)."""
    above20 = close > ema20
    above50 = close > ema50
    above9 = close > ema9

    if above20 and above50 and above9 and regime == "TREND_UP":
        return "STRONGLY_BULLISH"
    if not above20 and not above50 and not above9 and regime == "TREND_DOWN":
        return "STRONGLY_BEARISH"
    if above20 and above9 and s > 0:
        return "BULLISH"
    if not above20 and not above9 and s < 0:
        return "BEARISH"
    return "NEUTRAL"


def _compute_momentum_bias(closes: list[float], ema9: float) -> tuple[str, float]:
    """Short-term EMA-9 momentum direction and magnitude [0, 1]."""
    if not closes or ema9 == 0.0:
        return "NEUTRAL", 0.0
    deviation = (closes[-1] - ema9) / ema9
    magnitude = min(1.0, abs(deviation) * 100)
    if deviation > 0.0001:
        return "BULLISH", round(magnitude, 4)
    if deviation < -0.0001:
        return "BEARISH", round(magnitude, 4)
    return "NEUTRAL", 0.0


def _compute_csi(
    p_trend: float,
    volumes: list[float],
    session_mult: float,
    momentum_mag: float,
    context_coherence: float,
) -> float:
    """Contextual Strength Index v3 — probability-weighted.

    CSI v3 = regime_probability × 0.25
           + volume_factor     × 0.20
           + session_factor    × 0.15
           + momentum          × 0.15
           + context_coherence × 0.25

    CC as component = CSI rewards high-confidence regimes.
    """
    vol_factor = 0.5
    if volumes and len(volumes) >= 20:
        avg_v = sum(volumes[-20:]) / 20
        if avg_v > 0:
            vol_factor = min(1.0, (volumes[-1] / avg_v) / 2.0)

    csi = (
        p_trend * 0.25
        + vol_factor * 0.20
        + (session_mult / 1.3) * 0.15
        + momentum_mag * 0.15
        + context_coherence * 0.25
    )
    return round(min(1.0, csi), 4)


# ═══════════════════════════════════════════════════════════════════════════
# §8  RESULT CONTRACT
# ═══════════════════════════════════════════════════════════════════════════


def _classify_asset(pair: str) -> str:
    """Return human-readable asset class label."""
    upper = pair.upper()
    if upper in ("XAUUSD", "XAGUSD"):
        return "METALS"
    if upper in ("BTCUSD", "ETHUSD"):
        return "CRYPTO"
    if upper in ("US30", "US500", "NAS100"):
        return "INDEX"
    return "FX"


@dataclass(frozen=True)
class ContextResult:
    """Immutable L1 Context output contract (v3 — probabilistic).

    All downstream layers (L2-L12) consume via ``to_dict()``.
    New fields: regime_probability, context_coherence, volatility_percentile,
    entropy_score.  All [0, 1] bounded.
    """

    # ── Core regime output ────────────────────────────────────────
    regime: str
    dominant_force: str
    regime_probability: float
    context_coherence: float
    volatility_level: str
    volatility_percentile: float
    entropy_score: float
    regime_confidence: float
    csi: float
    market_alignment: str
    valid: bool

    # ── Session & instrument ──────────────────────────────────────
    session: str
    session_multiplier: float
    pair: str
    asset_class: str
    timestamp: str

    # ── Feature vector (for downstream transparency) ──────────────
    feature_spread: float
    feature_atr_frac: float
    feature_hurst: float
    feature_zscore: float

    # ── Indicator values ──────────────────────────────────────────
    ema20: float
    ema50: float
    ema9: float
    atr: float
    atr_pct: float

    # ── Momentum ──────────────────────────────────────────────────
    momentum_direction: str
    momentum_magnitude: float

    reason: str = ""

    # ── Hurst enrichment (optional — from RegimeClassifier) ──────
    hurst_regime: str | None = None
    hurst_confidence: float | None = None
    hurst_exponent: float | None = None
    hurst_volatility_state: str | None = None
    hurst_momentum: float | None = None
    regime_agreement: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for downstream consumption."""
        result = asdict(self)
        return {k: v for k, v in result.items() if v is not None}


# ═══════════════════════════════════════════════════════════════════════════
# §9  INPUT VALIDATION
# ═══════════════════════════════════════════════════════════════════════════


def _validate_market_data(
    closes: list[float],
    highs: list[float],
    lows: list[float],
) -> None:
    """Validate market data integrity.  Raises ContextError on bad data."""
    if not closes:
        raise ContextError("closes data is empty")

    check_count = min(len(closes), _MIN_BARS)
    for i, c in enumerate(closes[-check_count:]):
        if not math.isfinite(c):
            raise ContextError(f"closes[{len(closes) - check_count + i}] = {c} is not finite")
        if c <= 0:
            raise ContextError(f"closes[{len(closes) - check_count + i}] = {c} must be positive")

    if highs and lows:
        check_len = min(len(highs), len(lows), _MIN_BARS)
        for i in range(len(highs) - check_len, len(highs)):
            if highs[i] < lows[i]:
                raise ContextError(f"high[{i}]={highs[i]} < low[{i}]={lows[i]}")


# ═══════════════════════════════════════════════════════════════════════════
# §10  MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════


def analyze_context(
    market_data: dict[str, Any],
    pair: str = "GBPUSD",
    now: datetime | None = None,
    weights: LogisticWeights | None = None,
) -> dict[str, Any]:
    """L1 Context — PRODUCTION v3 (Probabilistic Regime).

    Pure analysis function.  Returns probabilistic regime classification,
    Shannon entropy coherence, volatility percentile, and CSI v3.
    No execution side-effects.

    Mathematical model:
      X_L1 = [S, A, H, Vz]
      P_trend = σ(w₁·S + w₂·A + w₃·H + w₄·Vz + b₀)
      CC = 1 - H_regime / ln(2)

    Parameters
    ----------
    market_data : dict
        Must contain ``closes`` (or ``close``) with ≥ 20 bars.
        Optionally ``highs``/``lows``/``volumes``.
    pair : str
        Currency pair / instrument label.
    now : datetime, optional
        Override for current UTC time (testing).
    weights : LogisticWeights, optional
        Override model weights (backtesting calibration).

    Returns
    -------
    dict[str, Any]
        Context analysis result.  Always includes ``valid`` key.
        New output fields: regime_probability, context_coherence,
        volatility_percentile, entropy_score.

    Raises
    ------
    ContextError
        On data integrity issues (NaN, negative prices, high < low).
    """
    w = weights or DEFAULT_WEIGHTS

    closes: list[float] = market_data.get("closes", market_data.get("close", []))
    highs: list[float] = market_data.get("highs", market_data.get("high", []))
    lows: list[float] = market_data.get("lows", market_data.get("low", []))
    volumes: list[float] = market_data.get("volumes", market_data.get("volume", []))

    if not closes or len(closes) < _MIN_BARS:
        return ContextResult(
            regime="UNKNOWN",
            dominant_force="NEUTRAL",
            regime_probability=0.0,
            context_coherence=0.0,
            volatility_level="UNKNOWN",
            volatility_percentile=0.0,
            entropy_score=math.log(2.0),
            regime_confidence=0.0,
            csi=0.0,
            market_alignment="NEUTRAL",
            valid=False,
            session="UNKNOWN",
            session_multiplier=0.0,
            pair=pair,
            asset_class=_classify_asset(pair),
            timestamp=datetime.now(UTC).isoformat(),
            feature_spread=0.0,
            feature_atr_frac=0.0,
            feature_hurst=w.hurst_fallback,
            feature_zscore=0.0,
            ema20=0.0,
            ema50=0.0,
            ema9=0.0,
            atr=0.0,
            atr_pct=0.0,
            momentum_direction="NEUTRAL",
            momentum_magnitude=0.0,
            reason=f"need {_MIN_BARS}+ bars, got {len(closes)}",
        ).to_dict()

    _validate_market_data(closes, highs, lows)

    if now is None:
        now = datetime.now(UTC)

    session, sess_mult = _get_session(now.hour)

    # ── Feature Extraction: X_L1 = [S, A, H, Vz] ─────────────────
    s = _compute_spread(closes)
    a = _compute_atr_frac(highs, lows, closes)
    h_raw = _compute_hurst(closes)
    h = h_raw if h_raw is not None else w.hurst_fallback
    vz = _compute_zscore(highs, lows, closes)

    # ── EMA values (for alignment & output) ───────────────────────
    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50) if len(closes) >= 50 else _ema(closes, len(closes))
    ema9 = _ema(closes, 9)

    # ── ATR (for output) ──────────────────────────────────────────
    atr_val = _atr(highs, lows, closes) if highs and lows else 0.0
    price = closes[-1]
    atr_pct = (atr_val / price * 100) if price != 0 else 0.0

    # ── Regime Probability ────────────────────────────────────────
    p_trend = _compute_regime_probability(s, a, h, vz, w)
    regime, dominant = _classify_regime(p_trend, s, w)

    # ── Context Coherence (Shannon Entropy) ───────────────────────
    entropy = _compute_entropy(p_trend)
    cc = _compute_context_coherence(p_trend)

    # ── Volatility Percentile ─────────────────────────────────────
    vol_pct = _compute_volatility_percentile(vz)
    vol_level = _classify_volatility_by_percentile(vol_pct)

    # ── Regime Confidence (CC × session quality) ──────────────────
    sess_quality = min(1.0, sess_mult / 1.3)
    regime_conf = round(cc * sess_quality, 4)

    # ── Momentum ──────────────────────────────────────────────────
    mom_dir, mom_mag = _compute_momentum_bias(closes, ema9)

    # ── CSI v3 ────────────────────────────────────────────────────
    csi = _compute_csi(p_trend, volumes, sess_mult, mom_mag, cc)

    # ── Alignment ─────────────────────────────────────────────────
    alignment = _compute_alignment(
        closes[-1],
        ema20,
        ema50,
        ema9,
        s,
        regime,
    )

    # ── Hurst Enrichment (full result from engine) ────────────────
    hurst_regime: str | None = None
    hurst_conf: float | None = None
    hurst_vol_state: str | None = None
    hurst_mom: float | None = None
    regime_agreement: bool | None = None

    if _regime_classifier is not None and h_raw is not None:
        try:
            rc = _regime_classifier.classify(closes)
            hurst_regime = rc.regime
            hurst_conf = rc.confidence
            hurst_vol_state = rc.volatility_state
            hurst_mom = rc.momentum
            _prob_trending = regime in ("TREND_UP", "TREND_DOWN")
            _hurst_trending = rc.regime == "TRENDING"
            regime_agreement = _prob_trending == _hurst_trending
        except Exception as exc:
            logger.debug("L1 Hurst enrichment skipped: %s", exc)

    logger.debug(
        "L1 v3: pair=%s P=%.4f CC=%.4f regime=%s vol=%s(%s) csi=%.4f session=%s X=[S=%.6f A=%.6f H=%.4f Vz=%.4f]",
        pair,
        p_trend,
        cc,
        regime,
        vol_level,
        _classify_asset(pair),
        csi,
        session,
        s,
        a,
        h,
        vz,
    )

    result = ContextResult(
        regime=regime,
        dominant_force=dominant,
        regime_probability=round(p_trend, 4),
        context_coherence=round(cc, 4),
        volatility_level=vol_level,
        volatility_percentile=round(vol_pct, 4),
        entropy_score=round(entropy, 4),
        regime_confidence=regime_conf,
        csi=csi,
        market_alignment=alignment,
        valid=True,
        session=session,
        session_multiplier=sess_mult,
        pair=pair,
        asset_class=_classify_asset(pair),
        timestamp=now.isoformat(),
        feature_spread=round(s, 8),
        feature_atr_frac=round(a, 8),
        feature_hurst=round(h, 4),
        feature_zscore=round(vz, 4),
        ema20=round(ema20, 5),
        ema50=round(ema50, 5),
        ema9=round(ema9, 5),
        atr=round(atr_val, 6),
        atr_pct=round(atr_pct, 4),
        momentum_direction=mom_dir,
        momentum_magnitude=mom_mag,
        hurst_regime=hurst_regime,
        hurst_confidence=hurst_conf,
        hurst_exponent=round(h, 4) if h_raw is not None else None,
        hurst_volatility_state=hurst_vol_state,
        hurst_momentum=hurst_mom,
        regime_agreement=regime_agreement,
    )

    return result.to_dict()


# ═══════════════════════════════════════════════════════════════════════════
# §11  PIPELINE-COMPATIBLE CLASS WRAPPER
# ═══════════════════════════════════════════════════════════════════════════


class L1ContextAnalyzer:
    """Pipeline-compatible wrapper around :func:`analyze_context`.

    The Wolf Constitutional Pipeline instantiates ``L1ContextAnalyzer()``
    and calls ``.analyze(symbol)``.  Pulls OHLCV from LiveContextBus.
    """

    def __init__(self, weights: LogisticWeights | None = None) -> None:
        from context.live_context_bus import LiveContextBus  # noqa: PLC0415

        self._bus = LiveContextBus()
        self._weights = weights or DEFAULT_WEIGHTS

    def analyze(self, symbol: str) -> dict[str, Any]:
        """Run L1 context analysis for *symbol*."""
        candles = self._bus.get_candle_history(symbol, "H1", count=80)

        if not candles:
            return analyze_context({}, pair=symbol, weights=self._weights)

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

        return analyze_context(
            market_data,
            pair=symbol,
            weights=self._weights,
        )
