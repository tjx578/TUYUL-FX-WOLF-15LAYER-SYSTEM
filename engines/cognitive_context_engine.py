"""Market context engine with regime and structure inference."""

from dataclasses import dataclass
from typing import Any


@dataclass
class CognitiveContext:
    regime: str
    structure: str
    liquidity: str
    institutional_flow: str
    confidence: float
    details: dict[str, Any]


class CognitiveContextEngine:
    """Analyze OHLCV to infer market context before core execution modules."""

    def analyze(self, market_data: dict[str, list[float]]) -> CognitiveContext:
        closes = market_data.get("close", [])
        highs = market_data.get("high", closes)
        lows = market_data.get("low", closes)
        volumes = market_data.get("volume", [1.0] * len(closes))
        if len(closes) < 30:
            return CognitiveContext("TRANSITIONAL", "RANGE", "THIN", "UNKNOWN", 0.2, {})

        sma20 = sum(closes[-20:]) / 20
        sma50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else sum(closes) / len(closes)
        atr = self._atr(highs, lows, closes, period=14)
        atr_norm = atr / max(closes[-1], 1e-9)

        if sma20 > sma50 and atr_norm < 0.03:
            regime = "RISK_ON"
        elif sma20 < sma50 and atr_norm < 0.03:
            regime = "RISK_OFF"
        else:
            regime = "TRANSITIONAL"

        structure = self._structure(closes)
        liquidity = self._liquidity(volumes)
        institutional_flow = self._institutional_flow(closes, highs, lows, volumes)
        confidence = min(1.0, 0.45 + abs(sma20 - sma50) / max(closes[-1], 1e-9) * 8)

        return CognitiveContext(
            regime=regime,
            structure=structure,
            liquidity=liquidity,
            institutional_flow=institutional_flow,
            confidence=round(confidence, 4),
            details={
                "sma20": round(sma20, 6),
                "sma50": round(sma50, 6),
                "atr_norm": round(atr_norm, 6),
            },
        )

    def _atr(
        self, highs: list[float], lows: list[float], closes: list[float], period: int
    ) -> float:
        trs: list[float] = []
        for i in range(1, len(closes)):
            tr = max(
                highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])
            )
            trs.append(tr)
        window = trs[-period:] if len(trs) >= period else trs
        return sum(window) / max(len(window), 1)

    def _structure(self, closes: list[float]) -> str:
        last = closes[-10:]
        if len(last) < 6:
            return "RANGE"
        up = sum(1 for i in range(1, len(last)) if last[i] > last[i - 1])
        if up >= 7:
            return "HH_HL"
        if up <= 2:
            return "LL_LH"
        return "RANGE"

    def _liquidity(self, volumes: list[float]) -> str:
        recent = volumes[-20:]
        mean = sum(recent) / max(len(recent), 1)
        current = recent[-1]
        if current > mean * 1.35:
            return "HIGH"
        if current < mean * 0.6:
            return "THIN"
        return "NORMAL"

    def _institutional_flow(
        self,
        closes: list[float],
        highs: list[float],
        lows: list[float],
        volumes: list[float],
    ) -> str:
        body = abs(closes[-1] - closes[-2]) if len(closes) > 1 else 0.0
        wick = (highs[-1] - lows[-1]) - body
        avg_vol = sum(volumes[-20:]) / max(len(volumes[-20:]), 1)
        if volumes[-1] > avg_vol * 1.6 and wick > body * 1.3:
            return "ABSORPTION"
        if volumes[-1] > avg_vol * 1.4 and closes[-1] > closes[-2]:
            return "ACCUMULATION"
        if volumes[-1] > avg_vol * 1.4 and closes[-1] < closes[-2]:
            return "DISTRIBUTION"
        return "NEUTRAL"
