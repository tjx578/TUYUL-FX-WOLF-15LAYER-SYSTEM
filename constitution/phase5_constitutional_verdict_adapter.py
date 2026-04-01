from __future__ import annotations

"""
Phase 5 Constitutional Verdict Adapter

Bridges the output of EndToEndConstitutionalWrapperToPhase4 into L12 verdict space.
Builds a synthesis payload from upstream phases and delegates to L12RouterEvaluator.

L12 is the SOLE constitutional verdict authority. This adapter ensures that:
- All upstream phase results are available
- Synthesis payload is correctly assembled
- L12 receives a well-formed input
- The verdict is final and cannot be overridden downstream except by governance/sovereignty

Analysis-only module. No execution authority.
"""

from dataclasses import dataclass  # noqa: E402
from typing import Any  # noqa: E402

from constitution.l12_router_evaluator import (  # noqa: E402
    L12EvaluationResult,
    L12RouterEvaluator,
    build_l12_input_from_upstream,
)


@dataclass(frozen=True)
class Phase5Result:
    phase: str
    phase_version: str
    input_ref: str
    timestamp: str
    phase_status: str
    continuation_allowed: bool
    next_legal_targets: list[str]
    l12_result: dict[str, Any]
    synthesis_payload: dict[str, Any]
    audit: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "phase_version": self.phase_version,
            "input_ref": self.input_ref,
            "timestamp": self.timestamp,
            "phase_status": self.phase_status,
            "continuation_allowed": self.continuation_allowed,
            "next_legal_targets": self.next_legal_targets,
            "l12_result": self.l12_result,
            "synthesis_payload": self.synthesis_payload,
            "audit": self.audit,
        }


class Phase5ConstitutionalVerdictAdapter:
    VERSION = "1.0.0"

    def __init__(
        self,
        l12_evaluator: L12RouterEvaluator | None = None,
    ) -> None:
        self.l12_evaluator = l12_evaluator or L12RouterEvaluator()

    @staticmethod
    def _extract_meta(upstream_result: dict[str, Any]) -> tuple[str, str]:
        input_ref = str(upstream_result.get("input_ref", "")).strip()
        timestamp = str(upstream_result.get("timestamp", "")).strip()
        if not input_ref or not timestamp:
            raise ValueError("Phase 5 adapter requires non-empty input_ref and timestamp from upstream.")
        return input_ref, timestamp

    @staticmethod
    def _build_synthesis_payload(upstream_result: dict[str, Any]) -> dict[str, Any]:
        """Build synthesis payload summarizing all upstream phase statuses."""
        phase4_result = upstream_result.get("phase4_result", {})
        # Phase4 E2E: upstream_result (Phase3 E2E) → upstream_result (FSE) → upstream_result (FS)
        phase3_e2e = upstream_result.get("upstream_result", {})
        fse = phase3_e2e.get("upstream_result", {})
        foundation_scoring = fse.get("upstream_result", {})

        phase_results = foundation_scoring.get("phase_results", {})
        phase1_result = phase_results.get("PHASE_1", {})
        phase2_result = phase_results.get("PHASE_2", {})
        phase25 = fse.get("phase25_result", {})
        phase3_result = phase3_e2e.get("phase3_result", {})

        return {
            "foundation_status": str(phase1_result.get("chain_status", "FAIL")).upper(),
            "scoring_status": str(phase2_result.get("chain_status", "FAIL")).upper(),
            "enrichment_status": str(phase25.get("phase_status", "WARN")).upper(),
            "structure_status": str(phase3_result.get("chain_status", "FAIL")).upper(),
            "risk_chain_status": str(phase4_result.get("chain_status", "FAIL")).upper(),
        }

    def run(self, upstream_result: dict[str, Any]) -> Phase5Result:
        input_ref, timestamp = self._extract_meta(upstream_result)
        audit_steps = ["Phase 5 synthesis start"]

        # Build synthesis payload
        synthesis_payload = self._build_synthesis_payload(upstream_result)
        audit_steps.append(f"Synthesis payload assembled: {synthesis_payload}")

        # Build L12 input from upstream
        l12_input = build_l12_input_from_upstream(upstream_result)
        audit_steps.append("L12 input built from upstream")

        # Evaluate L12
        l12_result: L12EvaluationResult = self.l12_evaluator.evaluate(l12_input)
        l12_dict = l12_result.to_dict()
        audit_steps.append(
            f"L12 verdict={l12_result.verdict} status={l12_result.verdict_status}"
        )

        phase_status = l12_result.verdict_status
        continuation_allowed = l12_result.continuation_allowed
        next_targets = list(l12_result.next_legal_targets)

        return Phase5Result(
            phase="PHASE_5_VERDICT",
            phase_version=self.VERSION,
            input_ref=input_ref,
            timestamp=timestamp,
            phase_status=phase_status,
            continuation_allowed=continuation_allowed,
            next_legal_targets=next_targets,
            l12_result=l12_dict,
            synthesis_payload=synthesis_payload,
            audit={
                "steps": audit_steps,
                "reason": "Phase 5 verdict adapter completed",
            },
        )
