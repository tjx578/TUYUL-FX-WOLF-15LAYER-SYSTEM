from __future__ import annotations

"""
L12 Router Evaluator — strict constitutional prototype

L12 is the sole constitutional verdict authority for Phase 5.
This module evaluates upstream phase results through a 9-gate model
and produces EXECUTE / HOLD / NO_TRADE verdicts.

L12 must NOT:
- send live orders
- compute lot size
- bypass upstream veto
- act as enrichment or sizing engine

Analysis-only module. No execution authority.
"""

from dataclasses import dataclass, field  # noqa: E402
from enum import StrEnum  # noqa: E402
from typing import Any  # noqa: E402


class L12Status(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class L12Verdict(StrEnum):
    EXECUTE = "EXECUTE"
    EXECUTE_REDUCED_RISK = "EXECUTE_REDUCED_RISK"
    HOLD = "HOLD"
    NO_TRADE = "NO_TRADE"


class L12BlockerCode(StrEnum):
    UPSTREAM_NOT_CONTINUABLE = "UPSTREAM_NOT_CONTINUABLE"
    UPSTREAM_TARGET_NOT_PHASE5 = "UPSTREAM_TARGET_NOT_PHASE5"
    L2_HARD_ILLEGALITY = "L2_HARD_ILLEGALITY"
    L9_HARD_STRUCTURE_ILLEGALITY = "L9_HARD_STRUCTURE_ILLEGALITY"
    PHASE1_MISSING = "PHASE1_MISSING"
    PHASE2_MISSING = "PHASE2_MISSING"
    PHASE3_MISSING = "PHASE3_MISSING"
    PHASE4_MISSING = "PHASE4_MISSING"
    FOUNDATION_FAIL = "FOUNDATION_FAIL"
    SCORING_FAIL = "SCORING_FAIL"
    STRUCTURE_FAIL = "STRUCTURE_FAIL"
    RISK_CHAIN_FAIL = "RISK_CHAIN_FAIL"
    INTEGRITY_FAIL = "INTEGRITY_FAIL"
    PROBABILITY_FAIL = "PROBABILITY_FAIL"
    FIREWALL_FAIL = "FIREWALL_FAIL"
    GOVERNANCE_FAIL = "GOVERNANCE_FAIL"
    SYNTHESIS_SCORE_TOO_LOW = "SYNTHESIS_SCORE_TOO_LOW"
    CONTRACT_PAYLOAD_MALFORMED = "CONTRACT_PAYLOAD_MALFORMED"


class L12GateName(StrEnum):
    FOUNDATION_OK = "FOUNDATION_OK"
    SCORING_OK = "SCORING_OK"
    ENRICHMENT_OK = "ENRICHMENT_OK"
    STRUCTURE_OK = "STRUCTURE_OK"
    RISK_CHAIN_OK = "RISK_CHAIN_OK"
    INTEGRITY_OK = "INTEGRITY_OK"
    PROBABILITY_OK = "PROBABILITY_OK"
    FIREWALL_OK = "FIREWALL_OK"
    GOVERNANCE_OK = "GOVERNANCE_OK"


@dataclass(frozen=True)
class L12Input:
    input_ref: str
    timestamp: str
    upstream_continuation_allowed: bool = True
    upstream_next_legal_targets: list[str] = field(default_factory=list)

    # Phase status from upstream
    foundation_status: str = "FAIL"
    scoring_status: str = "FAIL"
    enrichment_status: str = "WARN"
    structure_status: str = "FAIL"
    risk_chain_status: str = "FAIL"

    # Layer scores (per-layer numeric)
    layer_scores: dict[str, float] = field(default_factory=dict)

    # L2 evidence plane forwarded for verdict differentiation
    l2_status: str = "FAIL"
    l2_evidence_score: float | None = None
    l2_confidence_penalty: float = 0.0
    l2_hard_stop: bool = False
    l2_advisory_continuation: bool = False
    l2_hard_blockers: list[str] = field(default_factory=list)
    l2_soft_blockers: list[str] = field(default_factory=list)
    l2_primary_conflict: str | None = None

    # L9 structure evidence plane forwarded for verdict differentiation
    l9_status: str = "FAIL"
    l9_evidence_score: float | None = None
    l9_confidence_penalty: float = 0.0
    l9_hard_stop: bool = False
    l9_advisory_continuation: bool = False
    l9_hard_blockers: list[str] = field(default_factory=list)
    l9_soft_blockers: list[str] = field(default_factory=list)
    l9_source_builder_state: str | None = None

    # Phase availability flags
    phase1_available: bool = False
    phase2_available: bool = False
    phase3_available: bool = False
    phase4_available: bool = False

    # Synthesis aids
    synthesis_score: float = 0.0

    # Integrity / probability / firewall / governance from upstream
    integrity_status: str = "FAIL"
    probability_status: str = "FAIL"
    firewall_status: str = "FAIL"
    governance_status: str = "PASS"


@dataclass(frozen=True)
class L12EvaluationResult:
    layer: str
    layer_version: str
    timestamp: str
    input_ref: str
    verdict: str
    verdict_status: str
    continuation_allowed: bool
    next_legal_targets: list[str]
    score_numeric: float
    gate_summary: dict[str, str]
    blocker_codes: list[str]
    warning_codes: list[str]
    audit: dict[str, Any]
    # v2.0 fields: soft penalty + adaptive sizing + navigation confidence
    raw_confidence: float = 0.0
    penalized_confidence: float = 0.0
    sizing_multiplier: float = 1.0
    soft_fail_count: int = 0
    soft_warn_count: int = 0
    penalty_breakdown: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer": self.layer,
            "layer_version": self.layer_version,
            "timestamp": self.timestamp,
            "input_ref": self.input_ref,
            "verdict": self.verdict,
            "verdict_status": self.verdict_status,
            "continuation_allowed": self.continuation_allowed,
            "next_legal_targets": self.next_legal_targets,
            "score_numeric": self.score_numeric,
            "gate_summary": self.gate_summary,
            "blocker_codes": self.blocker_codes,
            "warning_codes": self.warning_codes,
            "audit": self.audit,
            "raw_confidence": self.raw_confidence,
            "penalized_confidence": self.penalized_confidence,
            "sizing_multiplier": self.sizing_multiplier,
            "soft_fail_count": self.soft_fail_count,
            "soft_warn_count": self.soft_warn_count,
            "penalty_breakdown": self.penalty_breakdown,
        }


class L12RouterEvaluator:
    VERSION = "2.0.0"

    # Score thresholds (applied to penalized confidence)
    EXECUTE_MIN_SCORE = 0.65
    EXECUTE_REDUCED_MIN_SCORE = 0.50
    HOLD_MIN_SCORE = 0.40

    # Hard gates: FAIL on any of these -> NO_TRADE
    HARD_GATES = {
        L12GateName.FOUNDATION_OK,
        L12GateName.STRUCTURE_OK,
        L12GateName.RISK_CHAIN_OK,
        L12GateName.FIREWALL_OK,
    }

    def __init__(self) -> None:
        from constitution.gate_penalty_engine import GatePenaltyEngine
        self._penalty_engine = GatePenaltyEngine()

    @staticmethod
    def _status_to_gate(status_str: str) -> str:
        s = str(status_str).upper().strip()
        if s == "PASS":
            return "PASS"
        if s == "WARN":
            return "WARN"
        return "FAIL"

    def _build_gate_summary(self, payload: L12Input) -> dict[str, str]:
        return {
            L12GateName.FOUNDATION_OK.value: self._status_to_gate(payload.foundation_status),
            L12GateName.SCORING_OK.value: self._status_to_gate(payload.scoring_status),
            L12GateName.ENRICHMENT_OK.value: self._status_to_gate(payload.enrichment_status),
            L12GateName.STRUCTURE_OK.value: self._status_to_gate(payload.structure_status),
            L12GateName.RISK_CHAIN_OK.value: self._status_to_gate(payload.risk_chain_status),
            L12GateName.INTEGRITY_OK.value: self._status_to_gate(payload.integrity_status),
            L12GateName.PROBABILITY_OK.value: self._status_to_gate(payload.probability_status),
            L12GateName.FIREWALL_OK.value: self._status_to_gate(payload.firewall_status),
            L12GateName.GOVERNANCE_OK.value: self._status_to_gate(payload.governance_status),
        }

    def evaluate(self, payload: L12Input) -> L12EvaluationResult:
        blockers: list[str] = []
        warnings: list[str] = []
        rule_hits: list[str] = []
        notes: list[str] = []

        # ── Contract validation ──
        if not payload.input_ref or not payload.timestamp:
            blockers.append(L12BlockerCode.CONTRACT_PAYLOAD_MALFORMED.value)

        # ── Upstream continuability ──
        if not payload.upstream_continuation_allowed:
            blockers.append(L12BlockerCode.UPSTREAM_NOT_CONTINUABLE.value)

        if payload.l2_hard_stop and payload.l2_hard_blockers:
            blockers.append(L12BlockerCode.L2_HARD_ILLEGALITY.value)
            rule_hits.append(
                "L2 hard illegality -> " + ",".join(sorted(dict.fromkeys(payload.l2_hard_blockers)))
            )
        elif payload.l2_soft_blockers:
            warnings.append("L2_WEAK_EVIDENCE")
            rule_hits.append(
                f"L2 weak evidence -> penalty={payload.l2_confidence_penalty:.2f}, "
                f"soft_blockers={','.join(sorted(dict.fromkeys(payload.l2_soft_blockers)))}"
            )
            if payload.l2_primary_conflict:
                warnings.append(payload.l2_primary_conflict)

        if payload.l9_hard_stop and payload.l9_hard_blockers:
            blockers.append(L12BlockerCode.L9_HARD_STRUCTURE_ILLEGALITY.value)
            rule_hits.append(
                "L9 hard structure illegality -> " + ",".join(sorted(dict.fromkeys(payload.l9_hard_blockers)))
            )
        elif payload.l9_soft_blockers:
            warnings.append("L9_WEAK_STRUCTURE_EVIDENCE")
            rule_hits.append(
                f"L9 weak structure evidence -> penalty={payload.l9_confidence_penalty:.2f}, "
                f"soft_blockers={','.join(sorted(dict.fromkeys(payload.l9_soft_blockers)))}"
            )
            if payload.l9_source_builder_state:
                warnings.append(f"L9_SOURCE_BUILDER_{payload.l9_source_builder_state.upper()}")

        targets = [str(t).upper().strip() for t in payload.upstream_next_legal_targets]
        if targets and "PHASE_5" not in targets:
            blockers.append(L12BlockerCode.UPSTREAM_TARGET_NOT_PHASE5.value)

        # ── Phase availability ──
        if not payload.phase1_available:
            blockers.append(L12BlockerCode.PHASE1_MISSING.value)
        if not payload.phase2_available:
            blockers.append(L12BlockerCode.PHASE2_MISSING.value)
        if not payload.phase3_available:
            blockers.append(L12BlockerCode.PHASE3_MISSING.value)
        if not payload.phase4_available:
            blockers.append(L12BlockerCode.PHASE4_MISSING.value)

        # ── 9-gate evaluation ──
        gate_summary = self._build_gate_summary(payload)

        # ── Penalty engine: soft penalty + navigation confidence + sizing ──
        penalty_result = self._penalty_engine.evaluate(
            gate_summary=gate_summary,
            layer_scores=payload.layer_scores,
        )

        # Hard gate blockers from penalty engine
        hard_gate_blocker_map: dict[str, str] = {
            L12GateName.FOUNDATION_OK.value: L12BlockerCode.FOUNDATION_FAIL.value,
            L12GateName.STRUCTURE_OK.value: L12BlockerCode.STRUCTURE_FAIL.value,
            L12GateName.RISK_CHAIN_OK.value: L12BlockerCode.RISK_CHAIN_FAIL.value,
            L12GateName.FIREWALL_OK.value: L12BlockerCode.FIREWALL_FAIL.value,
        }
        for veto_gate in penalty_result.hard_veto_gates:
            blocker_code = hard_gate_blocker_map.get(veto_gate)
            if blocker_code:
                blockers.append(blocker_code)
                rule_hits.append(f"{veto_gate}=FAIL -> HARD_VETO")

        # Soft gate FAILs → warnings (not blockers)
        soft_gate_warning_map: dict[str, str] = {
            L12GateName.SCORING_OK.value: "SCORING_DEGRADED",
            L12GateName.INTEGRITY_OK.value: "INTEGRITY_DEGRADED",
            L12GateName.PROBABILITY_OK.value: "PROBABILITY_DEGRADED",
            L12GateName.GOVERNANCE_OK.value: "GOVERNANCE_DEGRADED",
        }
        for gp in penalty_result.gate_penalties:
            if gp.status == "FAIL" and gp.tier == "SOFT":
                warning_label = soft_gate_warning_map.get(gp.gate, f"{gp.gate}_DEGRADED")
                warnings.append(warning_label)
                rule_hits.append(
                    f"{gp.gate}=FAIL -> soft penalty={gp.confidence_penalty:.2f}, "
                    f"sizing×{gp.sizing_factor:.2f}"
                )
            elif gp.status == "FAIL" and gp.tier == "ADVISORY":
                warnings.append("ENRICHMENT_DEGRADED")
                rule_hits.append(f"{gp.gate}=FAIL -> advisory warning")
            elif gp.status == "WARN":
                warnings.append(f"{gp.gate}_WARN")
                rule_hits.append(f"{gp.gate}=WARN")

        # ── Navigation-weighted penalized confidence ──
        penalized_score = penalty_result.penalized_confidence
        raw_confidence = penalty_result.raw_confidence
        sizing_multiplier = penalty_result.sizing_multiplier

        # ── Synthesis score check (on penalized confidence) ──
        if penalized_score < self.HOLD_MIN_SCORE and not blockers:
            blockers.append(L12BlockerCode.SYNTHESIS_SCORE_TOO_LOW.value)
            rule_hits.append(
                f"penalized_confidence={penalized_score:.4f} < {self.HOLD_MIN_SCORE}"
            )

        # ── Verdict determination ──
        if blockers or penalty_result.hard_veto:
            verdict = L12Verdict.NO_TRADE
            verdict_status = L12Status.FAIL
            continuation_allowed = False
            next_targets: list[str] = []
            notes.append("Hard blocker or gate FAIL detected -> NO_TRADE")
        elif (
            penalized_score >= self.EXECUTE_MIN_SCORE
            and penalty_result.soft_fail_count == 0
        ):
            verdict = L12Verdict.EXECUTE
            verdict_status = L12Status.WARN if warnings else L12Status.PASS
            continuation_allowed = True
            next_targets = ["PHASE_6"]
            notes.append(
                f"Penalized confidence={penalized_score:.4f} >= {self.EXECUTE_MIN_SCORE}, "
                f"no soft fails -> EXECUTE"
            )
        elif penalized_score >= self.EXECUTE_REDUCED_MIN_SCORE:
            verdict = L12Verdict.EXECUTE_REDUCED_RISK
            verdict_status = L12Status.WARN
            continuation_allowed = True
            next_targets = ["PHASE_6"]
            notes.append(
                f"Penalized confidence={penalized_score:.4f} >= {self.EXECUTE_REDUCED_MIN_SCORE}, "
                f"soft_fails={penalty_result.soft_fail_count}, "
                f"sizing_multiplier={sizing_multiplier:.4f} -> EXECUTE_REDUCED_RISK"
            )
        elif penalized_score >= self.HOLD_MIN_SCORE:
            verdict = L12Verdict.HOLD
            verdict_status = L12Status.WARN
            continuation_allowed = True
            next_targets = ["PHASE_6"]
            notes.append(
                f"Penalized confidence={penalized_score:.4f} in HOLD band -> HOLD"
            )
        else:
            verdict = L12Verdict.NO_TRADE
            verdict_status = L12Status.FAIL
            continuation_allowed = False
            next_targets = []
            notes.append(
                f"Penalized confidence={penalized_score:.4f} < {self.HOLD_MIN_SCORE} -> NO_TRADE"
            )

        audit: dict[str, Any] = {
            "rule_hits": rule_hits,
            "blocker_triggered": bool(blockers),
            "notes": notes,
            "l2_evidence": {
                "status": payload.l2_status,
                "evidence_score": payload.l2_evidence_score,
                "confidence_penalty": payload.l2_confidence_penalty,
                "hard_stop": payload.l2_hard_stop,
                "advisory_continuation": payload.l2_advisory_continuation,
                "hard_blockers": list(payload.l2_hard_blockers),
                "soft_blockers": list(payload.l2_soft_blockers),
                "primary_conflict": payload.l2_primary_conflict,
            },
            "l9_evidence": {
                "status": payload.l9_status,
                "evidence_score": payload.l9_evidence_score,
                "confidence_penalty": payload.l9_confidence_penalty,
                "hard_stop": payload.l9_hard_stop,
                "advisory_continuation": payload.l9_advisory_continuation,
                "hard_blockers": list(payload.l9_hard_blockers),
                "soft_blockers": list(payload.l9_soft_blockers),
                "source_builder_state": payload.l9_source_builder_state,
            },
            "penalty_engine": {
                "raw_confidence": raw_confidence,
                "penalized_confidence": penalized_score,
                "sizing_multiplier": sizing_multiplier,
                "soft_fail_count": penalty_result.soft_fail_count,
                "soft_warn_count": penalty_result.soft_warn_count,
                "penalty_breakdown": penalty_result.penalty_breakdown,
            },
        }

        return L12EvaluationResult(
            layer="L12",
            layer_version=self.VERSION,
            timestamp=payload.timestamp,
            input_ref=payload.input_ref,
            verdict=verdict.value,
            verdict_status=verdict_status.value,
            continuation_allowed=continuation_allowed,
            next_legal_targets=next_targets,
            score_numeric=penalized_score,
            gate_summary=gate_summary,
            blocker_codes=list(dict.fromkeys(blockers)),
            warning_codes=list(dict.fromkeys(warnings)),
            audit=audit,
            raw_confidence=raw_confidence,
            penalized_confidence=penalized_score,
            sizing_multiplier=sizing_multiplier,
            soft_fail_count=penalty_result.soft_fail_count,
            soft_warn_count=penalty_result.soft_warn_count,
            penalty_breakdown=penalty_result.penalty_breakdown,
        )


def build_l12_input_from_upstream(upstream_result: dict[str, Any]) -> L12Input:
    """Build L12Input from the EndToEndPhase4Result dict."""
    input_ref = str(upstream_result.get("input_ref", "")).strip()
    timestamp = str(upstream_result.get("timestamp", "")).strip()

    continuation_allowed = bool(upstream_result.get("continuation_allowed", False))
    next_targets = [str(t) for t in upstream_result.get("next_legal_targets", [])]

    # Extract phase statuses from nested structure
    # Phase4 E2E: upstream_result (Phase3 E2E) → upstream_result (FSE) → upstream_result (FS)
    phase4_result = upstream_result.get("phase4_result", {})
    phase3_e2e = upstream_result.get("upstream_result", {})  # Phase3 E2E
    fse = phase3_e2e.get("upstream_result", {})  # Foundation+Scoring+Enrichment
    foundation_scoring = fse.get("upstream_result", {})  # Foundation+Scoring

    # Phase results from foundation/scoring
    phase_results = foundation_scoring.get("phase_results", {})
    phase1_result = phase_results.get("PHASE_1", {})
    phase2_result = phase_results.get("PHASE_2", {})

    # Phase 2.5 enrichment
    phase25 = fse.get("phase25_result", {})

    # Phase 3
    phase3_result = phase3_e2e.get("phase3_result", {})
    phase1_layers = phase1_result.get("layer_results", {}) if isinstance(phase1_result, dict) else {}
    l2_layer = phase1_layers.get("L2", {}) if isinstance(phase1_layers, dict) else {}
    if not isinstance(l2_layer, dict):
        l2_layer = {}
    if not l2_layer and isinstance(phase1_result, dict):
        fallback_l2 = phase1_result.get("l2", {})
        if isinstance(fallback_l2, dict):
            l2_layer = fallback_l2
    phase3_layers = phase3_result.get("layer_results", {}) if isinstance(phase3_result, dict) else {}
    l9_layer = phase3_layers.get("L9", {}) if isinstance(phase3_layers, dict) else {}
    if not isinstance(l9_layer, dict):
        l9_layer = {}

    # Derive statuses
    foundation_status = str(phase1_result.get("chain_status", "FAIL")).upper()
    scoring_status = str(phase2_result.get("chain_status", "FAIL")).upper()
    enrichment_status = str(phase25.get("phase_status", "WARN")).upper()
    structure_status = str(phase3_result.get("chain_status", "FAIL")).upper()
    risk_chain_status = str(phase4_result.get("chain_status", "FAIL")).upper()

    # Derive layer-level statuses for specific gates
    phase3_summary = phase3_result.get("summary_status", {})
    phase4_summary = phase4_result.get("summary_status", {})

    integrity_status = str(phase3_summary.get("L8", "FAIL")).upper()
    probability_status = str(phase3_summary.get("L7", "FAIL")).upper()
    firewall_status = str(phase4_summary.get("L6", "FAIL")).upper()

    # Collect scores
    layer_scores: dict[str, float] = {}
    for phase_name in ("PHASE_1", "PHASE_2"):
        phase = phase_results.get(phase_name, {})
        for layer_name, layer in phase.get("layer_results", {}).items():
            if not isinstance(layer, dict):
                continue
            if layer_name == "L2":
                l2_evidence_score = layer.get("evidence_score")
                if isinstance(l2_evidence_score, (int, float)):
                    layer_scores[layer_name] = float(l2_evidence_score)
                    continue
            val = layer.get("score_numeric")
            if isinstance(val, (int, float)):
                layer_scores[layer_name] = float(val)
    for layer_name, layer in phase3_result.get("layer_results", {}).items():
        if not isinstance(layer, dict):
            continue
        if layer_name == "L9":
            l9_evidence_score = layer.get("evidence_score")
            if isinstance(l9_evidence_score, (int, float)):
                layer_scores[layer_name] = float(l9_evidence_score)
                continue
        val = layer.get("score_numeric")
        if isinstance(val, (int, float)):
            layer_scores[layer_name] = float(val)
    for layer_name, layer in phase4_result.get("layer_results", {}).items():
        val = layer.get("score_numeric")
        if isinstance(val, (int, float)):
            layer_scores[layer_name] = float(val)

    # Synthesis score = mean of available layer scores
    scores = [v for v in layer_scores.values() if isinstance(v, (int, float))]
    synthesis_score = sum(scores) / len(scores) if scores else 0.0

    l2_evidence_score = l2_layer.get("evidence_score")
    if not isinstance(l2_evidence_score, (int, float)):
        l2_evidence_score = l2_layer.get("features", {}).get("evidence_score") if isinstance(l2_layer.get("features"), dict) else None

    l2_confidence_penalty = l2_layer.get("confidence_penalty")
    if not isinstance(l2_confidence_penalty, (int, float)):
        l2_confidence_penalty = l2_layer.get("features", {}).get("confidence_penalty") if isinstance(l2_layer.get("features"), dict) else 0.0

    l2_hard_blockers = l2_layer.get("hard_blockers", l2_layer.get("blocker_codes", []))
    if not isinstance(l2_hard_blockers, list):
        l2_hard_blockers = []
    l2_soft_blockers = l2_layer.get("soft_blockers", l2_layer.get("warning_codes", []))
    if not isinstance(l2_soft_blockers, list):
        l2_soft_blockers = []
    l2_primary_conflict = None
    l2_mta = l2_layer.get("mta_diagnostics", {})
    if isinstance(l2_mta, dict):
        primary = l2_mta.get("primary_conflict")
        if isinstance(primary, str) and primary:
            l2_primary_conflict = primary

    l9_evidence_score = l9_layer.get("evidence_score")
    if not isinstance(l9_evidence_score, (int, float)):
        l9_evidence_score = l9_layer.get("features", {}).get("evidence_score") if isinstance(l9_layer.get("features"), dict) else None

    l9_confidence_penalty = l9_layer.get("confidence_penalty")
    if not isinstance(l9_confidence_penalty, (int, float)):
        l9_confidence_penalty = l9_layer.get("features", {}).get("confidence_penalty") if isinstance(l9_layer.get("features"), dict) else 0.0

    l9_hard_blockers = l9_layer.get("hard_blockers", l9_layer.get("blocker_codes", []))
    if not isinstance(l9_hard_blockers, list):
        l9_hard_blockers = []
    l9_soft_blockers = l9_layer.get("soft_blockers", l9_layer.get("warning_codes", []))
    if not isinstance(l9_soft_blockers, list):
        l9_soft_blockers = []
    l9_source_builder_state = None
    l9_structure = l9_layer.get("structure_diagnostics", {})
    if isinstance(l9_structure, dict):
        builder_state = l9_structure.get("source_builder_state")
        if isinstance(builder_state, str) and builder_state:
            l9_source_builder_state = builder_state

    return L12Input(
        input_ref=input_ref,
        timestamp=timestamp,
        upstream_continuation_allowed=continuation_allowed,
        upstream_next_legal_targets=next_targets,
        foundation_status=foundation_status,
        scoring_status=scoring_status,
        enrichment_status=enrichment_status,
        structure_status=structure_status,
        risk_chain_status=risk_chain_status,
        layer_scores=layer_scores,
        l2_status=str(l2_layer.get("status", "FAIL")).upper(),
        l2_evidence_score=float(l2_evidence_score) if isinstance(l2_evidence_score, (int, float)) else None,
        l2_confidence_penalty=float(l2_confidence_penalty) if isinstance(l2_confidence_penalty, (int, float)) else 0.0,
        l2_hard_stop=bool(l2_layer.get("hard_stop", False)),
        l2_advisory_continuation=bool(l2_layer.get("advisory_continuation", False)),
        l2_hard_blockers=[str(x) for x in l2_hard_blockers],
        l2_soft_blockers=[str(x) for x in l2_soft_blockers],
        l2_primary_conflict=l2_primary_conflict,
        l9_status=str(l9_layer.get("status", "FAIL")).upper(),
        l9_evidence_score=float(l9_evidence_score) if isinstance(l9_evidence_score, (int, float)) else None,
        l9_confidence_penalty=float(l9_confidence_penalty) if isinstance(l9_confidence_penalty, (int, float)) else 0.0,
        l9_hard_stop=bool(l9_layer.get("hard_stop", False)),
        l9_advisory_continuation=bool(l9_layer.get("advisory_continuation", False)),
        l9_hard_blockers=[str(x) for x in l9_hard_blockers],
        l9_soft_blockers=[str(x) for x in l9_soft_blockers],
        l9_source_builder_state=l9_source_builder_state,
        phase1_available=bool(phase1_result),
        phase2_available=bool(phase2_result),
        phase3_available=bool(phase3_result),
        phase4_available=bool(phase4_result),
        synthesis_score=synthesis_score,
        integrity_status=integrity_status,
        probability_status=probability_status,
        firewall_status=firewall_status,
        governance_status="PASS",
    )


if __name__ == "__main__":
    evaluator = L12RouterEvaluator()
    examples = [
        {
            "label": "All PASS, high score",
            "input": L12Input(
                input_ref="EURUSD_H1_run_1000",
                timestamp="2026-04-02T10:00:00+07:00",
                upstream_continuation_allowed=True,
                upstream_next_legal_targets=["PHASE_5"],
                foundation_status="PASS",
                scoring_status="PASS",
                enrichment_status="PASS",
                structure_status="PASS",
                risk_chain_status="PASS",
                phase1_available=True,
                phase2_available=True,
                phase3_available=True,
                phase4_available=True,
                synthesis_score=0.82,
                integrity_status="PASS",
                probability_status="PASS",
                firewall_status="PASS",
                governance_status="PASS",
            ),
        },
        {
            "label": "Foundation FAIL -> NO_TRADE",
            "input": L12Input(
                input_ref="EURUSD_H1_run_1001",
                timestamp="2026-04-02T10:05:00+07:00",
                upstream_continuation_allowed=True,
                upstream_next_legal_targets=["PHASE_5"],
                foundation_status="FAIL",
                scoring_status="PASS",
                enrichment_status="WARN",
                structure_status="PASS",
                risk_chain_status="PASS",
                phase1_available=True,
                phase2_available=True,
                phase3_available=True,
                phase4_available=True,
                synthesis_score=0.55,
                integrity_status="PASS",
                probability_status="PASS",
                firewall_status="PASS",
                governance_status="PASS",
            ),
        },
        {
            "label": "WARN gates, medium score -> HOLD",
            "input": L12Input(
                input_ref="EURUSD_H1_run_1002",
                timestamp="2026-04-02T10:10:00+07:00",
                upstream_continuation_allowed=True,
                upstream_next_legal_targets=["PHASE_5"],
                foundation_status="WARN",
                scoring_status="WARN",
                enrichment_status="WARN",
                structure_status="WARN",
                risk_chain_status="PASS",
                phase1_available=True,
                phase2_available=True,
                phase3_available=True,
                phase4_available=True,
                synthesis_score=0.55,
                integrity_status="WARN",
                probability_status="WARN",
                firewall_status="PASS",
                governance_status="PASS",
            ),
        },
    ]
    import json

    for ex in examples:
        result = evaluator.evaluate(ex["input"])
        print(f"\n{'=' * 60}")
        print(f"[{ex['label']}]")
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
