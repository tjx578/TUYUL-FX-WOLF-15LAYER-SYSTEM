"""EMA Fusion Engine + Multi EMA Fusion."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ._utils import _clamp01


class EMAFusionEngine:
    def __init__(self, periods: list[int] | None = None, smoothing: float = 2.0) -> None:
        self.periods = sorted(set(periods or [21, 55, 100]))
        self.smoothing = smoothing

    def compute(self, prices: list[float]) -> dict[str, Any]:
        if not prices or len(prices) < max(self.periods):
            return self._empty()
        emas = {f"ema{p}": self._ema(prices, p) for p in self.periods}
        return {
            **emas,
            "direction": self._direction(emas),
            "fusion_strength": self._strength(emas, prices[-1]),
            "price": prices[-1],
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def _ema(self, prices: list[float], period: int) -> float:
        if len(prices) < period:
            return prices[-1] if prices else 0.0
        m = self.smoothing / (period + 1)
        ema = sum(prices[:period]) / period
        for p in prices[period:]:
            ema = (p * m) + (ema * (1 - m))
        return round(ema, 5)

    def _direction(self, emas: dict[str, float]) -> str:
        vals = [emas.get(f"ema{p}", 0) for p in self.periods]
        if len(vals) < 2:
            return "NEUTRAL"
        if all(vals[i] >= vals[i + 1] for i in range(len(vals) - 1)):
            return "BULL"
        if all(vals[i] <= vals[i + 1] for i in range(len(vals) - 1)):
            return "BEAR"
        return "NEUTRAL"

    def _strength(self, emas: dict[str, float], price: float) -> float:
        if not emas:
            return 0.5
        avg = sum(emas.values()) / len(emas)
        if avg == 0:
            return 0.5
        return round(min(1.0, 0.5 + abs(price - avg) / avg * 10), 3)

    def _empty(self) -> dict[str, Any]:
        r: dict[str, Any] = {f"ema{p}": 0.0 for p in self.periods}
        r.update(
            {"direction": "NEUTRAL", "fusion_strength": 0.5, "price": 0.0, "timestamp": datetime.now(UTC).isoformat()}
        )
        return r


class MultiEMAFusion:
    def __init__(self, ema_periods: list[int] | None = None) -> None:
        self.ema_periods = ema_periods or [20, 50, 100, 200]

    def calculate_ema(self, closes: list[float], period: int) -> list[float]:
        if not closes:
            return []
        alpha = 2 / (period + 1)
        ema = [closes[0]]
        for i in range(1, len(closes)):
            ema.append((closes[i] * alpha) + (ema[i - 1] * (1 - alpha)))
        return ema

    def integrate(self, closes: list[float], wlwci: float = 0.88) -> dict[str, Any]:
        if not closes:
            return {"status": "no_data", "fusion_strength": 0.5}
        results: dict[str, Any] = {}
        slopes: list[float] = []
        for period in self.ema_periods:
            vals = self.calculate_ema(closes, period)
            key = f"ema_{period}"
            if vals:
                results[key] = round(vals[-1], 5)
                if len(vals) > 1 and vals[-2] != 0:
                    s = (vals[-1] - vals[-2]) / vals[-2]
                    results[f"{key}_slope"] = round(s, 6)
                    slopes.append(s)
                else:
                    results[f"{key}_slope"] = 0.0
            else:
                results[key] = 0.0
                results[f"{key}_slope"] = 0.0
        avg_slope = sum(slopes) / len(slopes) if slopes else 0.0
        results["fusion_strength"] = round(_clamp01(avg_slope * 0.5 + wlwci * 0.5), 3)
        results["wlwci"] = round(wlwci, 3)
        results["trend_bias"] = "Bullish" if avg_slope > 0 else "Bearish" if avg_slope < 0 else "Neutral"
        return results
