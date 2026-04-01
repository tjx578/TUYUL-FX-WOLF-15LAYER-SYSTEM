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
from enum import Enum  # noqa: E402
from typing import Any  # noqa: E402


class L12Status(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class L12Verdict(str, Enum):
    EXECUTE = "EXECUTE"
    HOLD = "HOLD"
    NO_TRADE = "NO_TRADE"


class L12BlockerCode(str, Enum):
    UPSTREAM_NOT_CONTINUABLE = "UPSTREAM_NOT_CONTINUABLE"
    UPSTREAM_TARGET_NOT_PHASE5 = "UPSTREAM_TARGET_NOT_PHASE5"
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


class L12GateName(str, Enum):
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
        }


class L12RouterEvaluator:
    VERSION = "1.0.0"

    # Synthesis score thresholds
    EXECUTE_MIN_SCORE = 0.65
    HOLD_MIN_SCORE = 0.40

    # Hard gates: FAIL on any of these -> NO_TRADE
    HARD_GATES = {
        L12GateName.FOUNDATION_OK,
        L12GateName.STRUCTURE_OK,
        L12GateName.RISK_CHAIN_OK,
        L12GateName.FIREWALL_OK,
    }

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

        gate_blocker_map = {
            L12GateName.FOUNDATION_OK: L12BlockerCode.FOUNDATION_FAIL,
            L12GateName.SCORING_OK: L12BlockerCode.SCORING_FAIL,
            L12GateName.STRUCTURE_OK: L12BlockerCode.STRUCTURE_FAIL,
            L12GateName.RISK_CHAIN_OK: L12BlockerCode.RISK_CHAIN_FAIL,
            L12GateName.INTEGRITY_OK: L12BlockerCode.INTEGRITY_FAIL,
            L12GateName.PROBABILITY_OK: L12BlockerCode.PROBABILITY_FAIL,
            L12GateName.FIREWALL_OK: L12BlockerCode.FIREWALL_FAIL,
            L12GateName.GOVERNANCE_OK: L12BlockerCode.GOVERNANCE_FAIL,
        }

        for gate_name, gate_status in gate_summary.items():
            gate_enum = L12GateName(gate_name)
            if gate_status == "FAIL":
                blocker_code = gate_blocker_map.get(gate_enum)
                if blocker_code:
                    blockers.append(blocker_code.value)
                    rule_hits.append(f"{gate_name}=FAIL -> blocker")
                elif gate_enum == L12GateName.ENRICHMENT_OK:
                    # Enrichment FAIL is not a hard blocker per spec
                    warnings.append("ENRICHMENT_DEGRADED")
                    rule_hits.append(f"{gate_name}=FAIL -> warning (enrichment is advisory)")
            elif gate_status == "WARN":
                warnings.append(f"{gate_name}_WARN")
                rule_hits.append(f"{gate_name}=WARN")

        # ── Hard gate check ──
        has_hard_gate_fail = any(
            gate_summary.get(g.value) == "FAIL"
            for g in self.HARD_GATES
        )

        # ── Synthesis score check ──
        synthesis_score = round(payload.synthesis_score, 4)
        if synthesis_score < self.HOLD_MIN_SCORE and not blockers:
            blockers.append(L12BlockerCode.SYNTHESIS_SCORE_TOO_LOW.value)
            rule_hits.append(f"synthesis_score={synthesis_score} < {self.HOLD_MIN_SCORE}")

        # ── Verdict determination ──
        if blockers or has_hard_gate_fail:
            verdict = L12Verdict.NO_TRADE
            verdict_status = L12Status.FAIL
            continuation_allowed = False
            next_targets: list[str] = []
            notes.append("Hard blocker or gate FAIL detected -> NO_TRADE")
        elif synthesis_score >= self.EXECUTE_MIN_SCORE and not any(
            gate_summary.get(g.value) == "FAIL"
            for g in L12GateName
            if g != L12GateName.ENRICHMENT_OK  # enrichment FAIL is non-fatal
        ):
            verdict = L12Verdict.EXECUTE
            verdict_status = L12Status.WARN if warnings else L12Status.PASS
            continuation_allowed = True
            next_targets = ["PHASE_6"]
            notes.append("All critical gates legal, synthesis high -> EXECUTE")
        else:
            verdict = L12Verdict.HOLD
            verdict_status = L12Status.WARN
            continuation_allowed = True
            next_targets = ["PHASE_6"]
            notes.append("No hard blockers but confluence insufficient -> HOLD")

        audit = {
            "rule_hits": rule_hits,
            "blocker_triggered": bool(blockers),
            "notes": notes,
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
            score_numeric=synthesis_score,
            gate_summary=gate_summary,
            blocker_codes=list(dict.fromkeys(blockers)),
            warning_codes=list(dict.fromkeys(warnings)),
            audit=audit,
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
            val = layer.get("score_numeric")
            if isinstance(val, (int, float)):
                layer_scores[layer_name] = float(val)
    for layer_name, layer in phase3_result.get("layer_results", {}).items():
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
