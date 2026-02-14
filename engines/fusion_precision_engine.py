"""Precision scoring using EMA stack, confluence, and zone proximity."""

from dataclasses import dataclass, field
from typing import Any, Dict, List
import math


@dataclass
class PrecisionResult:
    precision_weight: float
    ema_alignment: float
    confluence: float
    zone_proximity: float
    details: Dict[str, Any] = field(default_factory=dict)


class FusionPrecisionEngine:
    def evaluate(self, data: Dict[str, Any]) -> PrecisionResult:
        closes: List[float] = data.get("closes", [])
        atr = float(data.get("atr", 0.0))
        rsi = float(data.get("rsi", 50.0))
        macd = float(data.get("macd", 0.0))
        support = data.get("support")
        resistance = data.get("resistance")

        ema8 = self._ema(closes, 8)
        ema21 = self._ema(closes, 21)
        ema55 = self._ema(closes, 55)
        ema100 = self._ema(closes, 100)

        aligned = [ema8 > ema21, ema21 > ema55, ema55 > ema100]
        ema_alignment = sum(1.0 for item in aligned if item) / len(aligned)

        signal_up = rsi > 50 and macd >= 0 and ema8 > ema21
        signal_down = rsi < 50 and macd < 0 and ema8 < ema21
        confluence = 1.0 if (signal_up or signal_down) else 0.45

        zone_proximity = self._zone_proximity(closes[-1] if closes else 0.0, support, resistance, atr)
        base = math.tanh(abs((ema8 - ema21) / (atr or 1.0))) * math.exp(-abs(macd))

        damping = 0.85 if atr > 0 and closes and (atr / closes[-1]) > 0.03 else 1.0
        weight = max(0.0, min(1.0, base * confluence * zone_proximity * damping))

        return PrecisionResult(
            precision_weight=round(weight, 4),
            ema_alignment=round(ema_alignment, 4),
            confluence=round(confluence, 4),
            zone_proximity=round(zone_proximity, 4),
            details={"ema8": ema8, "ema21": ema21, "ema55": ema55, "ema100": ema100},
        )

    def _ema(self, values: List[float], period: int) -> float:
        if not values:
            return 0.0
        k = 2 / (period + 1)
        ema_value = values[0]
        for value in values[1:]:
            ema_value = (value * k) + (ema_value * (1 - k))
        return ema_value

    def _zone_proximity(self, price: float, support: Any, resistance: Any, atr: float) -> float:
        if not price or support is None or resistance is None or atr <= 0:
            return 0.7
        near_support = abs(price - float(support)) / atr
        near_res = abs(float(resistance) - price) / atr
        score = 1.0 - min(1.0, min(near_support, near_res) / 3.0)
        return max(0.5, score)


__all__ = ["PrecisionResult", "FusionPrecisionEngine"]
