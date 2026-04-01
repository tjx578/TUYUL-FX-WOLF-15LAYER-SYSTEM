from __future__ import annotations

"""
Foundation + Scoring + Enrichment Constitutional Wrapper

Runs:
  Phase 1 → Bridge → Phase 2 → Phase 2.5

Phase 2.5 remains non-fatal and advisory-only.
Analysis-only module. No execution authority.

Zone: constitution/ — pipeline governance, no execution side-effects.
"""

from dataclasses import dataclass  # noqa: E402
from typing import Any  # noqa: E402

from constitution.foundation_scoring_constitutional_wrapper import (  # noqa: E402
    FoundationScoringConstitutionalWrapper,
)
from constitution.phase25_enrichment_wrapper import Phase25EnrichmentWrapper  # noqa: E402


@dataclass(frozen=True)
class FoundationScoringEnrichmentResult:
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
    phase25_result: dict[str, Any]
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
            "phase25_result": self.phase25_result,
            "audit": self.audit,
        }


class FoundationScoringEnrichmentConstitutionalWrapper:
    VERSION = "1.0.0"

    def __init__(
        self,
        upstream_wrapper: FoundationScoringConstitutionalWrapper | None = None,
        phase25_wrapper: Phase25EnrichmentWrapper | None = None,
    ) -> None:
        self.upstream_wrapper = (
            upstream_wrapper or FoundationScoringConstitutionalWrapper()
        )
        self.phase25_wrapper = phase25_wrapper or Phase25EnrichmentWrapper()

    def run(
        self, payload: dict[str, Any]
    ) -> FoundationScoringEnrichmentResult:
        upstream = self.upstream_wrapper.run(payload)
        input_ref = upstream.input_ref
        timestamp = upstream.timestamp

        audit_steps = ["Foundation+Scoring wrapper executed"]

        if upstream.halted or not upstream.continuation_allowed:
            audit_steps.append("Wrapper halted before Phase 2.5")
            return FoundationScoringEnrichmentResult(
                wrapper="FOUNDATION_SCORING_ENRICHMENT_WRAPPER",
                wrapper_version=self.VERSION,
                input_ref=input_ref,
                timestamp=timestamp,
                halted=True,
                halted_at=upstream.halted_at,
                continuation_allowed=False,
                next_legal_targets=[],
                wrapper_status="FAIL",
                upstream_result=upstream.to_dict(),
                phase25_result={},
                audit={
                    "steps": audit_steps,
                    "reason": "Upstream wrapper not continuable",
                },
            )

        phase25 = self.phase25_wrapper.run(upstream.to_dict())
        audit_steps.append(
            f"Phase 2.5 executed with status={phase25.phase_status}"
        )

        wrapper_status = upstream.wrapper_status
        if phase25.phase_status == "WARN" and wrapper_status == "PASS":
            wrapper_status = "WARN"

        return FoundationScoringEnrichmentResult(
            wrapper="FOUNDATION_SCORING_ENRICHMENT_WRAPPER",
            wrapper_version=self.VERSION,
            input_ref=input_ref,
            timestamp=timestamp,
            halted=False,
            halted_at=None,
            continuation_allowed=True,
            next_legal_targets=["PHASE_3"],
            wrapper_status=wrapper_status,
            upstream_result=upstream.to_dict(),
            phase25_result=phase25.to_dict(),
            audit={
                "steps": audit_steps,
                "reason": "Foundation + Scoring + Enrichment completed legally",
                "phase25_non_fatal": True,
            },
        )
