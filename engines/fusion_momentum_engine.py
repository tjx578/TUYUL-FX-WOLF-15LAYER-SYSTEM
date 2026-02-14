"""Momentum engine with multi-window ROC and phase detection."""

from dataclasses import dataclass
from typing import Any


@dataclass
class MomentumReport:
    momentum_strength: float
    phase: str
    direction: str
    details: dict[str, Any]


class FusionMomentumEngine:
    def evaluate(self, energy_data: dict[str, list[float] | float]) -> MomentumReport:
        prices = list(energy_data.get("prices", []))
        volumes = list(energy_data.get("volumes", []))
        field_bias = float(energy_data.get("field_bias", 0.0))
        trq_energy = float(energy_data.get("trq_energy", 0.0))
        if len(prices) < 25:
            return MomentumReport(0.0, "NEUTRAL", "FLAT", {"reason": "insufficient_data"})

        roc5 = self._roc(prices, 5)
        roc10 = self._roc(prices, 10)
        roc20 = self._roc(prices, 20)
        vol_mom = self._volume_momentum(volumes)
        curvature = (roc5 - roc10) - (roc10 - roc20)

        raw = roc5 * 0.45 + roc10 * 0.35 + roc20 * 0.2 + vol_mom * 0.15 + field_bias * 0.2
        momentum = self._tanh(raw + trq_energy * 0.2)

        phase = (
            "EXPANSION" if curvature > 0.01 else "CONTRACTION" if curvature < -0.01 else "BALANCED"
        )
        direction = "BULLISH" if momentum > 0.15 else "BEARISH" if momentum < -0.15 else "NEUTRAL"

        return MomentumReport(
            momentum_strength=round(abs(momentum), 4),
            phase=phase,
            direction=direction,
            details={
                "roc5": round(roc5, 6),
                "roc10": round(roc10, 6),
                "roc20": round(roc20, 6),
                "volume_momentum": round(vol_mom, 6),
            },
        )

    def _roc(self, prices: list[float], window: int) -> float:
        if len(prices) <= window:
            return 0.0
        prev = prices[-window - 1]
        return 0.0 if prev == 0 else (prices[-1] - prev) / prev

    def _volume_momentum(self, volumes: list[float]) -> float:
        if len(volumes) < 10:
            return 0.0
        recent = sum(volumes[-5:]) / 5
        base = sum(volumes[-10:-5]) / 5
        return 0.0 if base == 0 else (recent - base) / base

    def _tanh(self, value: float) -> float:
        exp_pos = 2.718281828**value
        exp_neg = 2.718281828 ** (-value)
        return (exp_pos - exp_neg) / (exp_pos + exp_neg)
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
