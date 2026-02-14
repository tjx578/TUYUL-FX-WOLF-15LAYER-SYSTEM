"""Fusion momentum engine with multi-window price and energy analysis."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import math


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
    details: Dict[str, Any] = field(default_factory=dict)


class FusionMomentumEngine:
    """Context-only momentum synthesis. Never carries execution authority."""

    def __init__(
        self,
        roc_periods: Optional[List[int]] = None,
        volume_lookback: int = 20,
    ) -> None:
        self.roc_periods = roc_periods or [5, 10, 20]
        self.volume_lookback = volume_lookback

    def evaluate(self, energy: Dict[str, Any]) -> FusionMomentum:
        trq = float(energy.get("trq_energy", 0.0))
        reflect = float(energy.get("reflective_intensity", 0.0))
        closes: List[float] = energy.get("closes", [])
        volumes: List[float] = energy.get("volumes", [])
        field_bias = float(energy.get("field_bias", 0.0))

        price_mom, rocs = self._compute_price_momentum(closes)
        vol_mom = self._compute_volume_momentum(volumes)
        trq_norm = math.tanh(trq * 0.5)

        if len(closes) >= 10:
            momentum_strength = self._clamp(
                (price_mom * 0.40) + (trq_norm * 0.25) + (reflect * 0.20) + (vol_mom * 0.15)
            )
            momentum_direction = self._compute_direction(field_bias, rocs)
        else:
            momentum_strength = self._clamp((trq_norm + reflect) / 2.0)
            momentum_direction = self._clamp(field_bias, -1.0, 1.0)

        phase = self._detect_phase(rocs, momentum_strength, vol_mom)
        band = self._classify_band(momentum_direction, momentum_strength)
        coherence = self._clamp(
            (reflect * 0.6) + ((1.0 - abs(momentum_direction - field_bias)) * 0.4)
        )

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
                    str(p): round(v, 6) for p, v in zip(self.roc_periods, rocs)
                },
                "trq_raw": trq,
                "field_bias": field_bias,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    def export(self, momentum: FusionMomentum) -> Dict[str, Any]:
        return {
            "momentum_strength": momentum.momentum_strength,
            "momentum_direction": momentum.momentum_direction,
            "phase": momentum.phase.value,
            "band": momentum.band.value,
            "reflective_coherence": momentum.reflective_coherence,
            "trq_energy_contribution": momentum.trq_energy_contribution,
            "price_momentum_pct": momentum.price_momentum_pct,
            "volume_momentum": momentum.volume_momentum,
            "details": momentum.details,
        }

    def _compute_price_momentum(self, closes: List[float]) -> Tuple[float, List[float]]:
        if not closes or len(closes) < max(self.roc_periods) + 1:
            return 0.0, []

        roc_values: List[float] = []
        for period in self.roc_periods:
            base = closes[-period - 1]
            roc = (closes[-1] - base) / base if base else 0.0
            roc_values.append(roc)

        weights = [1.0 / (i + 1) for i in range(len(roc_values))]
        total_weight = sum(weights) or 1.0
        amplitude = sum(abs(v) * w for v, w in zip(roc_values, weights)) / total_weight
        return min(1.0, amplitude * 50.0), roc_values

    def _compute_volume_momentum(self, volumes: List[float]) -> float:
        if len(volumes) < 10:
            return 0.5
        lookback = min(self.volume_lookback, len(volumes))
        baseline = sum(volumes[-lookback:]) / lookback
        recent = sum(volumes[-5:]) / 5
        if baseline <= 0:
            return 0.5
        return self._clamp((recent / baseline) / 2.0)

    def _compute_direction(self, field_bias: float, rocs: List[float]) -> float:
        if not rocs:
            return self._clamp(field_bias, -1.0, 1.0)
        bullish = sum(1 for value in rocs if value > 0)
        bearish = sum(1 for value in rocs if value < 0)
        roc_direction = (bullish - bearish) / len(rocs)
        return self._clamp((roc_direction * 0.7) + (field_bias * 0.3), -1.0, 1.0)

    def _detect_phase(
        self,
        rocs: List[float],
        strength: float,
        volume_momentum: float,
    ) -> MomentumPhase:
        if len(rocs) < 2:
            return MomentumPhase.EXPANSION if strength >= 0.4 else MomentumPhase.NEUTRAL

        acceleration = rocs[-1] - rocs[0]
        sign_flip = rocs[-1] * rocs[0] < 0

        if strength > 0.6 and acceleration > 0:
            return MomentumPhase.EXPANSION
        if strength > 0.5 and acceleration < -0.001:
            return MomentumPhase.EXHAUSTION
        if strength < 0.3 and volume_momentum < 0.4:
            return MomentumPhase.COMPRESSION
        if abs(acceleration) > 0.005 and sign_flip:
            return MomentumPhase.REVERSAL
        return MomentumPhase.NEUTRAL

    def _classify_band(self, direction: float, strength: float) -> MomentumBand:
        score = direction * strength
        if score > 0.4:
            return MomentumBand.STRONG_BULLISH
        if score > 0.15:
            return MomentumBand.MODERATE_BULLISH
        if score < -0.4:
            return MomentumBand.STRONG_BEARISH
        if score < -0.15:
            return MomentumBand.MODERATE_BEARISH
        return MomentumBand.NEUTRAL

    @staticmethod
    def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
        return max(low, min(high, value))


__all__ = [
    "MomentumPhase",
    "MomentumBand",
    "FusionMomentum",
    "FusionMomentumEngine",
]
