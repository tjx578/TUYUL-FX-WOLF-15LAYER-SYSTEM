"""Structure and divergence analysis engine."""

from __future__ import annotations

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
    def evaluate(
        self,
        highs: List[float],
        lows: List[float],
        closes: List[float],
        volumes: List[float],
        rsi_values: List[float],
    ) -> StructureResult:
        if len(closes) < 40:
            return StructureResult("RANGE", False, False, 0.0, "NORMAL", {"reason": "insufficient_data"})

        swings_h = self._swings(highs, is_high=True)
        swings_l = self._swings(lows, is_high=False)
        structure = self._classify(swings_h, swings_l, closes)
        bull_div, bear_div = self._divergence(closes, rsi_values)
        mtf = self._mtf_alignment(closes)
        liq = self._liquidity(volumes)

        return StructureResult(
            structure=structure,
            bullish_divergence=bull_div,
            bearish_divergence=bear_div,
            mtf_alignment=round(mtf, 6),
            liquidity=liq,
            details={"swing_highs": len(swings_h), "swing_lows": len(swings_l)},
        )

    @staticmethod
    def _swings(values: List[float], is_high: bool, lookback: int = 2) -> List[float]:
        swings = []
        for i in range(lookback, len(values) - lookback):
            left = values[i - lookback : i]
            right = values[i + 1 : i + 1 + lookback]
            if is_high and values[i] > max(left + right):
                swings.append(values[i])
            if not is_high and values[i] < min(left + right):
                swings.append(values[i])
        return swings[-4:]

    @staticmethod
    def _classify(swings_h: List[float], swings_l: List[float], closes: List[float]) -> str:
        if len(swings_h) < 2 or len(swings_l) < 2:
            return "RANGE"
        hh = swings_h[-1] > swings_h[-2]
        hl = swings_l[-1] > swings_l[-2]
        ll = swings_l[-1] < swings_l[-2]
        lh = swings_h[-1] < swings_h[-2]
        if hh and hl:
            return "BREAKING_OUT"
        if ll and lh:
            return "BREAKING_DOWN"
        if abs(closes[-1] - closes[-20]) / closes[-20] < 0.004:
            return "RANGE"
        return "BULLISH" if closes[-1] > closes[-20] else "BEARISH"

    @staticmethod
    def _divergence(closes: List[float], rsi: List[float]) -> tuple[bool, bool]:
        if len(closes) < 8 or len(rsi) < 8:
            return False, False
        price_ll = closes[-1] < min(closes[-6:-1])
        rsi_hl = rsi[-1] > min(rsi[-6:-1])
        price_hh = closes[-1] > max(closes[-6:-1])
        rsi_lh = rsi[-1] < max(rsi[-6:-1])
        return price_ll and rsi_hl, price_hh and rsi_lh

    @staticmethod
    def _mtf_alignment(closes: List[float]) -> float:
        sma10 = sum(closes[-10:]) / 10
        sma20 = sum(closes[-20:]) / 20
        sma40 = sum(closes[-40:]) / 40
        up = [sma10 > sma20, sma20 > sma40]
        down = [sma10 < sma20, sma20 < sma40]
        return max(sum(up), sum(down)) / 2

    @staticmethod
    def _liquidity(volumes: List[float]) -> str:
        if len(volumes) < 20:
            return "NORMAL"
        avg = sum(volumes[-20:]) / 20
        ratio = volumes[-1] / avg if avg else 0.0
        if ratio > 1.6:
            return "HIGH"
        if ratio < 0.5:
            return "LOW"
        return "NORMAL"

    @staticmethod
    def export(result: StructureResult) -> Dict[str, Any]:
        return {
            "structure": result.structure,
            "bullish_divergence": result.bullish_divergence,
            "bearish_divergence": result.bearish_divergence,
            "mtf_alignment": result.mtf_alignment,
            "liquidity": result.liquidity,
            "details": result.details,
        }
"""Structure engine with swing and divergence analysis."""

from dataclasses import dataclass
from typing import Any


@dataclass
class StructureReport:
    structure: str
    divergence: str
    liquidity: str
    mtf_alignment: float
    details: dict[str, Any]


class FusionStructureEngine:
    def evaluate(self, market_data: dict[str, list[float] | float]) -> StructureReport:
        closes = list(market_data.get("close", []))
        highs = list(market_data.get("high", closes))
        lows = list(market_data.get("low", closes))
        volumes = list(market_data.get("volume", [1.0] * len(closes)))
        rsi_series = list(market_data.get("rsi", []))
        if len(closes) < 30:
            return StructureReport("RANGE", "NONE", "NORMAL", 0.0, {"reason": "insufficient_data"})

        recent_high = max(highs[-15:])
        recent_low = min(lows[-15:])
        if closes[-1] > recent_high * 0.999:
            structure = "BREAKING_OUT"
        elif closes[-1] < recent_low * 1.001:
            structure = "BREAKING_DOWN"
        elif closes[-1] > sum(closes[-10:]) / 10:
            structure = "BULLISH"
        elif closes[-1] < sum(closes[-10:]) / 10:
            structure = "BEARISH"
        else:
            structure = "RANGE"

        divergence = self._divergence(closes, rsi_series)
        liquidity = self._liquidity(volumes)

        slope_fast = (sum(closes[-10:]) / 10) - (sum(closes[-20:-10]) / 10)
        slope_slow = (sum(closes[-20:]) / 20) - (sum(closes[-40:-20]) / 20)
        mtf_alignment = 1.0 if slope_fast * slope_slow > 0 else 0.5 if slope_fast != 0 else 0.0

        return StructureReport(
            structure=structure,
            divergence=divergence,
            liquidity=liquidity,
            mtf_alignment=round(mtf_alignment, 4),
            details={"recent_high": round(recent_high, 6), "recent_low": round(recent_low, 6)},
        )

    def _divergence(self, closes: list[float], rsi: list[float]) -> str:
        if len(rsi) < 6 or len(closes) < 6:
            return "NONE"
        price_trend = closes[-1] - closes[-6]
        rsi_trend = rsi[-1] - rsi[-6]
        if price_trend > 0 and rsi_trend < 0:
            return "BEARISH"
        if price_trend < 0 and rsi_trend > 0:
            return "BULLISH"
        return "NONE"

    def _liquidity(self, volumes: list[float]) -> str:
        if len(volumes) < 10:
            return "LOW"
        avg = sum(volumes[-10:]) / 10
        if volumes[-1] > avg * 1.4:
            return "HIGH"
        if volumes[-1] < avg * 0.6:
            return "LOW"
        return "NORMAL"
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class StructureState(str, Enum):
    SUPPORTIVE = "supportive"
    CONFLICTED = "conflicted"
    FRAGILE = "fragile"


@dataclass(frozen=True)
class FusionStructure:
    state: StructureState
    divergence_score: float
    liquidity_signal: float
    mtf_alignment: float


class FusionStructureEngine:
    """Assess structural reliability from divergence, liquidity and MTF alignment."""

    def evaluate(self, state: Mapping[str, Any]) -> FusionStructure:
        divergence = max(0.0, min(1.0, float(state.get("divergence_score", 0.4))))
        liquidity = max(0.0, min(1.0, float(state.get("liquidity_signal", 0.5))))
        mtf = max(0.0, min(1.0, float(state.get("mtf_alignment", 0.5))))

        if divergence < 0.3 and mtf > 0.6:
            struct_state = StructureState.SUPPORTIVE
        elif divergence > 0.7 or liquidity < 0.3:
            struct_state = StructureState.FRAGILE
        else:
            struct_state = StructureState.CONFLICTED

        return FusionStructure(
            state=struct_state,
            divergence_score=divergence,
            liquidity_signal=liquidity,
            mtf_alignment=mtf,
        )
