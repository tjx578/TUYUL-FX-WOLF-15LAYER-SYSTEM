"""Cross-engine advisory synthesis (non-execution)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List


@dataclass
class AdvisorySummary:
    valid: bool
    signal: str
    confidence: float
    risk_posture: str
    directional_lean: str
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

        field_bias = getattr(field, "field_bias", 0.0)
        prob = getattr(probability, "weighted_probability", 0.0)
        gate = getattr(coherence, "gate", "REVIEW")
        coh = getattr(coherence, "coherence_index", 0.0)
        mom_bias = getattr(momentum, "directional_bias", "NEUTRAL")
        struct_state = getattr(structure, "structure", "RANGE")

        lean_score = 0.0
        lean_score += 0.35 if field_bias > 0 else -0.35
        lean_score += 0.35 if "BULL" in mom_bias else -0.35 if "BEAR" in mom_bias else 0.0
        lean_score += 0.2 if struct_state in {"BULLISH", "BREAKING_OUT"} else -0.2
        lean_score += 0.1 if getattr(context, "regime", "") == "RISK_ON" else -0.1
        directional_lean = "BULLISH" if lean_score > 0.2 else "BEARISH" if lean_score < -0.2 else "MIXED"

        conflicts: List[str] = []
        if ("BULL" in mom_bias and struct_state in {"BEARISH", "BREAKING_DOWN"}) or (
            "BEAR" in mom_bias and struct_state in {"BULLISH", "BREAKING_OUT"}
        ):
            conflicts.append("MOMENTUM_VS_STRUCTURE")
        if prob > 0.68 and gate == "LOCKOUT":
            conflicts.append("HIGH_PROB_BUT_LOCKOUT")
        if prob > 0.68 and getattr(risk, "cvar95", 0.0) > 0.15:
            conflicts.append("HIGH_PROB_BUT_TAIL_RISK")
        if directional_lean == "BULLISH" and getattr(structure, "bearish_divergence", False):
            conflicts.append("BULLISH_LEAN_BUT_BEARISH_DIVERGENCE")

        penalty = 0.12 * len(conflicts)
        precision_weight = getattr(precision, "precision_weight", 0.0)
        robustness = getattr(risk, "robustness", 0.0)
        stability = getattr(field, "stability_index", 0.0)
        base_conf = prob * coh * (0.6 + 0.4 * precision_weight) * (0.5 + 0.5 * robustness) * stability
        confidence = max(0.0, min(1.0, base_conf - penalty))

        if confidence > 0.75 and not conflicts:
            signal = "STRONG"
        elif confidence > 0.58 and len(conflicts) <= 1:
            signal = "MODERATE"
        elif confidence > 0.4:
            signal = "WEAK"
        elif prob > 0.65 and gate == "LOCKOUT":
            signal = "INSUFFICIENT"
        else:
            signal = "NO_TRADE"

        if getattr(risk, "max_drawdown", 0.0) < 0.12 and gate == "PASS":
            posture = "AGGRESSIVE"
        elif getattr(risk, "max_drawdown", 0.0) < 0.2:
            posture = "BALANCED"
        elif getattr(risk, "max_drawdown", 0.0) < 0.3:
            posture = "CAUTIOUS"
        else:
            posture = "DEFENSIVE"

        return AdvisorySummary(
            valid=True,
            signal=signal,
            confidence=round(confidence, 4),
            risk_posture=posture,
            directional_lean=directional_lean,
            conflicts=conflicts,
            details={
                "gate": gate,
                "weighted_probability": prob,
                "coherence": coh,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
