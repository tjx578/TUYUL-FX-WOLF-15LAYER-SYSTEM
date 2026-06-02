"""Structure-aware execution gates for final SignalJSON candidates.

The gates are deliberately output-facing. They do not change Layer-12,
microboost classification, or lifecycle state; they only decide whether a
final SignalJSON is execution-ready enough to publish as a final log.
"""

from __future__ import annotations

from typing import Any

from analysis.signal_execution_gate_models import ExecutionGateDecision
from analysis.signal_json_emitter import VALID_SIGNAL_STATUSES
from analysis.signal_json_enrichment import enrich_signal_json_payload

_STRUCTURE_TARGET_MODES = {
    "FINAL_MARKET_STRUCTURE",
    "STRUCTURE_LADDER_TARGET",
    "KEY_LEVEL_STRUCTURE_TARGET",
}
_MICROBOOST_LATE_OR_EXHAUSTION_PHASES = {
    "EXHAUSTION_AT_RESISTANCE",
    "EXHAUSTION_AT_SUPPORT",
    "LATE_DENSE_PRESSURE",
}
_MICROBOOST_PULLBACK_PHASES = {
    "BULLISH_PULLBACK_MICROBOOST",
    "BEARISH_PULLBACK_MICROBOOST",
    "MINOR_PULLBACK_MICROBOOST",
}
_MICROBOOST_CONTINUATION_PHASES = {
    "TREND_CONTINUATION_MICROBOOST",
    "CONTINUATION_MICROBOOST",
    "CONFIRMATION_MICROBOOST",
}
_MICROBOOST_STRUCTURE_REACTION_PHASES = {
    "SUPPORT_BOUNCE_MICROBOOST",
    "RESISTANCE_REJECTION_MICROBOOST",
}
_MICROBOOST_PRESSURE_WARNING_PHASES = {
    "RESISTANCE_PRESSURE_WARNING",
    "SUPPORT_PRESSURE_WARNING",
}
_MICROBOOST_UNPRICED_PHASES = {
    "IGNITION_MICROBOOST",
    "DENSE_MICROBOOST",
    "REPEATED_MICROBOOST",
    "NEAR_TIMING_GATE_MICROBOOST",
}


def evaluate_signal_execution_gates(
    payload: dict[str, Any],
    *,
    min_rr_required: float = 2.5,
    max_chase_r: float = 0.35,
) -> ExecutionGateDecision:
    """Evaluate a final SignalJSON payload against execution-readiness gates."""
    if not _is_directional_final(payload):
        return ExecutionGateDecision(
            applies=False,
            decision="ALLOW",
            execution_status="NOT_APPLICABLE",
        )

    enriched = enrich_signal_json_payload(payload)
    block_reasons: list[str] = []
    block_gates: list[str] = []
    defer_reasons: list[str] = []
    defer_gates: list[str] = []

    _reinforcement_management_gate(payload, defer_gates, defer_reasons)
    _tradeplan_gate(payload, enriched, min_rr_required, defer_gates, defer_reasons)
    _spread_news_gate(payload, block_gates, block_reasons)
    _session_volatility_gate(payload, defer_gates, defer_reasons)
    _basket_theme_gate(payload, defer_gates, defer_reasons)
    _microboost_timing_gate(payload, defer_gates, defer_reasons, block_gates, block_reasons)
    live_rr = _live_rr_gate(payload, enriched, min_rr_required, defer_gates, defer_reasons, block_gates, block_reasons)
    _no_chase_gate(payload, enriched, max_chase_r, live_rr, block_gates, block_reasons)
    _structure_retest_gate(payload, defer_gates, defer_reasons, block_gates, block_reasons)

    if block_reasons:
        return ExecutionGateDecision(
            applies=True,
            decision="BLOCK",
            execution_status="EXECUTION_GATE_BLOCKED",
            blocked_by=tuple(dict.fromkeys(block_gates)),
            reasons=tuple(dict.fromkeys(block_reasons)),
            live_rr=live_rr,
        )
    if defer_reasons:
        return ExecutionGateDecision(
            applies=True,
            decision="DEFER",
            execution_status="EXECUTION_GATE_DEFERRED",
            blocked_by=tuple(dict.fromkeys(defer_gates)),
            reasons=tuple(dict.fromkeys(defer_reasons)),
            live_rr=live_rr,
        )
    return ExecutionGateDecision(
        applies=True,
        decision="ALLOW",
        execution_status="EXECUTION_GATE_ALLOWED",
        live_rr=live_rr,
    )


def _reinforcement_management_gate(payload: dict[str, Any], gates: list[str], reasons: list[str]) -> None:
    if str(payload.get("lifecycle_status") or "").upper() != "REINFORCES_ACTIVE_SIGNAL":
        return
    add_position_allowed = _optional_bool(payload.get("add_position_allowed"))
    add_on_retest_ready = _optional_bool(payload.get("add_on_retest_ready"))
    if add_position_allowed is True and add_on_retest_ready is True:
        return
    _add(gates, reasons, "ReinforcementManagementGate", "REINFORCEMENT_MANAGEMENT_ONLY")


def _tradeplan_gate(
    payload: dict[str, Any],
    enriched: dict[str, Any],
    min_rr_required: float,
    gates: list[str],
    reasons: list[str],
) -> None:
    target_mode = str(payload.get("target_mode") or "").upper()
    # A confirmed breakout/continuation can run on RR-projected provisional
    # targets when the structure ladder is not yet built.  If the engine already
    # marked those targets execution-usable, the RR status is valid, and the
    # provisional RR clears the minimum, treat the plan as complete instead of
    # forcing a structure-only target mode that the engine cannot produce here.
    provisional_usable = (
        _optional_bool(payload.get("targets_execution_usable")) is True
        and str(payload.get("rr_status") or "").upper() in {"VALID", "ACCEPTABLE"}
        and _provisional_rr_meets_min(payload, min_rr_required)
    )
    if target_mode not in _STRUCTURE_TARGET_MODES and not provisional_usable:
        _add(gates, reasons, "TradePlanCompletenessGate", "STRUCTURE_TARGET_MODE_REQUIRED")
        return

    direction = _direction(payload)
    entry = _first_float(payload.get("entry_reference_price"), payload.get("signal_valid_price"))
    selected_sl = _first_float(
        payload.get("selected_sl"),
        _nested(payload, "risk_reward", "selected_sl"),
        enriched.get("selected_sl"),
        payload.get("sl_safe"),
        payload.get("sl_tight"),
    )
    if entry is None or selected_sl is None:
        _add(gates, reasons, "TradePlanCompletenessGate", "ENTRY_OR_SELECTED_SL_MISSING")
    elif direction == "BUY" and selected_sl >= entry:
        _add(gates, reasons, "TradePlanCompletenessGate", "BUY_STOP_NOT_BELOW_ENTRY")
    elif direction == "SELL" and selected_sl <= entry:
        _add(gates, reasons, "TradePlanCompletenessGate", "SELL_STOP_NOT_ABOVE_ENTRY")

    support = _first_float(
        payload.get("key_support"),
        _nested(payload, "structure_zones", "key_support"),
        payload.get("main_support"),
        _nested(enriched, "structure_zones", "key_support"),
    )
    resistance = _first_float(
        payload.get("key_resistance"),
        _nested(payload, "structure_zones", "key_resistance"),
        payload.get("main_resistance"),
        _nested(enriched, "structure_zones", "key_resistance"),
    )
    if support is None or resistance is None:
        _add(gates, reasons, "TradePlanCompletenessGate", "SUPPORT_RESISTANCE_LADDER_INCOMPLETE")

    if not provisional_usable and not _has_structure_target(payload, enriched, min_rr_required):
        _add(gates, reasons, "TradePlanCompletenessGate", "STRUCTURE_TARGET_AT_MIN_RR_MISSING")


def _spread_news_gate(payload: dict[str, Any], gates: list[str], reasons: list[str]) -> None:
    spread_normal = _optional_bool(
        payload.get("spread_normal")
        if payload.get("spread_normal") is not None
        else _nested(payload, "execution_quality", "spread_normal")
    )
    if spread_normal is False:
        _add(gates, reasons, "SpreadNewsExecutionGate", "SPREAD_NOT_NORMAL")

    news_lock = payload.get("news_lock")
    news_active = bool(news_lock.get("active")) if isinstance(news_lock, dict) else _optional_bool(news_lock)
    if news_active is True or _optional_bool(payload.get("news_lock_active")) is True:
        _add(gates, reasons, "SpreadNewsExecutionGate", "NEWS_LOCK_ACTIVE")
    if _optional_bool(payload.get("news_blocked")) is True or _optional_bool(payload.get("is_news_locked")) is True:
        _add(gates, reasons, "SpreadNewsExecutionGate", "NEWS_LOCK_ACTIVE")


def _session_volatility_gate(payload: dict[str, Any], gates: list[str], reasons: list[str]) -> None:
    if _optional_bool(payload.get("session_trade_allowed")) is False:
        _add(gates, reasons, "SessionVolatilityGate", "SESSION_NOT_TRADEABLE")
    if _optional_bool(payload.get("volatility_trade_allowed")) is False:
        _add(gates, reasons, "SessionVolatilityGate", "VOLATILITY_NOT_TRADEABLE")


def _basket_theme_gate(payload: dict[str, Any], gates: list[str], reasons: list[str]) -> None:
    _ = (payload, gates, reasons)
    return


def _microboost_timing_gate(
    payload: dict[str, Any],
    defer_gates: list[str],
    defer_reasons: list[str],
    block_gates: list[str],
    block_reasons: list[str],
) -> None:
    if not _is_microboost_payload(payload):
        return

    phase_priced = _phase_value(payload, "phase_priced")
    phase_unpriced = _phase_value(payload, "phase_unpriced")
    action = str(payload.get("action") or _nested(payload, "microboost", "action") or "").upper()
    requires_market_context = _optional_bool(
        payload.get("requires_market_context")
        if payload.get("requires_market_context") is not None
        else _nested(payload, "microboost", "requires_market_context")
    )
    if requires_market_context is True or (
        phase_priced is None
        and phase_unpriced in _MICROBOOST_UNPRICED_PHASES
        and _optional_bool(payload.get("market_context_applied")) is not True
    ):
        _add(defer_gates, defer_reasons, "MicroBoostTimingGate", "MICROBOOST_MARKET_CONTEXT_REQUIRED")
        return

    if phase_priced in _MICROBOOST_LATE_OR_EXHAUSTION_PHASES or action == "PROTECT_PROFIT":
        _add(block_gates, block_reasons, "MicroBoostTimingGate", "MICROBOOST_NO_NEW_ENTRY_PROTECT_PROFIT")
        return

    if phase_priced in _MICROBOOST_PULLBACK_PHASES or action == "WAIT_PULLBACK_COMPLETION":
        if not _microboost_pullback_confirmed(payload):
            _add(
                defer_gates, defer_reasons, "MicroBoostTimingGate", "MICROBOOST_WAIT_M15_RECLAIM_OR_PULLBACK_COMPLETION"
            )
        return

    if phase_priced in _MICROBOOST_STRUCTURE_REACTION_PHASES:
        if not _microboost_structure_reaction_confirmed(payload):
            _add(
                defer_gates,
                defer_reasons,
                "MicroBoostTimingGate",
                "MICROBOOST_STRUCTURE_REACTION_CONFIRMATION_REQUIRED",
            )
        return

    if phase_priced in _MICROBOOST_PRESSURE_WARNING_PHASES:
        if not _microboost_pressure_warning_confirmed(payload):
            _add(
                defer_gates, defer_reasons, "MicroBoostTimingGate", "MICROBOOST_PRESSURE_WARNING_CONFIRMATION_REQUIRED"
            )
        return

    if phase_priced in _MICROBOOST_CONTINUATION_PHASES:
        return

    if phase_priced in {"COUNTER_BIAS_MICROBOOST", "ABSORPTION_WARNING", "REVERSAL_WARNING"} and not (
        _microboost_structure_reaction_confirmed(payload)
    ):
        _add(defer_gates, defer_reasons, "MicroBoostTimingGate", "MICROBOOST_STRUCTURE_CONFIRMATION_REQUIRED")


def _live_rr_gate(
    payload: dict[str, Any],
    enriched: dict[str, Any],
    min_rr_required: float,
    defer_gates: list[str],
    defer_reasons: list[str],
    block_gates: list[str],
    block_reasons: list[str],
) -> dict[str, Any] | None:
    direction = _direction(payload)
    live_price = _live_price(payload)
    entry = _first_float(payload.get("entry_reference_price"), payload.get("signal_valid_price"))
    selected_sl = _first_float(
        payload.get("selected_sl"),
        _nested(payload, "risk_reward", "selected_sl"),
        enriched.get("selected_sl"),
        payload.get("sl_safe"),
        payload.get("sl_tight"),
    )
    target = _first_float(
        payload.get("tp_min_rr"),
        _nested(payload, "risk_reward", "tp_min_rr"),
        payload.get("tp3"),
        enriched.get("tp_min_rr"),
    )
    if live_price is None:
        _add(defer_gates, defer_reasons, "LiveRRRecalculationGate", "LIVE_PRICE_MISSING")
        return None

    # When price is at or near the validated entry reference, the engine's
    # pre-validated rr_to_valid_target (computed with sl_tight) is the correct
    # live RR.  Recalculating from selected_sl (sl_safe) would give a falsely
    # low RR because the engine uses sl_tight for target calculation but sl_safe
    # for selected_sl — an internal inconsistency that should not block a valid
    # confirmed signal.
    near_entry = entry is not None and abs(live_price - entry) <= _pip_size(payload) * 10
    pre_validated_rr = _first_float(payload.get("rr_to_valid_target"), payload.get("tp_min_rr_value"))
    # PROVISIONAL_RR_FALLBACK leaves rr_to_valid_target unset (no structure target
    # is selected), which previously disabled the reconciliation guard above and
    # let the gate recompute RR from sl_safe — deflating a valid 2.5R into ~1.5R
    # and emitting a false LIVE_RR_BELOW_MINIMUM block.  When the pre-validated RR
    # is absent but price is near entry, reconstruct it on the SAME basis the
    # engine used to project the target ladder (sl_tight) so the two halves of
    # the RR calculation stay consistent.
    if pre_validated_rr is None and near_entry and target is not None:
        sl_tight = _first_float(payload.get("sl_tight"), _nested(payload, "risk_reward", "sl_tight"))
        if sl_tight is not None:
            tight_risk = abs(entry - sl_tight)
            if tight_risk > 0:
                pre_validated_rr = round(abs(target - entry) / tight_risk, 2)
    if pre_validated_rr is not None and near_entry:
        result = {
            "price": live_price,
            "entry": entry,
            "selected_sl": selected_sl,
            "target": target,
            "rr": pre_validated_rr,
            "min_rr_required": min_rr_required,
            "rr_basis": "PRE_VALIDATED_TIGHT",
        }
        if pre_validated_rr < min_rr_required:
            _add(block_gates, block_reasons, "LiveRRRecalculationGate", "LIVE_RR_BELOW_MINIMUM")
        return result

    if direction is None or selected_sl is None or target is None:
        _add(defer_gates, defer_reasons, "LiveRRRecalculationGate", "LIVE_RR_INPUT_INCOMPLETE")
        return {"price": live_price, "rr": None}
    risk = abs(live_price - selected_sl)
    reward = abs(target - live_price)
    live_rr = round(reward / risk, 2) if risk > 0 else None
    result = {
        "price": live_price,
        "entry": entry,
        "selected_sl": selected_sl,
        "target": target,
        "rr": live_rr,
        "min_rr_required": min_rr_required,
    }
    if live_rr is None:
        _add(defer_gates, defer_reasons, "LiveRRRecalculationGate", "LIVE_RR_INPUT_INCOMPLETE")
    elif live_rr < min_rr_required:
        _add(block_gates, block_reasons, "LiveRRRecalculationGate", "LIVE_RR_BELOW_MINIMUM")
    return result


def _no_chase_gate(
    payload: dict[str, Any],
    enriched: dict[str, Any],
    max_chase_r: float,
    live_rr: dict[str, Any] | None,
    gates: list[str],
    reasons: list[str],
) -> None:
    direction = _direction(payload)
    live_price = _first_float(live_rr.get("price") if isinstance(live_rr, dict) else None, _live_price(payload))
    entry = _first_float(payload.get("entry_reference_price"), payload.get("signal_valid_price"))
    selected_sl = _first_float(
        payload.get("selected_sl"),
        _nested(payload, "risk_reward", "selected_sl"),
        enriched.get("selected_sl"),
        payload.get("sl_safe"),
        payload.get("sl_tight"),
    )
    if direction is None or live_price is None or entry is None or selected_sl is None:
        return
    risk = abs(entry - selected_sl)
    if risk <= 0:
        return
    favorable_move = (live_price - entry) if direction == "BUY" else (entry - live_price)
    if favorable_move > risk * max(0.0, max_chase_r):
        _add(gates, reasons, "PricePositionGate", "PRICE_CHASE_TOO_FAR_FROM_ENTRY_REFERENCE")


def _structure_retest_gate(
    payload: dict[str, Any],
    defer_gates: list[str],
    defer_reasons: list[str],
    block_gates: list[str],
    block_reasons: list[str],
) -> None:
    status = str(payload.get("status") or "").upper()
    if "BUY_BREAKOUT" in status:
        held = _optional_bool(payload.get("m15_breakout_retest_held"))
        if held is False:
            _add(block_gates, block_reasons, "StructureRetestGate", "BREAKOUT_RETEST_FAILED")
        elif held is None and "RETEST" in status:
            _add(defer_gates, defer_reasons, "StructureRetestGate", "BREAKOUT_RETEST_NOT_CONFIRMED")
    if "SELL_BREAKDOWN" in status:
        held = _optional_bool(payload.get("m15_breakdown_retest_held"))
        if held is False:
            _add(block_gates, block_reasons, "StructureRetestGate", "BREAKDOWN_RETEST_FAILED")
        elif held is None and "RETEST" in status:
            _add(defer_gates, defer_reasons, "StructureRetestGate", "BREAKDOWN_RETEST_NOT_CONFIRMED")


def _is_directional_final(payload: dict[str, Any]) -> bool:
    status = str(payload.get("status") or "")
    return (
        (status in VALID_SIGNAL_STATUSES or status.endswith("_VALID"))
        and _direction(payload) in {"BUY", "SELL"}
        and _optional_bool(payload.get("valid_for_execution")) is True
    )


def _has_structure_target(payload: dict[str, Any], enriched: dict[str, Any], min_rr_required: float) -> bool:
    for source in (payload, enriched):
        targets = source.get("targets")
        if isinstance(targets, list):
            for item in targets:
                if not isinstance(item, dict):
                    continue
                if str(item.get("type") or "").upper() != "STRUCTURE_TARGET":
                    continue
                rr = _optional_float(item.get("rr"))
                if rr is None or rr >= min_rr_required:
                    return True
    for source in (payload, enriched):
        rr = _first_float(source.get("rr_to_valid_target"), source.get("tp_min_rr_value"))
        if rr is not None and rr >= min_rr_required and _first_float(source.get("tp_min_rr")) is not None:
            return True
    return False


def _provisional_rr_meets_min(payload: dict[str, Any], min_rr_required: float) -> bool:
    """True when the engine's own RR fields show the (provisional) plan clears min RR.

    Used to accept RR-projected fallback targets for confirmed breakout/continuation
    signals when no structure target is available. Reads only RR values the engine
    pre-computed against sl_tight, so it stays consistent with the live-RR gate.
    """
    for key in (
        "rr_to_valid_target",
        "tp_min_rr_value",
        "rr_to_tp3_tight",
        "tp3_rr",
        "rr_to_tp2_tight",
        "tp2_rr",
    ):
        rr = _optional_float(payload.get(key))
        if rr is not None and rr >= min_rr_required:
            return True
    return False


def _live_price(payload: dict[str, Any]) -> float | None:
    bid = _first_float(payload.get("bid"), _nested(payload, "market_context_snapshot", "bid"))
    ask = _first_float(payload.get("ask"), _nested(payload, "market_context_snapshot", "ask"))
    if bid is not None and ask is not None:
        return round((bid + ask) / 2.0, _price_digits(payload))
    return _first_float(
        payload.get("current_price"),
        payload.get("mid_price"),
        payload.get("last_price"),
        payload.get("price_at_signal_end"),
        _nested(payload, "market_context_snapshot", "current_price"),
        _nested(payload, "market_context_snapshot", "price_at_signal_end"),
        payload.get("signal_valid_price"),
        payload.get("entry_reference_price"),
    )


def _pip_size(payload: dict[str, Any]) -> float:
    return 0.01 if _price_digits(payload) == 3 else 0.0001


def _direction(payload: dict[str, Any]) -> str | None:
    direction = str(payload.get("final_direction") or "").upper()
    return direction if direction in {"BUY", "SELL"} else None


def _is_microboost_payload(payload: dict[str, Any]) -> bool:
    family = str(payload.get("signal_family") or payload.get("signal_type") or "").upper()
    status = str(payload.get("status") or "").upper()
    return (
        "MICROBOOST" in family
        or "MICROBOOST" in status
        or _phase_value(payload, "phase_priced") is not None
        or _phase_value(payload, "phase_unpriced") is not None
    )


def _phase_value(payload: dict[str, Any], key: str) -> str | None:
    value = _optional_str(payload.get(key))
    if value is None:
        value = _optional_str(_nested(payload, "microboost", key))
    if value is None:
        value = _optional_str(_nested(payload, "microboost_summary", f"latest_{key}"))
    return None if value is None else value.upper()


def _microboost_pullback_confirmed(payload: dict[str, Any]) -> bool:
    if _optional_bool(payload.get("microboost_timing_confirmed")) is True:
        return True
    for key in (
        "m15_reclaim_confirmed",
        "reclaim_confirmed",
        "pullback_completion_confirmed",
        "m15_pullback_complete",
        "support_reclaim_confirmed",
        "breakout_retest_held",
        "m15_breakout_retest_held",
        "m15_breakdown_retest_held",
    ):
        if _optional_bool(payload.get(key)) is True:
            return True
    confirmation = str(payload.get("m15_confirmation_status") or "").upper()
    return any(token in confirmation for token in ("RECLAIM", "PULLBACK_COMPLETION", "RETEST_HELD", "SUPPORT_HOLD"))


def _microboost_structure_reaction_confirmed(payload: dict[str, Any]) -> bool:
    if _optional_bool(payload.get("microboost_timing_confirmed")) is True:
        return True
    for key in (
        "structure_reaction_confirmed",
        "m15_rejection_from_resistance",
        "m15_rejection_from_support",
        "m15_close_above_minor_resistance",
        "m15_close_below_minor_support",
        "m15_close_above_resistance",
        "m15_close_below_support",
    ):
        if _optional_bool(payload.get(key)) is True:
            return True
    confirmation = str(payload.get("m15_confirmation_status") or "").upper()
    return any(
        token in confirmation for token in ("REJECTION_CONFIRMED", "BOUNCE_CONFIRMED", "CLOSE_ABOVE", "CLOSE_BELOW")
    )


def _microboost_pressure_warning_confirmed(payload: dict[str, Any]) -> bool:
    if str(payload.get("confirmation_policy") or "").upper() == "DIRECT_ABSORPTION_NO_M15_WAIT":
        return True
    if str(payload.get("m15_confirmation_status") or "").upper() == "DIRECT_ABSORPTION_CONFIRMED":
        return True
    direction = _direction(payload)
    phase_priced = _phase_value(payload, "phase_priced")
    if direction == "BUY" and phase_priced == "RESISTANCE_PRESSURE_WARNING":
        return _optional_bool(payload.get("m15_close_above_resistance")) is True or (
            str(payload.get("m15_confirmation_status") or "").upper() == "M15_CLOSE_ABOVE_RESISTANCE"
        )
    if direction == "SELL" and phase_priced == "SUPPORT_PRESSURE_WARNING":
        return _optional_bool(payload.get("m15_close_below_support")) is True or (
            str(payload.get("m15_confirmation_status") or "").upper() == "M15_CLOSE_BELOW_SUPPORT"
        )
    return _microboost_structure_reaction_confirmed(payload)


def _nested(payload: dict[str, Any], container: str, key: str) -> Any:
    value = payload.get(container)
    return value.get(key) if isinstance(value, dict) else None


def _first_float(*values: Any) -> float | None:
    for value in values:
        number = _optional_float(value)
        if number is not None:
            return number
    return None


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return None


def _optional_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _price_digits(payload: dict[str, Any]) -> int:
    symbol = str(payload.get("symbol") or "").upper()
    return 3 if symbol.endswith("JPY") else 5


def _add(gates: list[str], reasons: list[str], gate: str, reason: str) -> None:
    gates.append(gate)
    reasons.append(reason)
