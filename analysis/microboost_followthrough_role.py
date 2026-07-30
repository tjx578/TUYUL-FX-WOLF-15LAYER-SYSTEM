"""Microboost role context for advisory pip follow-through telemetry.

This module does not grant direction, trade-plan, or execution permission. It
only names what the priced/unpriced Microboost evidence is doing inside the
SignalThrottle pressure story.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

MICROBOOST_ROLE_SOURCE_EVENT = "MicroboostFollowthroughRole"
MICROBOOST_FOLLOWTHROUGH_ROLE_FIELDS: tuple[str, ...] = (
    "microboost_role",
    "microboost_followthrough_bias",
    "microboost_room_to_move_pips",
    "microboost_pre_move_pips",
    "microboost_late_move_penalty",
    "microboost_followthrough_context_ready",
    "microboost_price_behavior",
    "microboost_room_to_move_status",
    "microboost_stall_pips",
    "microboost_room_to_target_pips",
    "microboost_expected_horizon",
    "microboost_outcome_tracking_required",
    "microboost_role_source_event",
    "microboost_role_reason_codes",
    "microboost_role_valid_for_execution",
    "microboost_role_execution_impact",
    "microboost_role_advisory_only",
    "room_to_move_pips",
    "pre_move_pips",
    "late_move_penalty",
    "followthrough_context_ready",
)

_ABSORPTION_PHASES = {
    "ABSORPTION_WARNING",
    "RESISTANCE_PRESSURE_WARNING",
    "SUPPORT_PRESSURE_WARNING",
    "EXHAUSTION_AT_RESISTANCE",
    "EXHAUSTION_AT_SUPPORT",
}
_REACTION_CONFIRMATION_PHASES = {
    "RESISTANCE_REJECTION_MICROBOOST",
    "SUPPORT_BOUNCE_MICROBOOST",
}
_ACCELERATION_PHASES = {
    "TREND_CONTINUATION_MICROBOOST",
    "CONTINUATION_MICROBOOST",
}
_PULLBACK_PHASES = {
    "BULLISH_PULLBACK_MICROBOOST",
    "BEARISH_PULLBACK_MICROBOOST",
    "MINOR_PULLBACK_MICROBOOST",
    "COUNTER_BIAS_MICROBOOST",
}


def build_microboost_followthrough_role(block: Mapping[str, Any]) -> dict[str, Any]:
    """Return advisory Microboost role fields for a detector block payload."""

    symbol = _text(block.get("symbol")).upper()
    direction = _normalize_direction(block.get("direction") or block.get("raw_direction"))
    phase_unpriced = _text(block.get("phase_unpriced")).upper()
    phase_priced = _text(block.get("phase_priced")).upper()
    action = _text(block.get("action")).upper()
    snapshot = block.get("market_context_snapshot")
    market_context = snapshot if isinstance(snapshot, Mapping) else {}
    price = _reference_price(block, market_context)
    pip_size = _pip_size(symbol, market_context)
    room_to_move = _directional_room_to_move_pips(
        direction=direction,
        price=price,
        pip_size=pip_size,
        market_context=market_context,
    )
    pre_move = _pre_move_pips(
        direction=direction,
        pip_size=pip_size,
        market_context=market_context,
    )
    stall_pips = _stall_pips(pip_size=pip_size, market_context=market_context)
    role, bias, role_reasons = _classify_role(
        phase_unpriced=phase_unpriced,
        phase_priced=phase_priced,
        action=action,
        requires_market_context=bool(block.get("requires_market_context")),
        has_market_context=bool(market_context),
        room_to_move_pips=room_to_move,
        pre_move_pips=pre_move,
    )
    reason_codes = _dedupe(
        [
            *role_reasons,
            *(["MARKET_CONTEXT_PRESENT"] if market_context else ["MARKET_CONTEXT_REQUIRED"]),
            *(["ROOM_TO_MOVE_PRESENT"] if room_to_move is not None else ["ROOM_TO_MOVE_MISSING"]),
            *(["PRE_MOVE_PRESENT"] if pre_move is not None else ["PRE_MOVE_MISSING"]),
            "EXECUTION_FIREWALL_UNCHANGED",
        ]
    )
    late_move_penalty = _late_move_penalty(
        role=role,
        bias=bias,
        room_to_move_pips=room_to_move,
        pre_move_pips=pre_move,
        late_risk_penalty=_number_or_none(block.get("late_risk_penalty")),
    )
    context_ready = bool(market_context) and room_to_move is not None and pre_move is not None
    price_behavior = _price_behavior(
        direction=direction,
        phase_priced=phase_priced,
        role=role,
        bias=bias,
    )
    room_status = _room_to_move_status(
        role=role,
        bias=bias,
        room_to_move_pips=room_to_move,
        has_market_context=bool(market_context),
    )
    room_to_target = room_to_move if bias == "CONTINUATION" and role in {"ACCELERATION", "CONFIRMATION"} else None

    return {
        "microboost_role": role,
        "microboost_followthrough_bias": bias,
        "microboost_room_to_move_pips": room_to_move,
        "microboost_pre_move_pips": pre_move,
        "microboost_late_move_penalty": late_move_penalty,
        "microboost_followthrough_context_ready": context_ready,
        "microboost_price_behavior": price_behavior,
        "microboost_room_to_move_status": room_status,
        "microboost_stall_pips": stall_pips,
        "microboost_room_to_target_pips": room_to_target,
        "microboost_expected_horizon": _expected_horizon(
            role=role,
            bias=bias,
            room_to_move_pips=room_to_move,
            pre_move_pips=pre_move,
        ),
        "microboost_outcome_tracking_required": True,
        "microboost_role_source_event": MICROBOOST_ROLE_SOURCE_EVENT,
        "microboost_role_reason_codes": reason_codes,
        "microboost_role_valid_for_execution": False,
        "microboost_role_execution_impact": False,
        "microboost_role_advisory_only": True,
        "room_to_move_pips": room_to_move,
        "pre_move_pips": pre_move,
        "late_move_penalty": late_move_penalty,
        "followthrough_context_ready": context_ready,
        "valid_for_execution": False,
        "is_final_signal": False,
    }


def microboost_role_fields_from(source: Mapping[str, Any]) -> dict[str, Any]:
    """Copy role fields from a Microboost source payload, including false values."""

    return {key: source[key] for key in MICROBOOST_FOLLOWTHROUGH_ROLE_FIELDS if key in source}


def _classify_role(
    *,
    phase_unpriced: str,
    phase_priced: str,
    action: str,
    requires_market_context: bool,
    has_market_context: bool,
    room_to_move_pips: float | None,
    pre_move_pips: float | None,
) -> tuple[str, str, list[str]]:
    reasons: list[str] = []
    if phase_unpriced:
        reasons.append(f"PHASE_UNPRICED_{phase_unpriced}")
    if phase_priced:
        reasons.append(f"PHASE_PRICED_{phase_priced}")

    if phase_priced in _ABSORPTION_PHASES:
        bias = (
            "NO_CHASE"
            if phase_priced.startswith("EXHAUSTION") or _room_exhausted(room_to_move_pips)
            else "COUNTER_WATCH"
        )
        return "ABSORPTION_WARNING", bias, [*reasons, "PRICE_EXTREME_ABSORPTION_WARNING"]

    if phase_priced == "LATE_DENSE_PRESSURE" or action == "PROTECT_PROFIT":
        return "PROFIT_PROTECTION", "PROTECT", [*reasons, "LATE_DENSE_PRESSURE_PROTECT_PROFIT"]

    if (
        has_market_context
        and pre_move_pips is not None
        and room_to_move_pips is not None
        and pre_move_pips >= 25.0
        and room_to_move_pips <= 10.0
    ):
        return "LATE_CONGESTION", "NO_CHASE", [*reasons, "ROOM_EXHAUSTED_AFTER_PRE_MOVE"]

    if phase_priced == "CONFIRMATION_MICROBOOST" or phase_priced in _REACTION_CONFIRMATION_PHASES:
        return "CONFIRMATION", "CONTINUATION", [*reasons, "PRICE_CONTEXT_CONFIRMS_MICROBOOST"]

    if phase_priced in _ACCELERATION_PHASES:
        return "ACCELERATION", "CONTINUATION", [*reasons, "TREND_OR_CONTINUATION_ACCELERATION"]

    if phase_priced in _PULLBACK_PHASES:
        return "CONFIRMATION", "CONTEXT_REQUIRED", [*reasons, "PULLBACK_OR_BIAS_CONTEXT_PENDING"]

    if requires_market_context or not has_market_context:
        if phase_unpriced == "IGNITION_MICROBOOST":
            return "IGNITION", "CONTEXT_REQUIRED", [*reasons, "EARLY_BURST_REQUIRES_PRICE_CONTEXT"]
        if phase_unpriced in {"DENSE_MICROBOOST", "REPEATED_MICROBOOST", "NEAR_TIMING_GATE_MICROBOOST"}:
            return "ACCELERATION", "CONTEXT_REQUIRED", [*reasons, "DENSE_BURST_REQUIRES_PRICE_CONTEXT"]
        return "IGNITION", "CONTEXT_REQUIRED", [*reasons, "UNPRICED_MICROBOOST_REQUIRES_CONTEXT"]

    if phase_unpriced == "IGNITION_MICROBOOST":
        return "IGNITION", "CONTINUATION", [*reasons, "PRICED_EARLY_IGNITION"]
    if phase_unpriced in {"DENSE_MICROBOOST", "REPEATED_MICROBOOST", "NEAR_TIMING_GATE_MICROBOOST"}:
        return "ACCELERATION", "CONTINUATION", [*reasons, "PRICED_DENSE_ACCELERATION"]
    return "CONFIRMATION", "CONTEXT_REQUIRED", [*reasons, "MICROBOOST_CONTEXT_PRESENT"]


def _expected_horizon(
    *,
    role: str,
    bias: str,
    room_to_move_pips: float | None,
    pre_move_pips: float | None,
) -> str:
    if bias == "CONTEXT_REQUIRED":
        return "CONTEXT_REQUIRED"
    if role in {"ABSORPTION_WARNING", "LATE_CONGESTION", "PROFIT_PROTECTION"}:
        return "15M"
    if room_to_move_pips is None:
        return "CONTEXT_REQUIRED"
    pre_move = pre_move_pips or 0.0
    if room_to_move_pips >= 120.0 and pre_move <= 20.0:
        return "24H"
    if room_to_move_pips >= 60.0:
        return "4H"
    if room_to_move_pips >= 25.0:
        return "1H"
    if room_to_move_pips >= 10.0:
        return "30M"
    return "15M"


def _late_move_penalty(
    *,
    role: str,
    bias: str,
    room_to_move_pips: float | None,
    pre_move_pips: float | None,
    late_risk_penalty: float | None,
) -> float:
    if late_risk_penalty is not None:
        return round(abs(late_risk_penalty), 2)
    if role == "PROFIT_PROTECTION":
        return 24.0
    if role == "LATE_CONGESTION":
        return 18.0
    if role == "ABSORPTION_WARNING" and bias == "NO_CHASE":
        return 16.0
    if role == "ABSORPTION_WARNING":
        return 10.0
    if (
        pre_move_pips is not None
        and room_to_move_pips is not None
        and pre_move_pips >= 25.0
        and room_to_move_pips <= 10.0
    ):
        return 10.0
    return 0.0


def _price_behavior(
    *,
    direction: str | None,
    phase_priced: str,
    role: str,
    bias: str,
) -> str:
    if phase_priced in {"RESISTANCE_PRESSURE_WARNING", "EXHAUSTION_AT_RESISTANCE"}:
        return f"{direction or 'RAW'}_PRESSURE_STALLED_AT_RESISTANCE"
    if phase_priced in {"SUPPORT_PRESSURE_WARNING", "EXHAUSTION_AT_SUPPORT"}:
        return f"{direction or 'RAW'}_PRESSURE_STALLED_AT_SUPPORT"
    if phase_priced == "SUPPORT_BOUNCE_MICROBOOST":
        return "BUY_PRESSURE_REACTING_FROM_SUPPORT"
    if phase_priced == "RESISTANCE_REJECTION_MICROBOOST":
        return "SELL_PRESSURE_REJECTING_RESISTANCE"
    if role == "PROFIT_PROTECTION":
        return "LATE_PRESSURE_AFTER_EXTENSION"
    if role == "LATE_CONGESTION":
        return "LATE_CONGESTION_AFTER_PRE_MOVE"
    if bias == "CONTINUATION":
        return "DIRECTIONAL_PRESSURE_WITH_OPEN_LANE"
    if bias == "CONTEXT_REQUIRED":
        return "PRICE_CONTEXT_REQUIRED"
    return "MICROBOOST_CONTEXT_PRESENT"


def _room_to_move_status(
    *,
    role: str,
    bias: str,
    room_to_move_pips: float | None,
    has_market_context: bool,
) -> str:
    if not has_market_context or room_to_move_pips is None:
        return "CONTEXT_REQUIRED"
    if role == "ABSORPTION_WARNING":
        return "COUNTER_CONFIRMATION_REQUIRED"
    if bias == "CONTEXT_REQUIRED":
        return "CONTEXT_REQUIRED"
    if bias == "PROTECT" or role in {"LATE_CONGESTION", "PROFIT_PROTECTION"}:
        return "PROTECT_OR_NO_CHASE"
    if room_to_move_pips <= 8.0:
        return "ROOM_EXHAUSTED_NO_CHASE"
    if room_to_move_pips <= 15.0:
        return "LIMITED_ROOM"
    return "ROOM_AVAILABLE"


def _directional_room_to_move_pips(
    *,
    direction: str | None,
    price: float | None,
    pip_size: float | None,
    market_context: Mapping[str, Any],
) -> float | None:
    if direction not in {"BUY", "SELL"} or price is None or pip_size is None or pip_size <= 0.0:
        return None
    if direction == "BUY":
        level = _nearest_above(
            price,
            _numbers(
                market_context,
                (
                    "key_resistance",
                    "main_resistance",
                    "resistance_low",
                    "resistance_high",
                    "minor_resistance",
                    "tp1_resistance",
                    "tp2_resistance",
                    "tp3_resistance",
                    "tp4_resistance",
                ),
            ),
        )
        if level is None:
            return None
        return round(max(0.0, (level - price) / pip_size), 2)
    level = _nearest_below(
        price,
        _numbers(
            market_context,
            (
                "key_support",
                "main_support",
                "support_low",
                "support_high",
                "minor_support",
                "major_support",
                "tp1_support",
                "tp2_support",
                "tp3_support",
                "tp4_support",
            ),
        ),
    )
    if level is None:
        return None
    return round(max(0.0, (price - level) / pip_size), 2)


def _pre_move_pips(
    *,
    direction: str | None,
    pip_size: float | None,
    market_context: Mapping[str, Any],
) -> float | None:
    if direction not in {"BUY", "SELL"} or pip_size is None or pip_size <= 0.0:
        return None
    start = _number_or_none(market_context.get("price_at_signal_start"))
    end = _number_or_none(market_context.get("price_at_signal_end"))
    if start is None or end is None:
        return None
    delta = (end - start) / pip_size if direction == "BUY" else (start - end) / pip_size
    return round(max(0.0, delta), 2)


def _stall_pips(
    *,
    pip_size: float | None,
    market_context: Mapping[str, Any],
) -> float | None:
    if pip_size is None or pip_size <= 0.0:
        return None
    start = _number_or_none(market_context.get("price_at_signal_start"))
    end = _number_or_none(market_context.get("price_at_signal_end"))
    if start is None or end is None:
        return None
    return round(abs(end - start) / pip_size, 2)


def _reference_price(block: Mapping[str, Any], market_context: Mapping[str, Any]) -> float | None:
    return _first_number(
        market_context.get("price_at_signal_end"),
        market_context.get("price_at_5m_confirm"),
        market_context.get("price_at_signal_start"),
        market_context.get("bid"),
        market_context.get("ask"),
        block.get("signal_valid_price"),
        block.get("entry_reference_price"),
    )


def _pip_size(symbol: str, market_context: Mapping[str, Any]) -> float | None:
    explicit = _number_or_none(market_context.get("pip_value"))
    if explicit is not None and explicit > 0.0:
        return explicit
    if not symbol:
        return None
    if symbol.startswith(("XAU", "XAG")):
        return 0.01
    quote = symbol[3:6] if len(symbol) >= 6 else ""
    return 0.01 if quote == "JPY" else 0.0001


def _nearest_above(price: float, levels: list[float]) -> float | None:
    above = [level for level in levels if level >= price]
    if above:
        return min(above)
    return max(levels, default=None)


def _nearest_below(price: float, levels: list[float]) -> float | None:
    below = [level for level in levels if level <= price]
    if below:
        return max(below)
    return min(levels, default=None)


def _numbers(source: Mapping[str, Any], keys: tuple[str, ...]) -> list[float]:
    values = [_number_or_none(source.get(key)) for key in keys]
    return [value for value in values if value is not None]


def _room_exhausted(room_to_move_pips: float | None) -> bool:
    return room_to_move_pips is not None and room_to_move_pips <= 8.0


def _first_number(*values: Any) -> float | None:
    for value in values:
        number = _number_or_none(value)
        if number is not None:
            return number
    return None


def _number_or_none(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_direction(value: Any) -> str | None:
    raw = _text(value).upper()
    return raw if raw in {"BUY", "SELL"} else None


def _text(value: Any) -> str:
    return str(value or "").strip()


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        deduped.append(cleaned)
    return deduped


__all__ = [
    "MICROBOOST_FOLLOWTHROUGH_ROLE_FIELDS",
    "MICROBOOST_ROLE_SOURCE_EVENT",
    "build_microboost_followthrough_role",
    "microboost_role_fields_from",
]
