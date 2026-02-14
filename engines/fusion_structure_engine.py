"""Fusion structure engine."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class StructureResult:
    structure: str
    bullish_divergence: bool
    bearish_divergence: bool
    mtf_alignment: float


class FusionStructureEngine:
    def evaluate(self, payload: dict[str, list[float]]) -> StructureResult:
        closes = payload.get("closes", [])
        rsi = payload.get("rsi", [])
        if len(closes) < 8:
            return StructureResult("UNKNOWN", False, False, 0.0)
        last = closes[-1]
        recent_max = max(closes[-6:-1])
        recent_min = min(closes[-6:-1])
        if last > recent_max:
            structure = "BREAKING_OUT"
        elif last < recent_min:
            structure = "BREAKING_DOWN"
        elif closes[-1] > closes[-4] > closes[-8]:
            structure = "BULLISH"
        elif closes[-1] < closes[-4] < closes[-8]:
            structure = "BEARISH"
        else:
            structure = "RANGE"
        bull_div = bool(len(rsi) >= 6 and closes[-1] < closes[-3] and rsi[-1] > rsi[-3])
        bear_div = bool(len(rsi) >= 6 and closes[-1] > closes[-3] and rsi[-1] < rsi[-3])
        htf_slope = (closes[-1] - closes[-6]) / closes[-6]
        ltf_slope = (closes[-1] - closes[-3]) / closes[-3]
        mtf = 1.0 if htf_slope * ltf_slope > 0 else 0.4
        return StructureResult(structure, bull_div, bear_div, round(mtf, 4))
