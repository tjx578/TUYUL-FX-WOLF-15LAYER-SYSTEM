from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class MarketRegime(str, Enum):
    TRENDING = "trending"
    RANGING = "ranging"
    VOLATILE = "volatile"


class MarketStructure(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class LiquidityContext(str, Enum):
    THIN = "thin"
    BALANCED = "balanced"
    DEEP = "deep"


class InstitutionalPresence(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class CognitiveContext:
    regime: MarketRegime
    structure: MarketStructure
    liquidity: LiquidityContext
    institutional_presence: InstitutionalPresence


class CognitiveContextEngine:
    """Classify market context from normalized state values."""

    def evaluate(self, state: Mapping[str, Any]) -> CognitiveContext:
        trend = float(state.get("trend_strength", 0.5))
        volatility = float(state.get("volatility", 0.5))
        structure_bias = float(state.get("structure_bias", 0.0))
        liquidity = float(state.get("liquidity_depth", 0.5))
        institutional = float(state.get("institutional_flow", 0.5))

        if volatility > 0.75:
            regime = MarketRegime.VOLATILE
        elif trend > 0.6:
            regime = MarketRegime.TRENDING
        else:
            regime = MarketRegime.RANGING

        if structure_bias > 0.2:
            structure = MarketStructure.BULLISH
        elif structure_bias < -0.2:
            structure = MarketStructure.BEARISH
        else:
            structure = MarketStructure.NEUTRAL

        if liquidity < 0.35:
            liq_context = LiquidityContext.THIN
        elif liquidity > 0.7:
            liq_context = LiquidityContext.DEEP
        else:
            liq_context = LiquidityContext.BALANCED

        if institutional < 0.35:
            inst = InstitutionalPresence.LOW
        elif institutional > 0.7:
            inst = InstitutionalPresence.HIGH
        else:
            inst = InstitutionalPresence.MEDIUM

        return CognitiveContext(
            regime=regime,
            structure=structure,
            liquidity=liq_context,
            institutional_presence=inst,
        )
