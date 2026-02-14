"""Cross-engine advisory synthesizer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class AdvisorySummary:
    signal: str
    confidence: float
    risk_posture: str
    directional_lean: float
    conflicts: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)


class QuantumAdvisoryEngine:
    def summarize(
        self,
        *,
        field: Dict[str, Any],
        probability: Dict[str, Any],
        coherence: Dict[str, Any],
        context: Dict[str, Any],
        momentum: Dict[str, Any],
        precision: Dict[str, Any],
        structure: Dict[str, Any],
        risk: Dict[str, Any] | None = None,
    ) -> AdvisorySummary:
        risk = risk or {}
        conflicts = self._detect_conflicts(
            probability=probability,
            coherence=coherence,
            momentum=momentum,
            structure=structure,
            risk=risk,
        )

        lean = (
            float(field.get("field_bias", 0.0)) * 0.25
            + float(momentum.get("directional_bias", 0.0)) * 0.35
            + (0.2 if structure.get("structure") in {"BULLISH", "BREAKING_OUT"} else -0.2)
            + (0.2 if context.get("market_regime") == "RISK_ON" else -0.2)
        )

        base_conf = (
            float(probability.get("weighted_probability", 0.0))
            * float(coherence.get("coherence_index", 0.0) or 0.0)
            * float(precision.get("precision_weight", 0.0) or 0.0)
            * float(risk.get("robustness", 1.0))
            * float(field.get("stability_index", 0.0) or 0.0)
        )
        penalty = max(0.5, 1 - 0.12 * len(conflicts))
        confidence = max(0.0, min(1.0, base_conf * penalty))

        if confidence >= 0.75 and not conflicts:
            signal = "STRONG"
        elif confidence >= 0.55:
            signal = "MODERATE"
        elif confidence >= 0.35:
            signal = "CAUTIOUS"
        elif confidence >= 0.2:
            signal = "WEAK"
        else:
            signal = "INSUFFICIENT"

        posture_score = confidence - (0.08 * len(conflicts))
        if posture_score > 0.6:
            risk_posture = "AGGRESSIVE"
        elif posture_score > 0.45:
            risk_posture = "BALANCED"
        elif posture_score > 0.3:
            risk_posture = "CONSERVATIVE"
        else:
            risk_posture = "DEFENSIVE"

        return AdvisorySummary(
            signal=signal,
            confidence=round(confidence, 6),
            risk_posture=risk_posture,
            directional_lean=round(lean, 6),
            conflicts=conflicts,
            details={"conflict_count": len(conflicts), "base_confidence": round(base_conf, 6)},
        )

    @staticmethod
    def _detect_conflicts(
        *,
        probability: Dict[str, Any],
        coherence: Dict[str, Any],
        momentum: Dict[str, Any],
        structure: Dict[str, Any],
        risk: Dict[str, Any],
    ) -> List[str]:
        conflicts: List[str] = []
        if (
            float(probability.get("weighted_probability", 0.0)) > 0.7
            and coherence.get("gate") == "LOCKOUT"
        ):
            conflicts.append("HIGH_PROB_BUT_LOCKOUT")
        if (
            momentum.get("directional_bias", 0.0) > 0
            and structure.get("structure") in {"BEARISH", "BREAKING_DOWN"}
        ) or (
            momentum.get("directional_bias", 0.0) < 0
            and structure.get("structure") in {"BULLISH", "BREAKING_OUT"}
        ):
            conflicts.append("MOMENTUM_VS_STRUCTURE")
        if (
            float(probability.get("weighted_probability", 0.0)) > 0.72
            and float(risk.get("cvar_95", 0.0)) < -0.1
        ):
            conflicts.append("HIGH_PROB_BUT_TAIL_RISK")
        if momentum.get("directional_bias", 0.0) > 0 and structure.get("bearish_divergence"):
            conflicts.append("BULLISH_LEAN_BUT_BEARISH_DIVERGENCE")
        return conflicts

    @staticmethod
    def export(result: AdvisorySummary) -> Dict[str, Any]:
        return {
            "signal": result.signal,
            "confidence": result.confidence,
            "risk_posture": result.risk_posture,
            "directional_lean": result.directional_lean,
            "conflicts": result.conflicts,
            "details": result.details,
        }
