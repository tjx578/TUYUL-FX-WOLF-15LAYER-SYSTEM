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
"""Momentum synthesis engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Sequence
import math
from typing import Any, Dict, List


@dataclass
class MomentumResult:
    valid: bool
    momentum_strength: float
    phase: str
    directional_bias: str
    volume_momentum: float
    momentum_strength: float
    phase: str
    directional_bias: float
    details: Dict[str, Any] = field(default_factory=dict)


class FusionMomentumEngine:
    def evaluate(self, data: Dict[str, Sequence[float]]) -> MomentumResult:
        prices = list(data.get("price", []))
        volumes = list(data.get("volume", [1.0] * len(prices)))
        trq = float(data.get("trq_energy", 0.0))
        field_bias = float(data.get("field_bias", 0.0))

        if len(prices) < 25:
            return MomentumResult(False, 0.0, "UNKNOWN", "NEUTRAL", 0.0, {"reason": "insufficient"})
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
