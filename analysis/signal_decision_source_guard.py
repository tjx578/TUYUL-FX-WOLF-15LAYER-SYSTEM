"""Guard routing between pressure telemetry and SignalDecision lifecycle events.

SignalDecisionUpdateJSON is reserved for Watch/Finalizer/ExecutionGate lifecycle
decisions.  Pressure-only observations are routed to SignalPressureStateJSON so
they remain observable without polluting the decision channel.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

ALLOWED_DECISION_SOURCES = frozenset({"SIGNAL_WATCH", "BLOCK_FINALIZER", "EXECUTION_GATE"})
PRESSURE_ONLY_SOURCES = frozenset(
    {
        "SIGNAL_THROTTLE",
        "SIGNAL_THROTTLE_INTEL",
        "PRESSURE_BLOCK",
        "CANDIDATE_LIFECYCLE",
        "MICROBOOST",
    }
)
PRESSURE_FAMILIES = frozenset({"SIGNAL_THROTTLE_PRESSURE", "SIGNAL_THROTTLE_ALLOWED_QUORUM"})


@dataclass(frozen=True)
class SignalDecisionRoute:
    route: str
    can_emit_signal_decision: bool
    reason: str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def route_decision_or_pressure(
    payload: Mapping[str, Any],
    *,
    require_lifecycle_anchor: bool = True,
) -> SignalDecisionRoute:
    if can_emit_signal_decision(payload, require_lifecycle_anchor=require_lifecycle_anchor):
        return SignalDecisionRoute(
            route="SIGNAL_DECISION_UPDATE",
            can_emit_signal_decision=True,
            reason="allowed_decision_source_with_lifecycle_anchor",
            payload=dict(payload),
        )
    pressure_payload = convert_to_signal_pressure_state(payload)
    return SignalDecisionRoute(
        route="SIGNAL_PRESSURE_STATE",
        can_emit_signal_decision=False,
        reason=str(pressure_payload.get("route_reason") or "pressure_only_routed_out_of_decision_channel"),
        payload=pressure_payload,
    )


def can_emit_signal_decision(
    payload: Mapping[str, Any],
    *,
    require_lifecycle_anchor: bool = True,
) -> bool:
    source_stage = _source_stage(payload)
    if source_stage not in ALLOWED_DECISION_SOURCES:
        return False
    if not require_lifecycle_anchor:
        return True
    return has_lifecycle_anchor(payload, source_stage=source_stage)


def has_lifecycle_anchor(payload: Mapping[str, Any], *, source_stage: str | None = None) -> bool:
    source = source_stage or _source_stage(payload)
    if _text(payload.get("source_watch_id")):
        return True
    if _text(payload.get("source_clean_block_id")):
        return True
    if _text(payload.get("pending_decision_id")):
        return True
    cluster_id = _text(payload.get("cluster_id"))
    return bool(cluster_id and source in {"SIGNAL_WATCH", "BLOCK_FINALIZER"})


def convert_to_signal_pressure_state(payload: Mapping[str, Any]) -> dict[str, Any]:
    source_stage = _source_stage(payload)
    source_family = _text(payload.get("source_family")) or _text(payload.get("signal_family"))
    pressure_payload = dict(payload)
    pressure_payload.update(
        {
            "event": "signal_pressure_state_json",
            "promotion_stage": "PRESSURE_ONLY",
            "source_stage": source_stage or "UNKNOWN",
            "source_family": source_family,
            "terminal_status": "PRESSURE_ONLY",
            "status": _pressure_status(payload),
            "final_direction": "WAIT",
            "validated_direction": None,
            "valid_for_execution": False,
            "execution_valid_now": False,
            "is_final_signal": False,
            "signal_valid": False,
            "tradeplan_valid": False,
            "eligible_for_signal_decision": False,
            "next_required_stage": "MICROBOOST_OR_MARKET_CONTEXT",
            "route_reason": _route_reason(payload, source_stage),
            "signal_quality": "PRESSURE_STATE_ONLY",
        }
    )
    pressure_payload.pop("signal_json_emit_result", None)
    return pressure_payload


def _source_stage(payload: Mapping[str, Any]) -> str | None:
    explicit = _text(payload.get("source_stage"))
    if explicit:
        return explicit.upper()
    family = _text(payload.get("signal_family"))
    trigger = _text(payload.get("decision_update_trigger"))
    if family in PRESSURE_FAMILIES:
        return "SIGNAL_THROTTLE_INTEL"
    if trigger in {"NON_EXECUTE_PRESSURE_CANARY", "ALLOWED_QUORUM_CONTEXT_INCOMPLETE"}:
        return "SIGNAL_THROTTLE_INTEL"
    return None


def _pressure_status(payload: Mapping[str, Any]) -> str:
    trigger = _text(payload.get("decision_update_trigger"))
    if trigger == "ALLOWED_QUORUM_CONTEXT_INCOMPLETE":
        return "ALLOWED_QUORUM_WAIT_CONTEXT"
    if trigger == "NON_EXECUTE_PRESSURE_CANARY":
        return "PRESSURE_CANARY"
    source_stage = _source_stage(payload)
    if source_stage in PRESSURE_ONLY_SOURCES:
        return "PRESSURE_ONLY"
    return "PRESSURE_STATE"


def _route_reason(payload: Mapping[str, Any], source_stage: str | None) -> str:
    if source_stage not in ALLOWED_DECISION_SOURCES:
        return "source_stage_not_allowed_for_signal_decision"
    if not has_lifecycle_anchor(payload, source_stage=source_stage):
        return "missing_lifecycle_anchor"
    return "pressure_only_routed_out_of_decision_channel"


def _text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text.upper() if text else None


__all__ = [
    "ALLOWED_DECISION_SOURCES",
    "PRESSURE_FAMILIES",
    "PRESSURE_ONLY_SOURCES",
    "SignalDecisionRoute",
    "can_emit_signal_decision",
    "convert_to_signal_pressure_state",
    "has_lifecycle_anchor",
    "route_decision_or_pressure",
]
