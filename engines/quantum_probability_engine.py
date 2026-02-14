"""Quantum probability engine for weighted layer aggregation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import math

DEFAULT_LAYER_WEIGHTS: Dict[str, float] = {
    "L0_regime": 0.08,
    "L1_reflex": 0.06,
    "L2_fusion": 0.10,
    "L3_trq3d": 0.09,
    "L5_governance": 0.07,
    "L7_structural": 0.12,
    "L8_tii": 0.10,
    "L9_montecarlo": 0.10,
    "L11_discipline": 0.08,
    "L12_verdict": 0.15,
    "L13_execution": 0.05,
}


@dataclass
class ProbabilityResult:
    valid: bool
    weighted_probability: float
    confidence_interval: tuple[float, float]
    layer_contributions: Dict[str, float]
    uncertainty: float
    agreement_ratio: float
    dominant_layer: str
    details: Dict[str, Any] = field(default_factory=dict)


class QuantumProbabilityEngine:
    def __init__(
        self,
        layer_weights: Optional[Dict[str, float]] = None,
        min_layers: int = 3,
    ) -> None:
        self.weights = layer_weights or DEFAULT_LAYER_WEIGHTS
        self.min_layers = min_layers

    def compute(self, layer_scores: Dict[str, float]) -> ProbabilityResult:
        if not layer_scores:
            return ProbabilityResult(
                valid=False,
                weighted_probability=0.0,
                confidence_interval=(0.0, 0.0),
                layer_contributions={},
                uncertainty=1.0,
                agreement_ratio=0.0,
                dominant_layer="NONE",
                details={"reason": "empty_layer_scores"},
            )

        known = {k: v for k, v in layer_scores.items() if k in self.weights}
        unknown = {k: v for k, v in layer_scores.items() if k not in self.weights}

        if len(known) < self.min_layers and len(layer_scores) < self.min_layers:
            active_scores = layer_scores
            active_weights = {k: 1.0 / len(layer_scores) for k in layer_scores}
        else:
            active_scores = known if known else layer_scores
            w_total = sum(self.weights.get(k, 0.05) for k in active_scores)
            active_weights = {k: self.weights.get(k, 0.05) / w_total for k in active_scores}

        weighted_prob = sum(active_scores[k] * active_weights[k] for k in active_scores)
        contributions = {k: round(active_scores[k] * active_weights[k], 4) for k in active_scores}

        bullish = sum(1 for v in active_scores.values() if v > 0.55)
        bearish = sum(1 for v in active_scores.values() if v < 0.45)
        total = len(active_scores)
        agreement = (max(bullish, bearish) / total) if total else 0.0

        values = list(active_scores.values())
        if len(values) > 1:
            mean_v = sum(values) / len(values)
            variance = sum((v - mean_v) ** 2 for v in values) / len(values)
            spread_unc = min(1.0, math.sqrt(variance) * 3)
        else:
            spread_unc = 0.5

        coverage_unc = max(0.0, 1.0 - len(active_scores) / max(len(self.weights), 1))
        uncertainty = spread_unc * 0.6 + coverage_unc * 0.4

        half_width = uncertainty * 0.3
        ci_lower = max(0.0, weighted_prob - half_width)
        ci_upper = min(1.0, weighted_prob + half_width)
        dominant = max(contributions, key=contributions.get) if contributions else "NONE"

        return ProbabilityResult(
            valid=True,
            weighted_probability=round(max(0.0, min(1.0, weighted_prob)), 4),
            confidence_interval=(round(ci_lower, 4), round(ci_upper, 4)),
            layer_contributions=contributions,
            uncertainty=round(uncertainty, 4),
            agreement_ratio=round(agreement, 4),
            dominant_layer=dominant,
            details={
                "n_layers": len(active_scores),
                "n_unknown_layers": len(unknown),
                "bullish_layers": bullish,
                "bearish_layers": bearish,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    @staticmethod
    def export(result: ProbabilityResult) -> Dict[str, Any]:
        return {
            "valid": result.valid,
            "weighted_probability": result.weighted_probability,
            "confidence_interval": list(result.confidence_interval),
            "layer_contributions": result.layer_contributions,
            "uncertainty": result.uncertainty,
            "agreement_ratio": result.agreement_ratio,
            "dominant_layer": result.dominant_layer,
            "details": result.details,
        }


__all__ = ["DEFAULT_LAYER_WEIGHTS", "ProbabilityResult", "QuantumProbabilityEngine"]
