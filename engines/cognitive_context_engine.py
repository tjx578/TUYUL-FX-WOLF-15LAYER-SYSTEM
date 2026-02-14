"""Market context pre-processor engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List


class MarketRegime(str, Enum):
    RISK_ON = "RISK_ON"
    RISK_OFF = "RISK_OFF"
    TRANSITIONAL = "TRANSITIONAL"


class MarketStructure(str, Enum):
    ACCUMULATION = "ACCUMULATION"
    EXPANSION = "EXPANSION"
    DISTRIBUTION = "DISTRIBUTION"
    RANGE = "RANGE"


class LiquidityContext(str, Enum):
    HIGH = "HIGH"
    NORMAL = "NORMAL"
    LOW = "LOW"
    THIN = "THIN"


class InstitutionalPresence(str, Enum):
    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"
    UNKNOWN = "UNKNOWN"


@dataclass
class CognitiveContext:
    market_regime: MarketRegime
    structure: MarketStructure
    liquidity_context: LiquidityContext
    institutional_presence: InstitutionalPresence
    regime_confidence: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)


class CognitiveContextEngine:
    """Context classification using trend, volatility, structure, and volume."""

    def __init__(
        self,
        sma_fast: int = 20,
        sma_slow: int = 50,
        atr_period: int = 14,
        vol_lookback: int = 20,
    ) -> None:
        self.sma_fast = sma_fast
        self.sma_slow = sma_slow
        self.atr_period = atr_period
        self.vol_lookback = vol_lookback

    def analyze(self, market_snapshot: Dict[str, Any]) -> CognitiveContext:
        closes = market_snapshot.get("closes", market_snapshot.get("close", []))
        highs = market_snapshot.get("highs", market_snapshot.get("high", []))
        lows = market_snapshot.get("lows", market_snapshot.get("low", []))
        volumes = market_snapshot.get("volumes", market_snapshot.get("volume", []))

        if not closes or len(closes) < self.sma_slow:
            return CognitiveContext(
                market_regime=MarketRegime.TRANSITIONAL,
                structure=MarketStructure.RANGE,
                liquidity_context=LiquidityContext.NORMAL,
                institutional_presence=InstitutionalPresence.UNKNOWN,
                details={"reason": "insufficient_data", "bars": len(closes)},
            )

        regime, regime_conf, regime_details = self._detect_regime(closes, highs, lows)
        structure, struct_details = self._classify_structure(closes, highs, lows)
        liquidity = self._assess_liquidity(volumes)
        institutional = self._infer_institutional(volumes, closes, highs, lows)

        return CognitiveContext(
            market_regime=regime,
            structure=structure,
            liquidity_context=liquidity,
            institutional_presence=institutional,
            regime_confidence=round(regime_conf, 4),
            details={
                **regime_details,
                **struct_details,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    def _detect_regime(self, closes: List[float], highs: List[float], lows: List[float]):
        sma_f = sum(closes[-self.sma_fast :]) / self.sma_fast
        sma_s = sum(closes[-self.sma_slow :]) / self.sma_slow
        spread_pct = (sma_f - sma_s) / sma_s if sma_s else 0.0
        atr = self._calc_atr(highs, lows, closes)
        atr_pct = atr / closes[-1] if closes[-1] else 0.0
        vol_state = "HIGH" if atr_pct > 0.015 else "LOW" if atr_pct < 0.003 else "NORMAL"

        if spread_pct > 0.003 and vol_state != "HIGH":
            regime = MarketRegime.RISK_ON
            confidence = min(1.0, abs(spread_pct) * 100)
        elif spread_pct < -0.003 or vol_state == "HIGH":
            regime = MarketRegime.RISK_OFF
            confidence = min(1.0, abs(spread_pct) * 80 + (0.3 if vol_state == "HIGH" else 0.0))
        else:
            regime = MarketRegime.TRANSITIONAL
            confidence = 0.3 + (1.0 - abs(spread_pct) * 200) * 0.3

        return regime, max(0.0, min(1.0, confidence)), {
            "sma_spread_pct": round(spread_pct, 6),
            "atr_pct": round(atr_pct, 6),
            "vol_state": vol_state,
        }

    def _classify_structure(self, closes: List[float], highs: List[float], lows: List[float]):
        lookback = min(30, len(highs))
        swing_highs: List[float] = []
        swing_lows: List[float] = []
        for i in range(-lookback + 2, -2):
            if highs[i] > highs[i - 1] and highs[i] > highs[i + 1]:
                swing_highs.append(highs[i])
            if lows[i] < lows[i - 1] and lows[i] < lows[i + 1]:
                swing_lows.append(lows[i])

        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return MarketStructure.RANGE, {
                "swing_highs": len(swing_highs),
                "swing_lows": len(swing_lows),
            }

        hh = swing_highs[-1] > swing_highs[-2]
        hl = swing_lows[-1] > swing_lows[-2]
        ll = swing_lows[-1] < swing_lows[-2]
        lh = swing_highs[-1] < swing_highs[-2]

        if hh and hl:
            structure = MarketStructure.EXPANSION
        elif ll and lh:
            structure = MarketStructure.DISTRIBUTION
        elif not hh and hl:
            structure = MarketStructure.ACCUMULATION
        else:
            structure = MarketStructure.RANGE
        return structure, {"hh": hh, "hl": hl, "ll": ll, "lh": lh}

    def _assess_liquidity(self, volumes: List[float]) -> LiquidityContext:
        if not volumes or len(volumes) < 10:
            return LiquidityContext.NORMAL
        lookback = min(self.vol_lookback, len(volumes))
        recent_vol = volumes[-lookback:]
        avg_vol = sum(recent_vol) / lookback
        ratio = volumes[-1] / avg_vol if avg_vol else 0.0
        if ratio > 1.5:
            return LiquidityContext.HIGH
        if ratio > 0.7:
            return LiquidityContext.NORMAL
        if ratio > 0.3:
            return LiquidityContext.LOW
        return LiquidityContext.THIN

    def _infer_institutional(
        self,
        volumes: List[float],
        closes: List[float],
        highs: List[float],
        lows: List[float],
    ) -> InstitutionalPresence:
        if not volumes or len(volumes) < 20:
            return InstitutionalPresence.UNKNOWN

        lookback = min(20, len(volumes))
        avg_vol = sum(volumes[-lookback:]) / lookback
        spikes = sum(1 for v in volumes[-lookback:] if v > avg_vol * 1.8)

        large_wicks = 0
        for i in range(-lookback, 0):
            rng = highs[i] - lows[i]
            if not rng:
                continue
            prev_close = closes[i - 1] if i - 1 >= -len(closes) else closes[i]
            body = abs(closes[i] - prev_close)
            if (1.0 - body / rng) > 0.6:
                large_wicks += 1

        score = spikes * 0.5 + large_wicks * 0.3
        if score > 4:
            return InstitutionalPresence.STRONG
        if score > 2:
            return InstitutionalPresence.MODERATE
        if score > 0.5:
            return InstitutionalPresence.WEAK
        return InstitutionalPresence.UNKNOWN

    def _calc_atr(self, highs: List[float], lows: List[float], closes: List[float]) -> float:
        period = min(self.atr_period, len(highs) - 1)
        if period < 1:
            return 0.0
        tr_values = []
        for i in range(-period, 0):
            tr_values.append(
                max(
                    highs[i] - lows[i],
                    abs(highs[i] - closes[i - 1]),
                    abs(lows[i] - closes[i - 1]),
                )
            )
        return sum(tr_values) / len(tr_values)

    @staticmethod
    def export(context: CognitiveContext) -> Dict[str, Any]:
        return {
            "market_regime": context.market_regime.value,
            "structure": context.structure.value,
            "liquidity_context": context.liquidity_context.value,
            "institutional_presence": context.institutional_presence.value,
            "regime_confidence": context.regime_confidence,
            "details": context.details,
        }
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
            liquidity=liq_context,
            institutional_presence=inst,
        )
