"""Route valid clean SignalThrottle blocks into Watch output or diagnostics.

This module is observability-only. It never produces an executable signal; a
clean block can only become a non-executable SignalWatch payload or an explicit
promotion diagnostic.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, datetime, timedelta
from numbers import Real
from typing import Any

DEFAULT_SIGNAL_WATCH_PROMOTION_DIAGNOSTIC_PREFIX = "[SignalWatchPromotionDiagnostic]"
_CONTEXT_BLOCKERS = {"MARKET_CONTEXT_MISSING", "SIGNAL_PRICE_MISSING"}
_PRIMARY_AUTHORITY_BLOCKERS = {"PRIMARY_WATCH_REQUIRES_PAIR_ROTATION_AUTHORITY"}
_PAIR_ROTATION_AUTHORITY = "PAIR_ROTATION_ONLY"
_SCANNER_CYCLE_MEMORY_AUTHORITY = "SCANNER_CYCLE_AWARE_MEMORY_ONLY"


@dataclass(frozen=True)
class CleanBlockWatchRoute:
    event: str
    payload: dict[str, Any]
    emit_as_watch: bool
    diagnostic: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "payload": dict(self.payload),
            "emit_as_watch": self.emit_as_watch,
            "diagnostic": self.diagnostic,
        }


def route_clean_blocks_to_watch(
    candidates: Iterable[Mapping[str, Any]],
    *,
    market_contexts: Mapping[str, Any] | None = None,
    clean_block_seconds: int = 300,
) -> list[CleanBlockWatchRoute]:
    contexts = market_contexts or {}
    return [
        route_clean_block_to_watch(
            candidate,
            market_context=_market_context_for_symbol(contexts, str(candidate.get("symbol") or "")),
            clean_block_seconds=clean_block_seconds,
        )
        for candidate in candidates
    ]


def route_clean_block_to_watch(
    candidate: Mapping[str, Any],
    *,
    market_context: Any | None = None,
    clean_block_seconds: int = 300,
) -> CleanBlockWatchRoute:
    block = dict(candidate)
    lineage = clean_block_lineage_fields(block, clean_block_seconds=clean_block_seconds)
    symbol = str(block.get("symbol") or "").upper()
    direction = _raw_pressure_direction(block)
    duration = _duration_seconds(block)
    blocked_by: list[str] = []

    if not symbol:
        blocked_by.append("SYMBOL_MISSING")
    if duration is None or duration < clean_block_seconds:
        blocked_by.append("CLEAN_BLOCK_DURATION_BELOW_THRESHOLD")
    if not lineage.get("source_clean_block_id"):
        blocked_by.append("SOURCE_CLEAN_BLOCK_ID_MISSING")
    if direction not in {"BUY", "SELL"}:
        blocked_by.append("CLEAN_BLOCK_DIRECTION_MISSING")
    authority = _primary_watch_authority(block)
    scanner_advisory_watch = _scanner_cycle_advisory_watch_allowed(
        block,
        lineage=lineage,
        authority=authority,
        clean_block_seconds=clean_block_seconds,
    )
    if not authority["eligible_for_primary_watch"] and not scanner_advisory_watch:
        blocked_by.append("PRIMARY_WATCH_REQUIRES_PAIR_ROTATION_AUTHORITY")

    signal_price = _signal_price(market_context)
    if market_context is None:
        blocked_by.append("MARKET_CONTEXT_MISSING")
    elif signal_price is None:
        blocked_by.append("SIGNAL_PRICE_MISSING")

    if blocked_by:
        if _should_emit_clean_block_radar(blocked_by=blocked_by, lineage=lineage):
            return CleanBlockWatchRoute(
                event="signal_throttle_clean_block_radar",
                payload=_clean_block_radar_payload(
                    block,
                    lineage=lineage,
                    blocked_by=blocked_by,
                    clean_block_seconds=clean_block_seconds,
                    authority=authority,
                ),
                emit_as_watch=False,
                diagnostic=True,
            )
        return CleanBlockWatchRoute(
            event="signal_watch_promotion_diagnostic",
            payload=_diagnostic_payload(
                block,
                lineage=lineage,
                blocked_by=blocked_by,
                clean_block_seconds=clean_block_seconds,
                authority=authority,
            ),
            emit_as_watch=False,
            diagnostic=True,
        )

    assert signal_price is not None  # for type checkers; guarded above
    return CleanBlockWatchRoute(
        event="signal_watch_json",
        payload=_watch_payload(
            block,
            lineage=lineage,
            market_context=market_context,
            signal_price=signal_price,
            direction=direction,
            authority=authority,
            scanner_advisory_watch=scanner_advisory_watch,
        ),
        emit_as_watch=True,
        diagnostic=False,
    )


def clean_block_lineage_fields(
    candidate: Mapping[str, Any],
    *,
    clean_block_seconds: int = 300,
) -> dict[str, Any]:
    symbol = str(candidate.get("symbol") or "").upper()
    start = _text(candidate.get("block_start_utc") or candidate.get("start_utc") or candidate.get("start"))
    end = _text(candidate.get("block_end_utc") or candidate.get("end_utc") or candidate.get("end"))
    duration = _duration_seconds(candidate)
    event_count = _int_value(candidate.get("events") or candidate.get("event_count"))
    direction = _raw_pressure_direction(candidate)
    explicit_valid_since = _text(
        candidate.get("source_clean_block_first_valid_end_utc")
        or candidate.get("clean_block_first_valid_end_utc")
        or candidate.get("clean_block_valid_since_utc")
        or candidate.get("valid_since_utc")
    )
    first_valid_end = explicit_valid_since or _first_valid_end_utc(start, clean_block_seconds)
    source_id = _text(candidate.get("source_clean_block_id")) or _stable_clean_block_id(
        symbol,
        start,
        first_valid_end,
    )
    latest_duration = None if duration is None else round(duration, 3)
    return {
        "source_clean_block_id": source_id,
        "source_pressure_block_id": _text(candidate.get("source_pressure_block_id")) or source_id,
        "clean_block_valid": duration is not None and duration >= clean_block_seconds,
        "clean_block_start_utc": start,
        "clean_block_end_utc": end,
        "clean_block_valid_since_utc": first_valid_end,
        "clean_block_confirmed_at_utc": first_valid_end,
        "clean_block_latest_end_utc": end,
        "clean_block_live_duration_seconds": latest_duration,
        "clean_block_duration_seconds": latest_duration,
        "clean_block_event_count": event_count,
        "clean_block_direction": direction if direction in {"BUY", "SELL"} else None,
        "source_clean_block_start_utc": start,
        "source_clean_block_first_valid_end_utc": first_valid_end,
        "source_clean_block_latest_end_utc": end,
        "source_clean_block_latest_duration_seconds": latest_duration,
        "watch_promotion_source": "CLEAN_BLOCK_ROUTER",
    }


def emit_signal_watch_promotion_diagnostic(
    payload: Mapping[str, Any],
    *,
    enabled: bool = True,
    prefix: str = DEFAULT_SIGNAL_WATCH_PROMOTION_DIAGNOSTIC_PREFIX,
) -> bool:
    if not enabled:
        return False
    data = dict(payload)
    data.setdefault("event", "signal_watch_promotion_diagnostic")
    data["valid_for_execution"] = False
    data["is_final_signal"] = False
    data["final_direction"] = "WAIT"
    logging.getLogger("signal_json").warning(
        "%s %s",
        prefix,
        json.dumps(data, separators=(",", ":"), ensure_ascii=False),
    )
    return True


def _watch_payload(
    candidate: Mapping[str, Any],
    *,
    lineage: Mapping[str, Any],
    market_context: Any,
    signal_price: float,
    direction: str,
    authority: Mapping[str, Any],
    scanner_advisory_watch: bool = False,
) -> dict[str, Any]:
    symbol = str(candidate.get("symbol") or "").upper()
    side = "BUY" if direction == "BUY" else "SELL"
    is_scanner_advisory = bool(scanner_advisory_watch)
    start_price = _first_number(_field(market_context, "price_at_signal_start"))
    end_price = _first_number(_field(market_context, "price_at_signal_end"))
    entry_zone = sorted(
        {
            round(start_price if start_price is not None else signal_price, 5),
            round(end_price if end_price is not None else signal_price, 5),
            round(signal_price, 5),
        }
    )
    signal_time = (
        lineage.get("clean_block_end_utc")
        or lineage.get("clean_block_valid_since_utc")
        or candidate.get("valid_since_utc")
    )
    requires_m15_close, requires_m15_close_policy = _requires_m15_close_policy(
        direction=direction,
        market_context=market_context,
    )
    structure_room = _structure_room_payload(
        symbol=symbol,
        direction=direction,
        market_context=market_context,
        signal_price=signal_price,
    )
    payload = {
        "enabled": True,
        "status": f"CLEAN_BLOCK_{side}_WATCH",
        "signal_family": f"CLEAN_BLOCK_{side}_WATCH",
        "cluster_id": lineage.get("source_clean_block_id"),
        "symbol": symbol,
        "raw_direction": direction,
        "candidate_direction": direction,
        "validated_direction": None,
        "watch_direction": direction,
        "direction_source": candidate.get("direction_source") or "CLEAN_BLOCK_DIRECTION",
        "direction_confidence": candidate.get("direction_confidence") or "CLEAN_BLOCK_CONTEXT",
        "resolved_family": "CLEAN_BLOCK_TO_SIGNAL_WATCH",
        "requires_m15_close": requires_m15_close,
        "requires_m15_close_policy": requires_m15_close_policy,
        "final_direction": "WAIT",
        "direction_status": "CLEAN_BLOCK_WATCH_ONLY",
        "direction_validation_status": "CLEAN_BLOCK_WATCH_PENDING_STRUCTURE",
        "action": "WAIT_PRICE_THEME_STRUCTURE",
        "reason": (
            "scanner_cycle_clean_block_mature_with_context_promoted_to_advisory_signal_watch"
            if is_scanner_advisory
            else "clean_block_router_promoted_valid_clean_block_to_signal_watch"
        ),
        "signal_valid_time": signal_time,
        "signal_valid_time_utc": signal_time,
        "signal_valid_price": signal_price,
        "entry_reference_price": signal_price,
        "entry_zone": entry_zone or [signal_price],
        "price_position": _field(market_context, "price_position"),
        "m15_phase": _field(market_context, "m15_phase"),
        "h1_phase": _field(market_context, "h1_phase"),
        "phase_unpriced": candidate.get("phase"),
        "phase_priced": None,
        "effective_ticks": candidate.get("effective_ticks"),
        "effective_density": candidate.get("effective_density_per_minute") or candidate.get("density_per_minute"),
        "duration_minutes": candidate.get("duration_minutes"),
        "rr_status": "UNVALIDATED",
        "market_context_applied": True,
        "valid_for_execution": False,
        "requires_market_context": True,
        "eligible_for_signal_watch": True,
        "eligible_for_primary_watch": bool(authority.get("eligible_for_primary_watch")),
        "confidence_bucket": "SCANNER_CYCLE_MEMORY_WATCH_ONLY" if is_scanner_advisory else "CLEAN_BLOCK_WATCH_ONLY",
        "emit_reason": (
            "SCANNER_CYCLE_MEMORY_TO_SIGNAL_WATCH"
            if is_scanner_advisory
            else "CLEAN_BLOCK_TO_SIGNAL_WATCH"
        ),
        "signal_quality": "WATCH_ONLY",
        "signal_watch_source": "SIGNAL_THROTTLE_CLEAN_BLOCK",
        "source_clean_block_confirmed": True,
        "source_clean_block_valid_since_utc": lineage.get("clean_block_valid_since_utc"),
        "source_clean_block_confirmed_at_utc": lineage.get("clean_block_confirmed_at_utc"),
        "source_clean_block_latest_end_utc": lineage.get("clean_block_latest_end_utc"),
        "microboost_validation_status": "NOT_REQUIRED_CLEAN_BLOCK_ROUTER",
        "promotion_path": (
            "SCANNER_CYCLE_MEMORY_TO_SIGNAL_WATCH"
            if is_scanner_advisory
            else "CLEAN_BLOCK_TO_SIGNAL_WATCH"
        ),
        "promotion_trigger": (
            "SCANNER_CYCLE_CLEAN_BLOCK_MATURE_WITH_CONTEXT"
            if is_scanner_advisory
            else "CLEAN_BLOCK_VALID"
        ),
        "watch_promotion_source": "SCANNER_CYCLE_MEMORY_ROUTER" if is_scanner_advisory else "CLEAN_BLOCK_ROUTER",
        "watch_scope": "SCANNER_CYCLE_MEMORY_ADVISORY" if is_scanner_advisory else "PAIR_ROTATION_PRIMARY",
        "scanner_cycle_advisory_watch": is_scanner_advisory,
        "advisory_watch_authority_rule": (
            "SCANNER_CYCLE_MEMORY_MATURE_WITH_CONTEXT_NON_EXECUTABLE"
            if is_scanner_advisory
            else None
        ),
        "primary_watch_authority": authority.get("primary_watch_authority"),
        "primary_watch_authority_rule": authority.get("primary_watch_authority_rule"),
        "scanner_cycle_memory_only": authority.get("scanner_cycle_memory_only"),
        "signal_valid": False,
        "tradeplan_valid": False,
        "execution_valid_now": False,
        "is_final_signal": False,
        "market_structure": {
            "structure_ready": False,
            "structure_source": "CLEAN_BLOCK_ROUTER",
            "structure_bias": f"{side}_WATCH",
            "market_structure_status": "PENDING_PRICE_THEME_STRUCTURE",
            "invalidation_level": None,
            "key_support": _field(market_context, "key_support") or _field(market_context, "main_support"),
            "key_resistance": _field(market_context, "key_resistance") or _field(market_context, "main_resistance"),
            "reason": (
                "scanner_cycle_memory_watch_requires_htf_tradeplan_validation"
                if is_scanner_advisory
                else "clean_block_watch_requires_structure_context_but_execution_not_authorized"
            ),
        },
    }
    if structure_room:
        payload["structure_room"] = structure_room
        payload["raw_structure_room_pips"] = structure_room.get("directional_room_pips")
    payload["pair_memory_context"] = _router_pair_memory_context(
        symbol=symbol,
        direction=direction,
        lineage=lineage,
        market_context=market_context,
        signal_price=signal_price,
        authority=authority,
    )
    payload.update(_pressure_root_fields(candidate))
    payload.update(lineage)
    if is_scanner_advisory:
        payload["watch_promotion_source"] = "SCANNER_CYCLE_MEMORY_ROUTER"
        payload["promotion_path"] = "SCANNER_CYCLE_MEMORY_TO_SIGNAL_WATCH"
        payload["promotion_trigger"] = "SCANNER_CYCLE_CLEAN_BLOCK_MATURE_WITH_CONTEXT"
    payload["clean_block_valid"] = True
    return payload


def _should_emit_clean_block_radar(*, blocked_by: list[str], lineage: Mapping[str, Any]) -> bool:
    blocked = {str(item) for item in blocked_by}
    non_context_blockers = blocked - _CONTEXT_BLOCKERS - _PRIMARY_AUTHORITY_BLOCKERS
    return not non_context_blockers and bool(lineage.get("clean_block_valid"))


def _clean_block_radar_payload(
    candidate: Mapping[str, Any],
    *,
    lineage: Mapping[str, Any],
    blocked_by: list[str],
    clean_block_seconds: int,
    authority: Mapping[str, Any],
) -> dict[str, Any]:
    authority_blocked = bool(set(blocked_by) & _PRIMARY_AUTHORITY_BLOCKERS)
    payload = {
        "event": "signal_throttle_clean_block_radar",
        "status": "CLEAN_BLOCK_SCANNER_MEMORY_RADAR" if authority_blocked else "CLEAN_BLOCK_CONFIRMED_RADAR",
        "signal_family": "SIGNAL_THROTTLE_CLEAN_BLOCK_RADAR",
        "symbol": str(candidate.get("symbol") or "").upper() or None,
        "clean_block_valid": lineage.get("clean_block_valid"),
        "eligible_for_signal_watch": False,
        "blocked_by": blocked_by,
        "next_required_stage": _clean_block_radar_next_stage(blocked_by),
        "clean_block_threshold_seconds": int(clean_block_seconds),
        "market_context_applied": False,
        "valid_for_execution": False,
        "execution_valid_now": False,
        "is_final_signal": False,
        "signal_valid": False,
        "final_direction": "WAIT",
        "action": "TRACK_AS_PRESSURE_MEMORY_RADAR" if authority_blocked else "WAIT_PRICE_STRUCTURE_CONTEXT",
        "signal_watch_source": "SIGNAL_THROTTLE_CLEAN_BLOCK",
        "reason": (
            "scanner_cycle_clean_block_memory_only_primary_watch_requires_pair_rotation"
            if authority_blocked
            else "clean_block_confirmed_market_context_pending"
        ),
    }
    payload.update(_promotion_authority_fields(authority))
    payload.update(_pressure_root_fields(candidate))
    payload.update(lineage)
    return payload


def _structure_room_payload(
    *,
    symbol: str,
    direction: str,
    market_context: Any,
    signal_price: float,
) -> dict[str, Any] | None:
    key_support = _first_number(_field(market_context, "key_support"), _field(market_context, "main_support"))
    key_resistance = _first_number(
        _field(market_context, "key_resistance"),
        _field(market_context, "main_resistance"),
    )
    if key_support is None and key_resistance is None:
        return None
    pip_size = _pip_size(symbol, market_context)
    downside = None if key_support is None else round((signal_price - key_support) / pip_size, 2)
    upside = None if key_resistance is None else round((key_resistance - signal_price) / pip_size, 2)
    directional = upside if direction == "BUY" else downside if direction == "SELL" else None
    directional_side = (
        "UPSIDE_TO_KEY_RESISTANCE"
        if direction == "BUY"
        else "DOWNSIDE_TO_KEY_SUPPORT"
        if direction == "SELL"
        else "UNRESOLVED_DIRECTION"
    )
    return {
        "advisory_only": True,
        "basis": "KEY_SUPPORT_RESISTANCE_VS_SIGNAL_VALID_PRICE",
        "symbol": symbol,
        "direction": direction,
        "reference_price": round(signal_price, 6),
        "pip_size": pip_size,
        "key_support": key_support,
        "key_resistance": key_resistance,
        "downside_to_key_support_pips": downside,
        "upside_to_key_resistance_pips": upside,
        "directional_room_side": directional_side,
        "directional_room_pips": directional,
        "valid_for_execution": False,
        "execution_impact": False,
    }


def _requires_m15_close_policy(*, direction: str, market_context: Any) -> tuple[bool, str]:
    price_position = _normalized_field(market_context, "price_position")
    m15_phase = _normalized_field(market_context, "m15_phase")
    h1_phase = _normalized_field(market_context, "h1_phase")
    market_bias = _normalized_field(market_context, "market_bias")
    trend_direction = _normalized_field(market_context, "trend_direction")

    if direction not in {"BUY", "SELL"}:
        return False, "NOT_APPLICABLE_DIRECTION_UNRESOLVED"

    if direction == "BUY" and price_position in {"MAIN_RESISTANCE", "KEY_RESISTANCE", "RESISTANCE"}:
        return True, "REQUIRED_KEY_LEVEL_OR_REJECTION_RISK"
    if direction == "SELL" and price_position in {"MAIN_SUPPORT", "KEY_SUPPORT", "SUPPORT"}:
        return True, "REQUIRED_KEY_LEVEL_OR_REJECTION_RISK"

    htf_aligned = any(
        _phase_aligned(direction, phase)
        for phase in (h1_phase, market_bias, trend_direction)
    )
    ltf_aligned = _phase_aligned(direction, m15_phase)
    if htf_aligned and ltf_aligned:
        return False, "OPTIONAL_HTF_ALIGNED_CONTINUATION"
    if htf_aligned and price_position not in {"MAIN_RESISTANCE", "MAIN_SUPPORT", "KEY_RESISTANCE", "KEY_SUPPORT"}:
        return False, "OPTIONAL_HTF_ALIGNED_STRUCTURE"
    return True, "REQUIRED_STRUCTURE_CONFIRMATION"


def _phase_aligned(direction: str, phase: str) -> bool:
    if not phase:
        return False
    bullish_tokens = ("BULL", "UPTREND", "SUPPORT_HOLD", "PIVOT_RECLAIM", "ACCUMULATION")
    bearish_tokens = ("BEAR", "DOWNTREND", "RESISTANCE_REJECTION", "SUPPORT_BREAK", "DISTRIBUTION")
    tokens = bullish_tokens if direction == "BUY" else bearish_tokens
    return any(token in phase for token in tokens)


def _normalized_field(source: Any, name: str) -> str:
    return str(_field(source, name) or "").strip().upper()


def _diagnostic_payload(
    candidate: Mapping[str, Any],
    *,
    lineage: Mapping[str, Any],
    blocked_by: list[str],
    clean_block_seconds: int,
    authority: Mapping[str, Any],
) -> dict[str, Any]:
    payload = {
        "event": "signal_watch_promotion_diagnostic",
        "symbol": str(candidate.get("symbol") or "").upper() or None,
        "clean_block_valid": lineage.get("clean_block_valid"),
        "eligible_for_signal_watch": False,
        "blocked_by": blocked_by,
        "next_required_stage": _next_required_stage(blocked_by),
        "clean_block_threshold_seconds": int(clean_block_seconds),
        "valid_for_execution": False,
        "is_final_signal": False,
        "final_direction": "WAIT",
        "signal_watch_source": "SIGNAL_THROTTLE_CLEAN_BLOCK",
        "reason": "clean_block_watch_promotion_blocked_explicitly",
    }
    payload.update(_promotion_authority_fields(authority))
    payload.update(_pressure_root_fields(candidate))
    payload.update(lineage)
    return payload


def _pressure_root_fields(candidate: Mapping[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for key in (
        "ledger_type",
        "ledger_source",
        "clean_block_rule",
        "legacy_pure_block_rule",
        "split_rule",
        "gap_policy",
        "scanner_cycle_aware",
        "source_stream_profile",
        "raw_signal_throttle_severity_profile",
        "raw_signal_throttle_error_count",
        "raw_signal_throttle_primary_severity",
        "raw_pressure_origin",
        "raw_signal_throttle_event_count",
        "allowed_events",
        "throttled_events",
        "downgraded_events",
    ):
        value = candidate.get(key)
        if value is not None:
            fields[key] = dict(value) if isinstance(value, Mapping) else value
    return fields


def _primary_watch_authority(candidate: Mapping[str, Any]) -> dict[str, Any]:
    explicit = _optional_bool(
        candidate.get("primary_watch_eligible")
        if candidate.get("primary_watch_eligible") is not None
        else candidate.get("signal_watch_primary_eligible")
    )
    split_rule = str(candidate.get("split_rule") or "").upper()
    ledger_type = str(candidate.get("ledger_type") or "").upper()
    scanner_cycle_aware = _optional_bool(candidate.get("scanner_cycle_aware")) is True
    pair_rotation = split_rule == _PAIR_ROTATION_AUTHORITY or ledger_type == "PURE_PRESSURE_LEDGER"
    eligible = bool(explicit) if explicit is not None else pair_rotation and not scanner_cycle_aware
    authority = _PAIR_ROTATION_AUTHORITY if eligible else _SCANNER_CYCLE_MEMORY_AUTHORITY
    return {
        "eligible_for_primary_watch": eligible,
        "primary_watch_authority": authority,
        "primary_watch_authority_rule": (
            "PAIR_ROTATION_ONLY_PRIMARY_WATCH"
            if eligible
            else "SCANNER_CYCLE_AWARE_MEMORY_RADAR_ONLY"
        ),
        "scanner_cycle_memory_only": not eligible and (scanner_cycle_aware or "SCANNER_CYCLE" in split_rule),
    }


def _scanner_cycle_advisory_watch_allowed(
    candidate: Mapping[str, Any],
    *,
    lineage: Mapping[str, Any],
    authority: Mapping[str, Any],
    clean_block_seconds: int,
) -> bool:
    if not _env_bool("SIGNAL_THROTTLE_SCANNER_MEMORY_ADVISORY_WATCH_ENABLED", True):
        return False
    if authority.get("eligible_for_primary_watch") is True:
        return False
    if authority.get("scanner_cycle_memory_only") is not True:
        return False
    if lineage.get("clean_block_valid") is not True:
        return False
    if _raw_pressure_direction(candidate) not in {"BUY", "SELL"}:
        return False

    min_seconds = max(
        float(clean_block_seconds),
        _env_float("SIGNAL_THROTTLE_SCANNER_MEMORY_ADVISORY_MIN_SECONDS", 900.0),
    )
    duration = _first_number(
        candidate.get("clean_block_duration_seconds"),
        candidate.get("source_clean_block_latest_duration_seconds"),
        candidate.get("duration_seconds"),
    )
    if duration is None or duration < min_seconds:
        return False

    min_events = max(1, int(_env_float("SIGNAL_THROTTLE_SCANNER_MEMORY_ADVISORY_MIN_EVENTS", 12.0)))
    events = _first_number(
        candidate.get("clean_block_event_count"),
        candidate.get("effective_ticks"),
        candidate.get("raw_signal_throttle_event_count"),
        candidate.get("events"),
    )
    return events is not None and events >= min_events


def _promotion_authority_fields(authority: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "eligible_for_primary_watch": bool(authority.get("eligible_for_primary_watch")),
        "primary_watch_authority": authority.get("primary_watch_authority"),
        "primary_watch_authority_rule": authority.get("primary_watch_authority_rule"),
        "scanner_cycle_memory_only": bool(authority.get("scanner_cycle_memory_only")),
    }


def _clean_block_radar_next_stage(blocked_by: list[str]) -> str:
    blocked = set(blocked_by)
    if blocked & _PRIMARY_AUTHORITY_BLOCKERS:
        return "PAIR_ROTATION_PRIMARY_AUTHORITY"
    return "PRICE_STRUCTURE_CONTEXT"


def _router_pair_memory_context(
    *,
    symbol: str,
    direction: str,
    lineage: Mapping[str, Any],
    market_context: Any,
    signal_price: float,
    authority: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "source": "CLEAN_BLOCK_ROUTER",
        "source_clean_block_id": lineage.get("source_clean_block_id"),
        "active_clean_block_id": lineage.get("source_clean_block_id"),
        "clean_block_start_utc": lineage.get("clean_block_start_utc"),
        "clean_block_latest_end_utc": lineage.get("clean_block_latest_end_utc"),
        "watch_direction": direction,
        "current_price": round(float(signal_price), 6),
        "price_position": _field(market_context, "price_position"),
        "m15_phase": _field(market_context, "m15_phase"),
        "h1_phase": _field(market_context, "h1_phase"),
        "lifecycle_transition": "PRIMARY_CLEAN_BLOCK_WATCH_ACTIVE",
        "phase_structure_validation": "PENDING_PRICE_THEME_STRUCTURE",
        "recommended_interpretation": "TRACK_AS_PRIMARY_WATCH_CONTEXT_ONLY",
        "primary_watch_authority": authority.get("primary_watch_authority"),
        "valid_for_execution": False,
        "execution_impact": False,
    }


def _next_required_stage(blocked_by: list[str]) -> str:
    blocked = set(blocked_by)
    if "MARKET_CONTEXT_MISSING" in blocked or "SIGNAL_PRICE_MISSING" in blocked:
        return "HYDRATE_MARKET_CONTEXT"
    if "CLEAN_BLOCK_DIRECTION_MISSING" in blocked:
        return "RESOLVE_CLEAN_BLOCK_DIRECTION"
    if "SOURCE_CLEAN_BLOCK_ID_MISSING" in blocked:
        return "ATTACH_CLEAN_BLOCK_LINEAGE"
    if "CLEAN_BLOCK_DURATION_BELOW_THRESHOLD" in blocked:
        return "WAIT_CLEAN_BLOCK_THRESHOLD"
    return "REVIEW_WATCH_PROMOTION"


def _market_context_for_symbol(contexts: Mapping[str, Any], symbol: str) -> Any | None:
    normalized = str(symbol or "").upper()
    return contexts.get(normalized) or contexts.get(symbol) or contexts.get(normalized.lower())


def _signal_price(market_context: Any | None) -> float | None:
    if market_context is None:
        return None
    return _first_number(
        _field(market_context, "price_at_signal_end"),
        _field(market_context, "price_at_5m_confirm"),
        _field(market_context, "price_at_signal_start"),
        _field(market_context, "bid"),
        _field(market_context, "ask"),
    )


def _field(source: Any, name: str) -> Any:
    if isinstance(source, Mapping):
        return source.get(name)
    if is_dataclass(source):
        return asdict(source).get(name)
    return getattr(source, name, None)


def _first_number(*values: Any) -> float | None:
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, Real):
            return float(value)
        try:
            text = str(value).strip()
            if text:
                return float(text)
        except (TypeError, ValueError):
            continue
    return None


def _pip_size(symbol: str, market_context: Any) -> float:
    explicit = _first_number(_field(market_context, "pip_value"), _field(market_context, "pip_size"))
    if explicit is not None and explicit > 0:
        return explicit
    return 0.01 if "JPY" in str(symbol or "").upper() else 0.0001


def _duration_seconds(candidate: Mapping[str, Any]) -> float | None:
    raw = candidate.get("duration_seconds")
    if raw is None and candidate.get("duration_minutes") is not None:
        minutes = _first_number(candidate.get("duration_minutes"))
        return None if minutes is None else minutes * 60.0
    return _first_number(raw)


def _raw_pressure_direction(candidate: Mapping[str, Any]) -> str | None:
    for key in ("raw_pressure_direction", "clean_block_direction", "direction"):
        value = str(candidate.get(key) or "").upper()
        if value in {"BUY", "SELL"}:
            return value
    return None


def _int_value(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    parsed = _optional_bool(raw)
    return default if parsed is None else parsed


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return float(default)


def _stable_clean_block_id(symbol: str, start: str | None, first_valid_end: str | None) -> str | None:
    if not symbol or not start or not first_valid_end:
        return None
    return f"{symbol}_{_compact_time(start)}_{_compact_time(first_valid_end)}"


def _first_valid_end_utc(start: str | None, clean_block_seconds: int) -> str | None:
    start_dt = _parse_datetime(start)
    if start_dt is None:
        return None
    return (start_dt + timedelta(seconds=int(clean_block_seconds))).astimezone(UTC).isoformat()


def _compact_time(value: Any) -> str:
    dt = _parse_datetime(value)
    if dt is None:
        text = str(value or "").strip()
        return re.sub(r"[^A-Za-z0-9]+", "", text) or "UNKNOWN"
    return dt.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


__all__ = [
    "CleanBlockWatchRoute",
    "DEFAULT_SIGNAL_WATCH_PROMOTION_DIAGNOSTIC_PREFIX",
    "clean_block_lineage_fields",
    "emit_signal_watch_promotion_diagnostic",
    "route_clean_block_to_watch",
    "route_clean_blocks_to_watch",
]
