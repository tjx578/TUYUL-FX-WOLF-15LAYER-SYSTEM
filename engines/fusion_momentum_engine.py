"""Momentum synthesis engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Sequence
import math


@dataclass
class MomentumResult:
    valid: bool
    momentum_strength: float
    phase: str
    directional_bias: str
    volume_momentum: float
    details: Dict[str, Any] = field(default_factory=dict)


class FusionMomentumEngine:
    def evaluate(self, data: Dict[str, Sequence[float]]) -> MomentumResult:
        prices = list(data.get("price", []))
        volumes = list(data.get("volume", [1.0] * len(prices)))
        trq = float(data.get("trq_energy", 0.0))
        field_bias = float(data.get("field_bias", 0.0))

        if len(prices) < 25:
            return MomentumResult(False, 0.0, "UNKNOWN", "NEUTRAL", 0.0, {"reason": "insufficient"})

        roc5 = self._roc(prices, 5)
        roc10 = self._roc(prices, 10)
        roc20 = self._roc(prices, 20)
        momentum = 0.45 * roc5 + 0.35 * roc10 + 0.2 * roc20

        vol_mom = self._roc(volumes, 5)
        curvature = roc5 - 2 * roc10 + roc20
        phase = "EXPANSION" if curvature > 0.002 else "DECELERATION" if curvature < -0.002 else "STABLE"

        fused = 0.65 * math.tanh(momentum * 14) + 0.2 * math.tanh(trq) + 0.15 * math.tanh(field_bias)
        if fused > 0.6:
            band = "STRONG_BULLISH"
        elif fused > 0.2:
            band = "BULLISH"
        elif fused < -0.6:
            band = "STRONG_BEARISH"
        elif fused < -0.2:
            band = "BEARISH"
        else:
            band = "NEUTRAL"

        return MomentumResult(
            valid=True,
            momentum_strength=round(abs(fused), 4),
            phase=phase,
            directional_bias=band,
            volume_momentum=round(vol_mom, 4),
            details={
                "roc5": round(roc5, 6),
                "roc10": round(roc10, 6),
                "roc20": round(roc20, 6),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    @staticmethod
    def _roc(values: Sequence[float], period: int) -> float:
        if len(values) <= period:
            return 0.0
        prev = values[-period - 1]
        if prev == 0:
            return 0.0
        return (values[-1] - prev) / abs(prev)
