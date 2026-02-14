"""Cognitive context engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ContextResult:
    regime: str
    structure: str
    liquidity: str
    institutional_activity: str
    regime_confidence: float


class CognitiveContextEngine:
    def analyze(self, market_data: dict[str, Any]) -> ContextResult:
        closes = [float(v) for v in market_data.get("closes", [])]
        highs = [float(v) for v in market_data.get("highs", closes)]
        lows = [float(v) for v in market_data.get("lows", closes)]
        volumes = [float(v) for v in market_data.get("volumes", [])]
        sma20 = self._sma(closes, 20)
        sma50 = self._sma(closes, 50)
        atr = self._atr(highs, lows, closes, 14)
        price = closes[-1] if closes else 0.0
        norm_vol = atr / price if price else 0.0
        regime = "RISK_ON" if sma20 > sma50 else "RISK_OFF"
        if norm_vol > 0.03:
            regime = "TRANSITIONAL"
        structure = self._structure(closes)
        liquidity = self._liquidity(volumes)
        institutional = self._institutional(highs, lows, closes, volumes)
        confidence = min(1.0, abs(sma20 - sma50) / price * 20.0 if price else 0.0)
        return ContextResult(regime, structure, liquidity, institutional, round(confidence, 4))

    @staticmethod
    def _sma(values: list[float], period: int) -> float:
        if len(values) < period:
            return values[-1] if values else 0.0
        return sum(values[-period:]) / period

    def _atr(
        self, highs: list[float], lows: list[float], closes: list[float], period: int
    ) -> float:
        if len(closes) < 2:
            return 0.0
        tr = [
            max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
            for i in range(1, len(closes))
        ]
        chunk = tr[-period:] if len(tr) >= period else tr
        return sum(chunk) / len(chunk)

    @staticmethod
    def _structure(closes: list[float]) -> str:
        if len(closes) < 6:
            return "UNKNOWN"
        h1 = closes[-1] > max(closes[-4:-1])
        l1 = closes[-1] < min(closes[-4:-1])
        if h1:
            return "BREAKING_OUT"
        if l1:
            return "BREAKING_DOWN"
        return "RANGE"

    @staticmethod
    def _liquidity(volumes: list[float]) -> str:
        if len(volumes) < 10:
            return "UNKNOWN"
        avg = sum(volumes[-20:]) / min(20, len(volumes))
        recent = sum(volumes[-5:]) / 5.0
        ratio = recent / avg if avg else 0.0
        if ratio > 1.4:
            return "HIGH"
        if ratio < 0.6:
            return "THIN"
        return "NORMAL"

    @staticmethod
    def _institutional(
        highs: list[float], lows: list[float], closes: list[float], volumes: list[float]
    ) -> str:
        if len(closes) < 5 or len(volumes) < 5:
            return "UNKNOWN"
        avg_vol = sum(volumes[-20:]) / min(20, len(volumes))
        spike = volumes[-1] > avg_vol * 1.8 if avg_vol else False
        spread = highs[-1] - lows[-1]
        body = abs(closes[-1] - closes[-2])
        return "LIKELY" if spike and body < spread * 0.4 else "UNLIKELY"
