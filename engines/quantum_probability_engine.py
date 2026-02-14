from __future__ import annotations

from dataclasses import dataclass
from statistics import pstdev
from typing import Any

DEFAULT_LAYER_WEIGHTS = {
    "context": 0.15,
    "coherence": 0.1,
    "risk": 0.2,
    "momentum": 0.2,
    "precision": 0.15,
    "structure": 0.1,
    "field": 0.1,
}


@dataclass
class ProbabilitySnapshot:
    valid: bool
    weighted_probability: float
    uncertainty: float
    agreement_ratio: float
    confidence_interval: tuple[float, float]
    dominant_layer: str


class QuantumProbabilityEngine:
    def evaluate(self, layer_scores: dict[str, float]) -> ProbabilitySnapshot:
        usable = {k: float(v) for k, v in layer_scores.items() if k in DEFAULT_LAYER_WEIGHTS}
        if not usable:
            return ProbabilitySnapshot(False, 0.5, 1.0, 0.0, (0.0, 1.0), "NONE")

        total_w = sum(DEFAULT_LAYER_WEIGHTS[k] for k in usable)
        w_prob = sum(usable[k] * DEFAULT_LAYER_WEIGHTS[k] for k in usable) / max(total_w, 1e-9)

        values = list(usable.values())
        spread = pstdev(values) if len(values) > 1 else 0.0
        coverage = len(usable) / len(DEFAULT_LAYER_WEIGHTS)
        uncertainty = max(0.0, min(1.0, spread * 1.2 + (1 - coverage) * 0.4))

        bullish = sum(1 for v in values if v >= 0.5)
        bearish = len(values) - bullish
        agreement = max(bullish, bearish) / len(values)

        dominant = max(usable, key=lambda k: abs(usable[k] - 0.5))
        ci_half = max(0.02, uncertainty * 0.25)
        ci = (max(0.0, w_prob - ci_half), min(1.0, w_prob + ci_half))

        return ProbabilitySnapshot(
            True,
            round(w_prob, 4),
            round(uncertainty, 4),
            round(agreement, 4),
            (round(ci[0], 4), round(ci[1], 4)),
            dominant,
        )

    @staticmethod
    def export(snapshot: ProbabilitySnapshot) -> dict[str, Any]:
        return {
            "valid": snapshot.valid,
            "weighted_probability": snapshot.weighted_probability,
            "uncertainty": snapshot.uncertainty,
            "agreement_ratio": snapshot.agreement_ratio,
            "confidence_interval": snapshot.confidence_interval,
            "dominant_layer": snapshot.dominant_layer,
        }
