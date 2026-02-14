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
