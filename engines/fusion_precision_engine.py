"""Fusion precision engine."""

from __future__ import annotations

import math

from dataclasses import dataclass


@dataclass
class PrecisionResult:
    precision_weight: float
    ema_alignment: float
    confluence: float
    zone_proximity: float


class FusionPrecisionEngine:
    def evaluate(self, payload: dict[str, float]) -> PrecisionResult:
        ema8 = payload.get("ema8", 0.0)
        ema21 = payload.get("ema21", 0.0)
        ema55 = payload.get("ema55", 0.0)
        ema100 = payload.get("ema100", 0.0)
        rsi = payload.get("rsi", 50.0)
        macd = payload.get("macd", 0.0)
        atr = max(payload.get("atr", 1e-6), 1e-6)
        vwap_delta = payload.get("vwap_delta", 0.0)
        sr_distance = abs(payload.get("sr_distance", atr))
        trend_up = ema8 > ema21 > ema55 > ema100
        trend_down = ema8 < ema21 < ema55 < ema100
        alignment = 1.0 if (trend_up or trend_down) else 0.25
        rsi_bias = 1.0 - min(1.0, abs(rsi - 50.0) / 50.0)
        macd_bias = min(1.0, abs(macd) / atr)
        confluence = max(0.0, min(1.0, (rsi_bias + macd_bias + alignment) / 3.0))
        zone = max(0.2, min(1.0, 1.0 - (sr_distance / (atr * 3.0))))
        damping = 0.85 if atr > payload.get("price", 1.0) * 0.03 else 1.0
        precision = (
            math.tanh(alignment) * math.exp(-abs(vwap_delta) / atr) * confluence * zone * damping
        )
        return PrecisionResult(
            round(precision, 4), round(alignment, 4), round(confluence, 4), round(zone, 4)
        )
