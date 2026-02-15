"""Fusion Precision Engine -- Layer-7 precise entry/exit zone detection.

Identifies optimal entry zones, stop-loss placements, and take-profit
targets using confluence of structure, Fibonacci, and order flow analysis.

ANALYSIS-ONLY module. No execution side-effects.
"""

from __future__ import annotations

import logging

from dataclasses import dataclass, field
from typing import Any

import numpy as np  # pyright: ignore[reportMissingImports]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class PrecisionZone:
    """A detected precision zone for entry/exit."""
    price: float
    zone_type: str  # "ENTRY" | "SL" | "TP1" | "TP2" | "TP3"
    strength: float = 0.0
    method: str = ""  # "FIB" | "STRUCTURE" | "OB" | "CONFLUENCE"


@dataclass
class PrecisionResult:
    """Output of the Fusion Precision Engine."""

    # Entry zone
    entry_zone_low: float = 0.0
    entry_zone_high: float = 0.0
    entry_optimal: float = 0.0

    # Stop loss
    stop_loss: float = 0.0
    sl_method: str = ""  # "ATR" | "STRUCTURE" | "FIB"

    # Take profit levels
    tp1: float = 0.0
    tp2: float = 0.0
    tp3: float = 0.0
    risk_reward_1: float = 0.0
    risk_reward_2: float = 0.0
    risk_reward_3: float = 0.0

    # Precision zones
    zones: list[PrecisionZone] = field(default_factory=list)

    # Fibonacci levels
    fib_levels: dict[str, float] = field(default_factory=dict)

    # Direction
    direction: str = "NONE"  # "BUY" | "SELL" | "NONE"

    # Confidence & metadata
    precision_score: float = 0.0
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_valid(self) -> bool:
        return self.confidence > 0.0 and self.entry_optimal > 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIB_RATIOS = {
    "0.0": 0.0,
    "0.236": 0.236,
    "0.382": 0.382,
    "0.5": 0.5,
    "0.618": 0.618,
    "0.786": 0.786,
    "1.0": 1.0,
    "1.272": 1.272,
    "1.618": 1.618,
    "2.0": 2.0,
    "2.618": 2.618,
}


def _compute_fib_levels(
    swing_high: float, swing_low: float, direction: str
) -> dict[str, float]:
    """Compute Fibonacci retracement/extension levels."""
    diff = swing_high - swing_low
    if diff <= 0:
        return {}

    levels: dict[str, float] = {}
    for label, ratio in FIB_RATIOS.items():
        if direction == "BUY":
            levels[label] = swing_high - diff * ratio
        else:
            levels[label] = swing_low + diff * ratio
    return levels


def _compute_atr(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14
) -> float:
    """Simple ATR computation."""
    if len(highs) < period + 1:
        return 0.0
    tr_list: list[float] = []
    for i in range(1, len(highs)):
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i - 1])
        lc = abs(lows[i] - closes[i - 1])
        tr_list.append(max(hl, hc, lc))
    return float(np.mean(tr_list[-period:])) if tr_list else 0.0


def _find_recent_swings(
    highs: np.ndarray, lows: np.ndarray, lookback: int = 3
) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """Detect recent swing highs and lows."""
    sh: list[tuple[int, float]] = []
    sl: list[tuple[int, float]] = []
    for i in range(lookback, len(highs) - lookback):
        if all(highs[i] >= highs[i - j] for j in range(1, lookback + 1)) and \
           all(highs[i] >= highs[i + j] for j in range(1, lookback + 1)):
            sh.append((i, float(highs[i])))
        if all(lows[i] <= lows[i - j] for j in range(1, lookback + 1)) and \
           all(lows[i] <= lows[i + j] for j in range(1, lookback + 1)):
            sl.append((i, float(lows[i])))
    return sh, sl


def _compute_rr(entry: float, sl: float, tp: float) -> float:
    """Risk-Reward ratio."""
    risk = abs(entry - sl)
    if risk <= 0:
        return 0.0
    return abs(tp - entry) / risk


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class FusionPrecisionEngine:
    """Fusion Precision Engine -- analysis only, no side-effects.

    Parameters
    ----------
    atr_period : int
        ATR period for SL calculation.
    atr_sl_multiplier : float
        Multiplier for ATR-based SL.
    swing_lookback : int
        Lookback for swing detection.
    """

    def __init__(
        self,
        atr_period: int = 14,
        atr_sl_multiplier: float = 1.5,
        swing_lookback: int = 3,
        **_extra: Any,
    ) -> None:
        self.atr_period = atr_period
        self.atr_sl_multiplier = atr_sl_multiplier
        self.swing_lookback = swing_lookback

    def analyze(
        self,
        candles: dict[str, list[dict[str, Any]]],
        direction: str = "NONE",
        symbol: str = "",
    ) -> PrecisionResult:
        """Compute precision entry/exit zones.

        Parameters
        ----------
        candles : dict
            Multi-timeframe candle data.
        direction : str
            Bias from structure/momentum engines: "BUY" | "SELL" | "NONE".
        symbol : str
            Symbol for metadata.
        """
        if not candles or direction == "NONE":
            return PrecisionResult(
                direction=direction,
                metadata={"symbol": symbol, "error": "no_candles_or_direction"},
            )

        primary_tf = self._select_primary(candles)
        tf_candles = candles[primary_tf]

        if len(tf_candles) < 20:
            return PrecisionResult(
                direction=direction,
                metadata={"symbol": symbol, "error": "insufficient_candles"},
            )

        highs = np.array([c.get("high", 0.0) for c in tf_candles], dtype=np.float64)
        lows = np.array([c.get("low", 0.0) for c in tf_candles], dtype=np.float64)
        closes = np.array([c.get("close", 0.0) for c in tf_candles], dtype=np.float64)

        current_close = float(closes[-1])
        atr = _compute_atr(highs, lows, closes, self.atr_period)

        swing_highs, swing_lows = _find_recent_swings(highs, lows, self.swing_lookback)

        # Identify key swing for Fibonacci
        if direction == "BUY" and swing_lows and swing_highs:
            fib_low = swing_lows[-1][1]
            fib_high = swing_highs[-1][1] if swing_highs[-1][0] > swing_lows[-1][0] else current_close
        elif direction == "SELL" and swing_highs and swing_lows:
            fib_high = swing_highs[-1][1]
            fib_low = swing_lows[-1][1] if swing_lows[-1][0] > swing_highs[-1][0] else current_close
        else:
            fib_high = float(np.max(highs[-20:]))
            fib_low = float(np.min(lows[-20:]))

        fib_levels = _compute_fib_levels(fib_high, fib_low, direction)

        # Entry zone
        if direction == "BUY":
            entry_optimal = fib_levels.get("0.618", current_close)
            entry_zone_low = fib_levels.get("0.786", entry_optimal - atr * 0.3)
            entry_zone_high = fib_levels.get("0.5", entry_optimal + atr * 0.3)
            stop_loss = entry_zone_low - atr * self.atr_sl_multiplier
            tp1 = entry_optimal + atr * 2.0
            tp2 = entry_optimal + atr * 3.5
            tp3 = fib_levels.get("1.618", entry_optimal + atr * 5.0)
        elif direction == "SELL":
            entry_optimal = fib_levels.get("0.618", current_close)
            entry_zone_low = fib_levels.get("0.5", entry_optimal - atr * 0.3)
            entry_zone_high = fib_levels.get("0.786", entry_optimal + atr * 0.3)
            stop_loss = entry_zone_high + atr * self.atr_sl_multiplier
            tp1 = entry_optimal - atr * 2.0
            tp2 = entry_optimal - atr * 3.5
            tp3 = fib_levels.get("1.618", entry_optimal - atr * 5.0)
        else:
            return PrecisionResult(direction=direction, metadata={"symbol": symbol})

        zones = [
            PrecisionZone(entry_optimal, "ENTRY", 0.8, "CONFLUENCE"),
            PrecisionZone(stop_loss, "SL", 0.9, "ATR"),
            PrecisionZone(tp1, "TP1", 0.7, "ATR"),
            PrecisionZone(tp2, "TP2", 0.5, "ATR"),
            PrecisionZone(tp3, "TP3", 0.3, "FIB"),
        ]

        confidence = min(1.0, 0.3 + len(swing_highs) * 0.05 + len(swing_lows) * 0.05)

        return PrecisionResult(
            entry_zone_low=round(entry_zone_low, 5),
            entry_zone_high=round(entry_zone_high, 5),
            entry_optimal=round(entry_optimal, 5),
            stop_loss=round(stop_loss, 5),
            sl_method="ATR",
            tp1=round(tp1, 5),
            tp2=round(tp2, 5),
            tp3=round(tp3, 5),
            risk_reward_1=round(_compute_rr(entry_optimal, stop_loss, tp1), 2),
            risk_reward_2=round(_compute_rr(entry_optimal, stop_loss, tp2), 2),
            risk_reward_3=round(_compute_rr(entry_optimal, stop_loss, tp3), 2),
            zones=zones,
            fib_levels={k: round(v, 5) for k, v in fib_levels.items()},
            direction=direction,
            precision_score=min(1.0, atr / (abs(current_close) + 1e-8) * 100),
            confidence=confidence,
            metadata={"symbol": symbol, "primary_tf": primary_tf, "atr": atr},
        )

    @staticmethod
    def _select_primary(candles: dict[str, list[dict[str, Any]]]) -> str:
        for tf in ["M15", "H1", "H4"]:
            if tf in candles and len(candles[tf]) >= 20:
                return tf
        return max(candles, key=lambda k: len(candles[k]))
