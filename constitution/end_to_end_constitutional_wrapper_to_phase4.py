from __future__ import annotations

"""
End-to-end constitutional wrapper up to Phase 4

Runs:
Foundation -> Scoring -> Enrichment -> Bridge -> Phase 3 -> Bridge -> Phase 4

This wrapper preserves halt-safe semantics for fatal phases and
non-fatal semantics for Phase 2.5 enrichment.
Analysis-only module. No execution authority.
"""

from dataclasses import dataclass
from typing import Any

from constitution.end_to_end_constitutional_wrapper_to_phase3 import (
    EndToEndConstitutionalWrapperToPhase3,
)
from constitution.end_to_end_phase3_to_phase4_bridge_adapter import (
    EndToEndPhase3ToPhase4BridgeAdapter,
)
from constitution.phase4_chain_adapter import Phase4ChainAdapter


@dataclass(frozen=True)
class EndToEndPhase4Result:
    wrapper: str
    wrapper_version: str
    input_ref: str
    timestamp: str
    halted: bool
    halted_at: str | None
    continuation_allowed: bool
    next_legal_targets: list[str]
    wrapper_status: str
    upstream_result: dict[str, Any]
    bridge_result: dict[str, Any]
    phase4_result: dict[str, Any]
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
            "upstream_result": self.upstream_result,
            "bridge_result": self.bridge_result,
            "phase4_result": self.phase4_result,
            "audit": self.audit,
        }


class EndToEndConstitutionalWrapperToPhase4:
    VERSION = "1.0.0"

    def __init__(
        self,
        upstream_wrapper: EndToEndConstitutionalWrapperToPhase3 | None = None,
        bridge_adapter: EndToEndPhase3ToPhase4BridgeAdapter | None = None,
        phase4_adapter: Phase4ChainAdapter | None = None,
    ) -> None:
        self.upstream_wrapper = upstream_wrapper or EndToEndConstitutionalWrapperToPhase3()
        self.bridge_adapter = bridge_adapter or EndToEndPhase3ToPhase4BridgeAdapter()
        self.phase4_adapter = phase4_adapter or Phase4ChainAdapter()

    @staticmethod
    def _extract_meta(payload: dict[str, Any]) -> tuple[str, str]:
        refs = []
        timestamps = []
        for layer in ("L1", "L2", "L3"):
            layer_payload = payload.get(layer, {})
            refs.append(str(layer_payload.get("input_ref", "")).strip())
            timestamps.append(str(layer_payload.get("timestamp", "")).strip())
        refs = [r for r in refs if r]
        timestamps = [t for t in timestamps if t]
        if not refs or not timestamps:
            raise ValueError("End-to-end wrapper requires at least one non-empty input_ref and timestamp in Phase 1 payload.")
        return refs[0], timestamps[0]

    def run(self, payload: dict[str, Any]) -> EndToEndPhase4Result:
        input_ref, timestamp = self._extract_meta(payload)
        audit_steps = ["Upstream end-to-end to Phase 3 start"]

        upstream = self.upstream_wrapper.run(payload)
        audit_steps.append(f"Upstream Phase 3 wrapper completed with status={upstream.wrapper_status}")

        if upstream.halted or not upstream.continuation_allowed:
            audit_steps.append("End-to-end Phase 4 wrapper halted at UPSTREAM")
            return EndToEndPhase4Result(
                wrapper="END_TO_END_TO_PHASE4",
                wrapper_version=self.VERSION,
                input_ref=input_ref,
                timestamp=timestamp,
                halted=True,
                halted_at="UPSTREAM",
                continuation_allowed=False,
                next_legal_targets=[],
                wrapper_status="FAIL",
                upstream_result=upstream.to_dict(),
                bridge_result={},
                phase4_result={},
                audit={
                    "halt_safe": True,
                    "steps": audit_steps,
                    "reason": "Upstream wrapper to Phase 3 not continuable",
                },
            )

        audit_steps.append("Bridge to Phase 4 start")
        bridge = self.bridge_adapter.build(upstream.to_dict())
        audit_steps.append(f"Bridge to Phase 4 completed with status={bridge.bridge_status}")

        if not bridge.bridge_allowed:
            audit_steps.append("End-to-end Phase 4 wrapper halted at BRIDGE")
            return EndToEndPhase4Result(
                wrapper="END_TO_END_TO_PHASE4",
                wrapper_version=self.VERSION,
                input_ref=input_ref,
                timestamp=timestamp,
                halted=True,
                halted_at="BRIDGE",
                continuation_allowed=False,
                next_legal_targets=[],
                wrapper_status="FAIL",
                upstream_result=upstream.to_dict(),
                bridge_result=bridge.to_dict(),
                phase4_result={},
                audit={
                    "halt_safe": True,
                    "steps": audit_steps,
                    "reason": "Bridge to Phase 4 not allowed",
                },
            )

        audit_steps.append("Phase 4 start")
        phase4 = self.phase4_adapter.run(bridge.l11_payload, bridge.l6_payload, bridge.l10_payload)
        audit_steps.append(f"Phase 4 completed with status={phase4.chain_status}")

        if phase4.halted or not phase4.continuation_allowed:
            audit_steps.append("End-to-end Phase 4 wrapper halted at PHASE_4")
            return EndToEndPhase4Result(
                wrapper="END_TO_END_TO_PHASE4",
                wrapper_version=self.VERSION,
                input_ref=input_ref,
                timestamp=timestamp,
                halted=True,
                halted_at="PHASE_4",
                continuation_allowed=False,
                next_legal_targets=[],
                wrapper_status="FAIL",
                upstream_result=upstream.to_dict(),
                bridge_result=bridge.to_dict(),
                phase4_result=phase4.to_dict(),
                audit={
                    "halt_safe": True,
                    "steps": audit_steps,
                    "reason": "Phase 4 not continuable",
                },
            )

        wrapper_status = "PASS"
        if upstream.wrapper_status == "WARN" or bridge.bridge_status == "WARN" or phase4.chain_status == "WARN":
            wrapper_status = "WARN"

        audit_steps.append("End-to-end wrapper to Phase 4 completed legally")
        return EndToEndPhase4Result(
            wrapper="END_TO_END_TO_PHASE4",
            wrapper_version=self.VERSION,
            input_ref=input_ref,
            timestamp=timestamp,
            halted=False,
            halted_at=None,
            continuation_allowed=True,
            next_legal_targets=["PHASE_5"],
            wrapper_status=wrapper_status,
            upstream_result=upstream.to_dict(),
            bridge_result=bridge.to_dict(),
            phase4_result=phase4.to_dict(),
            audit={
                "halt_safe": True,
                "steps": audit_steps,
                "reason": "Foundation -> Scoring -> Enrichment -> Bridge -> Phase 3 -> Bridge -> Phase 4 completed legally",
            },
        )
