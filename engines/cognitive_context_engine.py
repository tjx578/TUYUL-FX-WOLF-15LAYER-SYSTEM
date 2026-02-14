"""Market context engine with regime and structure inference."""
"""Cognitive context engine."""

from __future__ import annotations

"""Market context pre-processor engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from datetime import datetime, timezone
from typing import Any, Dict, List, Sequence
from enum import Enum
from typing import Any


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
    details: dict[str, Any] = field(default_factory=dict)


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

    def analyze(self, market_snapshot: dict[str, Any]) -> CognitiveContext:
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
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

    def _detect_regime(self, closes: list[float], highs: list[float], lows: list[float]):
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

        return (
            regime,
            max(0.0, min(1.0, confidence)),
            {
                "sma_spread_pct": round(spread_pct, 6),
                "atr_pct": round(atr_pct, 6),
                "vol_state": vol_state,
            },
        )

    def _classify_structure(self, closes: list[float], highs: list[float], lows: list[float]):
        lookback = min(30, len(highs))
        swing_highs: list[float] = []
        swing_lows: list[float] = []
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

    def _assess_liquidity(self, volumes: list[float]) -> LiquidityContext:
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
        volumes: list[float],
        closes: list[float],
        highs: list[float],
        lows: list[float],
    ) -> InstitutionalPresence:
        if not volumes or len(volumes) < 20:
            return InstitutionalPresence.UNKNOWN

        lookback = min(20, len(volumes))
        avg_vol = sum(volumes[-lookback:]) / lookback
        spikes = sum(1 for v in volumes[-lookback:] if v > avg_vol * 1.8)

        large_wicks = 0
        for i in range(
            -lookback + 1, 0
        ):  # Start from -lookback + 1 to avoid accessing i-1 = -lookback-1
            rng = highs[i] - lows[i]
            if not rng:
                continue
            prev_close = closes[i - 1]
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

    def _calc_atr(self, highs: list[float], lows: list[float], closes: list[float]) -> float:
        period = min(self.atr_period, len(highs) - 1)
        if period < 2:
            return 0.0
        tr_values = []
        # Start from -period + 1 to ensure i-1 stays within the intended ATR window
        # For the first iteration (i = -period + 1), we use closes[-period] as prev close
        for i in range(-period + 1, 0):
            prev_idx = i - 1  # This will be -period for first iteration, which is valid
            tr_values.append(
                max(
                    highs[i] - lows[i],
                    abs(highs[i] - closes[prev_idx]),
                    abs(lows[i] - closes[prev_idx]),
                )
            )
        return sum(tr_values) / len(tr_values) if tr_values else 0.0

    @staticmethod
    def export(context: CognitiveContext) -> dict[str, Any]:
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
