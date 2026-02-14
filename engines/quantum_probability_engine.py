"""Probability weighting engine for layer outputs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict

DEFAULT_LAYER_WEIGHTS = {
    "context": 0.13,
    "coherence": 0.12,
    "risk": 0.14,
    "momentum": 0.16,
    "precision": 0.14,
    "structure": 0.13,
    "field": 0.18,
}


@dataclass
class ProbabilityResult:
    weighted_probability: float
    uncertainty: float
    ci_low: float
    ci_high: float
    agreement_ratio: float
    dominant_layer: str
    details: Dict[str, Any] = field(default_factory=dict)


class QuantumProbabilityEngine:
    def __init__(self, layer_weights: Dict[str, float] | None = None) -> None:
        self.layer_weights = layer_weights or DEFAULT_LAYER_WEIGHTS

    def evaluate(self, layer_scores: Dict[str, float]) -> ProbabilityResult:
        known = [(k, float(v)) for k, v in layer_scores.items() if k in self.layer_weights]
        if not known:
            return ProbabilityResult(0.0, 1.0, 0.0, 0.0, 0.0, "UNKNOWN", {"reason": "no_known_layers"})

        total_weight = sum(self.layer_weights[k] for k, _ in known)
        weighted = sum(v * self.layer_weights[k] for k, v in known) / total_weight

        scores = [v for _, v in known]
        spread = max(scores) - min(scores)
        coverage = len(known) / len(self.layer_weights)
        uncertainty = min(1.0, spread * 0.7 + (1.0 - coverage) * 0.3)

        signs = [1 if s >= 0.5 else -1 for s in scores]
        agreement = abs(sum(signs)) / len(signs)

        dominant = max(known, key=lambda kv: abs(kv[1] - 0.5))[0]
        half_ci = uncertainty * 0.25

        return ProbabilityResult(
            weighted_probability=round(weighted, 6),
            uncertainty=round(uncertainty, 6),
            ci_low=round(max(0.0, weighted - half_ci), 6),
            ci_high=round(min(1.0, weighted + half_ci), 6),
            agreement_ratio=round(agreement, 6),
            dominant_layer=dominant,
            details={"coverage": round(coverage, 6), "known_layers": [k for k, _ in known]},
        )

    @staticmethod
    def export(result: ProbabilityResult) -> Dict[str, Any]:
        return {
            "weighted_probability": result.weighted_probability,
            "uncertainty": result.uncertainty,
            "ci_low": result.ci_low,
            "ci_high": result.ci_high,
            "agreement_ratio": result.agreement_ratio,
            "dominant_layer": result.dominant_layer,
            "details": result.details,
        }
