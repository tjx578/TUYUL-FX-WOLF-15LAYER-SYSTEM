"""Guard routing between pressure telemetry and SignalDecision lifecycle events.

SignalDecisionUpdateJSON is reserved for Watch/Finalizer/ExecutionGate lifecycle
decisions.  Pressure-only observations are routed to SignalPressureStateJSON so
they remain observable without polluting the decision channel.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from analysis.signal_pressure_state_emitter import signal_pressure_runtime_identity

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
PRESSURE_STATE_SCHEMA_VERSION = "2.0-pressure-state"


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
            **signal_pressure_runtime_identity(),
        }
    )
    pressure_payload.pop("signal_json_emit_result", None)
    return _apply_pressure_state_contract_v2(pressure_payload)


def _apply_pressure_state_contract_v2(payload: dict[str, Any]) -> dict[str, Any]:
    payload["schema_version"] = PRESSURE_STATE_SCHEMA_VERSION
    _apply_price_lineage_contract(payload)
    _apply_entry_field_integrity(payload)
    _apply_direction_scope_contract(payload)

    htf = payload.get("htf_structure_context")
    htf_context = htf if isinstance(htf, dict) else {}
    structural_location = _text_value(payload.get("structural_price_location")) or _text_value(
        htf_context.get("price_location")
    )
    payload["structural_price_location"] = structural_location
    payload["price_location"] = structural_location if payload.get("observed_price") is not None else "UNKNOWN"
    payload["price_location_operational_status"] = (
        "OBSERVED_PRICE_LINEAGE_AVAILABLE" if payload.get("observed_price") is not None else "UNKNOWN_NO_OBSERVED_PRICE"
    )

    context_basis = {
        "symbol": payload.get("symbol"),
        "cluster_id": payload.get("cluster_id"),
        "status": payload.get("status"),
        "terminal_status": payload.get("terminal_status"),
        "source_stage": payload.get("source_stage"),
        "source_family": payload.get("source_family"),
        "raw_direction": payload.get("raw_direction"),
        "pressure_direction_resolution": payload.get("pressure_direction_resolution"),
        "reference_price_status": payload.get("reference_price_status"),
        "reference_price_source": payload.get("reference_price_source"),
        "structural_price_location": structural_location,
        "htf_structure_context": _stable_htf_context(htf_context),
    }
    digest = hashlib.sha256(
        json.dumps(context_basis, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()[:16]
    payload["context_version"] = f"pressure-context-v2:{digest}"
    lifecycle_identity = "|".join(
        (
            str(payload.get("deployment_id") or "unknown"),
            str(payload.get("cluster_id") or payload.get("symbol") or "unknown"),
            str(payload.get("terminal_status") or payload.get("status") or "PRESSURE_ONLY"),
            payload["context_version"],
        )
    )
    payload["pressure_lifecycle_key"] = lifecycle_identity
    required = (
        "observed_price",
        "observed_price_source",
        "observed_price_time",
        "observed_price_age_seconds",
        "observed_price_status",
        "reference_price",
        "reference_price_source",
        "reference_price_time",
        "reference_price_age_seconds",
        "reference_price_role",
        "reference_price_status",
        "raw_direction_role",
        "pressure_direction_resolution",
        "context_version",
    )
    payload["schema_contract_complete"] = all(key in payload for key in required)
    return payload


def _apply_price_lineage_contract(payload: dict[str, Any]) -> None:
    reference_price = _first_number(
        payload.get("reference_price"),
        payload.get("reference_price_used_for_decision_update"),
        payload.get("entry_reference_price"),
        payload.get("signal_valid_price"),
    )
    source = _text_value(payload.get("reference_price_source") or payload.get("price_source")) or "UNKNOWN"
    snapshot_time = payload.get("reference_price_time") or payload.get("price_snapshot_time_utc")
    age_seconds = _first_non_negative_number(
        payload.get("reference_price_age_seconds"), payload.get("price_age_seconds")
    )
    freshness = _text_value(payload.get("price_freshness_status")) or "UNKNOWN"
    is_observed_source = source.startswith("LIVE_TICK") or source.endswith("_CLOSE")
    observed_price = _first_number(payload.get("observed_price"))
    if observed_price is None and is_observed_source:
        observed_price = reference_price
    reference_is_live = bool(payload.get("reference_price_is_live"))
    if reference_price is None:
        reference_status = "MISSING"
    elif reference_is_live:
        reference_status = "LIVE"
    elif "STALE" in freshness or freshness == "NO_PRODUCER":
        reference_status = "STALE"
    else:
        reference_status = "AVAILABLE"

    age_limit = _reference_price_max_age_seconds(source)
    if reference_status == "AVAILABLE":
        if age_limit is not None and age_seconds is not None and age_seconds > age_limit:
            reference_status = "STALE"
        elif source == "UNKNOWN" and snapshot_time is None and age_seconds is None:
            # A price with no source, no timestamp, and no age cannot be trusted
            # as anything better than an unverified reference.
            reference_status = "UNVERIFIED"

    payload.update(
        {
            "observed_price": observed_price,
            "observed_price_source": source if observed_price is not None else None,
            "observed_price_time": payload.get("observed_price_time") or snapshot_time,
            "observed_price_age_seconds": _first_non_negative_number(
                payload.get("observed_price_age_seconds"), age_seconds
            ),
            "observed_price_status": reference_status if observed_price is not None else "MISSING",
            "reference_price": reference_price,
            "reference_price_source": source,
            "reference_price_time": snapshot_time,
            "reference_price_age_seconds": age_seconds,
            "reference_price_role": "REFERENCE_ONLY_NOT_EXECUTABLE",
            "reference_price_status": reference_status,
            "reference_price_age_limit_seconds": age_limit,
            "decision_price_role": "REFERENCE_ONLY_NOT_EXECUTABLE",
            "price_lineage_version": 2,
        }
    )


_REFERENCE_PRICE_MAX_AGE_DEFAULTS: tuple[tuple[str, float], ...] = (
    ("LIVE_TICK", 60.0),
    ("M1_CLOSE", 180.0),
    ("M5_CLOSE", 600.0),
    ("M15_CLOSE", 1800.0),
    ("H1_CLOSE", 7200.0),
    ("H4_CLOSE", 28800.0),
    ("D1_CLOSE", 172800.0),
)


def _reference_price_max_age_seconds(source: str) -> float | None:
    override = os.getenv("SIGNAL_PRESSURE_REFERENCE_MAX_AGE_SECONDS", "").strip()
    if override:
        try:
            parsed = float(override)
        except ValueError:
            parsed = None
        if parsed is not None and parsed > 0.0:
            return parsed
    normalized = str(source or "").upper()
    for token, max_age in _REFERENCE_PRICE_MAX_AGE_DEFAULTS:
        if normalized.startswith(token) or normalized.endswith(token):
            return max_age
    return None


def _apply_entry_field_integrity(payload: dict[str, Any]) -> None:
    """Mirror the Watch-path price-integrity contract on the pressure channel.

    Without a LIVE observed quote, entry-shaped fields must not carry an
    audit/reference price: a stale number duplicated into ``signal_valid_price``,
    ``entry_reference_price`` and ``entry_zone`` reads as four independent pieces
    of evidence downstream when it is one unverified value.  The original values
    stay visible via ``reference_signal_price`` / ``reference_entry_price`` and
    the reference lineage fields.
    """
    if os.getenv("SIGNAL_PRESSURE_ENTRY_FIELD_INTEGRITY_ENABLED", "false").strip().lower() != "true":
        return
    operational = payload.get("observed_price") is not None and payload.get("observed_price_status") == "LIVE"
    payload["operational_price_valid"] = operational
    if operational:
        return
    payload.setdefault("reference_signal_price", payload.get("signal_valid_price"))
    payload.setdefault("reference_entry_price", payload.get("entry_reference_price"))
    payload["signal_valid_price"] = None
    payload["entry_reference_price"] = None
    payload["entry_zone"] = None
    payload["entry_field_integrity_reason"] = "OPERATIONAL_PRICE_NOT_LIVE_REFERENCE_ONLY"


def _apply_direction_scope_contract(payload: dict[str, Any]) -> None:
    raw_direction = _text_value(payload.get("raw_direction"))
    if raw_direction not in {"BUY", "SELL"}:
        raw_direction = None
    try:
        horizon_seconds = max(
            60.0,
            float(os.getenv("SIGNAL_PRESSURE_RAW_DIRECTION_MAX_AGE_SECONDS", "14400")),
        )
    except (TypeError, ValueError):
        horizon_seconds = 14_400.0
    observed_at = _first_timestamp(
        payload.get("signal_valid_time_utc"),
        payload.get("block_latest_end_utc"),
        payload.get("latest_event_utc"),
    )
    now = datetime.now(UTC)
    age_seconds = None if observed_at is None else max(0.0, (now - observed_at).total_seconds())
    expires_at = None if observed_at is None else observed_at + timedelta(seconds=horizon_seconds)

    htf = payload.get("htf_structure_context")
    htf_context = htf if isinstance(htf, dict) else {}
    liquidity_resolution = (
        _text_value(payload.get("liquidity_resolution") or htf_context.get("liquidity_resolution")) or "NONE"
    )
    resolution = "UNRESOLVED"
    resolved_direction: str | None = None
    if raw_direction == "BUY" and liquidity_resolution == "BUY_SIDE_ACCEPTED":
        resolution, resolved_direction = "ACCEPTED", "BUY"
    elif raw_direction == "BUY" and liquidity_resolution == "BUY_SIDE_REJECTED":
        resolution, resolved_direction = "REJECTED", "SELL"
    elif raw_direction == "SELL" and liquidity_resolution == "SELL_SIDE_ACCEPTED":
        resolution, resolved_direction = "ACCEPTED", "SELL"
    elif raw_direction == "SELL" and liquidity_resolution == "SELL_SIDE_REJECTED":
        resolution, resolved_direction = "REJECTED", "BUY"
    elif liquidity_resolution.endswith("_EXPIRED"):
        resolution = "EXPIRED"
    if age_seconds is not None and age_seconds > horizon_seconds:
        resolution = "EXPIRED"
        resolved_direction = None

    if raw_direction is None:
        direction_status = "NO_DIRECTION"
    elif resolution == "EXPIRED":
        direction_status = "STALE"
    elif resolution in {"ACCEPTED", "REJECTED"}:
        direction_status = f"RESOLVED_{resolution}"
    else:
        direction_status = "ACTIVE_ADVISORY"
    payload.update(
        {
            "raw_direction_role": "SHORT_HORIZON_PRESSURE_RADAR_ONLY",
            "raw_direction_validity_horizon": "M15_TO_H4",
            "raw_direction_validity_horizon_seconds": horizon_seconds,
            "raw_direction_observed_at_utc": None if observed_at is None else observed_at.isoformat(),
            "raw_direction_age_seconds": None if age_seconds is None else round(age_seconds, 3),
            "raw_direction_expires_at_utc": None if expires_at is None else expires_at.isoformat(),
            "raw_direction_status": direction_status,
            "raw_direction_direct_entry_eligible": False,
            "raw_direction_swing_eligible": False,
            "raw_direction_24h_eligible": False,
            "raw_direction_eligible_for_context_resolution": raw_direction is not None and resolution != "EXPIRED",
            "pressure_direction_resolution": resolution,
            "pressure_resolution_direction": resolved_direction,
            "pressure_resolution_source": "HTF_LIQUIDITY_LIFECYCLE",
            "liquidity_resolution": liquidity_resolution,
            "direction_next_required_stage": (
                "H1_M15_STRATEGY_5SCR_CONFIRMATION"
                if resolution in {"ACCEPTED", "REJECTED"}
                else "FRESH_PRESSURE_AND_CONTEXT"
                if resolution == "EXPIRED"
                else "LIQUIDITY_ACCEPTANCE_OR_REJECTION"
            ),
            "strategy_5scr_required": True,
        }
    )


def _first_number(*values: Any) -> float | None:
    for value in values:
        if value is None or isinstance(value, bool):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number > 0.0:
            return number
    return None


def _first_non_negative_number(*values: Any) -> float | None:
    for value in values:
        if value is None or isinstance(value, bool):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number >= 0.0:
            return number
    return None


def _first_timestamp(*values: Any) -> datetime | None:
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            continue
        return (parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)).astimezone(UTC)
    return None


def _text_value(value: Any) -> str | None:
    text = str(value or "").strip()
    return text.upper() if text else None


def _stable_htf_context(context: dict[str, Any]) -> dict[str, Any]:
    volatile = {"generated_at_utc", "daily_bias_snapshot_time"}
    return {key: value for key, value in context.items() if key not in volatile and not key.endswith("_age_seconds")}


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
    "PRESSURE_STATE_SCHEMA_VERSION",
    "SignalDecisionRoute",
    "can_emit_signal_decision",
    "convert_to_signal_pressure_state",
    "has_lifecycle_anchor",
    "route_decision_or_pressure",
]
