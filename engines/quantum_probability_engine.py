from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

DEFAULT_LAYER_WEIGHTS = {
    "coherence": 0.25,
    "context": 0.2,
    "momentum": 0.2,
    "precision": 0.15,
    "structure": 0.2,
}


@dataclass(frozen=True)
class ProbabilityResult:
    probability: float
    uncertainty: float


class QuantumProbabilityEngine:
    """Combine weighted layer scores into a calibrated probability estimate."""

    def __init__(self, layer_weights: Mapping[str, float] | None = None) -> None:
        self.layer_weights = dict(layer_weights or DEFAULT_LAYER_WEIGHTS)

    def evaluate(self, state: Mapping[str, Any]) -> ProbabilityResult:
        weighted_sum = 0.0
        used_weight = 0.0
        for key, weight in self.layer_weights.items():
            value = state.get(key)
            if value is None:
                continue
            weighted_sum += max(0.0, min(1.0, float(value))) * float(weight)
            used_weight += float(weight)

        probability = weighted_sum / used_weight if used_weight else 0.5
        uncertainty = max(0.0, min(1.0, 1.0 - used_weight))
        return ProbabilityResult(probability=probability, uncertainty=uncertainty)
