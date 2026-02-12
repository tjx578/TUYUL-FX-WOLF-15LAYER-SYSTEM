"""
VIX Proxy Estimator — FINAL PRODUCTION

Estimates synthetic VIX for forex pairs.
Uses ATR(14) / SMA(close, 20) → VIX-like scale.

Fallback for when real VIX unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
from loguru import logger


@dataclass
class VIXProxyState:
    """VIX proxy estimate with confidence."""

    vix_equivalent: float
    confidence: float
    atr_ratio: float
    term_structure_estimate: str


class VIXProxyEstimator:
    """Synthetic VIX for forex pairs."""

    ATR_VIX_SCALE = 20.0
    ATR_VIX_OFFSET = 12.0

    def __init__(self):
        self._history: dict[str, list[float]] = {}

    def estimate(
        self,
        symbol: str,
        candles: list[dict],
    ) -> Optional[VIXProxyState]:
        """Estimate synthetic VIX from H1 candles."""
        
        if not candles or len(candles) < 30:
            return None

        try:
            closes = np.array([float(c.get("close", 0)) for c in candles])
            highs = np.array([float(c.get("high", 0)) for c in candles])
            lows = np.array([float(c.get("low", 0)) for c in candles])

            if np.any(closes <= 0) or np.any(highs <= 0) or np.any(lows <= 0):
                return None

            # Calculate ATR
            tr_values = self._true_range(highs, lows, closes)
            atr = np.mean(tr_values[-14:])

            # SMA of close
            sma = np.mean(closes[-20:])

            if sma == 0:
                return None

            vol_ratio = (atr / sma) * 100

            # Scale to VIX
            vix_eq = self.ATR_VIX_OFFSET + (vol_ratio * self.ATR_VIX_SCALE)
            vix_eq = max(5.0, min(vix_eq, 80.0))

            # Confidence
            confidence = self._confidence(len(candles), vol_ratio)

            # Term structure
            term = self._term_structure(closes)

            # Store history
            if symbol not in self._history:
                self._history[symbol] = []
            self._history[symbol].append(vix_eq)
            if len(self._history[symbol]) > 100:
                self._history[symbol].pop(0)

            return VIXProxyState(
                vix_equivalent=round(vix_eq, 2),
                confidence=round(confidence, 2),
                atr_ratio=round(vol_ratio, 3),
                term_structure_estimate=term,
            )

        except Exception as exc:
            logger.error(f"Proxy estimation failed: {exc}")
            return None

    @staticmethod
    def _true_range(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> np.ndarray:
        tr = []
        for i in range(len(highs)):
            if i == 0:
                tr.append(highs[i] - lows[i])
            else:
                tr.append(max(
                    highs[i] - lows[i],
                    abs(highs[i] - closes[i - 1]),
                    abs(lows[i] - closes[i - 1]),
                ))
        return np.array(tr)

    @staticmethod
    def _confidence(num_candles: int, vol_ratio: float) -> float:
        candle_factor = min(1.0, num_candles / 100)
        vol_factor = 1.0 - abs((vol_ratio - 1.0) / 2.0)
        vol_factor = max(0, min(vol_factor, 1.0))
        return (candle_factor * 0.5) + (vol_factor * 0.5)

    @staticmethod
    def _term_structure(closes: np.ndarray) -> str:
        if len(closes) < 10:
            return "UNKNOWN"
        recent_vol = np.std(closes[-5:])
        older_vol = np.std(closes[-10:-5])
        if abs(recent_vol - older_vol) < 0.0001:
            return "FLAT"
        return "CONTANGO" if recent_vol < older_vol else "BACKWARDATION"
