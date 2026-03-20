"""
Technical Indicators
Pure calculation layer.
"""

import numpy as np


class IndicatorEngine:
    @staticmethod
    def ema(prices: list[float], period: int) -> float | None:
        if len(prices) < period:
            return None

        weights = np.exp(np.linspace(-1.0, 0.0, period))
        weights /= weights.sum()
        return float(np.dot(prices[-period:], weights))

    @staticmethod
    def rsi(prices: list[float], period: int = 14) -> float | None:
        if len(prices) < period + 1:
            return None

        deltas = np.diff(prices)
        gains = np.maximum(deltas, 0)
        losses = -np.minimum(deltas, 0)

        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        return float(100 - (100 / (1 + rs)))

    @staticmethod
    def atr(
        highs: list[float],
        lows: list[float],
        closes: list[float],
        period: int = 14,
    ) -> float | None:
        if len(highs) < period:
            return None

        trs = []
        for i in range(1, len(highs)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            trs.append(tr)

        return float(np.mean(trs[-period:]))


# Placeholder
