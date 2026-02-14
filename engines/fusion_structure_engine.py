"""Structure and divergence engine for swing state and alignment."""

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class StructureResult:
    structure: str
    bullish_divergence: bool
    bearish_divergence: bool
    mtf_alignment: float
    liquidity: str
    details: Dict[str, Any] = field(default_factory=dict)


class FusionStructureEngine:
    def __init__(self, swing_lookback: int = 3) -> None:
        self.swing_lookback = swing_lookback

    def evaluate(self, payload: Dict[str, Any]) -> StructureResult:
        closes: List[float] = payload.get("closes", [])
        highs: List[float] = payload.get("highs", closes)
        lows: List[float] = payload.get("lows", closes)
        volumes: List[float] = payload.get("volumes", [])
        rsi_series: List[float] = payload.get("rsi_series", [])

        swings = self._swing_points(highs, lows)
        structure = self._classify_structure(closes)
        bull_div, bear_div = self._detect_divergence(closes, rsi_series)
        mtf_alignment = self._mtf_alignment(closes)
        liquidity = self._liquidity(volumes)

        return StructureResult(
            structure=structure,
            bullish_divergence=bull_div,
            bearish_divergence=bear_div,
            mtf_alignment=round(mtf_alignment, 4),
            liquidity=liquidity,
            details={"swing_points": swings[-6:]},
        )

    def _swing_points(self, highs: List[float], lows: List[float]) -> List[Dict[str, float]]:
        points: List[Dict[str, float]] = []
        lb = self.swing_lookback
        for idx in range(lb, len(highs) - lb):
            if highs[idx] == max(highs[idx - lb : idx + lb + 1]):
                points.append({"type": "high", "idx": idx, "value": highs[idx]})
            if lows[idx] == min(lows[idx - lb : idx + lb + 1]):
                points.append({"type": "low", "idx": idx, "value": lows[idx]})
        return points

    def _classify_structure(self, closes: List[float]) -> str:
        if len(closes) < 20:
            return "RANGE"
        recent = closes[-5:]
        prior = closes[-10:-5]
        if max(recent) > max(prior) and min(recent) > min(prior):
            return "BREAKING_OUT"
        if max(recent) < max(prior) and min(recent) < min(prior):
            return "BREAKING_DOWN"
        if recent[-1] > prior[-1]:
            return "BULLISH"
        if recent[-1] < prior[-1]:
            return "BEARISH"
        return "RANGE"

    def _detect_divergence(self, closes: List[float], rsi: List[float]) -> tuple:
        if len(closes) < 6 or len(rsi) < 6:
            return False, False
        price_down = closes[-1] < closes[-4]
        rsi_up = rsi[-1] > rsi[-4]
        price_up = closes[-1] > closes[-4]
        rsi_down = rsi[-1] < rsi[-4]
        return price_down and rsi_up, price_up and rsi_down

    def _mtf_alignment(self, closes: List[float]) -> float:
        if len(closes) < 60:
            return 0.5
        short = closes[-1] - closes[-10]
        medium = closes[-1] - closes[-30]
        long = closes[-1] - closes[-60]
        same_sign = sum(1 for item in [short, medium, long] if item > 0)
        return abs((same_sign / 3.0) - ((3 - same_sign) / 3.0))

    def _liquidity(self, volumes: List[float]) -> str:
        if len(volumes) < 12:
            return "UNKNOWN"
        avg = sum(volumes[-12:]) / 12
        if avg <= 0:
            return "UNKNOWN"
        ratio = volumes[-1] / avg
        if ratio > 1.4:
            return "HIGH"
        if ratio < 0.6:
            return "LOW"
        return "NORMAL"


__all__ = ["StructureResult", "FusionStructureEngine"]
