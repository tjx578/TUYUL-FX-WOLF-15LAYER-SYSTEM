"""Cross-engine advisory synthesis and conflict diagnostics."""

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class AdvisorySummary:
    signal: str
    directional_lean: float
    risk_posture: str
    confidence: float
    conflicts: List[str]
    details: Dict[str, Any] = field(default_factory=dict)


class QuantumAdvisoryEngine:
    def summarize(self, **engines: Dict[str, Any]) -> AdvisorySummary:
        field = engines.get("field")
        probability = engines.get("probability")
        coherence = engines.get("coherence")
        context = engines.get("context")
        momentum = engines.get("momentum")
        precision = engines.get("precision")
        structure = engines.get("structure")
        risk = engines.get("risk")

        field_bias = float(getattr(field, "field_bias", 0.0))
        momentum_dir = float(getattr(momentum, "momentum_direction", 0.0))
        struct_score = self._structure_score(getattr(structure, "structure", "RANGE"))
        context_score = self._context_score(getattr(context, "regime", "TRANSITIONAL"))
        directional_lean = max(-1.0, min(1.0, (field_bias + momentum_dir + struct_score + context_score) / 4))

        prob = float(getattr(probability, "weighted_probability", 0.0))
        coh = float(getattr(coherence, "coherence_index", 0.0))
        prec = float(getattr(precision, "precision_weight", 0.0))
        robust = float(getattr(risk, "robustness", 0.0))
        stable = float(getattr(field, "stability_index", 0.0))

        conflicts: List[str] = []
        if momentum_dir * struct_score < -0.2:
            conflicts.append("MOMENTUM_VS_STRUCTURE")
        if prob > 0.7 and getattr(coherence, "gate", "PASS") == "LOCKOUT":
            conflicts.append("HIGH_PROB_BUT_LOCKOUT")
        if prob > 0.7 and bool(getattr(risk, "tail_risk", False)):
            conflicts.append("HIGH_PROB_BUT_TAIL_RISK")
        if directional_lean > 0.2 and bool(getattr(structure, "bearish_divergence", False)):
            conflicts.append("BULLISH_LEAN_BUT_BEARISH_DIVERGENCE")

        penalty = max(0.4, 1.0 - (0.12 * len(conflicts)))
        confidence = max(0.0, min(1.0, prob * coh * prec * robust * stable * penalty))

        signal = self._signal_label(confidence, prob, conflicts)
        risk_posture = self._risk_posture(confidence, getattr(coherence, "gate", "PASS"), risk)

        return AdvisorySummary(
            signal=signal,
            directional_lean=round(directional_lean, 4),
            risk_posture=risk_posture,
            confidence=round(confidence, 4),
            conflicts=conflicts,
            details={"penalty": round(penalty, 4), "probability": prob},
        )

    def _structure_score(self, structure: str) -> float:
        mapping = {
            "BULLISH": 0.5,
            "BREAKING_OUT": 0.7,
            "BEARISH": -0.5,
            "BREAKING_DOWN": -0.7,
            "RANGE": 0.0,
        }
        return mapping.get(structure, 0.0)

    def _context_score(self, regime: str) -> float:
        if regime == "RISK_ON":
            return 0.4
        if regime == "RISK_OFF":
            return -0.4
        return 0.0

    def _signal_label(self, confidence: float, probability: float, conflicts: List[str]) -> str:
        if conflicts:
            return "INSUFFICIENT"
        if confidence > 0.75 and probability > 0.7:
            return "STRONG"
        if confidence > 0.55 and probability > 0.6:
            return "MODERATE"
        if confidence > 0.35:
            return "WEAK"
        return "INSUFFICIENT"

    def _risk_posture(self, confidence: float, gate: str, risk: Any) -> str:
        if gate == "LOCKOUT" or bool(getattr(risk, "tail_risk", False)):
            return "DEFENSIVE"
        if confidence > 0.7:
            return "AGGRESSIVE"
        if confidence > 0.45:
            return "BALANCED"
        return "CAUTIOUS"


__all__ = ["AdvisorySummary", "QuantumAdvisoryEngine"]
