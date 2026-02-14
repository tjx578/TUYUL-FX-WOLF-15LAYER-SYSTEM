"""Precision weighting engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Sequence
import math


@dataclass
class PrecisionResult:
    valid: bool
    precision_weight: float
    ema_alignment: float
    confluence_score: float
    zone_proximity: float
    details: Dict[str, Any] = field(default_factory=dict)


class FusionPrecisionEngine:
    def evaluate(self, data: Dict[str, Sequence[float] | float]) -> PrecisionResult:
        prices = list(data.get("price", []))
        if len(prices) < 120:
            return PrecisionResult(False, 0.0, 0.0, 0.0, 0.0, {"reason": "insufficient"})

        ema8 = self._ema(prices, 8)
        ema21 = self._ema(prices, 21)
        ema55 = self._ema(prices, 55)
        ema100 = self._ema(prices, 100)

        ordered = [ema8 > ema21, ema21 > ema55, ema55 > ema100]
        alignment = sum(1.0 for ok in ordered if ok) / 3.0

        rsi = float(data.get("rsi", 50.0))
        macd = float(data.get("macd", 0.0))
        confluence = 0.0
        if rsi > 52:
            confluence += 0.34
        if macd > 0:
            confluence += 0.33
        if alignment > 0.66:
            confluence += 0.33

        atr = float(data.get("atr", 0.001))
        support = float(data.get("support", prices[-1] - atr * 2))
        resistance = float(data.get("resistance", prices[-1] + atr * 2))
        dist_support = abs(prices[-1] - support)
        dist_resistance = abs(resistance - prices[-1])
        zone_proximity = math.exp(-min(dist_support, dist_resistance) / max(atr * 4, 1e-9))

        vol = float(data.get("volatility", 0.2))
        vol_damp = 0.85 if vol > 0.75 else 1.0

        base = math.tanh((ema8 - ema21) / max(atr, 1e-9))
        weight = abs(base) * confluence * zone_proximity * vol_damp

        return PrecisionResult(
            valid=True,
            precision_weight=round(min(1.0, weight), 4),
            ema_alignment=round(alignment, 4),
            confluence_score=round(confluence, 4),
            zone_proximity=round(zone_proximity, 4),
            details={
                "ema8": round(ema8, 6),
                "ema21": round(ema21, 6),
                "ema55": round(ema55, 6),
                "ema100": round(ema100, 6),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    @staticmethod
    def _ema(values: Sequence[float], period: int) -> float:
        k = 2.0 / (period + 1.0)
        ema = values[0]
        for value in values[1:]:
            ema = value * k + ema * (1.0 - k)
        return ema
