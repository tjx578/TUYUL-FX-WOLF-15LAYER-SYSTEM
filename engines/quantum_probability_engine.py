"""Probability weighting engine for layer outputs.

This engine aggregates multiple layer scores into a single weighted probability estimate
with uncertainty quantification and directional consensus metrics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

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
}


@dataclass
class ProbabilityResult:
    weighted_probability: float
    uncertainty: float
    ci_low: float
    ci_high: float
    agreement_ratio: float
    dominant_layer: str
    details: dict[str, Any] = field(default_factory=dict)


class QuantumProbabilityEngine:
    def __init__(self, layer_weights: dict[str, float] | None = None) -> None:
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
            "weighted_probability": result.weighted_probability,
            "uncertainty": result.uncertainty,
            "ci_low": result.ci_low,
            "ci_high": result.ci_high,
            "agreement_ratio": result.agreement_ratio,
            "dominant_layer": result.dominant_layer,
            "details": result.details,
        }
