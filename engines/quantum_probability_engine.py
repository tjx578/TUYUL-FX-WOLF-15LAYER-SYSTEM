"""Quantum probability engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DEFAULT_LAYER_WEIGHTS: dict[str, float] = {
    "context": 0.12,
    "coherence": 0.12,
    "risk": 0.16,
    "momentum": 0.18,
    "precision": 0.14,
    "structure": 0.12,
    "field": 0.16,
}


@dataclass
class ProbabilityResult:
    weighted_probability: float
    uncertainty: float
    agreement_ratio: float
    ci_low: float
    ci_high: float
    dominant_layer: str


class QuantumProbabilityEngine:
    def evaluate(
        self, layer_scores: dict[str, float], weights: dict[str, float] | None = None
    ) -> ProbabilityResult:
        merged = weights or DEFAULT_LAYER_WEIGHTS
        weighted_total = 0.0
        weight_sum = 0.0
        vals: list[float] = []
        for layer, score in layer_scores.items():
            w = merged.get(layer, 0.05)
            v = max(0.0, min(1.0, float(score)))
            vals.append(v)
            weighted_total += w * v
            weight_sum += w
        if weight_sum == 0:
            return ProbabilityResult(0.0, 1.0, 0.0, 0.0, 0.0, "none")
        prob = weighted_total / weight_sum
        spread = max(vals) - min(vals) if vals else 1.0
        uncertainty = min(1.0, spread + (1.0 - min(1.0, len(vals) / len(merged))))
        direction = sum(1 for v in vals if v >= 0.5)
        agreement = direction / len(vals) if vals else 0.0
        ci_half = uncertainty * 0.25
        dominant = max(layer_scores, key=lambda k: merged.get(k, 0.05)) if layer_scores else "none"
        return ProbabilityResult(
            round(prob, 4),
            round(uncertainty, 4),
            round(agreement, 4),
            round(max(0.0, prob - ci_half), 4),
            round(min(1.0, prob + ci_half), 4),
            dominant,
        )

    @staticmethod
    def export(result: ProbabilityResult) -> dict[str, Any]:
        return result.__dict__
