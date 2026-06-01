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


@dataclass(frozen=True)
class SignalJsonGateConfig:
    enabled: bool = False
    enforce: bool = False
    final_barrier: bool = False
    emit_continuation: bool = False
    emit_sidecar: bool = True
    prefix: str = "[SignalExecutionGateJSON]"
    min_rr_required: float = 2.5
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
            min_rr_required=_env_float(env, "SIGNAL_JSON_MIN_RR_VALID", 2.5),
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
        blocked/deferred final signals are converted to decision updates.
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
            return self._blocked_as_decision_update(payload, decision)
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
