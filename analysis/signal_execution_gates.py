"""Structure-aware execution gates for final SignalJSON candidates.

The gates are deliberately output-facing. They do not change Layer-12,
microboost classification, or lifecycle state; they only decide whether a
final SignalJSON is execution-ready enough to publish as a final log.
"""

from __future__ import annotations

import os
from typing import Any

from analysis.signal_execution_gate_models import ExecutionGateDecision
from analysis.signal_json_emitter import VALID_SIGNAL_STATUSES
from analysis.signal_json_enrichment import enrich_signal_json_payload
from analysis.signal_thresholds import SIGNAL_MIN_RR
from contracts.strategy_5scr import evaluate_strategy_5scr_proof

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
    min_rr_required: float = SIGNAL_MIN_RR,
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

    _strategy_5scr_context_gate(payload, block_gates, block_reasons, defer_gates, defer_reasons)
    _reinforcement_management_gate(payload, defer_gates, defer_reasons)
    _tradeplan_gate(
        payload,
        enriched,
        min_rr_required,
        defer_gates,
        defer_reasons,
    )
    _execution_contract_flag_gate(payload, defer_gates, defer_reasons)
    _spread_news_gate(payload, block_gates, block_reasons)
    _pattern_permission_gate(payload, block_gates, block_reasons)
    _provisional_rr_fallback_gate(payload, block_gates, block_reasons)
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


def _strategy_5scr_context_gate(
    payload: dict[str, Any],
    block_gates: list[str],
    block_reasons: list[str],
    defer_gates: list[str],
    defer_reasons: list[str],
) -> None:
    execution_gate = payload.get("execution_gate")
    nested_proof = execution_gate.get("strategy_5scr") if isinstance(execution_gate, dict) else None
    if payload.get("strategy_5scr_required") is not True and not isinstance(
        payload.get("strategy_5scr") or nested_proof, dict
    ):
        return
    evaluation = evaluate_strategy_5scr_proof(payload)
    if evaluation.decision == "BLOCK":
        for reason in evaluation.reasons:
            _add(block_gates, block_reasons, "Strategy5SCRContextGate", reason)
    elif evaluation.decision == "DEFER":
        for reason in evaluation.reasons:
            _add(defer_gates, defer_reasons, "Strategy5SCRContextGate", reason)


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
    target_mode = str(_nested(payload, "tradeplan_preview", "target_mode") or payload.get("target_mode") or "").upper()
    if target_mode == "PROVISIONAL_RR_FALLBACK":
        _add(gates, reasons, "TradePlanCompletenessGate", "PROVISIONAL_RR_FALLBACK_NOT_EXECUTION_GRADE")
    if target_mode not in _STRUCTURE_TARGET_MODES:
        _add(gates, reasons, "TradePlanCompletenessGate", "STRUCTURE_TARGET_MODE_REQUIRED")
        return

    direction = _direction(payload)
    entry = _first_float(payload.get("entry_reference_price"), payload.get("signal_valid_price"))
    selected_sl = _first_float(
        payload.get("selected_sl"),
        _nested(payload, "risk_reward", "selected_sl"),
        enriched.get("selected_sl"),
        payload.get("sl_safe"),
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

    if not _has_structure_target(payload, enriched, min_rr_required):
        _add(gates, reasons, "TradePlanCompletenessGate", "STRUCTURE_TARGET_AT_MIN_RR_MISSING")


def _execution_contract_flag_gate(
    payload: dict[str, Any],
    gates: list[str],
    reasons: list[str],
) -> None:
    """Honor explicit contract flags already computed upstream."""
    explicit_execution_now = _first_bool(
        _nested(payload, "execution_gate", "execution_valid_now"),
        payload.get("execution_valid_now"),
    )
    if explicit_execution_now is False:
        _add(gates, reasons, "ExecutionContractGate", "EXECUTION_VALID_NOW_FALSE")
    explicit_valid_for_execution = _first_bool(
        _nested(payload, "execution_gate", "valid_for_execution"),
        payload.get("valid_for_execution"),
    )
    if explicit_valid_for_execution is False:
        _add(gates, reasons, "ExecutionContractGate", "VALID_FOR_EXECUTION_FALSE")

    explicit_tradeplan_valid = _first_bool(
        _nested(payload, "tradeplan_preview", "tradeplan_valid"),
        payload.get("tradeplan_valid"),
    )
    tradeplan_ready = _first_bool(
        _nested(payload, "tradeplan_preview", "tradeplan_context_ready"),
        payload.get("tradeplan_context_ready"),
    )
    targets_usable = _first_bool(
        _nested(payload, "tradeplan_preview", "targets_execution_usable"),
        payload.get("targets_execution_usable"),
    )
    if targets_usable is False or explicit_tradeplan_valid is False or tradeplan_ready is False:
        _add(gates, reasons, "ExecutionContractGate", "TRADEPLAN_CONTRACT_NOT_READY")


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


def _provisional_rr_fallback_gate(payload: dict[str, Any], gates: list[str], reasons: list[str]) -> None:
    """Hard-BLOCK any PROVISIONAL_RR_FALLBACK target from execution.

    A provisional RR-only target has no confirmed structure ladder, so it is never
    execution-grade. Previously this was only a DEFER (via ``_tradeplan_gate``), which
    means it could "un-defer" into execution once an unrelated condition cleared, and
    it relied on another gate (e.g. PatternPermissionGate) incidentally blocking it.
    This makes the rejection explicit and independent: target_mode==PROVISIONAL_RR_FALLBACK
    => BLOCK, so ``valid_for_execution``/``execution_valid_now`` are forced false by the
    gate adapter and no SignalJSON is ever published from it.
    Kill switch (default ON): ``SIGNAL_EXEC_PROVISIONAL_RR_HARD_BLOCK_ENABLED=false``.
    """
    if os.getenv("SIGNAL_EXEC_PROVISIONAL_RR_HARD_BLOCK_ENABLED", "true").strip().lower() != "true":
        return
    target_mode = str(_nested(payload, "tradeplan_preview", "target_mode") or payload.get("target_mode") or "").upper()
    if target_mode == "PROVISIONAL_RR_FALLBACK":
        _add(gates, reasons, "ProvisionalRRFallbackGate", "PROVISIONAL_RR_FALLBACK_NOT_EXECUTABLE")


def _pattern_permission_gate(payload: dict[str, Any], gates: list[str], reasons: list[str]) -> None:
    """Block a final whose pattern entry-permission contradicts the direction.

    The pattern/throttle layer can mark a price location as "no new entry"
    (exhaustion, absorption, late stage). A directional final must not claim
    execution while the selected pattern forbids opening that side here.
    Chase-only permissions (NO_MARKET_CHASE / *_CHASE) are deliberately left to
    the no-chase gate so a valid retest entry is not over-blocked.
    """
    direction = _direction(payload)
    permission = str(
        payload.get("entry_permission")
        or _nested(payload, "execution_gate", "entry_permission")
        or _nested(payload, "pattern_context", "entry_permission")
        or ""
    ).upper()
    if not permission:
        return
    if permission == "NO_TRADE":
        _add(gates, reasons, "PatternPermissionGate", "PATTERN_PERMISSION_NO_TRADE")
    elif permission in {"NO_NEW_ENTRY", "BLOCK_NEW_ENTRY"}:
        _add(gates, reasons, "PatternPermissionGate", "PATTERN_PERMISSION_NO_NEW_ENTRY")
    elif direction == "BUY" and (
        permission in {"NO_NEW_BUY", "NO_BUY"} or permission.startswith("NO_NEW_BUY") or permission.startswith("NO_BUY")
    ):
        _add(gates, reasons, "PatternPermissionGate", "PATTERN_PERMISSION_NO_NEW_BUY")
    elif direction == "SELL" and (
        permission in {"NO_NEW_SELL", "NO_SELL"}
        or permission.startswith("NO_NEW_SELL")
        or permission.startswith("NO_SELL")
    ):
        _add(gates, reasons, "PatternPermissionGate", "PATTERN_PERMISSION_NO_NEW_SELL")


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
    live_price = _live_entry_price(payload, direction)
    exit_price = _live_exit_price(payload, direction)
    entry = _first_float(payload.get("entry_reference_price"), payload.get("signal_valid_price"))
    selected_sl = _first_float(
        payload.get("selected_sl"),
        _nested(payload, "risk_reward", "selected_sl"),
        enriched.get("selected_sl"),
        payload.get("sl_safe"),
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

    if direction is not None and selected_sl is not None and target is not None:
        stop_breached = (direction == "BUY" and exit_price <= selected_sl) or (
            direction == "SELL" and exit_price >= selected_sl
        )
        target_reached = (direction == "BUY" and exit_price >= target) or (direction == "SELL" and exit_price <= target)
        if stop_breached or target_reached:
            reason = "LIVE_PRICE_AT_OR_BEYOND_STOP" if stop_breached else "TARGET_ALREADY_REACHED_NO_NEW_ENTRY"
            _add(block_gates, block_reasons, "LivePriceValidityGate", reason)
            return {
                "price": live_price,
                "exit_price": exit_price,
                "entry": entry,
                "selected_sl": selected_sl,
                "target": target,
                "rr": None,
                "min_rr_required": min_rr_required,
                "price_valid_for_new_entry": False,
                "price_invalid_reason": reason,
            }

    # Single-stop model: the target ladder and the live stop are both derived from
    # sl_safe, so the engine's pre-validated RR (rr_to_valid_target / tp_min_rr_value)
    # is the authoritative live RR when price is at or near the validated entry.
    # Prefer it so micro-noise in the recalculated value cannot trip a false block.
    near_entry = entry is not None and abs(live_price - entry) <= _pip_size(payload) * 10
    pre_validated_rr = _first_float(payload.get("rr_to_valid_target"), payload.get("tp_min_rr_value"))
    if pre_validated_rr is not None and near_entry:
        result = {
            "price": live_price,
            "entry": entry,
            "selected_sl": selected_sl,
            "target": target,
            "rr": pre_validated_rr,
            "min_rr_required": min_rr_required,
            "rr_basis": "PRE_VALIDATED",
        }
        if pre_validated_rr < min_rr_required:
            _add(block_gates, block_reasons, "LiveRRRecalculationGate", "LIVE_RR_BELOW_MINIMUM")
        return result

    if direction is None or selected_sl is None or target is None:
        _add(defer_gates, defer_reasons, "LiveRRRecalculationGate", "LIVE_RR_INPUT_INCOMPLETE")
        return {"price": live_price, "rr": None}
    risk = live_price - selected_sl if direction == "BUY" else selected_sl - live_price
    reward = target - live_price if direction == "BUY" else live_price - target
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


def _live_price(payload: dict[str, Any]) -> float | None:
    bid = _first_float(
        payload.get("observed_bid"), payload.get("bid"), _nested(payload, "market_context_snapshot", "bid")
    )
    ask = _first_float(
        payload.get("observed_ask"), payload.get("ask"), _nested(payload, "market_context_snapshot", "ask")
    )
    if bid is not None and ask is not None:
        return round((bid + ask) / 2.0, _price_digits(payload))
    return _first_float(
        payload.get("observed_mid"),
        payload.get("current_price"),
        payload.get("mid_price"),
        payload.get("last_price"),
        payload.get("price_at_signal_end"),
        _nested(payload, "market_context_snapshot", "current_price"),
        _nested(payload, "market_context_snapshot", "price_at_signal_end"),
        payload.get("signal_valid_price"),
        payload.get("entry_reference_price"),
    )


def _live_entry_price(payload: dict[str, Any], direction: str | None) -> float | None:
    bid = _first_float(
        payload.get("observed_bid"), payload.get("bid"), _nested(payload, "market_context_snapshot", "bid")
    )
    ask = _first_float(
        payload.get("observed_ask"), payload.get("ask"), _nested(payload, "market_context_snapshot", "ask")
    )
    if bid is not None and ask is not None:
        return (
            ask
            if direction == "BUY"
            else (bid if direction == "SELL" else round((bid + ask) / 2.0, _price_digits(payload)))
        )
    return _live_price(payload)


def _live_exit_price(payload: dict[str, Any], direction: str | None) -> float | None:
    bid = _first_float(
        payload.get("observed_bid"), payload.get("bid"), _nested(payload, "market_context_snapshot", "bid")
    )
    ask = _first_float(
        payload.get("observed_ask"), payload.get("ask"), _nested(payload, "market_context_snapshot", "ask")
    )
    if bid is not None and ask is not None:
        return (
            bid
            if direction == "BUY"
            else (ask if direction == "SELL" else round((bid + ask) / 2.0, _price_digits(payload)))
        )
    return _live_price(payload)


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


def _first_bool(*values: Any) -> bool | None:
    for value in values:
        parsed = _optional_bool(value)
        if parsed is not None:
            return parsed
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
