"""Fusion momentum engine."""

from __future__ import annotations

import math

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class MomentumPhase(str, Enum):
    EXPANSION = "EXPANSION"
    COMPRESSION = "COMPRESSION"
    EXHAUSTION = "EXHAUSTION"
    REVERSAL = "REVERSAL"
    NEUTRAL = "NEUTRAL"


class MomentumBand(str, Enum):
    STRONG_BULLISH = "STRONG_BULLISH"
    MODERATE_BULLISH = "MODERATE_BULLISH"
    NEUTRAL = "NEUTRAL"
    MODERATE_BEARISH = "MODERATE_BEARISH"
    STRONG_BEARISH = "STRONG_BEARISH"


@dataclass
class FusionMomentum:
    momentum_strength: float
    momentum_direction: float
    phase: MomentumPhase
    band: MomentumBand
    reflective_coherence: float
    trq_energy_contribution: float
    price_momentum_pct: float
    volume_momentum: float
    details: dict[str, Any] = field(default_factory=dict)


class FusionMomentumEngine:
    def __init__(self, roc_periods: list[int] | None = None, volume_lookback: int = 20) -> None:
        self.roc_periods = roc_periods or [5, 10, 20]
        self.volume_lookback = volume_lookback

    def evaluate(self, energy: dict[str, Any]) -> FusionMomentum:
        trq = float(energy.get("trq_energy", 0.0))
        reflect = float(energy.get("reflective_intensity", 0.0))
        closes = [float(v) for v in energy.get("closes", [])]
        volumes = [float(v) for v in energy.get("volumes", [])]
        field_bias = float(energy.get("field_bias", 0.0))
        price_mom, roc_values = self._compute_price_momentum(closes)
        vol_mom = self._compute_volume_momentum(volumes)
        trq_norm = math.tanh(trq * 0.5)

        if closes and len(closes) >= 10:
            momentum_strength = self._clamp(
                price_mom * 0.40 + trq_norm * 0.25 + reflect * 0.20 + vol_mom * 0.15
            )
            momentum_direction = self._compute_direction(field_bias, roc_values)
        else:
            momentum_strength = self._clamp((trq_norm + reflect) / 2.0)
            momentum_direction = self._clamp(field_bias, -1.0, 1.0)

        phase = self._detect_phase(roc_values, momentum_strength, vol_mom)
        band = self._classify_band(momentum_direction, momentum_strength)
        coherence = self._clamp(reflect * 0.6 + (1.0 - abs(momentum_direction - field_bias)) * 0.4)
        return FusionMomentum(
            momentum_strength=round(momentum_strength, 4),
            momentum_direction=round(momentum_direction, 4),
            phase=phase,
            band=band,
            reflective_coherence=round(coherence, 4),
            trq_energy_contribution=round(trq_norm, 4),
            price_momentum_pct=round(price_mom, 6),
            volume_momentum=round(vol_mom, 4),
            details={
                "roc_values": {
                    str(p): round(v, 6) for p, v in zip(self.roc_periods, roc_values, strict=False)
                },
                "trq_raw": trq,
                "field_bias": field_bias,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

    def _compute_price_momentum(self, closes: list[float]) -> tuple[float, list[float]]:
        if not closes or len(closes) < max(self.roc_periods):
            return 0.0, []
        roc_values: list[float] = []
        for period in self.roc_periods:
            if len(closes) > period and closes[-period - 1] != 0:
                roc = (closes[-1] - closes[-period - 1]) / closes[-period - 1]
            else:
                roc = 0.0
            roc_values.append(roc)
        weights = [1.0 / (i + 1) for i in range(len(roc_values))]
        w_sum = sum(weights)
        price_mom = sum(abs(r) * w for r, w in zip(roc_values, weights, strict=False)) / w_sum
        return min(1.0, price_mom * 50), roc_values

    def _compute_volume_momentum(self, volumes: list[float]) -> float:
        if not volumes or len(volumes) < 10:
            return 0.5
        lookback = min(self.volume_lookback, len(volumes))
        avg = sum(volumes[-lookback:]) / lookback
        recent = sum(volumes[-5:]) / 5.0
        if avg == 0:
            return 0.5
        return self._clamp((recent / avg) / 2.0)

    def _compute_direction(self, field_bias: float, roc_values: list[float]) -> float:
        if not roc_values:
            return self._clamp(field_bias, -1.0, 1.0)
        bullish = sum(1 for r in roc_values if r > 0)
        bearish = sum(1 for r in roc_values if r < 0)
        roc_direction = (bullish - bearish) / len(roc_values)
        return self._clamp(roc_direction * 0.7 + field_bias * 0.3, -1.0, 1.0)

    def _detect_phase(
        self, roc_values: list[float], strength: float, vol_mom: float
    ) -> MomentumPhase:
        if len(roc_values) < 2:
            return MomentumPhase.NEUTRAL if strength < 0.4 else MomentumPhase.EXPANSION
        accel = roc_values[-1] - roc_values[0]
        if strength > 0.6 and accel > 0:
            return MomentumPhase.EXPANSION
        if strength > 0.5 and accel < -0.001:
            return MomentumPhase.EXHAUSTION
        if strength < 0.3 and vol_mom < 0.4:
            return MomentumPhase.COMPRESSION
        if abs(accel) > 0.005 and roc_values[-1] * roc_values[0] < 0:
            return MomentumPhase.REVERSAL
        return MomentumPhase.NEUTRAL

    def _classify_band(self, direction: float, strength: float) -> MomentumBand:
        magnitude = direction * strength
        if magnitude > 0.4:
            return MomentumBand.STRONG_BULLISH
        if magnitude > 0.15:
            return MomentumBand.MODERATE_BULLISH
        if magnitude < -0.4:
            return MomentumBand.STRONG_BEARISH
        if magnitude < -0.15:
            return MomentumBand.MODERATE_BEARISH
        return MomentumBand.NEUTRAL

    @staticmethod
    def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
        return max(lo, min(hi, v))

    @staticmethod
    def export(m: FusionMomentum) -> dict[str, Any]:
        return {
            "momentum_strength": m.momentum_strength,
            "momentum_direction": m.momentum_direction,
            "phase": m.phase.value,
            "band": m.band.value,
            "reflective_coherence": m.reflective_coherence,
            "trq_energy_contribution": m.trq_energy_contribution,
            "price_momentum_pct": m.price_momentum_pct,
            "volume_momentum": m.volume_momentum,
            "details": m.details,
        }
