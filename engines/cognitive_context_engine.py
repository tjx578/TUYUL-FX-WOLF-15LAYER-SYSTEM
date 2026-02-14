"""Market context engine with regime and structure inference."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Sequence


@dataclass
class ContextResult:
    valid: bool
    regime: str
    structure: str
    liquidity: str
    institutional_activity: str
    confidence: float
    details: Dict[str, Any] = field(default_factory=dict)


class CognitiveContextEngine:
    def analyze(self, market_data: Dict[str, Sequence[float]]) -> ContextResult:
        closes = list(market_data.get("close", []))
        highs = list(market_data.get("high", closes))
        lows = list(market_data.get("low", closes))
        volumes = list(market_data.get("volume", [1.0] * len(closes)))

        if len(closes) < 60:
            return ContextResult(
                valid=False,
                regime="UNKNOWN",
                structure="UNKNOWN",
                liquidity="UNKNOWN",
                institutional_activity="UNKNOWN",
                confidence=0.0,
                details={"reason": "insufficient_bars"},
            )

        sma20 = self._sma(closes, 20)
        sma50 = self._sma(closes, 50)
        atr14 = self._atr(highs, lows, closes, 14)
        atr_norm = atr14 / max(closes[-1], 1e-9)

        regime = "RISK_ON" if sma20 > sma50 and atr_norm < 0.02 else "RISK_OFF"
        if abs(sma20 - sma50) / max(closes[-1], 1e-9) < 0.0015:
            regime = "TRANSITIONAL"

        swings = self._swing_tags(closes[-30:])
        structure = "RANGE"
        if swings.count("HH") >= 2 and swings.count("HL") >= 2:
            structure = "UPTREND"
        elif swings.count("LL") >= 2 and swings.count("LH") >= 2:
            structure = "DOWNTREND"

        vol_ratio = volumes[-1] / max(self._sma(volumes, 20), 1e-9)
        liquidity = "THIN" if vol_ratio < 0.6 else "LOW" if vol_ratio < 0.9 else "HIGH"

        wick_signal = (highs[-1] - max(closes[-1], market_data.get("open", closes)[-1]))
        wick_ratio = wick_signal / max(highs[-1] - lows[-1], 1e-9)
        if vol_ratio > 1.8 and wick_ratio > 0.55:
            inst = "DISTRIBUTION"
        elif vol_ratio > 1.8 and wick_ratio < 0.2:
            inst = "ACCUMULATION"
        else:
            inst = "NEUTRAL"

        confidence = min(1.0, 0.45 + min(0.4, abs(sma20 - sma50) * 10) + min(0.15, vol_ratio / 10))

        return ContextResult(
            valid=True,
            regime=regime,
            structure=structure,
            liquidity=liquidity,
            institutional_activity=inst,
            confidence=round(confidence, 4),
            details={
                "atr_normalized": round(atr_norm, 5),
                "sma20": round(sma20, 6),
                "sma50": round(sma50, 6),
                "swing_tags": swings,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    @staticmethod
    def _sma(values: Sequence[float], period: int) -> float:
        window = values[-period:]
        return sum(window) / max(len(window), 1)

    @staticmethod
    def _atr(high: List[float], low: List[float], close: List[float], period: int) -> float:
        trs = []
        for i in range(1, len(close)):
            tr = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
            trs.append(tr)
        window = trs[-period:]
        return sum(window) / max(len(window), 1)

    @staticmethod
    def _swing_tags(values: List[float]) -> List[str]:
        if len(values) < 5:
            return []
        tags: List[str] = []
        for i in range(2, len(values) - 2):
            p = values[i]
            left = values[i - 2 : i]
            right = values[i + 1 : i + 3]
            if p > max(left + right):
                tags.append("HH" if not tags or tags[-1] != "HH" else "LH")
            elif p < min(left + right):
                tags.append("LL" if not tags or tags[-1] != "LL" else "HL")
        return tags
