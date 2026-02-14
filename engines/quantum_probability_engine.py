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
"""Probability weighting engine for layer outputs.

This engine aggregates multiple layer scores into a single weighted probability estimate
with uncertainty quantification and directional consensus metrics.
"""
"""Quantum probability engine for weighted layer aggregation."""
"""Quantum probability engine."""

from __future__ import annotations

"""Probability weighting engine for layer outputs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
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
from typing import Any, Dict

# Layer weights for probability aggregation
# These weights represent the relative importance of each analysis layer in the final decision.
#
# **Rationale for weights** (totaling 1.0):
# - field (0.18): Highest weight. Quantum field energy captures market microstructure,
#   order flow dynamics, and volatility clustering - critical for entry timing.
# - momentum (0.16): Strong trend signals are reliable in directional markets. ROC-based
#   momentum across multiple windows provides robust directional bias.
# - risk (0.14): Monte Carlo simulation with stress scenarios validates trade viability
#   under adverse conditions. Essential for capital preservation.
# - precision (0.14): EMA confluence and zone proximity indicate high-quality entry points.
#   Multi-timeframe alignment reduces false signals.
# - context (0.13): Market regime detection (risk-on/off, structure) provides environmental
#   awareness. Moderate weight as context sets stage but doesn't predict direction.
# - structure (0.13): Swing highs/lows and breakout patterns confirm directional bias.
#   Lower weight as structure is slower-moving than momentum.
# - coherence (0.12): Trader psychological state. Lowest weight as it's a risk filter
#   rather than a signal generator, but still critical for discipline.
#
# **Customization guidelines**:
# - Increase 'field' weight for scalping/intraday strategies (up to 0.25)
# - Increase 'momentum' weight for trend-following strategies (up to 0.22)
# - Increase 'risk' weight for conservative risk management (up to 0.20)
# - Decrease 'coherence' weight if using automated execution (down to 0.08)
# - Adjust based on backtesting results for your specific market and timeframe
#
# **Layer correlations**:
# - momentum, precision, and structure are partially correlated (all trend-based)
# - field and context are partially correlated (both measure market state)
# - coherence and risk are independent of market factors
# The multiplicative weighting assumes approximate independence, which is acceptable
# given the diverse nature of the signals.
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
    "risk": 0.16,
    "momentum": 0.18,
    "precision": 0.14,
    "structure": 0.12,
    "field": 0.16,
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
class ProbabilitySnapshot:
    valid: bool
    weighted_probability: float
    uncertainty: float
    agreement_ratio: float
    confidence_interval: tuple[float, float]
class ProbabilityResult:
    valid: bool
    weighted_probability: float
    confidence_interval: tuple[float, float]
    layer_contributions: Dict[str, float]
    uncertainty: float
    agreement_ratio: float
    weighted_probability: float
    uncertainty: float
    agreement_ratio: float
    ci_low: float
    ci_high: float
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
    def export(snapshot: ProbabilitySnapshot) -> dict[str, Any]:
        return {
            "valid": snapshot.valid,
            "weighted_probability": snapshot.weighted_probability,
            "uncertainty": snapshot.uncertainty,
            "agreement_ratio": snapshot.agreement_ratio,
            "confidence_interval": snapshot.confidence_interval,
            "dominant_layer": snapshot.dominant_layer,
        }
    def export(result: ProbabilityResult) -> dict[str, Any]:
        return result.__dict__
    ci_low: float
    ci_high: float
    agreement_ratio: float
    dominant_layer: str
    details: dict[str, Any] = field(default_factory=dict)


class QuantumProbabilityEngine:
    def __init__(self, layer_weights: dict[str, float] | None = None) -> None:
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
    def __init__(self, layer_weights: Dict[str, float] | None = None) -> None:
        self.layer_weights = layer_weights or DEFAULT_LAYER_WEIGHTS

    def evaluate(self, layer_scores: dict[str, float]) -> ProbabilityResult:
        known = [(k, float(v)) for k, v in layer_scores.items() if k in self.layer_weights]
        if not known:
            return ProbabilityResult(
                0.0, 1.0, 0.0, 0.0, 0.0, "UNKNOWN", {"reason": "no_known_layers"}
            )

        total_weight = sum(self.layer_weights[k] for k, _ in known)
        weighted = sum(v * self.layer_weights[k] for k, v in known) / total_weight

        scores = [v for _, v in known]
        spread = max(scores) - min(scores)
        coverage = len(known) / len(self.layer_weights)
        uncertainty = min(1.0, spread * 0.7 + (1.0 - coverage) * 0.3)

        # Calculate directional consensus (agreement_ratio)
        # This measures whether layers agree on direction (bullish vs bearish)
        # using 0.5 as the neutral point: >=0.5 is bullish (+1), <0.5 is bearish (-1)
        #
        # Note: This metric only captures directional alignment, not strength of consensus.
        # For example, scores [0.51, 0.49] and [0.9, 0.1] both yield agreement_ratio=0.0
        # despite vastly different conviction levels. The metric is useful for identifying
        # conflicting directional signals but does not account for magnitude of disagreement.
        #
        # Consider using 'uncertainty' and 'spread' for magnitude-aware analysis.
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
    def export(result: ProbabilityResult) -> dict[str, Any]:
        return {
            "valid": result.valid,
            "weighted_probability": result.weighted_probability,
            "confidence_interval": list(result.confidence_interval),
            "layer_contributions": result.layer_contributions,
            "uncertainty": result.uncertainty,
            "weighted_probability": result.weighted_probability,
            "uncertainty": result.uncertainty,
            "ci_low": result.ci_low,
            "ci_high": result.ci_high,
            "agreement_ratio": result.agreement_ratio,
            "dominant_layer": result.dominant_layer,
            "details": result.details,
        }


__all__ = ["DEFAULT_LAYER_WEIGHTS", "ProbabilityResult", "QuantumProbabilityEngine"]
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
