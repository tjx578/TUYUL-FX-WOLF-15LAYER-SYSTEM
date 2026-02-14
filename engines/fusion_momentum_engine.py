from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _roc(values: list[float], n: int) -> float:
    if len(values) <= n:
        return 0.0
    start = values[-n - 1]
    return (values[-1] - start) / max(abs(start), 1e-9)


@dataclass
class MomentumSnapshot:
    valid: bool
    momentum_strength: float
    momentum_direction: float
    phase: str
    band: str


class FusionMomentumEngine:
    def evaluate(self, payload: dict[str, Any]) -> MomentumSnapshot:
        prices = [float(v) for v in payload.get("prices", [])]
        volumes = [float(v) for v in payload.get("volumes", [1.0] * len(prices))]
        trq_energy = float(payload.get("trq_energy", 0.0))
        field_bias = float(payload.get("field_bias", 0.0))

        if len(prices) < 25:
            return MomentumSnapshot(False, 0.0, 0.0, "UNKNOWN", "NEUTRAL")

        roc5 = _roc(prices, 5)
        roc10 = _roc(prices, 10)
        roc20 = _roc(prices, 20)
        raw = roc5 * 0.5 + roc10 * 0.3 + roc20 * 0.2

        vol_mom = _roc(volumes, 5)
        curvature = roc5 - roc10
        if curvature > 0.01:
            phase = "EXPANSION"
        elif curvature < -0.01:
            phase = "DECELERATION"
        else:
            phase = "STABLE"

        direction = max(-1.0, min(1.0, raw * 6 + field_bias * 0.4))
        strength = max(
            0.0, min(1.0, abs(direction) * 0.7 + abs(vol_mom) * 0.2 + abs(trq_energy) * 0.1)
        )

        if direction > 0.6:
            band = "STRONG_BULLISH"
        elif direction > 0.2:
            band = "BULLISH"
        elif direction < -0.6:
            band = "STRONG_BEARISH"
        elif direction < -0.2:
            band = "BEARISH"
        else:
            band = "NEUTRAL"

        return MomentumSnapshot(True, round(strength, 4), round(direction, 4), phase, band)

    @staticmethod
    def export(snapshot: MomentumSnapshot) -> dict[str, Any]:
        return {
            "valid": snapshot.valid,
            "momentum_strength": snapshot.momentum_strength,
            "momentum_direction": snapshot.momentum_direction,
            "phase": snapshot.phase,
            "band": snapshot.band,
        }
