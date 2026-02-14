"""Structure and divergence analysis engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StructureResult:
    structure: str
    bullish_divergence: bool
    bearish_divergence: bool
    mtf_alignment: float
    liquidity: str
    details: dict[str, Any] = field(default_factory=dict)


class FusionStructureEngine:
    def evaluate(
        self,
        highs: list[float],
        lows: list[float],
        closes: list[float],
        volumes: list[float],
        rsi_values: list[float],
    ) -> StructureResult:
        if len(closes) < 40:
            return StructureResult(
                "RANGE", False, False, 0.0, "NORMAL", {"reason": "insufficient_data"}
            )

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
    def _swings(values: list[float], is_high: bool, lookback: int = 2) -> list[float]:
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
    def _classify(swings_h: list[float], swings_l: list[float], closes: list[float]) -> str:
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
    def _divergence(closes: list[float], rsi: list[float]) -> tuple[bool, bool]:
        if len(closes) < 8 or len(rsi) < 8:
            return False, False
        price_ll = closes[-1] < min(closes[-6:-1])
        rsi_hl = rsi[-1] > min(rsi[-6:-1])
        price_hh = closes[-1] > max(closes[-6:-1])
        rsi_lh = rsi[-1] < max(rsi[-6:-1])
        return price_ll and rsi_hl, price_hh and rsi_lh

    @staticmethod
    def _mtf_alignment(closes: list[float]) -> float:
        sma10 = sum(closes[-10:]) / 10
        sma20 = sum(closes[-20:]) / 20
        sma40 = sum(closes[-40:]) / 40
        up = [sma10 > sma20, sma20 > sma40]
        down = [sma10 < sma20, sma20 < sma40]
        return max(sum(up), sum(down)) / 2

    @staticmethod
    def _liquidity(volumes: list[float]) -> str:
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
    def export(result: StructureResult) -> dict[str, Any]:
        return {
            "structure": result.structure,
            "bullish_divergence": result.bullish_divergence,
            "bearish_divergence": result.bearish_divergence,
            "mtf_alignment": result.mtf_alignment,
            "liquidity": result.liquidity,
            "details": result.details,
        }
