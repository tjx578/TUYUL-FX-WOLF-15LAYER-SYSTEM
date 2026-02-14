from __future__ import annotations

from dataclasses import dataclass
from math import exp, tanh
from typing import Any


def _ema(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    k = 2 / (period + 1)
    acc = values[0]
    for value in values[1:]:
        acc = value * k + acc * (1 - k)
    return acc


@dataclass
class PrecisionSnapshot:
    valid: bool
    precision_weight: float
    ema_alignment: float
    confluence_score: float
    zone_proximity: float


class FusionPrecisionEngine:
    def evaluate(self, payload: dict[str, Any]) -> PrecisionSnapshot:
        prices = [float(v) for v in payload.get("prices", [])]
        rsi = float(payload.get("rsi", 50.0))
        macd = float(payload.get("macd", 0.0))
        atr = max(1e-9, float(payload.get("atr", 1.0)))
        sr_zone = float(payload.get("sr_zone_distance", atr))
        volatility = float(payload.get("volatility", 0.5))
        if len(prices) < 30:
            return PrecisionSnapshot(False, 0.0, 0.0, 0.0, 0.0)

        ema8 = _ema(prices, 8)
        ema21 = _ema(prices, 21)
        ema55 = _ema(prices, 55)
        ema100 = _ema(prices, 100)

        aligns = [
            ema8 > ema21,
            ema21 > ema55,
            ema55 > ema100,
        ]
        ema_alignment = sum(1 for cond in aligns if cond) / len(aligns)

        rsi_score = 1.0 - abs(rsi - 50.0) / 50.0
        macd_score = min(1.0, abs(macd) / atr)
        confluence = max(0.0, min(1.0, (ema_alignment * 0.5 + rsi_score * 0.3 + macd_score * 0.2)))

        zone_proximity = max(0.0, min(1.0, 1.0 - min(sr_zone / atr, 2.0) / 2.0))

        base = tanh((ema8 - ema21) / atr) * exp(-abs(sr_zone) / (atr * 2.0))
        weight = abs(base) * confluence * (0.5 + zone_proximity * 0.5)
        if volatility > 0.7:
            weight *= 0.85

        return PrecisionSnapshot(
            True,
            round(max(0.0, min(1.0, weight)), 4),
            round(ema_alignment, 4),
            round(confluence, 4),
            round(zone_proximity, 4),
        )

    @staticmethod
    def export(snapshot: PrecisionSnapshot) -> dict[str, Any]:
        return {
            "valid": snapshot.valid,
            "precision_weight": snapshot.precision_weight,
            "ema_alignment": snapshot.ema_alignment,
            "confluence_score": snapshot.confluence_score,
            "zone_proximity": snapshot.zone_proximity,
        }
