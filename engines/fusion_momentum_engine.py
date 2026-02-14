"""Momentum synthesis engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class MomentumResult:
    momentum_strength: float
    phase: str
    directional_bias: float
    details: Dict[str, Any] = field(default_factory=dict)


class FusionMomentumEngine:
    def evaluate(self, closes: List[float], volumes: List[float], trq_energy: float = 0.0) -> MomentumResult:
        if len(closes) < 24:
            return MomentumResult(0.0, "INSUFFICIENT", 0.0, {"reason": "not_enough_bars"})

        roc5 = self._roc(closes, 5)
        roc10 = self._roc(closes, 10)
        roc20 = self._roc(closes, 20)
        composite = roc5 * 0.5 + roc10 * 0.3 + roc20 * 0.2

        curvature = roc5 - roc10
        phase = "EXPANSION" if curvature > 0.002 else "DECELERATION" if curvature < -0.002 else "BALANCED"

        vol_momentum = 0.0
        if len(volumes) > 8:
            short = sum(volumes[-4:]) / 4
            long = sum(volumes[-8:-4]) / 4
            vol_momentum = (short - long) / long if long else 0.0

        trq_norm = trq_energy / (1.0 + abs(trq_energy))
        bias = composite * 0.7 + vol_momentum * 0.2 + trq_norm * 0.1
        strength = max(0.0, min(1.0, abs(bias) * 25))

        return MomentumResult(
            momentum_strength=round(strength, 6),
            phase=phase,
            directional_bias=round(bias, 6),
            details={"roc5": roc5, "roc10": roc10, "roc20": roc20, "vol_momentum": vol_momentum},
        )

    @staticmethod
    def _roc(closes: List[float], period: int) -> float:
        base = closes[-period - 1]
        if base == 0:
            return 0.0
        return (closes[-1] - base) / base

    @staticmethod
    def export(result: MomentumResult) -> Dict[str, Any]:
        return {
            "momentum_strength": result.momentum_strength,
            "phase": result.phase,
            "directional_bias": result.directional_bias,
            "details": result.details,
        }
