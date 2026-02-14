from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _slope(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    return values[-1] - values[0]


@dataclass
class StructureSnapshot:
    valid: bool
    structure: str
    divergence_present: bool
    divergence_type: str
    mtf_alignment: float
    liquidity_state: str


class FusionStructureEngine:
    def evaluate(self, payload: dict[str, Any]) -> StructureSnapshot:
        close = [float(v) for v in payload.get("close", payload.get("prices", []))]
        high = [float(v) for v in payload.get("high", close)]
        low = [float(v) for v in payload.get("low", close)]
        volume = [float(v) for v in payload.get("volume", [1.0] * len(close))]
        rsi = [float(v) for v in payload.get("rsi_series", [50.0] * len(close))]

        if len(close) < 25:
            return StructureSnapshot(False, "UNKNOWN", False, "NONE", 0.0, "THIN")

        recent_high = max(high[-10:])
        recent_low = min(low[-10:])
        broke_up = close[-1] > recent_high * 0.998
        broke_down = close[-1] < recent_low * 1.002

        if broke_up:
            structure = "BREAKING_OUT"
        elif broke_down:
            structure = "BREAKING_DOWN"
        elif close[-1] > close[-10]:
            structure = "BULLISH"
        elif close[-1] < close[-10]:
            structure = "BEARISH"
        else:
            structure = "RANGE"

        price_higher_high = close[-1] > close[-6]
        rsi_lower_high = rsi[-1] < rsi[-6]
        price_lower_low = close[-1] < close[-6]
        rsi_higher_low = rsi[-1] > rsi[-6]

        divergence = False
        div_type = "NONE"
        if price_higher_high and rsi_lower_high:
            divergence = True
            div_type = "BEARISH"
        elif price_lower_low and rsi_higher_low:
            divergence = True
            div_type = "BULLISH"

        short_slope = _slope(close[-5:])
        mid_slope = _slope(close[-15:])
        long_slope = _slope(close[-25:])
        same_dir = sum(1 for s in (short_slope, mid_slope, long_slope) if s > 0)
        mtf_alignment = same_dir / 3 if close[-1] >= close[0] else (3 - same_dir) / 3

        v_avg = sum(volume[-20:]) / 20
        if volume[-1] > v_avg * 1.5:
            liq = "HIGH"
        elif volume[-1] < v_avg * 0.7:
            liq = "LOW"
        else:
            liq = "NORMAL"

        return StructureSnapshot(
            True, structure, divergence, div_type, round(mtf_alignment, 4), liq
        )

    @staticmethod
    def export(snapshot: StructureSnapshot) -> dict[str, Any]:
        return {
            "valid": snapshot.valid,
            "structure": snapshot.structure,
            "divergence_present": snapshot.divergence_present,
            "divergence_type": snapshot.divergence_type,
            "mtf_alignment": snapshot.mtf_alignment,
            "liquidity_state": snapshot.liquidity_state,
        }
