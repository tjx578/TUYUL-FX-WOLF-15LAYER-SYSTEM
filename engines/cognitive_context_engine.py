from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _sma(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    if len(values) < period:
        return sum(values) / len(values)
    window = values[-period:]
    return sum(window) / period


def _atr(high: list[float], low: list[float], close: list[float], period: int = 14) -> float:
    if not close:
        return 0.0
    tr = [
        max(
            high[idx] - low[idx],
            abs(high[idx] - close[idx - 1]),
            abs(low[idx] - close[idx - 1]),
        )
        for idx in range(1, len(close))
    ]
    if not tr:
        return 0.0
    if len(tr) < period:
        return sum(tr) / len(tr)
    return sum(tr[-period:]) / period


@dataclass
class ContextSnapshot:
    valid: bool
    market_regime: str
    structure_state: str
    liquidity_state: str
    institutional_inference: str
    regime_confidence: float


class CognitiveContextEngine:
    def analyze(self, market_data: dict[str, Any]) -> ContextSnapshot:
        close = [float(x) for x in market_data.get("close", [])]
        high = [float(x) for x in market_data.get("high", close)]
        low = [float(x) for x in market_data.get("low", close)]
        volume = [float(x) for x in market_data.get("volume", [1.0] * len(close))]

        if len(close) < 10:
            return ContextSnapshot(False, "UNKNOWN", "UNKNOWN", "THIN", "UNKNOWN", 0.0)

        sma20 = _sma(close, 20)
        sma50 = _sma(close, 50)
        atr14 = _atr(high, low, close, 14)
        vol_norm = atr14 / max(close[-1], 1e-9)

        if sma20 > sma50 and vol_norm < 0.02:
            regime = "RISK_ON"
        elif sma20 < sma50 and vol_norm > 0.02:
            regime = "RISK_OFF"
        else:
            regime = "TRANSITIONAL"

        recent = close[-8:]
        swings_up = int(recent[-1] > recent[-4] > recent[0])
        swings_down = int(recent[-1] < recent[-4] < recent[0])
        if swings_up:
            structure = "BULLISH"
        elif swings_down:
            structure = "BEARISH"
        else:
            structure = "RANGE"

        vol_avg = sum(volume[-20:]) / min(len(volume), 20)
        vol_now = volume[-1]
        if vol_now > vol_avg * 1.4:
            liquidity = "HIGH"
        elif vol_now < vol_avg * 0.6:
            liquidity = "THIN"
        else:
            liquidity = "NORMAL"

        wick_ratio = 0.0
        if high[-1] != low[-1]:
            body = abs(close[-1] - close[-2]) if len(close) > 1 else 0.0
            wick_ratio = (high[-1] - low[-1] - body) / max(high[-1] - low[-1], 1e-9)
        if vol_now > vol_avg * 1.6 and wick_ratio > 0.55:
            inst = "ABSORPTION"
        elif vol_now > vol_avg * 1.6:
            inst = "INITIATIVE"
        else:
            inst = "NEUTRAL"

        confidence = min(1.0, abs(sma20 - sma50) / max(close[-1], 1e-9) * 10 + (1 - vol_norm))

        return ContextSnapshot(True, regime, structure, liquidity, inst, round(confidence, 4))

    @staticmethod
    def export(snapshot: ContextSnapshot) -> dict[str, Any]:
        return {
            "valid": snapshot.valid,
            "market_regime": snapshot.market_regime,
            "structure_state": snapshot.structure_state,
            "liquidity_state": snapshot.liquidity_state,
            "institutional_inference": snapshot.institutional_inference,
            "regime_confidence": snapshot.regime_confidence,
        }
