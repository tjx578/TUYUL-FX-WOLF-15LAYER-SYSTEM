"""
Phase 2 Chain Adapter — Strict Sequential Halt-on-Failure
=========================================================

Enforces the Phase 2 canonical pipeline semantics:
    L4 → L5 (strict sequential, halt-on-failure)

Each layer's constitutional governor is evaluated before proceeding
to the next layer. If any layer produces ``continuation_allowed == false``,
the chain halts and returns a Phase2ChainResult with the failure details.

Authority boundary:
  This adapter orchestrates Phase 2 only. It does not emit direction,
  verdict, or execution authority. It connects constitutional governors
  to enforce halt-on-failure semantics that the parallel DAG batch
  runner cannot enforce.

Zone: constitution/ — pipeline governance, no execution side-effects.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# §1  CHAIN RESULT
# ═══════════════════════════════════════════════════════════════════════════


class Phase2ChainStatus(str, Enum):
    """Phase 2 chain execution status."""

    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass
class Phase2ChainResult:
    """Result of the Phase 2 chain execution."""

    status: Phase2ChainStatus
    continuation_allowed: bool
    halted_at: str | None = None
    l4: dict[str, Any] = field(default_factory=dict)
    l5: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    timing_ms: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for pipeline consumption."""
        return {
            "phase": "PHASE_2",
            "status": self.status.value,
            "chain_status": self.status.value,
            "continuation_allowed": self.continuation_allowed,
            "halted": self.halted_at is not None,
            "halted_at": self.halted_at,
            "l4": self.l4,
            "l5": self.l5,
            "errors": self.errors,
            "warnings": self.warnings,
            "timing_ms": self.timing_ms,
        }

    @property
    def chain_status(self) -> str:
        """Chain status as string."""
        return self.status.value

    @property
    def halted(self) -> bool:
        """Whether the chain halted before completing all layers."""
        return self.halted_at is not None


# ═══════════════════════════════════════════════════════════════════════════
# §2  PHASE 2 CHAIN ADAPTER
# ═══════════════════════════════════════════════════════════════════════════


class Phase2ChainAdapter:
    """Strict sequential halt-on-failure chain for Phase 2 (L4 → L5).

    Usage::

        adapter = Phase2ChainAdapter()
        result = adapter.run(l4_payload, l5_payload)

    The adapter:
    1. Evaluates L4 constitutional governor, checks continuation_allowed
    2. If L4 passes, injects upstream flag, evaluates L5
    3. Returns Phase2ChainResult with all layer outputs and halt details
    """

    def __init__(self) -> None:
        from analysis.layers.L4_constitutional import L4ConstitutionalGovernor
        from analysis.layers.L5_constitutional import L5ConstitutionalGovernor

        self._l4_gov = L4ConstitutionalGovernor()
        self._l5_gov = L5ConstitutionalGovernor()

    def run(
        self,
        l4_payload: dict[str, Any],
        l5_payload: dict[str, Any],
    ) -> Phase2ChainResult:
        """Execute the Phase 2 chain.

        Parameters
        ----------
        l4_payload : dict
            Must contain ``l3_output`` and ``l4_analysis`` keys.
        l5_payload : dict
            Must contain ``l4_output`` and ``l5_analysis`` keys.
            ``l4_output`` will be overwritten with actual L4 governor result.
        """
        timing: dict[str, float] = {}
        errors: list[str] = []
        warnings: list[str] = []
        worst_status = Phase2ChainStatus.PASS

        # ── Step 1: L4 ───────────────────────────────────────
        l4_start = time.monotonic()
        try:
            l3_output = l4_payload.get("l3_output", {})
            l4_analysis = l4_payload.get("l4_analysis", {})
            symbol = l4_payload.get("symbol", "")
            l4_result = self._l4_gov.evaluate(l3_output, l4_analysis, symbol)
        except Exception as exc:
            logger.error(
                "[Phase2] L4 governor raised: %s: %s",
                type(exc).__name__, exc, exc_info=True,
            )
            errors.append(f"L4_EXCEPTION:{type(exc).__name__}")
            return Phase2ChainResult(
                status=Phase2ChainStatus.FAIL,
                continuation_allowed=False,
                halted_at="L4",
                errors=errors,
                timing_ms=timing,
            )
        timing["L4"] = (time.monotonic() - l4_start) * 1000

        l4_status = l4_result.get("status", "FAIL")
        l4_continue = l4_result.get("continuation_allowed", False)
        l4_blockers = l4_result.get("blocker_codes", [])
        l4_warnings = l4_result.get("warning_codes", [])

        if l4_status == "WARN":
            worst_status = Phase2ChainStatus.WARN
            warnings.extend(f"L4:{w}" for w in l4_warnings)

        if not l4_continue:
            errors.append(f"L4_HALT:status={l4_status}")
            errors.extend(f"L4_BLOCKER:{b}" for b in l4_blockers)
            logger.warning(
                "[Phase2] L4 HALT | symbol=%s status=%s blockers=%s",
                symbol, l4_status, l4_blockers,
            )
            return Phase2ChainResult(
                status=Phase2ChainStatus.FAIL,
                continuation_allowed=False,
                halted_at="L4",
                l4=l4_result,
                errors=errors,
                warnings=warnings,
                timing_ms=timing,
            )

        # ── Step 2: L5 (with upstream L4 result) ─────────────
        l5_start = time.monotonic()
        try:
            # Override l5_payload's l4_output with actual L4 governor result
            l5_payload_resolved = dict(l5_payload)
            l5_payload_resolved["l4_output"] = l4_result

            l4_output = l5_payload_resolved.get("l4_output", {})
            l5_analysis = l5_payload_resolved.get("l5_analysis", {})
            l5_symbol = l5_payload_resolved.get("symbol", symbol)
            l5_result = self._l5_gov.evaluate(l4_output, l5_analysis, l5_symbol)
        except Exception as exc:
            logger.error(
                "[Phase2] L5 governor raised: %s: %s",
                type(exc).__name__, exc, exc_info=True,
            )
            errors.append(f"L5_EXCEPTION:{type(exc).__name__}")
            return Phase2ChainResult(
                status=Phase2ChainStatus.FAIL,
                continuation_allowed=False,
                halted_at="L5",
                l4=l4_result,
                errors=errors,
                timing_ms=timing,
            )
        timing["L5"] = (time.monotonic() - l5_start) * 1000

        l5_status = l5_result.get("status", "FAIL")
        l5_continue = l5_result.get("continuation_allowed", False)
        l5_blockers = l5_result.get("blocker_codes", [])
        l5_warnings = l5_result.get("warning_codes", [])

        if l5_status == "WARN" and worst_status == Phase2ChainStatus.PASS:
            worst_status = Phase2ChainStatus.WARN
            warnings.extend(f"L5:{w}" for w in l5_warnings)

        if not l5_continue:
            errors.append(f"L5_HALT:status={l5_status}")
            errors.extend(f"L5_BLOCKER:{b}" for b in l5_blockers)
            logger.warning(
                "[Phase2] L5 HALT | symbol=%s status=%s blockers=%s",
                l5_symbol, l5_status, l5_blockers,
            )
            return Phase2ChainResult(
                status=Phase2ChainStatus.FAIL,
                continuation_allowed=False,
                halted_at="L5",
                l4=l4_result,
                l5=l5_result,
                errors=errors,
                warnings=warnings,
                timing_ms=timing,
            )

        # ── Both layers passed ────────────────────────────────
        logger.info(
            "[Phase2] PASS | symbol=%s chain_status=%s L4=%s L5=%s "
            "timing_ms=L4:%.1f/L5:%.1f",
            symbol,
            worst_status.value,
            l4_status,
            l5_status,
            timing.get("L4", 0),
            timing.get("L5", 0),
        )

        return Phase2ChainResult(
            status=worst_status,
            continuation_allowed=True,
            halted_at=None,
            l4=l4_result,
            l5=l5_result,
            errors=errors,
            warnings=warnings,
            timing_ms=timing,
        )


# ═══════════════════════════════════════════════════════════════════════════
# §3  PAYLOAD BUILDER
# ═══════════════════════════════════════════════════════════════════════════


def build_phase2_payloads_from_dict(
    l3_output: dict[str, Any],
    l4_analysis: dict[str, Any],
    l5_analysis: dict[str, Any],
    symbol: str = "",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build L4 and L5 payloads from raw layer outputs.

    Returns a (l4_payload, l5_payload) tuple ready for Phase2ChainAdapter.run().
    """
    l4_payload = {
        "l3_output": l3_output,
        "l4_analysis": l4_analysis,
        "symbol": symbol,
    }
    l5_payload = {
        "l4_output": {},  # will be overwritten by chain adapter
        "l5_analysis": l5_analysis,
        "symbol": symbol,
    }
    return l4_payload, l5_payload


# ═══════════════════════════════════════════════════════════════════════════
# §4  EVALUATOR CHAIN RESULT
# ═══════════════════════════════════════════════════════════════════════════


class Phase2EvaluatorChainResult:
    """Rich result from the router-evaluator based Phase 2 chain.

    Wraps the canonical Phase2ChainResult from the router evaluator
    prototype and exposes a ``to_dict`` compatible with the constitution
    layer.
    """

    __slots__ = (
        "phase", "phase_version", "input_ref", "timestamp",
        "halted", "halted_at", "continuation_allowed",
        "next_legal_targets", "chain_status", "summary_status",
        "blocker_map", "warning_map", "layer_results", "audit",
    )

    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            object.__setattr__(self, k, v)

    def to_dict(self) -> dict[str, Any]:
        return {s: getattr(self, s) for s in self.__slots__}


# ═══════════════════════════════════════════════════════════════════════════
# §5  ROUTER EVALUATOR ADAPTER
# ═══════════════════════════════════════════════════════════════════════════


class Phase2RouterEvaluatorAdapter:
    """Runs L4→L5 using the standalone router evaluators.

    This adapter delegates to ``L4RouterEvaluator``, ``L5RouterEvaluator``
    from ``constitution/`` and orchestrates them in strict halt-safe order
    with upstream flag injection.

    Usage::

        adapter = Phase2RouterEvaluatorAdapter()
        result = adapter.run(l4_payload, l5_payload)
    """

    VERSION = "1.0.0"

    def __init__(
        self,
        l4_evaluator: Any | None = None,
        l5_evaluator: Any | None = None,
    ) -> None:
        from constitution.l4_router_evaluator import L4RouterEvaluator
        from constitution.l5_router_evaluator import L5RouterEvaluator

        self.l4_evaluator = l4_evaluator or L4RouterEvaluator()
        self.l5_evaluator = l5_evaluator or L5RouterEvaluator()

    @staticmethod
    def _canonicalize(payloads: list[dict[str, Any]], key: str) -> str:
        vals = [str(p.get(key, "")).strip() for p in payloads]
        non_empty = [v for v in vals if v]
        if not non_empty:
            raise ValueError(f"Phase 2 requires at least one non-empty {key}.")
        return non_empty[0]

    @staticmethod
    def _inject_upstream_flags(
        l4_result: Any | None,
        l5_payload: dict[str, Any],
    ) -> dict[str, Any]:
        l5_runtime = dict(l5_payload)
        if l4_result is not None:
            l5_runtime["upstream_l4_continuation_allowed"] = (
                l4_result.continuation_allowed
            )
        return l5_runtime

    def run(
        self,
        l4_payload: dict[str, Any],
        l5_payload: dict[str, Any],
    ) -> Phase2EvaluatorChainResult:
        """Evaluate Phase 2 chain using router evaluators."""
        from constitution.l4_router_evaluator import build_l4_input_from_dict
        from constitution.l5_router_evaluator import build_l5_input_from_dict

        payloads = [l4_payload, l5_payload]
        input_ref = self._canonicalize(payloads, "input_ref")
        timestamp = self._canonicalize(payloads, "timestamp")

        summary_status: dict[str, str] = {}
        blocker_map: dict[str, list[str]] = {}
        warning_map: dict[str, list[str]] = {}
        layer_results: dict[str, dict[str, Any]] = {}
        audit_steps: list[str] = []

        def _halt(at: str, reason: str) -> Phase2EvaluatorChainResult:
            audit_steps.append(f"Chain halted at {at}")
            return Phase2EvaluatorChainResult(
                phase="PHASE_2_SCORING",
                phase_version=self.VERSION,
                input_ref=input_ref,
                timestamp=timestamp,
                halted=True,
                halted_at=at,
                continuation_allowed=False,
                next_legal_targets=[],
                chain_status="FAIL",
                summary_status=summary_status,
                blocker_map=blocker_map,
                warning_map=warning_map,
                layer_results=layer_results,
                audit={
                    "halt_safe": True,
                    "steps": audit_steps,
                    "reason": reason,
                },
            )

        # ── L4 ────────────────────────────────────────────
        l4_input = build_l4_input_from_dict(l4_payload)
        l4_result = self.l4_evaluator.evaluate(l4_input)
        summary_status["L4"] = l4_result.status.value
        blocker_map["L4"] = list(l4_result.blocker_codes)
        warning_map["L4"] = list(l4_result.warning_codes)
        layer_results["L4"] = l4_result.to_dict()
        audit_steps.append("L4 evaluated")
        audit_steps.append(
            f"L4 continuation_allowed={l4_result.continuation_allowed}"
        )

        if not l4_result.continuation_allowed:
            return _halt("L4", "L4 continuation disallowed")

        # ── L5 (with upstream L4 flag) ────────────────────
        l5_runtime = self._inject_upstream_flags(l4_result, l5_payload)
        l5_input = build_l5_input_from_dict(l5_runtime)
        l5_result = self.l5_evaluator.evaluate(l5_input)
        summary_status["L5"] = l5_result.status.value
        blocker_map["L5"] = list(l5_result.blocker_codes)
        warning_map["L5"] = list(l5_result.warning_codes)
        layer_results["L5"] = l5_result.to_dict()
        audit_steps.append("L5 evaluated")
        audit_steps.append(
            f"L5 continuation_allowed={l5_result.continuation_allowed}"
        )

        if not l5_result.continuation_allowed:
            return _halt("L5", "L5 continuation disallowed")

        # ── ALL PASS ──────────────────────────────────────
        chain_status = "PASS"
        if any(s == "WARN" for s in summary_status.values()):
            chain_status = "WARN"

        audit_steps.append("Phase 2 completed")
        return Phase2EvaluatorChainResult(
            phase="PHASE_2_SCORING",
            phase_version=self.VERSION,
            input_ref=input_ref,
            timestamp=timestamp,
            halted=False,
            halted_at=None,
            continuation_allowed=True,
            next_legal_targets=["PHASE_2_5"],
            chain_status=chain_status,
            summary_status=summary_status,
            blocker_map=blocker_map,
            warning_map=warning_map,
            layer_results=layer_results,
            audit={
                "halt_safe": True,
                "steps": audit_steps,
                "reason": "Phase 2 completed legally",
            },
        )


def build_phase2_evaluator_payloads_from_dict(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Extract L4, L5 evaluator payloads from a combined Phase 2 dict.

    Expected keys: ``L4``, ``L5`` (each a dict).
    Returns (l4_payload, l5_payload).
    """
    required = ["L4", "L5"]
    missing = [key for key in required if key not in payload]
    if missing:
        raise ValueError(
            f"Missing required Phase 2 layer payloads: {', '.join(missing)}"
        )
    return dict(payload["L4"]), dict(payload["L5"])
