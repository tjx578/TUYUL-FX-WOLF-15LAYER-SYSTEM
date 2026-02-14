"""Structure and divergence engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Sequence


@dataclass
class StructureResult:
    valid: bool
    structure: str
    bullish_divergence: bool
    bearish_divergence: bool
    liquidity: str
    mtf_alignment: float
    details: Dict[str, Any] = field(default_factory=dict)


class FusionStructureEngine:
    def evaluate(self, data: Dict[str, Sequence[float] | float]) -> StructureResult:
        closes = list(data.get("close", []))
        highs = list(data.get("high", closes))
        lows = list(data.get("low", closes))
        volumes = list(data.get("volume", [1.0] * len(closes)))
        rsi = list(data.get("rsi_series", []))

        if len(closes) < 50:
            return StructureResult(False, "UNKNOWN", False, False, "UNKNOWN", 0.0, {"reason": "insufficient"})

        highs_idx, lows_idx = self._swings(highs, lows, lookback=2)
        structure = "RANGE"
        if len(highs_idx) >= 2 and len(lows_idx) >= 2:
            hh = highs[highs_idx[-1]] > highs[highs_idx[-2]]
            hl = lows[lows_idx[-1]] > lows[lows_idx[-2]]
            ll = lows[lows_idx[-1]] < lows[lows_idx[-2]]
            lh = highs[highs_idx[-1]] < highs[highs_idx[-2]]
            if hh and hl:
                structure = "BREAKING_OUT"
            elif ll and lh:
                structure = "BREAKING_DOWN"
            elif hh:
                structure = "BULLISH"
            elif ll:
                structure = "BEARISH"

        bull_div = False
        bear_div = False
        if len(rsi) >= len(closes) and len(lows_idx) >= 2 and len(highs_idx) >= 2:
            l1, l2 = lows_idx[-2], lows_idx[-1]
            h1, h2 = highs_idx[-2], highs_idx[-1]
            bull_div = lows[l2] < lows[l1] and rsi[l2] > rsi[l1]
            bear_div = highs[h2] > highs[h1] and rsi[h2] < rsi[h1]

        vol_ratio = volumes[-1] / max(sum(volumes[-20:]) / 20.0, 1e-9)
        liquidity = "HIGH" if vol_ratio > 1.2 else "LOW" if vol_ratio < 0.8 else "NORMAL"

        slope_fast = closes[-1] - closes[-10]
        slope_slow = closes[-1] - closes[-30]
        mtf = 1.0 if slope_fast * slope_slow > 0 else 0.4

        return StructureResult(
            valid=True,
            structure=structure,
            bullish_divergence=bull_div,
            bearish_divergence=bear_div,
            liquidity=liquidity,
            mtf_alignment=round(mtf, 4),
            details={
                "swing_highs": highs_idx[-5:],
                "swing_lows": lows_idx[-5:],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    @staticmethod
    def _swings(highs: List[float], lows: List[float], lookback: int) -> tuple[List[int], List[int]]:
        sh: List[int] = []
        sl: List[int] = []
        for i in range(lookback, len(highs) - lookback):
            left_h = highs[i - lookback : i]
            right_h = highs[i + 1 : i + lookback + 1]
            left_l = lows[i - lookback : i]
            right_l = lows[i + 1 : i + lookback + 1]
            if highs[i] > max(left_h + right_h):
                sh.append(i)
            if lows[i] < min(left_l + right_l):
                sl.append(i)
        return sh, sl
