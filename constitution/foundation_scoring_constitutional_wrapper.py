"""
Foundation + Scoring Constitutional Wrapper
============================================

Runs:
  Phase 1 (L1 → L2 → L3) → Bridge (Phase1 → Phase2) → Phase 2 (L4 → L5)

This wrapper preserves halt-safe semantics across the multi-phase transition.
Analysis-only module. No execution authority.

Zone: constitution/ — pipeline governance, no execution side-effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from constitution.phase1_chain_adapter import (
    Phase1ChainAdapter,
    build_phase1_payloads_from_dict,
)
from constitution.phase1_to_phase2_bridge_adapter import Phase1ToPhase2BridgeAdapter
from constitution.phase2_chain_adapter import Phase2ChainAdapter


@dataclass(frozen=True)
class FoundationScoringWrapperResult:
    wrapper: str
    wrapper_version: str
    input_ref: str
    timestamp: str
    halted: bool
    halted_at: str | None
    continuation_allowed: bool
    next_legal_targets: list[str]
    wrapper_status: str
    phase_status: dict[str, str]
    phase_results: dict[str, dict[str, Any]]
    bridge_result: dict[str, Any]
    audit: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "wrapper": self.wrapper,
            "wrapper_version": self.wrapper_version,
            "input_ref": self.input_ref,
            "timestamp": self.timestamp,
            "halted": self.halted,
            "halted_at": self.halted_at,
            "continuation_allowed": self.continuation_allowed,
            "next_legal_targets": self.next_legal_targets,
            "wrapper_status": self.wrapper_status,
            "phase_status": self.phase_status,
            "phase_results": self.phase_results,
            "bridge_result": self.bridge_result,
            "audit": self.audit,
        }


class FoundationScoringConstitutionalWrapper:
    """Halt-safe wrapper: Phase 1 → Bridge → Phase 2."""

    VERSION = "1.0.0"

    def __init__(
        self,
        phase1_adapter: Phase1ChainAdapter | None = None,
        bridge_adapter: Phase1ToPhase2BridgeAdapter | None = None,
        phase2_adapter: Phase2ChainAdapter | None = None,
    ) -> None:
        self.phase1_adapter = phase1_adapter or Phase1ChainAdapter(
            l1_callable=lambda s: {},
            l2_callable=lambda s: {},
            l3_callable=lambda s: {},
        )
        self.bridge_adapter = bridge_adapter or Phase1ToPhase2BridgeAdapter()
        self.phase2_adapter = phase2_adapter or Phase2ChainAdapter()

    @staticmethod
    def _extract_meta(payload: dict[str, Any]) -> tuple[str, str]:
        refs: list[str] = []
        timestamps: list[str] = []
        for layer in ("L1", "L2", "L3"):
            lp = payload.get(layer, {})
            r = str(lp.get("input_ref", "")).strip()
            t = str(lp.get("timestamp", "")).strip()
            if r:
                refs.append(r)
            if t:
                timestamps.append(t)
        if not refs or not timestamps:
            raise ValueError(
                "Wrapper requires at least one non-empty input_ref and "
                "timestamp in Phase 1 payload."
            )
        return refs[0], timestamps[0]

    def run(self, payload: dict[str, Any]) -> FoundationScoringWrapperResult:
        input_ref, timestamp = self._extract_meta(payload)
        l1_payload, l2_payload, l3_payload = build_phase1_payloads_from_dict(payload)

        audit_steps: list[str] = ["Phase 1 start"]
        phase1_result = self.phase1_adapter.run(l1_payload, l2_payload, l3_payload)
        phase_status: dict[str, str] = {"PHASE_1": phase1_result.chain_status}
        phase_results: dict[str, dict[str, Any]] = {"PHASE_1": phase1_result.to_dict()}
        audit_steps.append(f"Phase 1 completed with status={phase1_result.chain_status}")

        if phase1_result.halted or not phase1_result.continuation_allowed:
            audit_steps.append("Wrapper halted at Phase 1")
            return FoundationScoringWrapperResult(
                wrapper="FOUNDATION_SCORING_WRAPPER",
                wrapper_version=self.VERSION,
                input_ref=input_ref,
                timestamp=timestamp,
                halted=True,
                halted_at="PHASE_1",
                continuation_allowed=False,
                next_legal_targets=[],
                wrapper_status="FAIL",
                phase_status=phase_status,
                phase_results=phase_results,
                bridge_result={},
                audit={
                    "halt_safe": True,
                    "steps": audit_steps,
                    "reason": "Phase 1 not continuable",
                },
            )

        audit_steps.append("Bridge start")
        bridge_result = self.bridge_adapter.build(phase1_result.to_dict())
        audit_steps.append(f"Bridge completed with status={bridge_result.bridge_status}")

        if not bridge_result.bridge_allowed:
            audit_steps.append("Wrapper halted at BRIDGE")
            return FoundationScoringWrapperResult(
                wrapper="FOUNDATION_SCORING_WRAPPER",
                wrapper_version=self.VERSION,
                input_ref=input_ref,
                timestamp=timestamp,
                halted=True,
                halted_at="BRIDGE",
                continuation_allowed=False,
                next_legal_targets=[],
                wrapper_status="FAIL",
                phase_status=phase_status,
                phase_results=phase_results,
                bridge_result=bridge_result.to_dict(),
                audit={
                    "halt_safe": True,
                    "steps": audit_steps,
                    "reason": "Bridge not allowed",
                },
            )

        audit_steps.append("Phase 2 start")
        phase2_result = self.phase2_adapter.run(
            bridge_result.l4_payload, bridge_result.l5_payload,
        )
        phase_status["PHASE_2"] = phase2_result.chain_status
        phase_results["PHASE_2"] = phase2_result.to_dict()
        audit_steps.append(f"Phase 2 completed with status={phase2_result.chain_status}")

        if phase2_result.halted or not phase2_result.continuation_allowed:
            audit_steps.append("Wrapper halted at Phase 2")
            return FoundationScoringWrapperResult(
                wrapper="FOUNDATION_SCORING_WRAPPER",
                wrapper_version=self.VERSION,
                input_ref=input_ref,
                timestamp=timestamp,
                halted=True,
                halted_at="PHASE_2",
                continuation_allowed=False,
                next_legal_targets=[],
                wrapper_status="FAIL",
                phase_status=phase_status,
                phase_results=phase_results,
                bridge_result=bridge_result.to_dict(),
                audit={
                    "halt_safe": True,
                    "steps": audit_steps,
                    "reason": "Phase 2 not continuable",
                },
            )

        wrapper_status = "PASS"
        if any(s == "WARN" for s in phase_status.values()):
            wrapper_status = "WARN"
        if bridge_result.bridge_status == "WARN":
            wrapper_status = "WARN"

        audit_steps.append("Foundation + Scoring wrapper completed")
        return FoundationScoringWrapperResult(
            wrapper="FOUNDATION_SCORING_WRAPPER",
            wrapper_version=self.VERSION,
            input_ref=input_ref,
            timestamp=timestamp,
            halted=False,
            halted_at=None,
            continuation_allowed=True,
            next_legal_targets=["PHASE_2_5"],
            wrapper_status=wrapper_status,
            phase_status=phase_status,
            phase_results=phase_results,
            bridge_result=bridge_result.to_dict(),
            audit={
                "halt_safe": True,
                "steps": audit_steps,
                "reason": "Foundation + Scoring completed legally",
            },
        )
