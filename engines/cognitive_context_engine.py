"""Market context pre-processor engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
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
        if period < 1:
            return 0.0
        tr_values = []
        for i in range(
            -period + 1, 0
        ):  # Start from -period + 1 to ensure i-1 stays within intended window
            # Clamp previous close index to stay within the ATR lookback window
            prev_idx = max(i - 1, -period)
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
