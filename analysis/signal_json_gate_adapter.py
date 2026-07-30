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
from analysis.signal_json_enrichment import enrich_signal_json_payload
from analysis.signal_thresholds import SIGNAL_MIN_RR

_STRUCTURE_TARGET_MODES = {
    "FINAL_MARKET_STRUCTURE",
    "STRUCTURE_LADDER_TARGET",
    "KEY_LEVEL_STRUCTURE_TARGET",
}


@dataclass(frozen=True)
class SignalJsonGateConfig:
    enabled: bool = False
    enforce: bool = False
    final_barrier: bool = False
    emit_continuation: bool = False
    emit_sidecar: bool = True
    prefix: str = "[SignalExecutionGateJSON]"
    min_rr_required: float = SIGNAL_MIN_RR
    max_chase_r: float = 0.35

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
            prefix=str(env.get("SIGNAL_EXECUTION_GATE_JSON_LOG_PREFIX") or "[SignalExecutionGateJSON]"),
            min_rr_required=_env_float(env, "SIGNAL_JSON_MIN_RR_VALID", SIGNAL_MIN_RR),
            max_chase_r=_env_float(env, "SIGNAL_JSON_EXEC_GATES_MAX_CHASE_R", 0.35),
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
        BLOCK and DEFER candidates are converted to decision updates. Only an
        execution-grade ALLOW may remain a final SignalJSON.
        """
        if not isinstance(payload, dict) or not self.config.enabled:
            return payload

        decision = evaluate_signal_execution_gates(
            payload,
            min_rr_required=self.config.min_rr_required,
            max_chase_r=self.config.max_chase_r,
        )
        if self.config.emit_sidecar and decision.applies:
            self._emit_sidecar(payload, decision)
        if self.config.enforce and decision.applies and not decision.allows_execution:
            if decision.decision == "DEFER":
                return self._deferred_as_decision_update(payload, decision)
            return self._blocked_as_decision_update(payload, decision)
        if self.config.enforce and decision.applies and decision.allows_execution:
            return self._allowed_as_terminal_execution_ready(payload)
        if self.config.enforce and not decision.applies and _is_direction_valid_waiting(payload):
            return self._direction_valid_wait_as_decision_update(payload)
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
            # Reflect the GATE outcome, not the pre-gate input: a blocked/deferred
            # candidate is never execution-valid, so the sidecar must not show
            # valid_for_execution=true on it. The original input is kept separately.
            "valid_for_execution": bool(payload.get("valid_for_execution")) and decision.allows_execution,
            "source_valid_for_execution": payload.get("valid_for_execution"),
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
        action = "HOLD_TRAIL_OR_ADD_ONLY_ON_RETEST" if reinforcement_management_only else "WAIT_EXECUTION_GATE_RECHECK"
        next_action = (
            "MANAGE_ACTIVE_SIGNAL_WAIT_ADD_ON_RETEST"
            if reinforcement_management_only
            else "WAIT_EXECUTION_GATE_RECHECK"
        )
        execution_status = (
            "REINFORCEMENT_MANAGEMENT_ONLY" if reinforcement_management_only else decision.execution_status
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
                "watch_direction": source_direction
                if source_direction in {"BUY", "SELL"}
                else payload.get("watch_direction"),
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
    def _deferred_as_decision_update(
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
                "event": "signal_decision_update_json",
                "source_status": source_status,
                "source_final_direction": payload.get("final_direction") or source_direction,
                "previous_status": payload.get("previous_status") or source_status,
                "status": terminal_status,
                "new_status": terminal_status,
                "terminal_status": terminal_status,
                "final_direction": "WAIT",
                "validated_direction": source_direction,
                "watch_direction": source_direction
                if source_direction in {"BUY", "SELL"}
                else payload.get("watch_direction"),
                "direction_validation_status": "FINAL_DIRECTION_VALID_EXECUTION_DEFERRED",
                "action": action,
                "next_action": next_action,
                "is_final_signal": False,
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
                "terminal_decision_event_type": "signal_decision_update_json",
                "audit_valid": False,
                "audit_block_reasons": list(decision.reasons),
                "emit_reason": "EXECUTION_DEFERRED_DECISION_UPDATE",
                "signal_quality": _terminal_signal_quality(terminal_status),
                "exec_gate_decision": decision.decision,
                "exec_gate_defer_reasons": list(decision.reasons),
                "reason": (
                    f"{payload.get('reason') or 'signal_candidate'} Direction valid; execution deferred: {reasons}."
                ),
            }
        )
        return terminal

    @staticmethod
    def _allowed_as_terminal_execution_ready(payload: dict[str, Any]) -> dict[str, Any]:
        """Normalize an ALLOW decision into the terminal execution contract."""
        tradeplan = payload.get("tradeplan_preview")
        nested_target_mode = tradeplan.get("target_mode") if isinstance(tradeplan, dict) else None
        source_target_mode = str(nested_target_mode or payload.get("target_mode") or "").upper()
        direction = str(
            payload.get("final_direction")
            or payload.get("validated_direction")
            or payload.get("candidate_direction")
            or "WAIT"
        ).upper()
        if direction not in {"BUY", "SELL"}:
            return SignalJsonGateAdapter._deferred_as_decision_update(
                payload,
                ExecutionGateDecision(
                    applies=True,
                    decision="DEFER",
                    execution_status="EXECUTION_GATE_DEFERRED",
                    blocked_by=("DirectionContractGate",),
                    reasons=("FINAL_DIRECTION_NOT_VALIDATED",),
                ),
            )

        if source_target_mode not in _STRUCTURE_TARGET_MODES:
            return SignalJsonGateAdapter._deferred_as_decision_update(
                payload,
                ExecutionGateDecision(
                    applies=True,
                    decision="DEFER",
                    execution_status="EXECUTION_GATE_DEFERRED",
                    blocked_by=("TradePlanCompletenessGate",),
                    reasons=("STRUCTURE_TARGET_MODE_REQUIRED",),
                ),
            )

        enriched = enrich_signal_json_payload({**payload, "execution_valid_now": True})
        terminal = dict(enriched)
        source_status = str(payload.get("status") or "")
        terminal.update(
            {
                "event": "signal_json",
                "source_status": source_status,
                "source_final_direction": payload.get("final_direction") or direction,
                "previous_status": payload.get("previous_status") or source_status,
                "status": "FINAL_EXECUTION_READY",
                "new_status": "FINAL_EXECUTION_READY",
                "terminal_status": "FINAL_EXECUTION_READY",
                "final_direction": direction,
                "validated_direction": direction,
                "direction_validation_status": "VALIDATED_EXECUTION",
                "signal_valid": True,
                "direction_valid": True,
                "analysis_valid": True,
                "tradeplan_valid": True,
                "valid_for_execution": True,
                "execution_valid_now": True,
                "execution_status": "EXECUTION_READY",
                "execution_grade": "FINAL_STRUCTURE",
                "audit_valid": True,
                "audit_block_reasons": [],
                "emit_reason": "TERMINAL_EXECUTION_READY",
                "signal_quality": "FINAL_EXECUTION_READY",
                "next_action": "EXECUTE_OR_SEND_TRADE_PLAN",
                "exec_gate_decision": "ALLOW",
                "reason": (
                    f"{payload.get('reason') or 'signal_candidate'} "
                    "Direction, tradeplan, RR, and execution gate are ready."
                ),
            }
        )
        strategy_proof = payload.get("strategy_5scr")
        if isinstance(strategy_proof, dict):
            execution_gate = terminal.get("execution_gate")
            bound_gate = dict(execution_gate) if isinstance(execution_gate, dict) else {}
            bound_gate["strategy_5scr"] = strategy_proof
            terminal["execution_gate"] = bound_gate
        if not _has_parent_or_pending_decision(terminal):
            terminal.update(
                {
                    "parent_event_type": None,
                    "parent_event_exists": False,
                    "parent_watch_id": None,
                    "parent_watch_required": False,
                    "promotion_path": "DIRECT_BYPASS",
                    "bypass_reason": "EXECUTION_GATE_ALLOWED_DIRECT_SIGNAL",
                    "terminal_decision_confirmed": True,
                    "terminal_decision_event_type": "signal_json",
                }
            )
        return terminal

    @staticmethod
    def _direction_valid_wait_as_decision_update(payload: dict[str, Any]) -> dict[str, Any]:
        terminal = dict(payload)
        direction = _direction_from_payload(payload)
        status = _terminal_status_for_direction_valid_wait(payload)
        terminal.update(
            {
                "event": "signal_decision_update_json",
                "source_status": payload.get("status"),
                "source_final_direction": payload.get("final_direction") or direction,
                "previous_status": payload.get("previous_status") or payload.get("status"),
                "status": status,
                "new_status": status,
                "terminal_status": status,
                "final_direction": "WAIT",
                "validated_direction": direction,
                "watch_direction": direction,
                "direction_validation_status": "FINAL_DIRECTION_VALID_EXECUTION_DEFERRED",
                "action": _terminal_action(status),
                "next_action": _terminal_next_action(status),
                "is_final_signal": False,
                "signal_valid": True,
                "direction_valid": True,
                "analysis_valid": True,
                "source_valid_for_execution": bool(payload.get("valid_for_execution", False)),
                "tradeplan_valid": _terminal_tradeplan_valid(payload, status),
                "valid_for_execution": False,
                "execution_valid_now": False,
                "execution_status": _terminal_execution_status(status),
                "execution_reason": payload.get("target_block_reason")
                or payload.get("tp_missing_reason")
                or "execution_contract_not_ready",
                "execution_grade": "TERMINAL_VALID_NON_EXECUTION",
                "terminal_decision_confirmed": True,
                "terminal_decision_event_type": "signal_decision_update_json",
                "audit_valid": False,
                "audit_block_reasons": _direction_valid_wait_reasons(payload),
                "emit_reason": "EXECUTION_DEFERRED_DECISION_UPDATE",
                "signal_quality": _terminal_signal_quality(status),
                "reason": (
                    f"{payload.get('reason') or 'signal_candidate'} "
                    "Direction valid; execution remains deferred in DecisionUpdate."
                ),
            }
        )
        return terminal


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


def _is_direction_valid_waiting(payload: dict[str, Any]) -> bool:
    if str(payload.get("event") or "") == "signal_decision_update_json":
        return False
    if _truthy(payload.get("valid_for_execution")):
        return False
    direction = _direction_from_payload(payload)
    if direction not in {"BUY", "SELL"}:
        return False
    if _truthy(payload.get("requires_m15_close")):
        return False
    status = str(payload.get("status") or "").upper()
    direction_status = str(payload.get("direction_status") or payload.get("direction_validation_status") or "").upper()
    target_mode = str(payload.get("target_mode") or "").upper()
    has_structure_wait = (
        status in {"WAIT_M15_CLOSE_OR_STRUCTURE_TARGET", "WAIT_STRUCTURE_OR_NEXT_M15"}
        or target_mode in {"PROVISIONAL_RR_FALLBACK", "NONE"}
        or _truthy(payload.get("tradeplan_context_ready")) is False
        or _truthy(payload.get("targets_execution_usable")) is False
    )
    has_direction_contract = (
        _truthy(payload.get("direction_valid"))
        or _truthy(payload.get("signal_valid"))
        or "VALID" in direction_status
        or "AWAIT" in direction_status
    )
    return has_structure_wait and has_direction_contract


def _direction_from_payload(payload: dict[str, Any]) -> str:
    for key in ("final_direction", "validated_direction", "candidate_direction"):
        direction = str(payload.get(key) or "").upper()
        if direction in {"BUY", "SELL"}:
            return direction
    return "WAIT"


def _terminal_status_for_direction_valid_wait(payload: dict[str, Any]) -> str:
    if str(payload.get("lifecycle_status") or "").upper() == "REINFORCES_ACTIVE_SIGNAL":
        return "FINAL_VALID_MANAGEMENT_ONLY"
    action = str(payload.get("action") or "").upper()
    if "RETEST" in action and str(payload.get("target_mode") or "").upper() not in {"PROVISIONAL_RR_FALLBACK", "NONE"}:
        return "FINAL_VALID_WAIT_RETEST"
    return "FINAL_VALID_WAIT_STRUCTURE_TARGET"


def _direction_valid_wait_reasons(payload: dict[str, Any]) -> list[str]:
    reasons = []
    for key in ("target_block_reason", "tp_missing_reason", "execution_reason", "block_reason"):
        value = payload.get(key)
        if value:
            reasons.append(str(value))
    if not _truthy(payload.get("tradeplan_context_ready")):
        reasons.append("TRADEPLAN_CONTRACT_NOT_READY")
    if not _truthy(payload.get("targets_execution_usable")):
        reasons.append("TARGETS_EXECUTION_NOT_USABLE")
    return list(dict.fromkeys(reasons)) or ["EXECUTION_CONTRACT_NOT_READY"]


def _has_parent_or_pending_decision(payload: dict[str, Any]) -> bool:
    return bool(
        payload.get("pending_decision_id")
        or payload.get("parent_watch_id")
        or _truthy(payload.get("parent_event_exists"))
    )


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
