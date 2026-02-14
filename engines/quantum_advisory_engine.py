from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class AdvisorySignal(str, Enum):
    STRONG_CONTEXT = "STRONG_CONTEXT"
    MODERATE_CONTEXT = "MODERATE_CONTEXT"
    WEAK_CONTEXT = "WEAK_CONTEXT"
    CONFLICTED = "CONFLICTED"
    INSUFFICIENT = "INSUFFICIENT"


class RiskPosture(str, Enum):
    CONSERVATIVE = "CONSERVATIVE"
    BALANCED = "BALANCED"
    AGGRESSIVE = "AGGRESSIVE"
    DEFENSIVE = "DEFENSIVE"


@dataclass
class AdvisorySummary:
    valid: bool
    signal: AdvisorySignal
    confidence_estimate: float
    risk_posture: RiskPosture
    directional_lean: float
    conflict_flags: list[str]
    synthesis_note: str
    details: dict[str, Any] = field(default_factory=dict)


class QuantumAdvisoryEngine:
    def __init__(
        self, min_confidence_threshold: float = 0.3, conflict_penalty: float = 0.15
    ) -> None:
        self.min_confidence = min_confidence_threshold
        self.conflict_penalty = conflict_penalty

    def summarize(  # noqa: PLR0912
        self,
        field: dict[str, Any],
        probability: dict[str, Any],
        coherence: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        risk_sim: dict[str, Any] | None = None,
        momentum: dict[str, Any] | None = None,
        precision: dict[str, Any] | None = None,
        structure: dict[str, Any] | None = None,
    ) -> AdvisorySummary:
        if not field.get("valid") or not probability.get("valid"):
            return AdvisorySummary(
                valid=False,
                signal=AdvisorySignal.INSUFFICIENT,
                confidence_estimate=0.0,
                risk_posture=RiskPosture.DEFENSIVE,
                directional_lean=0.0,
                conflict_flags=["INVALID_CORE_INPUTS"],
                synthesis_note="Field or probability engine returned invalid data",
            )

        w_prob = float(probability.get("weighted_probability", 0.5))
        uncertainty = float(probability.get("uncertainty", 0.5))
        field_energy = float(field.get("field_energy", 0.0))
        field_bias = float(field.get("field_bias", 0.0))
        stability = float(field.get("stability_index", 0.5))

        direction_signals = [field_bias * 2.0]
        weights = [0.3]

        if momentum:
            direction_signals.append(float(momentum.get("momentum_direction", 0.0)))
            weights.append(0.25)
        if structure:
            direction_signals.append(float(structure.get("mtf_alignment", 0.0)))
            weights.append(0.25)
        if context:
            regime = context.get("market_regime", "")
            if regime == "RISK_ON":
                direction_signals.append(0.3)
            elif regime == "RISK_OFF":
                direction_signals.append(-0.3)
            else:
                direction_signals.append(0.0)
            weights.append(0.2)

        total = sum(weights)
        directional_lean = sum(
            x * w for x, w in zip(direction_signals, weights, strict=False)
        ) / max(total, 1e-9)
        directional_lean = max(-1.0, min(1.0, directional_lean))

        conflicts: list[str] = []
        if momentum and structure:
            if (
                float(momentum.get("momentum_direction", 0))
                * float(structure.get("mtf_alignment", 0))
                < -0.3
            ):
                conflicts.append("MOMENTUM_VS_STRUCTURE")
        if coherence and coherence.get("gate") == "LOCKOUT" and w_prob > 0.6:
            conflicts.append("HIGH_PROB_BUT_LOCKOUT")
        if risk_sim and risk_sim.get("tail_risk_flag") and w_prob > 0.7:
            conflicts.append("HIGH_PROB_BUT_TAIL_RISK")
        if structure and structure.get("divergence_present") and directional_lean > 0.3:
            if structure.get("divergence_type") == "BEARISH":
                conflicts.append("BULLISH_LEAN_BUT_BEARISH_DIVERGENCE")

        confidence = w_prob
        if coherence:
            coh = float(coherence.get("coherence_index", 0.7))
            psych = float(coherence.get("psych_confidence", 0.7))
            confidence *= coh * 0.5 + psych * 0.5
        if precision:
            confidence *= 0.5 + float(precision.get("precision_weight", 0.5)) * 0.5
        if risk_sim:
            confidence *= 0.6 + float(risk_sim.get("robustness_estimate", 0.5)) * 0.4
        confidence *= 0.7 + stability * 0.3
        confidence -= len(conflicts) * self.conflict_penalty
        confidence *= 1.0 - uncertainty * 0.3
        confidence = max(0.0, min(1.0, confidence))

        if confidence >= 0.7 and not conflicts:
            signal = AdvisorySignal.STRONG_CONTEXT
        elif confidence >= 0.5 and len(conflicts) <= 1:
            signal = AdvisorySignal.MODERATE_CONTEXT
        elif len(conflicts) >= 2:
            signal = AdvisorySignal.CONFLICTED
        elif confidence >= self.min_confidence:
            signal = AdvisorySignal.WEAK_CONTEXT
        else:
            signal = AdvisorySignal.INSUFFICIENT

        if risk_sim and risk_sim.get("tail_risk_flag"):
            posture = RiskPosture.DEFENSIVE
        elif confidence > 0.7 and stability > 0.7:
            posture = RiskPosture.AGGRESSIVE
        elif confidence > 0.5:
            posture = RiskPosture.BALANCED
        else:
            posture = RiskPosture.CONSERVATIVE

        parts = [f"Confidence {confidence:.0%}"]
        if momentum:
            parts.append(f"phase={momentum.get("phase", "?")}")
        if context:
            parts.append(f"regime={context.get("market_regime", "?")}")
        if conflicts:
            parts.append(f"conflicts={len(conflicts)}")
        parts.append("non-execution advisory")

        return AdvisorySummary(
            valid=True,
            signal=signal,
            confidence_estimate=round(confidence, 4),
            risk_posture=posture,
            directional_lean=round(directional_lean, 4),
            conflict_flags=conflicts,
            synthesis_note=" | ".join(parts),
            details={
                "raw_probability": round(w_prob, 4),
                "uncertainty": round(uncertainty, 4),
                "field_energy": round(field_energy, 6),
                "stability": round(stability, 4),
                "n_conflicts": len(conflicts),
                "engines_available": sum(
                    1
                    for x in [
                        field,
                        probability,
                        coherence,
                        context,
                        risk_sim,
                        momentum,
                        precision,
                        structure,
                    ]
                    if x is not None
                ),
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

    @staticmethod
    def export(summary: AdvisorySummary) -> dict[str, Any]:
        return {
            "valid": summary.valid,
            "signal": summary.signal.value,
            "confidence_estimate": summary.confidence_estimate,
            "risk_posture": summary.risk_posture.value,
            "directional_lean": summary.directional_lean,
            "conflict_flags": summary.conflict_flags,
            "synthesis_note": summary.synthesis_note,
            "details": summary.details,
        }


__all__ = [
    "AdvisorySignal",
    "AdvisorySummary",
    "QuantumAdvisoryEngine",
    "RiskPosture",
]
