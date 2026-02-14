"""Weighted probability aggregator with uncertainty and confidence intervals."""

from dataclasses import dataclass
from typing import Any

DEFAULT_LAYER_WEIGHTS: dict[str, float] = {
    "context": 0.12,
    "coherence": 0.12,
    "risk": 0.15,
    "momentum": 0.15,
    "precision": 0.14,
    "structure": 0.14,
    "field": 0.1,
    "external": 0.08,
}


@dataclass
class ProbabilityReport:
    weighted_probability: float
    uncertainty: float
    confidence_interval: tuple[float, float]
    agreement_ratio: float
    dominant_layer: str
    details: dict[str, Any]


class QuantumProbabilityEngine:
    def __init__(self, layer_weights: dict[str, float] | None = None) -> None:
        self.layer_weights = layer_weights or DEFAULT_LAYER_WEIGHTS

    def evaluate(self, layer_scores: dict[str, float]) -> ProbabilityReport:
        aligned = {k: float(v) for k, v in layer_scores.items() if k in self.layer_weights}
        if not aligned:
            return ProbabilityReport(0.0, 1.0, (0.0, 0.0), 0.0, "NONE", {})

        total_w = sum(self.layer_weights[k] for k in aligned)
        weighted = sum(aligned[k] * self.layer_weights[k] for k in aligned) / max(total_w, 1e-9)

        scores = list(aligned.values())
        spread = max(scores) - min(scores)
        coverage = len(aligned) / len(self.layer_weights)
        uncertainty = min(1.0, 0.55 * spread + 0.45 * (1.0 - coverage))

        signs = [1 if s >= 0.5 else -1 for s in scores]
        agreement = abs(sum(signs)) / len(signs)

        dominant = max(aligned, key=lambda k: abs(aligned[k] - 0.5))
        ci_half = uncertainty * 0.25
        low = max(0.0, weighted - ci_half)
        high = min(1.0, weighted + ci_half)

        return ProbabilityReport(
            weighted_probability=round(weighted, 4),
            uncertainty=round(uncertainty, 4),
            confidence_interval=(round(low, 4), round(high, 4)),
            agreement_ratio=round(agreement, 4),
            dominant_layer=dominant,
            details={"coverage": round(coverage, 4), "layers": sorted(aligned.keys())},
        )
