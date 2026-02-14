"""Market context inference for regime, structure, and liquidity."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple


@dataclass
class ContextState:
    regime: str
    structure: str
    liquidity: str
    institutional_activity: str
    confidence: float
    details: Dict[str, Any] = field(default_factory=dict)


class CognitiveContextEngine:
    def analyze(self, market: Dict[str, Any]) -> ContextState:
        closes: List[float] = market.get("closes", [])
        highs: List[float] = market.get("highs", closes)
        lows: List[float] = market.get("lows", closes)
        volumes: List[float] = market.get("volumes", [])

        sma20 = self._sma(closes, 20)
        sma50 = self._sma(closes, 50)
        atr = self._atr(highs, lows, closes, period=14)

        regime = "TRANSITIONAL"
        if sma20 > sma50 and atr < 0.03:
            regime = "RISK_ON"
        elif sma20 < sma50 and atr > 0.04:
            regime = "RISK_OFF"

        structure = self._swing_structure(closes)
        liquidity = self._liquidity(volumes)
        institutional = self._institutional_inference(highs, lows, closes, volumes)

        confidence = 0.3
        confidence += 0.25 if regime != "TRANSITIONAL" else 0.0
        confidence += 0.25 if structure in {"UPTREND", "DOWNTREND"} else 0.0
        confidence += 0.20 if liquidity in {"HIGH", "NORMAL"} else 0.0

        return ContextState(
            regime=regime,
            structure=structure,
            liquidity=liquidity,
            institutional_activity=institutional,
            confidence=round(min(1.0, confidence), 4),
            details={"sma20": sma20, "sma50": sma50, "atr_norm": atr},
        )

    def _sma(self, values: List[float], period: int) -> float:
        if len(values) < period:
            return values[-1] if values else 0.0
        window = values[-period:]
        return sum(window) / len(window)

    def _atr(
        self,
        highs: List[float],
        lows: List[float],
        closes: List[float],
        period: int,
    ) -> float:
        if len(closes) < period + 1:
            return 0.0
        true_ranges: List[float] = []
        for i in range(-period, 0):
            prev_close = closes[i - 1]
            tr = max(highs[i] - lows[i], abs(highs[i] - prev_close), abs(lows[i] - prev_close))
            true_ranges.append(tr)
        atr = sum(true_ranges) / len(true_ranges)
        ref_price = closes[-1] if closes[-1] else 1.0
        return atr / ref_price

    def _swing_structure(self, closes: List[float]) -> str:
        if len(closes) < 8:
            return "RANGE"
        recent = closes[-8:]
        up = sum(1 for a, b in zip(recent, recent[1:]) if b > a)
        down = sum(1 for a, b in zip(recent, recent[1:]) if b < a)
        if up >= 6:
            return "UPTREND"
        if down >= 6:
            return "DOWNTREND"
        return "RANGE"

    def _liquidity(self, volumes: List[float]) -> str:
        if len(volumes) < 10:
            return "UNKNOWN"
        avg = sum(volumes[-20:]) / min(20, len(volumes))
        latest = volumes[-1]
        if latest > avg * 1.5:
            return "HIGH"
        if latest < avg * 0.5:
            return "THIN"
        return "NORMAL"

    def _institutional_inference(
        self,
        highs: List[float],
        lows: List[float],
        closes: List[float],
        volumes: List[float],
    ) -> str:
        if len(closes) < 2 or not volumes:
            return "UNKNOWN"
        wick = (highs[-1] - lows[-1]) - abs(closes[-1] - closes[-2])
        vol_spike = volumes[-1] > (sum(volumes[-10:]) / min(10, len(volumes))) * 1.7
        if vol_spike and wick > 0:
            return "POSSIBLE_ACCUMULATION"
        return "NEUTRAL"


__all__ = ["ContextState", "CognitiveContextEngine"]
