"""SignalThrottle Fusion V3 diagnostic router.

This router explains where pure pressure currently sits in the lifecycle. It
never emits SignalJSON, never grants execution permission, and never resolves
final trade direction.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def build_signal_throttle_fusion_v3_diagnostic(
    pure_candidate: Mapping[str, Any] | None,
    *,
    radar_context_validation: Mapping[str, Any] | None = None,
    execution_context_validation: Mapping[str, Any] | None = None,
    microboost_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    pressure_seen = isinstance(pure_candidate, Mapping) and bool(pure_candidate.get("symbol"))
    raw_direction = _direction(pure_candidate)
    radar_ready = bool((radar_context_validation or {}).get("radar_context_ready", False))
    execution_ready = bool((execution_context_validation or {}).get("direction_validated", False))
    microboost_detected = isinstance((microboost_summary or {}).get("latest"), Mapping)

    status, reason, next_stage = _route_status(
        pressure_seen=pressure_seen,
        raw_direction=raw_direction,
        radar_ready=radar_ready,
        execution_ready=execution_ready,
        execution_context_validation=execution_context_validation,
        microboost_detected=microboost_detected,
    )

    return {
        "event": "signal_throttle_fusion_v3",
        "status": status,
        "symbol": None if pure_candidate is None else str(pure_candidate.get("symbol") or "").upper() or None,
        "pressure_seen": pressure_seen,
        "pressure_event_count": _int_value(None if pure_candidate is None else pure_candidate.get("events")),
        "raw_pressure_direction": raw_direction or "NONE",
        "direction_status": "UNRESOLVED" if raw_direction is None else "RAW_RECOVERED",
        "radar_context_ready": radar_ready,
        "execution_context_ready": execution_ready,
        "microboost_detected": microboost_detected,
        "next_stage": next_stage,
        "reason": reason,
        "source_pressure_block_id": None
        if pure_candidate is None
        else pure_candidate.get("source_pressure_block_id") or pure_candidate.get("source_clean_block_id"),
        "source_clean_block_id": None if pure_candidate is None else pure_candidate.get("source_clean_block_id"),
        "final_direction": "WAIT",
        "valid_for_execution": False,
        "execution_valid_now": False,
        "is_final_signal": False,
        "signal_valid": False,
        "execution_tier": "WAIT",
        "advisory_only": True,
    }


def _route_status(
    *,
    pressure_seen: bool,
    raw_direction: str | None,
    radar_ready: bool,
    execution_ready: bool,
    execution_context_validation: Mapping[str, Any] | None,
    microboost_detected: bool,
) -> tuple[str, str, str]:
    if not pressure_seen:
        return ("NO_PURE_PRESSURE", "no_pure_pressure_candidate", "WAIT_PRESSURE")
    if raw_direction is None:
        return ("PURE_RADAR_ONLY", "pure_pressure_without_direction", "WAIT_DIRECTION")
    if _direction_conflict(raw_direction, execution_context_validation):
        return ("WAIT_DIRECTION_CONFLICT", "execution_context_direction_conflict", "WAIT_DIRECTION_RESOLUTION")
    if not radar_ready:
        return ("CLEAN_BLOCK_WATCH_PENDING_CONTEXT", "radar_context_missing_or_partial", "HYDRATE_RADAR_CONTEXT")
    if not execution_ready:
        next_stage = "SIGNAL_WATCH" if microboost_detected else "WAIT_MICROBOOST_OR_STRUCTURE"
        return ("CLEAN_BLOCK_WATCH_PENDING_STRUCTURE", "execution_context_not_ready", next_stage)
    return ("CLEAN_BLOCK_WATCH_PENDING_EXECUTION_FIREWALL", "execution_context_ready_but_firewall_required", "SIGNALJSON_GATE")


def _direction_conflict(raw_direction: str, validation: Mapping[str, Any] | None) -> bool:
    if not isinstance(validation, Mapping):
        return False
    final_direction = str(validation.get("final_direction") or "").upper()
    if final_direction not in {"BUY", "SELL"}:
        return False
    return final_direction != raw_direction


def _direction(candidate: Mapping[str, Any] | None) -> str | None:
    if not isinstance(candidate, Mapping):
        return None
    for key in ("raw_pressure_direction", "clean_block_direction", "direction"):
        value = str(candidate.get(key) or "").upper()
        if value in {"BUY", "SELL"}:
            return value
    return None


def _int_value(value: Any) -> int:
    if value is None or isinstance(value, bool):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


__all__ = ["build_signal_throttle_fusion_v3_diagnostic"]
