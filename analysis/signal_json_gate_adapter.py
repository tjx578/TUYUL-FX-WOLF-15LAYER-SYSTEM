"""Adapter that applies execution gates before SignalJSON emission."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from analysis.signal_execution_gate_models import ExecutionGateDecision
from analysis.signal_execution_gates import evaluate_signal_execution_gates
from analysis.signal_thresholds import SIGNAL_MIN_RR


@dataclass(frozen=True)
class SignalJsonGateConfig:
    enabled: bool = False
    enforce: bool = False
    final_barrier: bool = False
    emit_continuation: bool = False
    emit_sidecar: bool = True
    # When True, a DEFER (not BLOCK) on a directionally-confirmed candidate is
    # emitted as a CONDITIONAL final signal (execution_mode=WAIT_RETEST) instead
    # of being demoted to a non-final decision update. Off by default so live
    # execution semantics do not change until downstream honors WAIT_RETEST.
    emit_deferred_as_conditional_final: bool = False
    prefix: str = "[SignalExecutionGateJSON]"
    min_rr_required: float = SIGNAL_MIN_RR
    max_chase_r: float = 0.35
    rr_fallback_validates_signal: bool = False

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> SignalJsonGateConfig:
        env = os.environ if environ is None else environ
        # Official production path: every final SignalJSON candidate should
        # pass through the execution gate adapter in ENFORCE mode.  The legacy
        # shadow flags remain useful only after this explicit kill switch is
        # set false for diagnostics.
        final_barrier = _env_bool(env, "SIGNAL_JSON_FINAL_BARRIER_ENABLED", True)
        enabled = _env_bool(env, "SIGNAL_JSON_EXEC_GATES_ENABLED", final_barrier)
        enforce = _env_bool(env, "SIGNAL_JSON_EXEC_GATES_ENFORCE", final_barrier)
        if final_barrier:
            enabled = True
            enforce = True
        return cls(
            enabled=enabled,
            enforce=enforce,
            final_barrier=final_barrier,
            emit_continuation=_env_bool(env, "SIGNAL_JSON_EXEC_GATES_EMIT_CONTINUATION", final_barrier),
            emit_sidecar=_env_bool(env, "SIGNAL_JSON_EXEC_GATES_EMIT_SIDECAR", True),
            emit_deferred_as_conditional_final=_env_bool(
                env, "SIGNAL_JSON_EXEC_GATES_EMIT_DEFERRED_FINAL", False
            ),
            prefix=str(env.get("SIGNAL_EXECUTION_GATE_JSON_LOG_PREFIX") or "[SignalExecutionGateJSON]"),
            min_rr_required=_env_float(env, "SIGNAL_JSON_MIN_RR_VALID", SIGNAL_MIN_RR),
            max_chase_r=_env_float(env, "SIGNAL_JSON_EXEC_GATES_MAX_CHASE_R", 0.35),
            rr_fallback_validates_signal=_env_bool(env, "SIGNAL_JSON_RR_FALLBACK_VALIDATES_SIGNAL", False),
        )


class SignalJsonGateAdapter:
    """Output-layer gate adapter with default no-op behavior."""

    def __init__(
        self,
        config: SignalJsonGateConfig | None = None,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self.config = config or SignalJsonGateConfig()
        self.logger = logger or logging.getLogger("signal_json")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> SignalJsonGateAdapter:
        return cls(SignalJsonGateConfig.from_env(environ))

    @property
    def emit_continuation(self) -> bool:
        return self.config.emit_continuation

    def apply(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Return the payload to pass to ``build_signal_json_event``.

        With gates disabled this is a strict no-op. In shadow mode it logs a
        sidecar gate decision and returns the original payload. In enforce mode
        BLOCK final signals are converted to decision updates, while DEFER
        signals keep their direction and become terminal valid SignalJSON
        payloads with ``valid_for_execution=False``.
        """
        if not isinstance(payload, dict) or not self.config.enabled:
            return payload

        decision = evaluate_signal_execution_gates(
            payload,
            min_rr_required=self.config.min_rr_required,
            max_chase_r=self.config.max_chase_r,
            rr_fallback_validates_signal=self.config.rr_fallback_validates_signal,
        )
        if self.config.emit_sidecar and decision.applies:
            self._emit_sidecar(payload, decision)
        if self.config.enforce and decision.applies and not decision.allows_execution:
            if (
                self.config.emit_deferred_as_conditional_final
                and decision.decision == "DEFER"
                and _is_retest_eligible(payload, decision)
            ):
                return self._deferred_as_conditional_final(payload, decision)
            if decision.decision == "DEFER":
                return self._deferred_as_terminal_valid_signal(payload, decision)
            return self._blocked_as_decision_update(payload, decision)
        if self.config.enforce and decision.applies and decision.allows_execution:
            # Contract consistency: when the gate ALLOWS execution, the nested
            # execution_gate.execution_valid_now (built downstream from this flat
            # field) must agree with the top-level valid_for_execution=True so the
            # final never claims execution-ready while its own gate says "not now".
            return {**payload, "execution_valid_now": True}
        return payload

    def _emit_sidecar(self, payload: dict[str, Any], decision: ExecutionGateDecision) -> None:
        sidecar = {
            "event": "signal_execution_gate_json",
            "schema_version": "1.0",
            "schema_extensions": [decision.gate_version],
            "symbol": payload.get("symbol"),
            "signal_family": payload.get("signal_family") or payload.get("signal_type"),
            "cluster_id": payload.get("cluster_id"),
            "signal_id": payload.get("signal_id"),
            "pending_decision_id": payload.get("pending_decision_id"),
            "source_status": payload.get("status"),
            "source_final_direction": payload.get("final_direction"),
            "target_mode": payload.get("target_mode"),
            "target_source": payload.get("target_source"),
            "valid_for_execution": payload.get("valid_for_execution"),
            "enforcement_mode": "ENFORCE" if self.config.enforce else "SHADOW",
            "final_barrier": self.config.final_barrier,
            "exec_gate": decision.to_dict(),
        }
        self.logger.warning(
            "%s %s",
            self.config.prefix,
            json.dumps(sidecar, separators=(",", ":"), ensure_ascii=False),
        )

    @staticmethod
    def _blocked_as_decision_update(
        payload: dict[str, Any],
        decision: ExecutionGateDecision,
    ) -> dict[str, Any]:
        blocked = dict(payload)
        source_status = str(payload.get("status") or "")
        source_direction = str(payload.get("final_direction") or "WAIT")
        reasons = ", ".join(decision.reasons) or decision.execution_status
        reinforcement_management_only = "REINFORCEMENT_MANAGEMENT_ONLY" in decision.reasons
        action = (
            "HOLD_TRAIL_OR_ADD_ONLY_ON_RETEST"
            if reinforcement_management_only
            else "WAIT_EXECUTION_GATE_RECHECK"
        )
        next_action = (
            "MANAGE_ACTIVE_SIGNAL_WAIT_ADD_ON_RETEST"
            if reinforcement_management_only
            else "WAIT_EXECUTION_GATE_RECHECK"
        )
        execution_status = (
            "REINFORCEMENT_MANAGEMENT_ONLY"
            if reinforcement_management_only
            else decision.execution_status
        )
        blocked.update(
            {
                "event": "signal_decision_update_json",
                "source_status": source_status,
                "source_final_direction": source_direction,
                "previous_status": payload.get("previous_status") or source_status,
                "status": "WAIT_STRUCTURE_OR_NEXT_M15",
                "new_status": "WAIT_STRUCTURE_OR_NEXT_M15",
                "final_direction": "WAIT",
                "validated_direction": None,
                "watch_direction": source_direction if source_direction in {"BUY", "SELL"} else payload.get("watch_direction"),
                "direction_validation_status": "FINAL_CANDIDATE_BLOCKED_BY_EXECUTION_GATE",
                "action": action,
                "next_action": next_action,
                "is_final_signal": False,
                "emit_reason": "EXECUTION_GATE_DECISION_UPDATE",
                "signal_quality": "DECISION_UPDATE",
                "valid_for_execution": False,
                "execution_valid_now": False,
                "execution_status": execution_status,
                "execution_grade": "CONDITIONAL",
                "audit_valid": False,
                "audit_block_reasons": list(decision.reasons),
                "reason": (
                    f"{payload.get('reason') or 'signal_candidate'} "
                    f"Execution gate {decision.decision.lower()}: {reasons}."
                ),
            }
        )
        return blocked

    @staticmethod
    def _deferred_as_terminal_valid_signal(
        payload: dict[str, Any],
        decision: ExecutionGateDecision,
    ) -> dict[str, Any]:
        terminal = dict(payload)
        source_status = str(payload.get("status") or "")
        source_direction = str(
            payload.get("final_direction")
            or payload.get("validated_direction")
            or payload.get("candidate_direction")
            or "WAIT"
        ).upper()
        if source_direction not in {"BUY", "SELL"}:
            source_direction = "WAIT"
        terminal_status = _terminal_status_for_defer(decision)
        reasons = ", ".join(decision.reasons) or decision.execution_status
        action = _terminal_action(terminal_status)
        next_action = _terminal_next_action(terminal_status)
        terminal.update(
            {
                "event": "signal_json",
                "source_status": source_status,
                "source_final_direction": payload.get("final_direction") or source_direction,
                "previous_status": payload.get("previous_status") or source_status,
                "status": terminal_status,
                "new_status": terminal_status,
                "terminal_status": terminal_status,
                "final_direction": source_direction,
                "validated_direction": source_direction,
                "watch_direction": payload.get("watch_direction"),
                "direction_validation_status": "FINAL_DIRECTION_VALID_EXECUTION_DEFERRED",
                "action": action,
                "next_action": next_action,
                "is_final_signal": True,
                "signal_valid": True,
                "direction_valid": True,
                "analysis_valid": True,
                "source_valid_for_execution": bool(payload.get("valid_for_execution", False)),
                "tradeplan_valid": _terminal_tradeplan_valid(payload, terminal_status),
                "valid_for_execution": False,
                "execution_valid_now": False,
                "execution_status": _terminal_execution_status(terminal_status),
                "execution_reason": reasons,
                "execution_grade": "TERMINAL_VALID_NON_EXECUTION",
                "terminal_decision_confirmed": True,
                "terminal_decision_event_type": "signal_json",
                "audit_valid": False,
                "audit_block_reasons": list(decision.reasons),
                "emit_reason": "TERMINAL_VALID_SIGNAL",
                "signal_quality": _terminal_signal_quality(terminal_status),
                "exec_gate_decision": decision.decision,
                "exec_gate_defer_reasons": list(decision.reasons),
                "reason": (
                    f"{payload.get('reason') or 'signal_candidate'} "
                    f"Direction valid; execution deferred: {reasons}."
                ),
            }
        )
        return terminal

    @staticmethod
    def _deferred_as_conditional_final(
        payload: dict[str, Any],
        decision: ExecutionGateDecision,
    ) -> dict[str, Any]:
        """Emit a DEFER on a confirmed candidate as a CONDITIONAL final signal.

        The directional plan is valid; only immediate market execution is
        deferred (e.g. waiting a retest or structure confirmation). Rather than
        burying it as a non-final WAIT, keep it final and instruct a pending
        limit at the entry zone with no chasing.
        """
        final = dict(payload)
        reasons = ", ".join(decision.reasons) or decision.execution_status
        final.update(
            {
                "is_final_signal": True,
                "valid_for_execution": True,
                "execution_valid_now": False,
                "execution_mode": "WAIT_RETEST",
                "entry_type": "PENDING_LIMIT",
                "pending_entry_zone": payload.get("entry_zone"),
                "execution_grade": "CONDITIONAL",
                "execution_status": decision.execution_status,
                "direction_validation_status": "FINAL_VALID_PENDING_RETEST",
                "action": "PLACE_PENDING_LIMIT_AT_ENTRY_ZONE_NO_CHASE",
                "next_action": "WAIT_RETEST_FILL_OR_INVALIDATION",
                "emit_reason": "CONDITIONAL_FINAL_WAIT_RETEST",
                "signal_quality": "CONDITIONAL_FINAL",
                "exec_gate_decision": decision.decision,
                "exec_gate_defer_reasons": list(decision.reasons),
                "reason": (
                    f"{payload.get('reason') or 'signal_candidate'} "
                    "Final signal valid; enter on retest of the entry zone (no chase). "
                    f"Execution deferred now because: {reasons}."
                ),
            }
        )
        return final


_RETEST_ELIGIBLE_DEFER_REASONS = frozenset(
    {
        "STRUCTURE_TARGET_MODE_REQUIRED",
        "STRUCTURE_TARGET_AT_MIN_RR_MISSING",
        "SUPPORT_RESISTANCE_LADDER_INCOMPLETE",
        "BREAKOUT_RETEST_NOT_CONFIRMED",
        "BREAKDOWN_RETEST_NOT_CONFIRMED",
        "MICROBOOST_WAIT_M15_RECLAIM_OR_PULLBACK_COMPLETION",
        "MICROBOOST_STRUCTURE_REACTION_CONFIRMATION_REQUIRED",
        "MICROBOOST_PRESSURE_WARNING_CONFIRMATION_REQUIRED",
    }
)

_MANAGEMENT_DEFER_REASONS = frozenset(
    {
        "REINFORCEMENT_MANAGEMENT_ONLY",
    }
)

_STRUCTURE_TARGET_DEFER_REASONS = frozenset(
    {
        "PROVISIONAL_RR_FALLBACK_NOT_EXECUTION_GRADE",
        "STRUCTURE_TARGET_MODE_REQUIRED",
        "STRUCTURE_TARGET_AT_MIN_RR_MISSING",
        "SUPPORT_RESISTANCE_LADDER_INCOMPLETE",
        "TRADEPLAN_CONTRACT_NOT_READY",
        "ENTRY_OR_SELECTED_SL_MISSING",
        "LIVE_RR_INPUT_INCOMPLETE",
    }
)

_RETEST_DEFER_REASONS = frozenset(
    {
        "BREAKOUT_RETEST_NOT_CONFIRMED",
        "BREAKDOWN_RETEST_NOT_CONFIRMED",
        "MICROBOOST_WAIT_M15_RECLAIM_OR_PULLBACK_COMPLETION",
        "MICROBOOST_STRUCTURE_REACTION_CONFIRMATION_REQUIRED",
        "MICROBOOST_PRESSURE_WARNING_CONFIRMATION_REQUIRED",
        "MICROBOOST_STRUCTURE_CONFIRMATION_REQUIRED",
    }
)


def _terminal_status_for_defer(decision: ExecutionGateDecision) -> str:
    reasons = set(decision.reasons)
    if reasons & _MANAGEMENT_DEFER_REASONS:
        return "FINAL_VALID_MANAGEMENT_ONLY"
    if reasons & _STRUCTURE_TARGET_DEFER_REASONS:
        return "FINAL_VALID_WAIT_STRUCTURE_TARGET"
    if reasons & _RETEST_DEFER_REASONS:
        return "FINAL_VALID_WAIT_RETEST"
    return "FINAL_VALID_EXECUTION_DEFERRED"


def _terminal_action(status: str) -> str:
    if status == "FINAL_VALID_MANAGEMENT_ONLY":
        return "HOLD_TRAIL_OR_ADD_ONLY_ON_RETEST"
    if status == "FINAL_VALID_WAIT_RETEST":
        return "WAIT_RETEST_OR_CONFIRMATION"
    if status == "FINAL_VALID_WAIT_STRUCTURE_TARGET":
        return "WAIT_STRUCTURE_TARGET_OR_RETEST"
    return "WAIT_EXECUTION_CONTRACT"


def _terminal_next_action(status: str) -> str:
    if status == "FINAL_VALID_MANAGEMENT_ONLY":
        return "MANAGE_ACTIVE_SIGNAL_OR_WAIT_RETEST"
    if status == "FINAL_VALID_WAIT_RETEST":
        return "WAIT_RETEST_OR_CONFIRMATION"
    if status == "FINAL_VALID_WAIT_STRUCTURE_TARGET":
        return "WAIT_STRUCTURE_TARGET_OR_RETEST"
    return "WAIT_EXECUTION_CONTRACT"


def _terminal_execution_status(status: str) -> str:
    if status == "FINAL_VALID_MANAGEMENT_ONLY":
        return "REINFORCEMENT_MANAGEMENT_ONLY"
    if status == "FINAL_VALID_WAIT_RETEST":
        return "WAIT_RETEST_CONFIRMATION"
    if status == "FINAL_VALID_WAIT_STRUCTURE_TARGET":
        return "WAIT_STRUCTURE_TARGET"
    return "WAIT_EXECUTION_CONTRACT"


def _terminal_signal_quality(status: str) -> str:
    if status == "FINAL_VALID_MANAGEMENT_ONLY":
        return "TERMINAL_VALID_MANAGEMENT_ONLY"
    if status == "FINAL_VALID_WAIT_RETEST":
        return "TERMINAL_VALID_WAIT_RETEST"
    return "TERMINAL_VALID_EXECUTION_DEFERRED"


def _terminal_tradeplan_valid(payload: dict[str, Any], status: str) -> bool:
    if status == "FINAL_VALID_WAIT_STRUCTURE_TARGET":
        return False
    if _truthy(payload.get("tradeplan_valid")):
        return True
    return (
        _truthy(payload.get("tradeplan_context_ready"))
        and _truthy(payload.get("targets_execution_usable"))
        and str(payload.get("rr_status") or "").upper() in {"VALID", "ACCEPTABLE", "PROTECT_ONLY"}
    )


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _is_retest_eligible(payload: dict[str, Any], decision: ExecutionGateDecision) -> bool:
    """True when a DEFER can safely become a WAIT_RETEST conditional final signal."""
    status = str(payload.get("status") or "")
    direction = str(payload.get("final_direction") or "").upper()
    rr_status = str(payload.get("rr_status") or "").upper()
    directionally_valid = (
        status.endswith("_VALID")
        and direction in {"BUY", "SELL"}
        and rr_status in {"VALID", "ACCEPTABLE"}
        and bool(payload.get("valid_for_execution", False))
    )
    if not directionally_valid:
        return False
    reasons = set(decision.reasons)
    return bool(reasons) and reasons.issubset(_RETEST_ELIGIBLE_DEFER_REASONS)


def _env_bool(env: Mapping[str, str], key: str, default: bool) -> bool:
    raw = env.get(key)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_float(env: Mapping[str, str], key: str, default: float) -> float:
    raw = env.get(key)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default
