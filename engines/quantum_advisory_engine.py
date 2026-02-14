"""Quantum advisory engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AdvisorySummary:
    signal: str
    risk_posture: str
    confidence: float
    directional_lean: float
    conflicts: list[str] = field(default_factory=list)


class QuantumAdvisoryEngine:
    def summarize(self, **inputs: dict[str, Any]) -> AdvisorySummary:
        field = inputs.get("field", {})
        probability = inputs.get("probability", {})
        coherence = inputs.get("coherence", {})
        context = inputs.get("context", {})
        momentum = inputs.get("momentum", {})
        precision = inputs.get("precision", {})
        structure = inputs.get("structure", {})

        conflicts: list[str] = []
        weighted_prob = float(probability.get("weighted_probability", 0.0))
        gate = coherence.get("gate", "REVIEW")
        momentum_dir = float(momentum.get("momentum_direction", 0.0))
        field_bias = float(field.get("field_bias", 0.0))
        struct_state = structure.get("structure", "RANGE")
        bear_div = bool(structure.get("bearish_divergence", False))
        lean = (momentum_dir * 0.35) + (field_bias * 0.35) + ((weighted_prob - 0.5) * 0.6)

        if weighted_prob > 0.7 and gate == "LOCKOUT":
            conflicts.append("HIGH_PROB_BUT_LOCKOUT")
        if momentum_dir > 0 and struct_state in {"BEARISH", "BREAKING_DOWN"}:
            conflicts.append("MOMENTUM_VS_STRUCTURE")
        if weighted_prob > 0.7 and inputs.get("risk", {}).get("cvar_95", 0) > 0.08:
            conflicts.append("HIGH_PROB_BUT_TAIL_RISK")
        if lean > 0.2 and bear_div:
            conflicts.append("BULLISH_LEAN_BUT_BEARISH_DIVERGENCE")

        base_conf = (
            float(coherence.get("coherence_index", 0.0))
            * float(getattr(precision, "precision_weight", precision.get("precision_weight", 0.0)))
            * float(inputs.get("risk", {}).get("robustness", 0.0))
            * float(field.get("stability_index", 0.0))
        )
        confidence = max(0.0, min(1.0, base_conf - 0.15 * len(conflicts)))

        if confidence > 0.7 and not conflicts:
            signal = "STRONG"
        elif confidence > 0.5:
            signal = "MODERATE"
        elif confidence > 0.3:
            signal = "WEAK"
        else:
            signal = "INSUFFICIENT"

        regime = context.get("regime", "TRANSITIONAL")
        if regime == "RISK_ON" and confidence > 0.65:
            posture = "AGGRESSIVE"
        elif regime == "RISK_OFF" or conflicts:
            posture = "DEFENSIVE"
        else:
            posture = "BALANCED"
        return AdvisorySummary(signal, posture, round(confidence, 4), round(lean, 4), conflicts)
