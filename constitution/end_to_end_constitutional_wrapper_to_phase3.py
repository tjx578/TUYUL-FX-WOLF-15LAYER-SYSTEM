from __future__ import annotations

"""
End-to-end constitutional wrapper up to Phase 3

Runs:
Foundation -> Scoring -> Enrichment -> Bridge -> Phase 3

This wrapper preserves halt-safe semantics for fatal phases and
non-fatal semantics for Phase 2.5 enrichment.
Analysis-only module. No execution authority.

Zone: constitution/ — pipeline governance, no execution side-effects.
"""

from dataclasses import dataclass  # noqa: E402
from typing import Any  # noqa: E402

from constitution.foundation_scoring_enrichment_constitutional_wrapper import (  # noqa: E402
    FoundationScoringEnrichmentConstitutionalWrapper,
)
from constitution.foundation_scoring_enrichment_to_phase3_bridge_adapter import (  # noqa: E402
    FoundationScoringEnrichmentToPhase3BridgeAdapter,
)
from constitution.phase3_chain_adapter import Phase3ChainAdapter  # noqa: E402


@dataclass(frozen=True)
class EndToEndPhase3Result:
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
    phase3_result: dict[str, Any]
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
            "phase3_result": self.phase3_result,
            "audit": self.audit,
        }


class EndToEndConstitutionalWrapperToPhase3:
    VERSION = "1.0.0"

    def __init__(
        self,
        upstream_wrapper: FoundationScoringEnrichmentConstitutionalWrapper | None = None,
        bridge_adapter: FoundationScoringEnrichmentToPhase3BridgeAdapter | None = None,
        phase3_adapter: Phase3ChainAdapter | None = None,
    ) -> None:
        self.upstream_wrapper = upstream_wrapper or FoundationScoringEnrichmentConstitutionalWrapper()
        self.bridge_adapter = bridge_adapter or FoundationScoringEnrichmentToPhase3BridgeAdapter()
        self.phase3_adapter = phase3_adapter or Phase3ChainAdapter()

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

    def run(self, payload: dict[str, Any]) -> EndToEndPhase3Result:
        input_ref, timestamp = self._extract_meta(payload)
        audit_steps = ["Foundation->Scoring->Enrichment wrapper start"]

        upstream = self.upstream_wrapper.run(payload)
        audit_steps.append(f"Upstream wrapper completed with status={upstream.wrapper_status}")

        if upstream.halted or not upstream.continuation_allowed:
            audit_steps.append("End-to-end wrapper halted at UPSTREAM")
            return EndToEndPhase3Result(
                wrapper="END_TO_END_TO_PHASE3",
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
                phase3_result={},
                audit={
                    "halt_safe": True,
                    "steps": audit_steps,
                    "reason": "Upstream wrapper not continuable",
                },
            )

        audit_steps.append("Bridge to Phase 3 start")
        bridge = self.bridge_adapter.build(upstream.to_dict())
        audit_steps.append(f"Bridge completed with status={bridge.bridge_status}")

        if not bridge.bridge_allowed:
            audit_steps.append("End-to-end wrapper halted at BRIDGE")
            return EndToEndPhase3Result(
                wrapper="END_TO_END_TO_PHASE3",
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
                phase3_result={},
                audit={
                    "halt_safe": True,
                    "steps": audit_steps,
                    "reason": "Bridge to Phase 3 not allowed",
                },
            )

        audit_steps.append("Phase 3 start")
        phase3 = self.phase3_adapter.run(bridge.l7_payload, bridge.l8_payload, bridge.l9_payload)
        audit_steps.append(f"Phase 3 completed with status={phase3.chain_status}")

        if phase3.halted or not phase3.continuation_allowed:
            audit_steps.append("End-to-end wrapper halted at PHASE_3")
            return EndToEndPhase3Result(
                wrapper="END_TO_END_TO_PHASE3",
                wrapper_version=self.VERSION,
                input_ref=input_ref,
                timestamp=timestamp,
                halted=True,
                halted_at="PHASE_3",
                continuation_allowed=False,
                next_legal_targets=[],
                wrapper_status="FAIL",
                upstream_result=upstream.to_dict(),
                bridge_result=bridge.to_dict(),
                phase3_result=phase3.to_dict(),
                audit={
                    "halt_safe": True,
                    "steps": audit_steps,
                    "reason": "Phase 3 not continuable",
                },
            )

        wrapper_status = "PASS"
        if upstream.wrapper_status == "WARN" or bridge.bridge_status == "WARN" or phase3.chain_status == "WARN":
            wrapper_status = "WARN"

        audit_steps.append("End-to-end wrapper completed legally")
        return EndToEndPhase3Result(
            wrapper="END_TO_END_TO_PHASE3",
            wrapper_version=self.VERSION,
            input_ref=input_ref,
            timestamp=timestamp,
            halted=False,
            halted_at=None,
            continuation_allowed=True,
            next_legal_targets=["PHASE_4"],
            wrapper_status=wrapper_status,
            upstream_result=upstream.to_dict(),
            bridge_result=bridge.to_dict(),
            phase3_result=phase3.to_dict(),
            audit={
                "halt_safe": True,
                "steps": audit_steps,
                "reason": "Foundation -> Scoring -> Enrichment -> Bridge -> Phase 3 completed legally",
            },
        )
