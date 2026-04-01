from __future__ import annotations

"""
Phase 4 Chain Adapter — strict constitutional prototype

Runs L11 -> L6 -> L10 in a halt-safe wrapper.
Analysis-only module. This adapter does NOT emit execute,
trade_valid, sizing authority, or final trading verdict.
"""

from dataclasses import dataclass  # noqa: E402
from typing import Any  # noqa: E402

from constitution.l6_router_evaluator import (  # noqa: E402
    L6EvaluationResult,
    L6RouterEvaluator,
    build_l6_input_from_dict,
)
from constitution.l10_router_evaluator import L10RouterEvaluator, build_l10_input_from_dict  # noqa: E402
from constitution.l11_router_evaluator import (  # noqa: E402
    L11EvaluationResult,
    L11RouterEvaluator,
    build_l11_input_from_dict,
)


@dataclass(frozen=True)
class Phase4ChainResult:
    phase: str
    phase_version: str
    input_ref: str
    timestamp: str
    halted: bool
    halted_at: str | None
    continuation_allowed: bool
    next_legal_targets: list[str]
    chain_status: str
    summary_status: dict[str, str]
    blocker_map: dict[str, list[str]]
    warning_map: dict[str, list[str]]
    layer_results: dict[str, dict[str, Any]]
    audit: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "phase_version": self.phase_version,
            "input_ref": self.input_ref,
            "timestamp": self.timestamp,
            "halted": self.halted,
            "halted_at": self.halted_at,
            "continuation_allowed": self.continuation_allowed,
            "next_legal_targets": self.next_legal_targets,
            "chain_status": self.chain_status,
            "summary_status": self.summary_status,
            "blocker_map": self.blocker_map,
            "warning_map": self.warning_map,
            "layer_results": self.layer_results,
            "audit": self.audit,
        }


class Phase4ChainAdapter:
    VERSION = "1.0.0"

    def __init__(
        self,
        l11_evaluator: L11RouterEvaluator | None = None,
        l6_evaluator: L6RouterEvaluator | None = None,
        l10_evaluator: L10RouterEvaluator | None = None,
    ) -> None:
        self.l11_evaluator = l11_evaluator or L11RouterEvaluator()
        self.l6_evaluator = l6_evaluator or L6RouterEvaluator()
        self.l10_evaluator = l10_evaluator or L10RouterEvaluator()

    @staticmethod
    def _canonicalize_input_ref(l11_payload: dict[str, Any], l6_payload: dict[str, Any], l10_payload: dict[str, Any]) -> str:
        refs = [
            str(l11_payload.get("input_ref", "")).strip(),
            str(l6_payload.get("input_ref", "")).strip(),
            str(l10_payload.get("input_ref", "")).strip(),
        ]
        non_empty = [r for r in refs if r]
        if not non_empty:
            raise ValueError("Phase 4 requires at least one non-empty input_ref.")
        return non_empty[0]

    @staticmethod
    def _canonicalize_timestamp(l11_payload: dict[str, Any], l6_payload: dict[str, Any], l10_payload: dict[str, Any]) -> str:
        timestamps = [
            str(l11_payload.get("timestamp", "")).strip(),
            str(l6_payload.get("timestamp", "")).strip(),
            str(l10_payload.get("timestamp", "")).strip(),
        ]
        non_empty = [t for t in timestamps if t]
        if not non_empty:
            raise ValueError("Phase 4 requires at least one non-empty timestamp.")
        return non_empty[0]

    @staticmethod
    def _inject_upstream_flags(
        l11_result: L11EvaluationResult | None,
        l6_payload: dict[str, Any],
        l6_result: L6EvaluationResult | None,
        l10_payload: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        l6_runtime = dict(l6_payload)
        if l11_result is not None:
            l6_runtime["upstream_l11_continuation_allowed"] = l11_result.continuation_allowed

        l10_runtime = dict(l10_payload)
        if l6_result is not None:
            l10_runtime["upstream_l6_continuation_allowed"] = l6_result.continuation_allowed

        return l6_runtime, l10_runtime

    def run(self, l11_payload: dict[str, Any], l6_payload: dict[str, Any], l10_payload: dict[str, Any]) -> Phase4ChainResult:
        input_ref = self._canonicalize_input_ref(l11_payload, l6_payload, l10_payload)
        timestamp = self._canonicalize_timestamp(l11_payload, l6_payload, l10_payload)

        l11_input = build_l11_input_from_dict(l11_payload)
        l11_result = self.l11_evaluator.evaluate(l11_input)

        summary_status = {"L11": l11_result.status.value}
        blocker_map = {"L11": list(l11_result.blocker_codes)}
        warning_map = {"L11": list(l11_result.warning_codes)}
        layer_results = {"L11": l11_result.to_dict()}
        audit_steps = ["L11 evaluated", f"L11 continuation_allowed={l11_result.continuation_allowed}"]

        if not l11_result.continuation_allowed:
            audit_steps.append("Chain halted at L11")
            return Phase4ChainResult(
                phase="PHASE_4_RISK_CHAIN",
                phase_version=self.VERSION,
                input_ref=input_ref,
                timestamp=timestamp,
                halted=True,
                halted_at="L11",
                continuation_allowed=False,
                next_legal_targets=[],
                chain_status="FAIL",
                summary_status=summary_status,
                blocker_map=blocker_map,
                warning_map=warning_map,
                layer_results=layer_results,
                audit={"halt_safe": True, "steps": audit_steps, "reason": "L11 continuation disallowed"},
            )

        l6_runtime, _ = self._inject_upstream_flags(l11_result, l6_payload, None, l10_payload)
        l6_input = build_l6_input_from_dict(l6_runtime)
        l6_result = self.l6_evaluator.evaluate(l6_input)

        summary_status["L6"] = l6_result.status.value
        blocker_map["L6"] = list(l6_result.blocker_codes)
        warning_map["L6"] = list(l6_result.warning_codes)
        layer_results["L6"] = l6_result.to_dict()
        audit_steps.extend(["L6 evaluated", f"L6 continuation_allowed={l6_result.continuation_allowed}"])

        if not l6_result.continuation_allowed:
            audit_steps.append("Chain halted at L6")
            return Phase4ChainResult(
                phase="PHASE_4_RISK_CHAIN",
                phase_version=self.VERSION,
                input_ref=input_ref,
                timestamp=timestamp,
                halted=True,
                halted_at="L6",
                continuation_allowed=False,
                next_legal_targets=[],
                chain_status="FAIL",
                summary_status=summary_status,
                blocker_map=blocker_map,
                warning_map=warning_map,
                layer_results=layer_results,
                audit={"halt_safe": True, "steps": audit_steps, "reason": "L6 continuation disallowed"},
            )

        _, l10_runtime = self._inject_upstream_flags(l11_result, l6_payload, l6_result, l10_payload)
        l10_input = build_l10_input_from_dict(l10_runtime)
        l10_result = self.l10_evaluator.evaluate(l10_input)

        summary_status["L10"] = l10_result.status.value
        blocker_map["L10"] = list(l10_result.blocker_codes)
        warning_map["L10"] = list(l10_result.warning_codes)
        layer_results["L10"] = l10_result.to_dict()
        audit_steps.extend(["L10 evaluated", f"L10 continuation_allowed={l10_result.continuation_allowed}"])

        if not l10_result.continuation_allowed:
            audit_steps.append("Chain halted at L10")
            return Phase4ChainResult(
                phase="PHASE_4_RISK_CHAIN",
                phase_version=self.VERSION,
                input_ref=input_ref,
                timestamp=timestamp,
                halted=True,
                halted_at="L10",
                continuation_allowed=False,
                next_legal_targets=[],
                chain_status="FAIL",
                summary_status=summary_status,
                blocker_map=blocker_map,
                warning_map=warning_map,
                layer_results=layer_results,
                audit={"halt_safe": True, "steps": audit_steps, "reason": "L10 continuation disallowed"},
            )

        chain_status = "WARN" if any(s == "WARN" for s in summary_status.values()) else "PASS"
        audit_steps.append("Phase 4 completed")
        return Phase4ChainResult(
            phase="PHASE_4_RISK_CHAIN",
            phase_version=self.VERSION,
            input_ref=input_ref,
            timestamp=timestamp,
            halted=False,
            halted_at=None,
            continuation_allowed=True,
            next_legal_targets=["PHASE_5"],
            chain_status=chain_status,
            summary_status=summary_status,
            blocker_map=blocker_map,
            warning_map=warning_map,
            layer_results=layer_results,
            audit={"halt_safe": True, "steps": audit_steps, "reason": "Phase 4 completed legally"},
        )


def build_phase4_payloads_from_dict(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    required = ["L11", "L6", "L10"]
    missing = [k for k in required if k not in payload]
    if missing:
        raise ValueError(f"Missing required Phase 4 layer payloads: {', '.join(missing)}")
    return dict(payload["L11"]), dict(payload["L6"]), dict(payload["L10"])
