"""Cross-engine advisory synthesis and conflict diagnostics."""

from dataclasses import dataclass, field
from typing import Any, Dict, List
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class AdvisorySignal(str, Enum):
"""Cross-engine advisory synthesis (non-execution)."""
"""Quantum Advisory Engine v2.0 (sanitized, non-execution)."""
"""Quantum advisory engine."""
"""Cross-engine advisory synthesizer."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List
from enum import Enum
from typing import Any, Dict, List, Optional


class AdvisorySignal(str, Enum):
    """Analytical signal quality classification."""

    STRONG_CONTEXT = "STRONG_CONTEXT"
    MODERATE_CONTEXT = "MODERATE_CONTEXT"
    WEAK_CONTEXT = "WEAK_CONTEXT"
    CONFLICTED = "CONFLICTED"
    INSUFFICIENT = "INSUFFICIENT"


class RiskPosture(str, Enum):
    """Risk profile for advisory context."""

    CONSERVATIVE = "CONSERVATIVE"
    BALANCED = "BALANCED"
    AGGRESSIVE = "AGGRESSIVE"
    DEFENSIVE = "DEFENSIVE"


@dataclass
class AdvisorySummary:
    signal: str
    directional_lean: float
    risk_posture: str
    confidence: float
    conflicts: List[str]
    details: Dict[str, Any] = field(default_factory=dict)


class QuantumAdvisoryEngine:
    valid: bool
    signal: str
    confidence: float
    risk_posture: str
    directional_lean: str
    conflicts: List[str]
    """Unified advisory context output (non-execution only)."""

    valid: bool
    signal: AdvisorySignal
    confidence_estimate: float
    risk_posture: RiskPosture
    directional_lean: float
    conflict_flags: list[str]
    synthesis_note: str
    conflict_flags: List[str]
    synthesis_note: str
from typing import Any, Dict, List
"""Cross-engine advisory synthesizer with conflict and risk posture detection."""

from dataclasses import dataclass
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
    confidence: float
    risk_posture: str
    directional_lean: float
    conflicts: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


class QuantumAdvisoryEngine:
    def __init__(
        self, min_confidence_threshold: float = 0.3, conflict_penalty: float = 0.15
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
    """Cross-engine synthesis to produce risk-aware, non-execution context."""

    def __init__(
        self,
        min_confidence_threshold: float = 0.3,
        conflict_penalty: float = 0.15,
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
    def summarize(
        self,
        field: Dict[str, Any],
        probability: Dict[str, Any],
        coherence: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
        risk_sim: Optional[Dict[str, Any]] = None,
        momentum: Optional[Dict[str, Any]] = None,
        precision: Optional[Dict[str, Any]] = None,
        structure: Optional[Dict[str, Any]] = None,
    ) -> AdvisorySummary:
        """Generate advisory summary from engine outputs."""
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
        weight_total = sum(weights)
        directional_lean = (
            sum(signal * weight for signal, weight in zip(direction_signals, weights))
            / weight_total
            if weight_total > 0
            else 0.0
        )
        directional_lean = max(-1.0, min(1.0, directional_lean))

        conflicts: List[str] = []
        if momentum and structure:
            mom_dir = float(momentum.get("momentum_direction", 0.0))
            mtf = float(structure.get("mtf_alignment", 0.0))
            if mom_dir * mtf < -0.3:
                conflicts.append("MOMENTUM_VS_STRUCTURE")
        if coherence:
            gate = coherence.get("gate", "PASS")
            if gate == "LOCKOUT" and w_prob > 0.6:
                conflicts.append("HIGH_PROB_BUT_LOCKOUT")
        if risk_sim and risk_sim.get("tail_risk_flag") and w_prob > 0.7:
            conflicts.append("HIGH_PROB_BUT_TAIL_RISK")
        if structure and structure.get("divergence_present") and directional_lean > 0.3:
            if structure.get("divergence_type", "") == "BEARISH":
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
            coh_idx = float(coherence.get("coherence_index", 0.7))
            psych = float(coherence.get("psych_confidence", 0.7))
            confidence *= (coh_idx * 0.5) + (psych * 0.5)
        if precision:
            prec_w = float(precision.get("precision_weight", 0.5))
            confidence *= 0.5 + (prec_w * 0.5)
        if risk_sim:
            robustness = float(risk_sim.get("robustness_estimate", 0.5))
            confidence *= 0.6 + (robustness * 0.4)

        confidence *= 0.7 + (stability * 0.3)
        confidence -= len(conflicts) * self.conflict_penalty
        confidence *= 1.0 - (uncertainty * 0.3)
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
            parts.append(f"phase={momentum.get('phase', '?')}")
        if context:
            parts.append(f"regime={context.get('market_regime', '?')}")
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
                    for item in [
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
                    if item is not None
                ),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    def export(self, summary: AdvisorySummary) -> Dict[str, Any]:
        """Return serialization-safe dictionary payload."""
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
    "RiskPosture",
    "AdvisorySummary",
    "QuantumAdvisoryEngine",
]
    def summarize(
        self,
        *,
        field: dict[str, Any],
        probability: dict[str, Any],
        coherence: dict[str, Any],
        context: dict[str, Any],
        momentum: dict[str, Any],
        precision: dict[str, Any],
        structure: dict[str, Any],
        risk: dict[str, Any] | None = None,
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

        regime = context.get("regime", "TRANSITIONAL")
        if regime == "RISK_ON" and confidence > 0.65:
            posture = "AGGRESSIVE"
        elif regime == "RISK_OFF" or conflicts:
            posture = "DEFENSIVE"
        else:
            posture = "BALANCED"
        return AdvisorySummary(signal, posture, round(confidence, 4), round(lean, 4), conflicts)
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
        probability: dict[str, Any],
        coherence: dict[str, Any],
        momentum: dict[str, Any],
        structure: dict[str, Any],
        risk: dict[str, Any],
    ) -> list[str]:
        conflicts: list[str] = []
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
    def export(result: AdvisorySummary) -> dict[str, Any]:
        return {
            "signal": result.signal,
            "confidence": result.confidence,
            "risk_posture": result.risk_posture,
            "directional_lean": result.directional_lean,
            "conflicts": result.conflicts,
            "details": result.details,
        }
