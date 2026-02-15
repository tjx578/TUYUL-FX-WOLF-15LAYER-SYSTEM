"""
🧭 L1 -- Context Layer (PRODUCTION)
------------------------------------
Real regime detection via:
  - SMA 20/50 crossover for regime
  - ATR-14 for volatility classification
  - Session awareness (London/NY/Tokyo overlap)
  - Volume-weighted CSI (Contextual Strength Index)

Zone: analysis/ -- pure read-only analysis, no execution side-effects.
"""

import logging

from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["analyze_context"]

# Session definitions: (name, start_hour_utc, end_hour_utc, multiplier)
# Ordered by priority -- overlaps checked first.
SESSIONS = {
    "LONDON_NEWYORK_OVERLAP": (13, 16, 1.30),
    "TOKYO_LONDON_OVERLAP":   (7,  9,  1.15),
    "LONDON":                 (7,  16, 1.10),
    "NEWYORK":                (13, 22, 1.05),
    "TOKYO":                  (0,  9,  0.85),
    "SYDNEY":                 (22, 7,  0.70),
}

# Regime detection thresholds (SMA spread as fraction)
_TREND_THRESHOLD = 0.002
_TRANSITION_THRESHOLD = 0.0005

# Volatility thresholds (session-adjusted ATR %)
_VOL_EXTREME = 1.5
_VOL_HIGH = 0.8
_VOL_NORMAL = 0.3
_VOL_LOW = 0.1

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


def _sma(data: list[float], n: int) -> float:
    """Simple moving average over the last *n* values of *data*."""
    if not data:
        return 0.0
    if len(data) < n:
        return sum(data) / len(data)
    return sum(data[-n:]) / n


def _atr(highs: list[float], lows: list[float], closes: list[float],
         period: int = 14) -> float:
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
    return sum(trs) / len(trs)


def _classify_volatility(adj_atr_pct: float) -> str:
    """Map session-adjusted ATR% to a volatility label."""
    if adj_atr_pct > _VOL_EXTREME:
        return "EXTREME"
    if adj_atr_pct > _VOL_HIGH:
        return "HIGH"
    if adj_atr_pct > _VOL_NORMAL:
        return "NORMAL"
    if adj_atr_pct > _VOL_LOW:
        return "LOW"
    return "DEAD"


def _detect_regime(spread: float) -> tuple[str, str]:
    """Return (regime, dominant_force) from SMA spread fraction."""
    if spread > _TREND_THRESHOLD:
        return "TREND_UP", "BULLISH"
    if spread < -_TREND_THRESHOLD:
        return "TREND_DOWN", "BEARISH"
    if abs(spread) > _TRANSITION_THRESHOLD:
        return "TRANSITION", "NEUTRAL"
    return "RANGE", "NEUTRAL"


def _compute_alignment(close: float, sma20: float, sma50: float,
                       spread: float, regime: str) -> str:
    """Price-to-SMA alignment label."""
    above20 = close > sma20
    above50 = close > sma50
    if above20 and above50 and regime == "TREND_UP":
        return "STRONGLY_BULLISH"
    if not above20 and not above50 and regime == "TREND_DOWN":
        return "STRONGLY_BEARISH"
    if above20 and spread > 0:
        return "BULLISH"
    if not above20 and spread < 0:
        return "BEARISH"
    return "NEUTRAL"


def _compute_csi(trend_strength: float, volumes: list[float],
                 session_mult: float) -> float:
    """Contextual Strength Index (0-1 range, volume-weighted)."""
    vol_factor = 0.5
    if volumes and len(volumes) >= 20:
        avg_v = sum(volumes[-20:]) / 20
        if avg_v > 0:
            vol_factor = min(1.0, (volumes[-1] / avg_v) / 2)
    csi = (
        trend_strength * 0.45
        + vol_factor * 0.30
        + (session_mult / 1.3) * 0.25
    )
    return round(csi, 4)


def analyze_context(market_data: dict[str, Any],
                    pair: str = "GBPUSD",
                    now: datetime | None = None) -> dict[str, Any]:
    """L1 Context -- PRODUCTION.

    Pure analysis function.  Returns regime, volatility, alignment, and CSI.
    No execution side-effects.

    Parameters
    ----------
    market_data : dict
        Must contain ``closes`` (or ``close``) with ≥ 20 bars.
        Optionally ``highs``/``lows``/``volumes``.
    pair : str
        Currency pair label (informational).
    now : datetime, optional
        Override for current UTC time (useful for testing).
    """
    closes: list[float] = market_data.get("closes", market_data.get("close", []))
    highs: list[float] = market_data.get("highs", market_data.get("high", []))
    lows: list[float] = market_data.get("lows", market_data.get("low", []))
    volumes: list[float] = market_data.get("volumes", market_data.get("volume", []))

    if not closes or len(closes) < _MIN_BARS:
        return {
            "regime": "UNKNOWN",
            "dominant_force": "NEUTRAL",
            "volatility_level": "UNKNOWN",
            "regime_confidence": 0.0,
            "csi": 0.0,
            "market_alignment": "NEUTRAL",
            "valid": False,
            "reason": f"need {_MIN_BARS}+ bars, got {len(closes)}",
        }

    if now is None:
        now = datetime.now(UTC)

    session, sess_mult = _get_session(now.hour)

    # --- Regime (SMA crossover) ---
    sma20 = _sma(closes, 20)
    sma50 = _sma(closes, 50) if len(closes) >= 50 else _sma(closes, len(closes))
    spread = (sma20 - sma50) / sma50 if sma50 != 0 else 0.0

    regime, dominant = _detect_regime(spread)

    # --- Volatility ---
    atr_val = _atr(highs, lows, closes) if highs and lows else 0.0
    atr_pct = (atr_val / closes[-1] * 100) if closes[-1] != 0 else 0.0
    adj_atr = atr_pct * sess_mult
    vol_level = _classify_volatility(adj_atr)

    # --- Confidence ---
    trend_strength = min(1.0, abs(spread) * 200)
    vol_penalty = (
        max(0.0, 1.0 - adj_atr * 0.3) if vol_level in ("EXTREME", "HIGH") else 1.0
    )
    regime_conf = round(trend_strength * vol_penalty, 4)

    # --- CSI ---
    csi = _compute_csi(trend_strength, volumes, sess_mult)

    # --- Alignment ---
    alignment = _compute_alignment(closes[-1], sma20, sma50, spread, regime)

    logger.debug(
        "L1 context: pair=%s regime=%s vol=%s csi=%.4f session=%s",
        pair, regime, vol_level, csi, session,
    )

    return {
        "regime": regime,
        "dominant_force": dominant,
        "volatility_level": vol_level,
        "regime_confidence": regime_conf,
        "csi": csi,
        "market_alignment": alignment,
        "valid": True,
        "session": session,
        "session_multiplier": sess_mult,
        "sma20": round(sma20, 5),
        "sma50": round(sma50, 5),
        "sma_spread_pct": round(spread, 6),
        "atr": round(atr_val, 6),
        "atr_pct": round(atr_pct, 4),
        "pair": pair,
        "timestamp": now.isoformat(),
    }
