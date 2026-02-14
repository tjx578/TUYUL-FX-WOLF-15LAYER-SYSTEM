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
