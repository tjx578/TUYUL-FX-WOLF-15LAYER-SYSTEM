"""Semantic pair lifecycle memory for SignalWatch payloads.

This module is observability-only. It enriches SignalWatchJSON with pair-local
memory so repeated pressure is interpreted as lifecycle context instead of a
fresh standalone signal. It never grants execution permission.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from numbers import Real
from typing import Any

PAIR_MEMORY_SOURCE_EVENT = "PairSignalMemory"


class PairSignalMemoryStore:
    """Small in-process memory keyed by pair and cluster for live SignalWatch."""

    def __init__(
        self,
        *,
        lookback_minutes: float = 720.0,
        phase_structure_validation_enabled: bool = True,
    ) -> None:
        self.lookback_minutes = max(1.0, float(lookback_minutes))
        self.phase_structure_validation_enabled = bool(phase_structure_validation_enabled)
        self._by_symbol: dict[str, dict[str, Any]] = {}
        self._by_cluster: dict[str, dict[str, Any]] = {}

    def enrich_watch_payload(self, payload: dict[str, Any], *, material_state: str | None = None) -> None:
        symbol = _text(payload.get("symbol")).upper()
        if not symbol:
            return
        cluster_key = _cluster_key(payload)
        previous_cluster = self._by_cluster.get(cluster_key)
        previous_symbol = self._by_symbol.get(symbol)
        previous = previous_cluster or previous_symbol
        if previous is not None and _memory_expired(
            previous,
            current_time=_text(payload.get("signal_valid_time_utc")),
            lookback_minutes=self.lookback_minutes,
        ):
            previous = None

        context = build_pair_memory_context(
            payload,
            previous=previous,
            material_state=material_state,
            phase_structure_validation_enabled=self.phase_structure_validation_enabled,
        )
        payload["pair_memory_context"] = _clean_context(context)
        payload["phase_structure_validation"] = context.get("phase_structure_validation")
        payload["pair_lifecycle_transition"] = context.get("lifecycle_transition")
        payload["pair_memory_recommended_interpretation"] = context.get("recommended_interpretation")

        state = memory_state_from_watch(payload, material_state=material_state)
        self._by_symbol[symbol] = state
        self._by_cluster[cluster_key] = state


def build_pair_memory_context(
    current: Mapping[str, Any],
    *,
    previous: Mapping[str, Any] | None = None,
    material_state: str | None = None,
    phase_structure_validation_enabled: bool = True,
) -> dict[str, Any]:
    symbol = _text(current.get("symbol")).upper()
    current_price = _first_number(current.get("entry_reference_price"), current.get("signal_valid_price"))
    previous_price = _first_number((previous or {}).get("current_price"), (previous or {}).get("previous_valid_price"))
    delta_pips = _price_delta_pips(symbol=symbol, current_price=current_price, previous_price=previous_price)
    minutes_since = _minutes_between(
        _text((previous or {}).get("current_valid_time_utc") or (previous or {}).get("previous_valid_time_utc")),
        _text(current.get("signal_valid_time_utc")),
    )
    previous_role = _text((previous or {}).get("current_signal_role") or (previous or {}).get("previous_signal_role"))
    current_role = _signal_role(current)
    transition, validation, interpretation = _classify_lifecycle(
        current=current,
        previous=previous,
        delta_pips=delta_pips,
        material_state=material_state,
        phase_structure_validation_enabled=phase_structure_validation_enabled,
    )
    existing = current.get("pair_memory_context") if isinstance(current.get("pair_memory_context"), Mapping) else {}
    context = {
        **dict(existing),
        "memory_available": previous is not None,
        "memory_source_event": PAIR_MEMORY_SOURCE_EVENT,
        "memory_scope": "PAIR_LIFECYCLE",
        "lookback_minutes": None,
        "symbol": symbol,
        "previous_watch_signal_id": (previous or {}).get("signal_id"),
        "previous_watch_time_utc": (previous or {}).get("current_valid_time_utc"),
        "previous_watch_time_wita": (previous or {}).get("current_valid_time_wita"),
        "previous_watch_price": previous_price,
        "previous_watch_family": (previous or {}).get("current_signal_family"),
        "previous_watch_role": previous_role,
        "previous_valid_signal_id": (previous or {}).get("signal_id"),
        "previous_valid_time_utc": (previous or {}).get("current_valid_time_utc"),
        "previous_valid_time_wita": (previous or {}).get("current_valid_time_wita"),
        "previous_valid_price": previous_price,
        "previous_signal_family": (previous or {}).get("current_signal_family"),
        "previous_signal_role": previous_role,
        "previous_price_position": (previous or {}).get("current_price_position"),
        "previous_m15_phase": (previous or {}).get("current_m15_phase"),
        "previous_h1_phase": (previous or {}).get("current_h1_phase"),
        "previous_microboost_role": (previous or {}).get("current_microboost_role"),
        "previous_watch_direction": (previous or {}).get("watch_direction"),
        "previous_source_clean_block_id": (previous or {}).get("source_clean_block_id"),
        "current_valid_time_utc": _text(current.get("signal_valid_time_utc")),
        "current_valid_time_wita": _text(current.get("signal_valid_time_wita")),
        "current_price": current_price,
        "current_signal_family": _text(current.get("signal_family")),
        "current_signal_role": current_role,
        "current_price_position": _text(current.get("price_position")).upper() or None,
        "current_m15_phase": _text(current.get("m15_phase")).upper() or None,
        "current_h1_phase": _text(current.get("h1_phase")).upper() or None,
        "current_microboost_role": _text(current.get("microboost_role")).upper() or None,
        "current_watch_direction": _watch_direction(current),
        "current_source_clean_block_id": current.get("source_clean_block_id"),
        "minutes_since_previous_watch": minutes_since,
        "minutes_since_previous_valid": minutes_since,
        "price_delta_from_previous_watch_pips": delta_pips,
        "price_delta_from_previous_valid_pips": delta_pips,
        "lifecycle_transition": transition,
        "phase_structure_validation": validation,
        "recommended_interpretation": interpretation,
        "material_state": material_state,
        "valid_for_execution": False,
        "execution_impact": False,
        "advisory_only": True,
    }
    context["lookback_minutes"] = None if previous is None else context.get("lookback_minutes")
    return context


def memory_state_from_watch(payload: Mapping[str, Any], *, material_state: str | None = None) -> dict[str, Any]:
    symbol = _text(payload.get("symbol")).upper()
    return {
        "symbol": symbol,
        "signal_id": payload.get("signal_id"),
        "status": payload.get("status"),
        "current_valid_time_utc": _text(payload.get("signal_valid_time_utc")),
        "current_valid_time_wita": _text(payload.get("signal_valid_time_wita")),
        "current_price": _first_number(payload.get("entry_reference_price"), payload.get("signal_valid_price")),
        "current_signal_family": _text(payload.get("signal_family")),
        "current_signal_role": _signal_role(payload),
        "current_price_position": _text(payload.get("price_position")).upper() or None,
        "current_m15_phase": _text(payload.get("m15_phase")).upper() or None,
        "current_h1_phase": _text(payload.get("h1_phase")).upper() or None,
        "current_microboost_role": _text(payload.get("microboost_role")).upper() or None,
        "watch_direction": _watch_direction(payload),
        "source_clean_block_id": payload.get("source_clean_block_id"),
        "cluster_id": payload.get("cluster_id"),
        "material_state": material_state,
    }


def _classify_lifecycle(
    *,
    current: Mapping[str, Any],
    previous: Mapping[str, Any] | None,
    delta_pips: float | None,
    material_state: str | None,
    phase_structure_validation_enabled: bool,
) -> tuple[str, str, str]:
    if previous is None:
        return (
            "FIRST_VALID_PRESSURE",
            "FRESH_SIGNAL_NO_MEMORY" if phase_structure_validation_enabled else "CONTEXT_INSUFFICIENT",
            "TRACK_AS_FRESH_WATCH_CONTEXT",
        )

    previous_state = _text(previous.get("material_state"))
    same_cluster = _text(previous.get("cluster_id")) and _text(previous.get("cluster_id")) == _text(
        current.get("cluster_id")
    )
    if same_cluster and material_state and previous_state == material_state:
        return (
            "SAME_CLEAN_BLOCK_STILL_PENDING",
            "NO_NEW_STATE_CHANGE",
            "DO_NOT_TREAT_AS_FRESH_SIGNAL",
        )
    if same_cluster:
        return (
            "SAME_CLEAN_BLOCK_STILL_PENDING",
            "MATERIAL_STATE_CHANGED",
            "TRACK_AS_SAME_LIFECYCLE_STATE_CHANGE",
        )
    if material_state and previous_state == material_state:
        return (
            "SAME_CLEAN_BLOCK_STILL_PENDING",
            "NO_NEW_STATE_CHANGE",
            "DO_NOT_TREAT_AS_FRESH_SIGNAL",
        )

    previous_direction = _text(previous.get("watch_direction")).upper()
    current_direction = _watch_direction(current)
    if (
        previous_direction in {"BUY", "SELL"}
        and current_direction in {"BUY", "SELL"}
        and previous_direction != current_direction
    ):
        return (
            "RESET_BY_OPPOSITE_CLEAN_BLOCK",
            "RESET_BY_OPPOSITE_CLEAN_BLOCK",
            "REVIEW_AS_NEW_OPPOSITE_WATCH_NOT_CONTINUATION",
        )

    current_position = _text(current.get("price_position")).upper()
    previous_position = _text(previous.get("current_price_position")).upper()
    current_h1 = _text(current.get("h1_phase")).upper()
    density = _first_number(current.get("effective_density"), current.get("effective_density_per_minute")) or 0.0

    if current_direction == "BUY":
        if (current_position == "MAIN_RESISTANCE" or previous_position == "MAIN_RESISTANCE") and (
            delta_pips is not None and delta_pips <= 2.0 or "BEAR" in current_h1
        ):
            return (
                "FAILED_BUY_PRESSURE_TO_ABSORPTION",
                "ABSORPTION_CONFIRMED_BY_MEMORY",
                "NO_CHASE_BUY_SELL_WATCH_PENDING_CONFIRMATION",
            )
        if delta_pips is not None and delta_pips < -5.0:
            return (
                "FAILED_BUY_PRESSURE_TO_WEAKENING",
                "BUY_PHASE_CONTRADICTED_BY_PRICE_RESPONSE",
                "NO_CHASE_BUY_WAIT_RECLAIM_OR_COUNTER_WATCH",
            )
        if delta_pips is not None and delta_pips >= 40.0:
            return _positive_continuation_transition(density=density, late=True)
        if delta_pips is not None and delta_pips >= 12.0:
            return _positive_continuation_transition(density=density, late=False)

    if current_direction == "SELL":
        if (current_position == "MAIN_SUPPORT" or previous_position == "MAIN_SUPPORT") and (
            delta_pips is not None and delta_pips >= -2.0 or "BULL" in current_h1
        ):
            return (
                "FAILED_SELL_PRESSURE_TO_ABSORPTION",
                "SELL_PRESSURE_ABSORBED_AT_SUPPORT",
                "NO_CHASE_SELL_BUY_WATCH_PENDING_CONFIRMATION",
            )
        if delta_pips is not None and delta_pips > 5.0:
            return (
                "FAILED_SELL_PRESSURE_TO_WEAKENING",
                "SELL_PHASE_CONTRADICTED_BY_PRICE_RESPONSE",
                "NO_CHASE_SELL_WAIT_BREAKDOWN_OR_COUNTER_WATCH",
            )
        if delta_pips is not None and delta_pips <= -40.0:
            return _positive_continuation_transition(density=density, late=True)
        if delta_pips is not None and delta_pips <= -12.0:
            return _positive_continuation_transition(density=density, late=False)

    return (
        "SAME_PAIR_CONTEXT_CONTINUATION",
        "STRUCTURE_IMPROVING" if phase_structure_validation_enabled else "CONTEXT_INSUFFICIENT",
        "TRACK_AS_LIFECYCLE_CONTINUATION_NOT_STANDALONE_SIGNAL",
    )


def _positive_continuation_transition(*, density: float, late: bool) -> tuple[str, str, str]:
    if late:
        return (
            "LATE_PRESSURE_AFTER_PRE_MOVE",
            "LATE_PRESSURE_AFTER_PRE_MOVE",
            "HOLD_TRAIL_OR_RETEST_ONLY_NO_FRESH_CHASE",
        )
    if density >= 8.0:
        return (
            "EARLY_TIMING_TO_ACCELERATION",
            "ACCELERATION_AFTER_PRIOR_VALID_BLOCK",
            "HOLD_TRAIL_OR_RETEST_ONLY",
        )
    return (
        "SUSTAINED_PRESSURE_CONTINUATION",
        "STRUCTURE_CONFIRMED",
        "TRACK_CONTINUATION_WAIT_RETEST_FOR_NEW_ENTRY",
    )


def _signal_role(payload: Mapping[str, Any]) -> str:
    status = _text(payload.get("status")).upper()
    direction = _watch_direction(payload) or _text(payload.get("candidate_direction")).upper()
    position = _text(payload.get("price_position")).upper()
    microboost_role = _text(payload.get("microboost_role")).upper()
    density = _first_number(payload.get("effective_density"), payload.get("effective_density_per_minute")) or 0.0
    if microboost_role:
        return microboost_role
    if "MICROBOOST" in status or density >= 8.0:
        return "HIGH_DENSITY_ACCELERATION"
    if "CLEAN_BLOCK" in status and direction in {"BUY", "SELL"} and position:
        return f"{direction}_CLEAN_BLOCK_AT_{position}"
    return status or "WATCH_CONTEXT"


def _watch_direction(payload: Mapping[str, Any]) -> str | None:
    for key in ("watch_direction", "candidate_direction", "validated_direction", "raw_direction", "final_direction"):
        value = _text(payload.get(key)).upper()
        if value in {"BUY", "SELL"}:
            return value
    return None


def _memory_expired(
    previous: Mapping[str, Any],
    *,
    current_time: str | None,
    lookback_minutes: float,
) -> bool:
    minutes = _minutes_between(_text(previous.get("current_valid_time_utc")), current_time)
    return minutes is not None and minutes > lookback_minutes


def _cluster_key(payload: Mapping[str, Any]) -> str:
    return _text(payload.get("cluster_id")) or "|".join(
        _text(payload.get(key)) for key in ("symbol", "signal_family", "entry_reference_price")
    )


def _price_delta_pips(
    *,
    symbol: str,
    current_price: float | None,
    previous_price: float | None,
) -> float | None:
    if current_price is None or previous_price is None:
        return None
    pip_size = _pip_size_for_symbol(symbol)
    if pip_size <= 0:
        return None
    return round((current_price - previous_price) / pip_size, 2)


def _pip_size_for_symbol(symbol: str) -> float:
    if not symbol:
        return 0.0001
    if symbol.startswith(("XAU", "XAG")):
        return 0.01
    quote = symbol[3:6] if len(symbol) >= 6 else ""
    return 0.01 if quote == "JPY" else 0.0001


def _minutes_between(previous_time: str | None, current_time: str | None) -> float | None:
    previous_dt = _parse_time(previous_time)
    current_dt = _parse_time(current_time)
    if previous_dt is None or current_dt is None:
        return None
    return round(max(0.0, (current_dt - previous_dt).total_seconds() / 60.0), 3)


def _parse_time(value: str | None) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _first_number(*values: Any) -> float | None:
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, Real):
            return float(value)
        text = _text(value)
        if not text:
            continue
        try:
            return float(text)
        except (TypeError, ValueError):
            continue
    return None


def _text(value: Any) -> str:
    return str(value or "").strip()


def _clean_context(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            cleaned_item = _clean_context(item)
            if cleaned_item is None or cleaned_item == [] or cleaned_item == {}:
                continue
            cleaned[key] = cleaned_item
        return cleaned or None
    if isinstance(value, list):
        cleaned_list = []
        for item in value:
            cleaned_item = _clean_context(item)
            if cleaned_item is None or cleaned_item == [] or cleaned_item == {}:
                continue
            cleaned_list.append(cleaned_item)
        return cleaned_list or None
    return value


__all__ = [
    "PAIR_MEMORY_SOURCE_EVENT",
    "PairSignalMemoryStore",
    "build_pair_memory_context",
    "memory_state_from_watch",
]
