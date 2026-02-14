"""Layer-weighted probability and uncertainty quantification."""

from dataclasses import dataclass, field
from typing import Any, Dict, Tuple


DEFAULT_LAYER_WEIGHTS = {
    "context": 1.0,
    "coherence": 1.3,
    "risk": 1.2,
    "momentum": 1.1,
    "precision": 1.0,
    "structure": 1.0,
    "field": 1.1,
}


@dataclass
class ProbabilityResult:
    weighted_probability: float
    agreement_ratio: float
    uncertainty: float
    confidence_interval: Tuple[float, float]
    dominant_layer: str
    details: Dict[str, Any] = field(default_factory=dict)


class QuantumProbabilityEngine:
    def __init__(self, layer_weights: Dict[str, float] | None = None) -> None:
        self.layer_weights = layer_weights or DEFAULT_LAYER_WEIGHTS

    def evaluate(self, layer_scores: Dict[str, float]) -> ProbabilityResult:
        weighted_sum = 0.0
        weight_total = 0.0
        known = {}

        for layer, score in layer_scores.items():
            weight = self.layer_weights.get(layer, 0.5)
            bounded = max(0.0, min(1.0, float(score)))
            weighted_sum += bounded * weight
            weight_total += weight
            known[layer] = bounded

        weighted_prob = weighted_sum / (weight_total or 1.0)
        spread = max(known.values()) - min(known.values()) if known else 1.0
        coverage = min(1.0, len(known) / max(1, len(self.layer_weights)))
        uncertainty = min(1.0, (spread * 0.65) + ((1.0 - coverage) * 0.35))

        bullish = sum(1 for score in known.values() if score >= 0.55)
        bearish = sum(1 for score in known.values() if score <= 0.45)
        agreement = abs(bullish - bearish) / (len(known) or 1)

        margin = max(0.02, uncertainty * 0.2)
        ci = (max(0.0, weighted_prob - margin), min(1.0, weighted_prob + margin))

        dominant = max(known.items(), key=lambda item: item[1])[0] if known else "unknown"

        return ProbabilityResult(
            weighted_probability=round(weighted_prob, 4),
            agreement_ratio=round(agreement, 4),
            uncertainty=round(uncertainty, 4),
            confidence_interval=(round(ci[0], 4), round(ci[1], 4)),
            dominant_layer=dominant,
            details={"coverage": round(coverage, 4), "spread": round(spread, 4)},
        )


__all__ = ["ProbabilityResult", "QuantumProbabilityEngine", "DEFAULT_LAYER_WEIGHTS"]
