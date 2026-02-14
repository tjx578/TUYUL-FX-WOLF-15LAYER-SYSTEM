from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class MomentumPhase(str, Enum):
    ACCELERATING = "accelerating"
    DECELERATING = "decelerating"
    FLAT = "flat"


class MomentumBand(str, Enum):
    LOW = "low"
    MID = "mid"
    HIGH = "high"


@dataclass(frozen=True)
class FusionMomentum:
    phase: MomentumPhase
    band: MomentumBand
    trq_energy: float


class FusionMomentumEngine:
    """Fuse momentum vectors into phase and energy buckets."""

    def evaluate(self, state: Mapping[str, Any]) -> FusionMomentum:
        velocity = float(state.get("momentum_velocity", 0.0))
        impulse = float(state.get("momentum_impulse", 0.0))
        energy = max(0.0, min(1.0, (abs(velocity) + abs(impulse)) / 2.0))

        if velocity > 0.2 and impulse > 0:
            phase = MomentumPhase.ACCELERATING
        elif velocity < -0.2 and impulse < 0:
            phase = MomentumPhase.DECELERATING
        else:
            phase = MomentumPhase.FLAT

        if energy > 0.7:
            band = MomentumBand.HIGH
        elif energy > 0.35:
            band = MomentumBand.MID
        else:
            band = MomentumBand.LOW

        return FusionMomentum(phase=phase, band=band, trq_energy=energy)
