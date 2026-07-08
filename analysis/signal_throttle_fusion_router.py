"""SignalThrottle Fusion V3 diagnostic router.

This router explains where pure pressure currently sits in the lifecycle. It
never emits SignalJSON, never grants execution permission, and never resolves
final trade direction.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from numbers import Real
from typing import Any

DEFAULT_SIGNAL_THROTTLE_FUSION_V3_LOGGER = "signal_throttle_fusion_v3"
DEFAULT_SIGNAL_THROTTLE_FUSION_V3_PREFIX = "[SignalThrottleFusionV3]"


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
    conflict = _direction_conflict(raw_direction, execution_context_validation) if raw_direction else False

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
        "block_type": "PURE_PRESSURE_BLOCK" if pressure_seen else None,
        "ledger_type": _text_value(pure_candidate, "ledger_type"),
        "ledger_source": _text_value(pure_candidate, "ledger_source"),
        "symbol": None if pure_candidate is None else str(pure_candidate.get("symbol") or "").upper() or None,
        "block_id": _block_id(pure_candidate),
        "start_ts": _text_value(pure_candidate, "block_start_utc", "start_utc", "start"),
        "end_ts": _text_value(pure_candidate, "block_end_utc", "end_utc", "end"),
        "duration_minutes": _duration_minutes(pure_candidate),
        "event_count": _int_value(None if pure_candidate is None else pure_candidate.get("events")),
        "density_per_minute": _float_value(
            None
            if pure_candidate is None
            else pure_candidate.get("effective_density_per_minute") or pure_candidate.get("density_per_minute")
        ),
        "max_gap_seconds": _float_value(None if pure_candidate is None else pure_candidate.get("max_gap_seconds")),
        "gap_split_applied": bool(pure_candidate.get("gap_split_applied", False))
        if isinstance(pure_candidate, Mapping)
        else False,
        "split_rule": _text_value(pure_candidate, "split_rule") or "PAIR_ROTATION_ONLY",
        "gap_policy": _text_value(pure_candidate, "gap_policy") or "QUALITY_ONLY",
        "scanner_cycle_aware": bool(pure_candidate.get("scanner_cycle_aware", False))
        if isinstance(pure_candidate, Mapping)
        else False,
        "pure_pressure_score": _float_value(
            None if pure_candidate is None else pure_candidate.get("pure_pressure_score")
        ),
        "heat_score": _float_value(None if pure_candidate is None else pure_candidate.get("heat_score")),
        "pressure_class": _text_value(pure_candidate, "pressure_class"),
        "pressure_seen": pressure_seen,
        "pressure_event_count": _int_value(None if pure_candidate is None else pure_candidate.get("events")),
        "raw_pressure_direction": raw_direction,
        "direction_status": _direction_status(
            raw_direction=raw_direction,
            execution_ready=execution_ready,
            conflict=conflict,
        ),
        "market_structure_status": _market_structure_status(
            execution_context_validation=execution_context_validation,
            execution_ready=execution_ready,
            conflict=conflict,
        ),
        "radar_context_ready": radar_ready,
        "execution_context_ready": execution_ready,
        "microboost_detected": microboost_detected,
        "next_stage": next_stage,
        "reason": reason,
        "source_pressure_block_id": None
        if pure_candidate is None
        else pure_candidate.get("source_pressure_block_id") or pure_candidate.get("source_clean_block_id"),
        "source_clean_block_id": None if pure_candidate is None else pure_candidate.get("source_clean_block_id"),
        "source_stream_profile": _mapping_value(pure_candidate, "source_stream_profile"),
        "raw_signal_throttle_severity_profile": _mapping_value(
            pure_candidate,
            "raw_signal_throttle_severity_profile",
        ),
        "raw_signal_throttle_error_count": _int_value(
            None if pure_candidate is None else pure_candidate.get("raw_signal_throttle_error_count")
        ),
        "raw_signal_throttle_primary_severity": _text_value(
            pure_candidate,
            "raw_signal_throttle_primary_severity",
        ),
        "raw_pressure_origin": _text_value(pure_candidate, "raw_pressure_origin"),
        "final_direction": "WAIT",
        "valid_for_execution": False,
        "execution_valid_now": False,
        "is_final_signal": False,
        "signal_valid": False,
        "execution_tier": "WAIT",
        "advisory_only": True,
    }


def emit_signal_throttle_fusion_v3_diagnostic(
    payload: Mapping[str, Any] | None,
    *,
    prefix: str | None = None,
    logger_name: str | None = None,
) -> bool:
    """Emit Fusion V3 diagnostics on a dedicated SignalThrottle lane.

    This must never use ``signal_json`` and must not be parsed back into the
    raw ``[SignalThrottle]`` pressure stream.
    """

    if not isinstance(payload, Mapping):
        return False
    data = dict(payload)
    data["event"] = "signal_throttle_fusion_v3"
    data["final_direction"] = "WAIT"
    data["valid_for_execution"] = False
    data["execution_valid_now"] = False
    data["is_final_signal"] = False
    data["signal_valid"] = False
    data["advisory_only"] = True
    logging.getLogger(
        logger_name
        or os.getenv("SIGNAL_THROTTLE_FUSION_V3_LOGGER", DEFAULT_SIGNAL_THROTTLE_FUSION_V3_LOGGER)
    ).warning(
        "%s %s",
        prefix or os.getenv("SIGNAL_THROTTLE_FUSION_V3_LOG_PREFIX", DEFAULT_SIGNAL_THROTTLE_FUSION_V3_PREFIX),
        json.dumps(data, separators=(",", ":"), ensure_ascii=False),
    )
    return True


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
        return ("PURE_RADAR_ONLY", "pure_pressure_without_direction", "SIGNAL_WATCH")
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


def _direction_status(*, raw_direction: str | None, execution_ready: bool, conflict: bool) -> str:
    if raw_direction is None:
        return "UNRESOLVED"
    if conflict:
        return "CONFLICT"
    if execution_ready:
        return "STRUCTURE_ALIGNED"
    return "RAW_RECOVERED"


def _market_structure_status(
    *,
    execution_context_validation: Mapping[str, Any] | None,
    execution_ready: bool,
    conflict: bool,
) -> str:
    if conflict:
        return "CONFLICT"
    if execution_ready:
        return "ALIGNED"
    if isinstance(execution_context_validation, Mapping) and execution_context_validation.get("requires_market_context") is False:
        return "PARTIAL"
    return "PENDING"


def _block_id(candidate: Mapping[str, Any] | None) -> str | None:
    if not isinstance(candidate, Mapping):
        return None
    for key in ("source_pressure_block_id", "source_clean_block_id", "block_id", "cluster_id"):
        value = str(candidate.get(key) or "").strip()
        if value:
            return value
    return None


def _duration_minutes(candidate: Mapping[str, Any] | None) -> float | None:
    if not isinstance(candidate, Mapping):
        return None
    existing = _float_value(candidate.get("duration_minutes"))
    if existing is not None:
        return existing
    seconds = _float_value(candidate.get("duration_seconds"))
    return None if seconds is None else round(seconds / 60.0, 3)


def _int_value(value: Any) -> int:
    if value is None or isinstance(value, bool):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _float_value(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Real):
        return round(float(value), 3)
    try:
        text = str(value).strip()
        return round(float(text), 3) if text else None
    except (TypeError, ValueError):
        return None


def _text_value(candidate: Mapping[str, Any] | None, *keys: str) -> str | None:
    if not isinstance(candidate, Mapping):
        return None
    for key in keys:
        value = str(candidate.get(key) or "").strip()
        if value and value.upper() != "NONE":
            return value
    return None


def _mapping_value(candidate: Mapping[str, Any] | None, key: str) -> dict[str, Any] | None:
    if not isinstance(candidate, Mapping):
        return None
    value = candidate.get(key)
    return dict(value) if isinstance(value, Mapping) else None


__all__ = [
    "DEFAULT_SIGNAL_THROTTLE_FUSION_V3_LOGGER",
    "DEFAULT_SIGNAL_THROTTLE_FUSION_V3_PREFIX",
    "build_signal_throttle_fusion_v3_diagnostic",
    "emit_signal_throttle_fusion_v3_diagnostic",
]
