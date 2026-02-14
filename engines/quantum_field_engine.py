from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class QuantumField:
    field_energy: float
    bias: float
    stability: float


class QuantumFieldEngine:
    """Compute aggregate field state from directional and noise components."""

    def evaluate(self, state: Mapping[str, Any]) -> QuantumField:
        direction = float(state.get("directional_pressure", 0.0))
        coherence = max(0.0, min(1.0, float(state.get("signal_coherence", 0.5))))
        noise = max(0.0, min(1.0, float(state.get("market_noise", 0.5))))

        energy = max(0.0, min(1.0, (abs(direction) * 0.55) + coherence * 0.45))
        bias = max(-1.0, min(1.0, direction))
        stability = max(0.0, min(1.0, coherence * (1.0 - noise)))
        return QuantumField(field_energy=energy, bias=bias, stability=stability)
