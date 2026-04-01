from __future__ import annotations

"""
End-to-end constitutional wrapper up to Phase 5

Runs:
Foundation -> Scoring -> Enrichment -> Bridge -> Phase 3 -> Bridge -> Phase 4 -> Synthesis/L12

This wrapper preserves halt-safe semantics for fatal phases and
non-fatal semantics for Phase 2.5 enrichment.
Analysis-only module. No live execution authority.
"""

from dataclasses import dataclass  # noqa: E402
from typing import Any  # noqa: E402

from constitution.end_to_end_constitutional_wrapper_to_phase4 import (  # noqa: E402
    EndToEndConstitutionalWrapperToPhase4,
)
from constitution.phase5_constitutional_verdict_adapter import (  # noqa: E402
    Phase5ConstitutionalVerdictAdapter,
)


@dataclass(frozen=True)
class EndToEndPhase5Result:
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
    phase5_result: dict[str, Any]
    final_verdict: str
    final_verdict_status: str
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
            "phase5_result": self.phase5_result,
            "final_verdict": self.final_verdict,
            "final_verdict_status": self.final_verdict_status,
            "audit": self.audit,
        }


class EndToEndConstitutionalWrapperToPhase5:
    VERSION = "1.0.0"

    def __init__(
        self,
        upstream_wrapper: EndToEndConstitutionalWrapperToPhase4 | None = None,
        phase5_adapter: Phase5ConstitutionalVerdictAdapter | None = None,
    ) -> None:
        self.upstream_wrapper = upstream_wrapper or EndToEndConstitutionalWrapperToPhase4()
        self.phase5_adapter = phase5_adapter or Phase5ConstitutionalVerdictAdapter()

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

    def run(self, payload: dict[str, Any]) -> EndToEndPhase5Result:
        input_ref, timestamp = self._extract_meta(payload)
        audit_steps = ["Upstream end-to-end to Phase 4 start"]

        upstream = self.upstream_wrapper.run(payload)
        audit_steps.append(f"Upstream Phase 4 wrapper completed with status={upstream.wrapper_status}")

        # Phase 5 always receives the upstream result, because L12 is the constitutional sink.
        # Upstream failures should resolve into NO_TRADE rather than skipping authority entirely.
        audit_steps.append("Phase 5 synthesis/L12 start")
        phase5 = self.phase5_adapter.run(upstream.to_dict())
        audit_steps.append(
            f"Phase 5 completed with verdict={phase5.l12_result['verdict']} status={phase5.l12_result['verdict_status']}"
        )

        final_verdict = phase5.l12_result["verdict"]
        final_verdict_status = phase5.l12_result["verdict_status"]

        halted = final_verdict == "NO_TRADE"
        halted_at = "L12" if halted else None
        continuation_allowed = bool(phase5.continuation_allowed)
        next_targets = list(phase5.next_legal_targets)

        wrapper_status = final_verdict_status

        return EndToEndPhase5Result(
            wrapper="END_TO_END_TO_PHASE5",
            wrapper_version=self.VERSION,
            input_ref=input_ref,
            timestamp=timestamp,
            halted=halted,
            halted_at=halted_at,
            continuation_allowed=continuation_allowed,
            next_legal_targets=next_targets,
            wrapper_status=wrapper_status,
            upstream_result=upstream.to_dict(),
            phase5_result=phase5.to_dict(),
            final_verdict=final_verdict,
            final_verdict_status=final_verdict_status,
            audit={
                "halt_safe": True,
                "steps": audit_steps,
                "reason": "Foundation -> Scoring -> Enrichment -> Phase 3 -> Phase 4 -> Synthesis/L12 completed",
            },
        )
