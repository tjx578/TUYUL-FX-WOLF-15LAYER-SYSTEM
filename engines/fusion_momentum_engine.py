"""Fusion Momentum Engine — Layer-4 momentum and trend analysis.

Computes RSI, MACD, ADX, Stochastic, and custom momentum composites
to detect trend strength, divergences, and overbought/oversold conditions.

ANALYSIS-ONLY module. No execution side-effects.
"""

from __future__ import annotations

import logging

from dataclasses import dataclass, field
from typing import Any, Dict  # noqa: UP035

import numpy as np  # pyright: ignore[reportMissingImports]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class MomentumResult:
    """Output of the Fusion Momentum Engine."""

    # Core indicators
    rsi: float = 50.0
    rsi_signal: str = "NEUTRAL"  # OVERBOUGHT | OVERSOLD | NEUTRAL

    macd_value: float = 0.0
    macd_signal_line: float = 0.0
    macd_histogram: float = 0.0
    macd_cross: str = "NONE"  # BULLISH_CROSS | BEARISH_CROSS | NONE

    stoch_k: float = 50.0
    stoch_d: float = 50.0
    stoch_signal: str = "NEUTRAL"

    adx: float = 0.0
    plus_di: float = 0.0
    minus_di: float = 0.0
    trend_strength: str = "WEAK"  # WEAK | MODERATE | STRONG | VERY_STRONG

    # Composite
    momentum_score: float = 0.0  # 0.0–1.0
    momentum_bias: str = "NEUTRAL"  # BULLISH | BEARISH | NEUTRAL
    divergence_detected: bool = False
    divergence_type: str = "NONE"  # BULLISH_DIV | BEARISH_DIV | NONE

    # MTF
    mtf_momentum_alignment: float = 0.0
    timeframe_biases: Dict[str, str] = field(default_factory=dict)  # noqa: UP006

    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_valid(self) -> bool:
        return self.confidence > 0.0


# ---------------------------------------------------------------------------
# Indicator helpers
# ---------------------------------------------------------------------------

def _ema(data: np.ndarray, period: int) -> np.ndarray:
    """Exponential moving average."""
    alpha = 2.0 / (period + 1)
    result = np.empty_like(data)
    result[0] = data[0]
    for i in range(1, len(data)):
        result[i] = alpha * data[i] + (1 - alpha) * result[i - 1]
    return result


def _rsi(closes: np.ndarray, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _macd(
    closes: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[float, float, float]:
    if len(closes) < slow + signal:
        return 0.0, 0.0, 0.0
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    histogram = macd_line - signal_line
    return float(macd_line[-1]), float(signal_line[-1]), float(histogram[-1])


def _stochastic(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
    k_period: int = 14, d_period: int = 3,
) -> tuple[float, float]:
    if len(closes) < k_period:
        return 50.0, 50.0
    k_values: list[float] = []
    for i in range(k_period - 1, len(closes)):
        highest = float(np.max(highs[i - k_period + 1:i + 1]))
        lowest = float(np.min(lows[i - k_period + 1:i + 1]))
        if highest == lowest:
            k_values.append(50.0)
        else:
            k_values.append(100.0 * (closes[i] - lowest) / (highest - lowest))
    if len(k_values) < d_period:
        return k_values[-1] if k_values else 50.0, 50.0
    d_value = float(np.mean(k_values[-d_period:]))
    return k_values[-1], d_value


def _adx(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14
) -> tuple[float, float, float]:
    """Compute ADX, +DI, -DI."""
    if len(highs) < period + 1:
        return 0.0, 0.0, 0.0

    plus_dm: list[float] = []
    minus_dm: list[float] = []
    tr_list: list[float] = []

    for i in range(1, len(highs)):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i - 1])
        lc = abs(lows[i] - closes[i - 1])
        tr_list.append(max(hl, hc, lc))

    if len(tr_list) < period:
        return 0.0, 0.0, 0.0

    atr = float(np.mean(tr_list[:period]))
    avg_plus = float(np.mean(plus_dm[:period]))
    avg_minus = float(np.mean(minus_dm[:period]))

    for i in range(period, len(tr_list)):
        atr = (atr * (period - 1) + tr_list[i]) / period
        avg_plus = (avg_plus * (period - 1) + plus_dm[i]) / period
        avg_minus = (avg_minus * (period - 1) + minus_dm[i]) / period

    plus_di = 100.0 * avg_plus / atr if atr > 0 else 0.0
    minus_di = 100.0 * avg_minus / atr if atr > 0 else 0.0
    dx = 100.0 * abs(plus_di - minus_di) / (plus_di + minus_di) if (plus_di + minus_di) > 0 else 0.0
    return dx, plus_di, minus_di


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class FusionMomentumEngine:
    """Fusion Momentum Engine — analysis only, no side-effects."""

    def __init__(
        self,
        rsi_period: int = 14,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
        stoch_k: int = 14,
        stoch_d: int = 3,
        adx_period: int = 14,
        **_extra: Any,
    ) -> None:
        self.rsi_period = rsi_period
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.stoch_k = stoch_k
        self.stoch_d = stoch_d
        self.adx_period = adx_period

    def analyze(  # noqa: PLR0912
        self,
        candles: dict[str, list[dict[str, Any]]],
        symbol: str = "",
    ) -> MomentumResult:
        if not candles:
            return MomentumResult(metadata={"symbol": symbol, "error": "no_candles"})

        primary_tf = self._select_primary(candles)
        tf_candles = candles[primary_tf]

        if len(tf_candles) < 30:
            return MomentumResult(metadata={"symbol": symbol, "error": "insufficient_candles"})

        highs = np.array([c.get("high", 0.0) for c in tf_candles], dtype=np.float64)
        lows = np.array([c.get("low", 0.0) for c in tf_candles], dtype=np.float64)
        closes = np.array([c.get("close", 0.0) for c in tf_candles], dtype=np.float64)

        # Compute indicators
        rsi_val = _rsi(closes, self.rsi_period)
        macd_val, macd_sig, macd_hist = _macd(closes, self.macd_fast, self.macd_slow, self.macd_signal)
        stoch_k_val, stoch_d_val = _stochastic(highs, lows, closes, self.stoch_k, self.stoch_d)
        adx_val, plus_di, minus_di = _adx(highs, lows, closes, self.adx_period)

        # RSI signal
        rsi_signal = "OVERBOUGHT" if rsi_val > 70 else ("OVERSOLD" if rsi_val < 30 else "NEUTRAL")

        # MACD cross
        prev_macd_val, prev_macd_sig, _ = _macd(
            closes[:-1], self.macd_fast, self.macd_slow, self.macd_signal
        )
        macd_cross = "NONE"
        if prev_macd_val <= prev_macd_sig and macd_val > macd_sig:
            macd_cross = "BULLISH_CROSS"
        elif prev_macd_val >= prev_macd_sig and macd_val < macd_sig:
            macd_cross = "BEARISH_CROSS"

        # Stoch signal
        stoch_signal = "OVERBOUGHT" if stoch_k_val > 80 else ("OVERSOLD" if stoch_k_val < 20 else "NEUTRAL")

        # ADX strength
        if adx_val >= 40:
            trend_strength = "VERY_STRONG"
        elif adx_val >= 25:
            trend_strength = "STRONG"
        elif adx_val >= 15:
            trend_strength = "MODERATE"
        else:
            trend_strength = "WEAK"

        # Composite momentum score
        bull_signals = 0
        bear_signals = 0
        total_signals = 4

        if rsi_val > 50:
            bull_signals += 1
        else:
            bear_signals += 1

        if macd_hist > 0:
            bull_signals += 1
        else:
            bear_signals += 1

        if stoch_k_val > 50:
            bull_signals += 1
        else:
            bear_signals += 1

        if plus_di > minus_di:
            bull_signals += 1
        else:
            bear_signals += 1

        momentum_score = bull_signals / total_signals
        momentum_bias = "BULLISH" if momentum_score > 0.6 else ("BEARISH" if momentum_score < 0.4 else "NEUTRAL")

        # MTF analysis
        tf_biases: dict[str, str] = {}
        for tf_name, tfc in candles.items():
            if len(tfc) < 20:
                continue
            c = np.array([x.get("close", 0.0) for x in tfc], dtype=np.float64)
            r = _rsi(c)
            tf_biases[tf_name] = "BULLISH" if r > 55 else ("BEARISH" if r < 45 else "NEUTRAL")

        bias_list = list(tf_biases.values())
        if bias_list:
            dominant = max(set(bias_list), key=bias_list.count)
            mtf_alignment = bias_list.count(dominant) / len(bias_list)
        else:
            mtf_alignment = 0.0

        confidence = min(1.0, 0.3 + (adx_val / 100.0) * 0.3 + mtf_alignment * 0.3 + 0.1)

        return MomentumResult(
            rsi=round(rsi_val, 2),
            rsi_signal=rsi_signal,
            macd_value=round(macd_val, 6),
            macd_signal_line=round(macd_sig, 6),
            macd_histogram=round(macd_hist, 6),
            macd_cross=macd_cross,
            stoch_k=round(stoch_k_val, 2),
            stoch_d=round(stoch_d_val, 2),
            stoch_signal=stoch_signal,
            adx=round(adx_val, 2),
            plus_di=round(plus_di, 2),
            minus_di=round(minus_di, 2),
            trend_strength=trend_strength,
            momentum_score=round(momentum_score, 3),
            momentum_bias=momentum_bias,
            mtf_momentum_alignment=round(mtf_alignment, 3),
            timeframe_biases=tf_biases,
            confidence=round(confidence, 3),
            metadata={"symbol": symbol, "primary_tf": primary_tf},
        )

    @staticmethod
    def _select_primary(candles: dict[str, list[dict[str, Any]]]) -> str:
        for tf in ["M15", "H1", "H4"]:
            if tf in candles and len(candles[tf]) >= 30:
                return tf
        return max(candles, key=lambda k: len(candles[k]))
