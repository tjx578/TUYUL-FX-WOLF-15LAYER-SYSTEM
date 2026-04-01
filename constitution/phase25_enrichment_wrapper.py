from __future__ import annotations

"""
Phase 2.5 Enrichment Wrapper — strict constitutional prototype

Semantics:
- Runs enrichment engines E1..E8 in non-fatal batch style
- Collects results with isolated errors
- Runs advisory E9 only after enrichment collection completes
- Never overrides constitutional authority
- Never emits execution permission or final verdict

Analysis-only module.
"""

from collections.abc import Callable  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from typing import Any  # noqa: E402


@dataclass(frozen=True)
class EnrichmentEngineResult:
    engine_id: str
    status: str  # success | partial | failed | skipped
    outputs: dict[str, Any]
    warnings: list[str]
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine_id": self.engine_id,
            "status": self.status,
            "outputs": self.outputs,
            "warnings": self.warnings,
            "errors": self.errors,
        }


@dataclass(frozen=True)
class Phase25EnrichmentResult:
    phase: str
    phase_version: str
    input_ref: str
    timestamp: str
    continuation_allowed: bool
    phase_status: str  # PASS | WARN
    next_legal_targets: list[str]
    engine_results: dict[str, dict[str, Any]]
    advisory_result: dict[str, Any]
    error_list: list[str]
    warning_list: list[str]
    audit: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "phase_version": self.phase_version,
            "input_ref": self.input_ref,
            "timestamp": self.timestamp,
            "continuation_allowed": self.continuation_allowed,
            "phase_status": self.phase_status,
            "next_legal_targets": self.next_legal_targets,
            "engine_results": self.engine_results,
            "advisory_result": self.advisory_result,
            "error_list": self.error_list,
            "warning_list": self.warning_list,
            "audit": self.audit,
        }


def _default_enrichment_runner(
    engine_id: str, context: dict[str, Any]
) -> EnrichmentEngineResult:
    """Deterministic default stub for enrichment engines."""
    chain_status = str(context.get("wrapper_status", "WARN")).upper()
    phase2_status = str(
        context.get("phase_status", {}).get("PHASE_2", "WARN")
    ).upper()

    if chain_status == "FAIL":
        return EnrichmentEngineResult(
            engine_id=engine_id,
            status="skipped",
            outputs={},
            warnings=["UPSTREAM_NOT_BRIDGEABLE_FOR_ENRICHMENT"],
            errors=[],
        )

    if phase2_status == "PASS":
        return EnrichmentEngineResult(
            engine_id=engine_id,
            status="success",
            outputs={
                "engine_id": engine_id,
                "advisory_only": True,
                "confidence_hint": 0.75,
                "upstream_phase2_status": phase2_status,
            },
            warnings=[],
            errors=[],
        )

    return EnrichmentEngineResult(
        engine_id=engine_id,
        status="partial",
        outputs={
            "engine_id": engine_id,
            "advisory_only": True,
            "confidence_hint": 0.55,
            "upstream_phase2_status": phase2_status,
        },
        warnings=["UPSTREAM_WARN_ENRICHMENT_DEGRADED"],
        errors=[],
    )


def _default_advisory_runner(
    collected: dict[str, EnrichmentEngineResult], context: dict[str, Any]
) -> EnrichmentEngineResult:
    """Sequential advisory after enrichment collection."""
    success_count = sum(1 for r in collected.values() if r.status == "success")
    partial_count = sum(1 for r in collected.values() if r.status == "partial")
    failed_count = sum(1 for r in collected.values() if r.status == "failed")

    status = "success"
    warnings: list[str] = []
    if failed_count > 0 or partial_count > 0:
        status = "partial"
        warnings.append("ADVISORY_BUILT_FROM_DEGRADED_ENRICHMENT_SET")

    outputs = {
        "advisory_only": True,
        "success_count": success_count,
        "partial_count": partial_count,
        "failed_count": failed_count,
        "non_authoritative": True,
        "note": (
            "Advisory built after enrichment collection; "
            "cannot override constitutional layers."
        ),
    }

    return EnrichmentEngineResult(
        engine_id="E9_ADVISORY",
        status=status,
        outputs=outputs,
        warnings=warnings,
        errors=[],
    )


class Phase25EnrichmentWrapper:
    VERSION = "1.0.0"
    ENGINE_IDS = ["E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8"]

    def __init__(
        self,
        engine_runners: (
            dict[str, Callable[[str, dict[str, Any]], EnrichmentEngineResult]] | None
        ) = None,
        advisory_runner: (
            Callable[
                [dict[str, EnrichmentEngineResult], dict[str, Any]],
                EnrichmentEngineResult,
            ]
            | None
        ) = None,
    ) -> None:
        self.engine_runners = engine_runners or {}
        self.advisory_runner = advisory_runner or _default_advisory_runner

    @staticmethod
    def _extract_meta(wrapper_result: dict[str, Any]) -> tuple[str, str]:
        input_ref = str(wrapper_result.get("input_ref", "")).strip()
        timestamp = str(wrapper_result.get("timestamp", "")).strip()
        if not input_ref or not timestamp:
            raise ValueError(
                "Phase 2.5 enrichment wrapper requires non-empty "
                "input_ref and timestamp."
            )
        return input_ref, timestamp

    @staticmethod
    def _is_eligible(wrapper_result: dict[str, Any]) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        if bool(wrapper_result.get("halted", False)):
            reasons.append("UPSTREAM_HALTED")
        if not bool(wrapper_result.get("continuation_allowed", False)):
            reasons.append("UPSTREAM_CONTINUATION_DISALLOWED")

        next_targets = [
            str(x) for x in wrapper_result.get("next_legal_targets", [])
        ]
        if "PHASE_2_5" not in next_targets:
            reasons.append("UPSTREAM_NEXT_TARGET_NOT_PHASE_2_5")

        status = str(wrapper_result.get("wrapper_status", "")).upper()
        if status not in {"PASS", "WARN"}:
            reasons.append("UPSTREAM_STATUS_NOT_ENRICHABLE")

        return (len(reasons) == 0, reasons)

    def run(
        self, wrapper_result: dict[str, Any]
    ) -> Phase25EnrichmentResult:
        input_ref, timestamp = self._extract_meta(wrapper_result)
        eligible, reasons = self._is_eligible(wrapper_result)

        if not eligible:
            return Phase25EnrichmentResult(
                phase="PHASE_2_5_ENRICHMENT",
                phase_version=self.VERSION,
                input_ref=input_ref,
                timestamp=timestamp,
                continuation_allowed=False,
                phase_status="WARN",
                next_legal_targets=[],
                engine_results={},
                advisory_result={},
                error_list=reasons,
                warning_list=["ENRICHMENT_SKIPPED_DUE_TO_UPSTREAM_STATE"],
                audit={
                    "non_fatal": True,
                    "parallel_semantic": True,
                    "advisory_after_collection": True,
                    "notes": [
                        "Phase 2.5 skipped because upstream wrapper "
                        "is not legally enrichable.",
                    ],
                },
            )

        collected: dict[str, EnrichmentEngineResult] = {}
        all_errors: list[str] = []
        all_warnings: list[str] = []
        audit_steps: list[str] = ["Batch enrichment start"]

        for engine_id in self.ENGINE_IDS:
            runner = self.engine_runners.get(engine_id, _default_enrichment_runner)
            try:
                result = runner(engine_id, wrapper_result)
            except Exception as exc:  # isolated, non-fatal
                result = EnrichmentEngineResult(
                    engine_id=engine_id,
                    status="failed",
                    outputs={},
                    warnings=[],
                    errors=[f"{type(exc).__name__}: {exc}"],
                )
            collected[engine_id] = result
            all_errors.extend(result.errors)
            all_warnings.extend(result.warnings)
            audit_steps.append(f"{engine_id} status={result.status}")

        audit_steps.append("Advisory start after enrichment collection")
        try:
            advisory = self.advisory_runner(collected, wrapper_result)
        except Exception as exc:
            advisory = EnrichmentEngineResult(
                engine_id="E9_ADVISORY",
                status="failed",
                outputs={},
                warnings=[],
                errors=[f"{type(exc).__name__}: {exc}"],
            )

        all_errors.extend(advisory.errors)
        all_warnings.extend(advisory.warnings)
        audit_steps.append(f"E9_ADVISORY status={advisory.status}")

        phase_status = "PASS"
        if (
            all_errors
            or all_warnings
            or advisory.status != "success"
            or any(r.status != "success" for r in collected.values())
        ):
            phase_status = "WARN"

        return Phase25EnrichmentResult(
            phase="PHASE_2_5_ENRICHMENT",
            phase_version=self.VERSION,
            input_ref=input_ref,
            timestamp=timestamp,
            continuation_allowed=True,
            phase_status=phase_status,
            next_legal_targets=["PHASE_3"],
            engine_results={k: v.to_dict() for k, v in collected.items()},
            advisory_result=advisory.to_dict(),
            error_list=all_errors,
            warning_list=all_warnings,
            audit={
                "non_fatal": True,
                "parallel_semantic": True,
                "advisory_after_collection": True,
                "steps": audit_steps,
                "notes": [
                    "Individual enrichment engine failure is isolated "
                    "and cannot halt pipeline by itself.",
                    "Advisory runs only after enrichment results "
                    "are collected.",
                ],
            },
        )
