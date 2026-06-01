"""Feature matcher for the Golden SignalThrottle pattern registry."""

from __future__ import annotations

from collections.abc import Mapping
from numbers import Real
from typing import Any

from .registry import GoldenPattern, get_pattern, pair_role_for_symbol

_STRATEGY_TO_PATTERN = {
    "UPPER_RANGE_EXHAUSTION": "UPPER_ABSORPTION_WARNING",
    "UPPER_ABSORPTION_WARNING": "UPPER_ABSORPTION_WARNING",
    "BEARISH_LIQUIDATION_EXPANSION": "LIQUIDATION_EXPANSION",
    "BEARISH_BREAKDOWN_CASCADE": "PHASE_SENSITIVE_BREAKDOWN",
    "CLEAN_BEARISH_CONTINUATION_PRESSURE": "LOWER_RANGE_NO_CHASE_FILTER",
    "BEARISH_PULLBACK_SELL_RALLY": "LOWER_RANGE_NO_CHASE_FILTER",
    "LOWER_RANGE_SELL_EXHAUSTION": "LOWER_RANGE_NO_CHASE_FILTER",
    "BULLISH_UPPER_RANGE_CONTINUATION": "HIGH_DENSITY_ACCELERATION",
    "BULLISH_CONTINUATION_PRESSURE": "OPEN_LANE_TIMING_VALID",
    "BUY_PRESSURE_COUNTER_TO_BEARISH_PHASE": "PRE_IGNITION_COUNTERFLOW_TRAP",
    "SELL_PRESSURE_COUNTER_TO_BULLISH_PHASE": "PRE_IGNITION_COUNTERFLOW_TRAP",
}


def match_golden_patterns(features: Mapping[str, Any] | Any) -> dict[str, Any]:
    data = _as_mapping(features)
    symbol = _text(data.get("symbol")).upper()
    pair_role = pair_role_for_symbol(symbol)
    pair_patterns = set(pair_role.get("golden_patterns") or [])
    strategy_pattern = _text(data.get("strategy_pattern")).upper()
    phase_priced = _text(data.get("phase_priced")).upper()
    phase_unpriced = _text(data.get("phase_unpriced")).upper()
    pressure_temperature = _text(data.get("pressure_temperature")).upper()
    price_position = _normalize_position(data.get("price_position"))
    final_direction = _normalize_direction(data.get("final_direction"))
    raw_direction = _normalize_direction(data.get("raw_allowed_direction") or data.get("raw_direction") or data.get("direction"))
    theme_aligned = _optional_bool(data.get("theme_aligned"))
    jpy_alignment = _text(data.get("jpy_alignment") or data.get("jpy_alignment_status")).upper()
    dual_theme_status = _text(data.get("dual_theme_status")).upper()
    candidates: dict[str, int] = {}
    evidence: list[str] = []

    _add_strategy_candidate(candidates, evidence, strategy_pattern)
    _add_pressure_candidate(candidates, evidence, data, pressure_temperature)
    _add_microboost_candidate(candidates, evidence, phase_unpriced, phase_priced, price_position, data)
    _add_pair_role_candidate(candidates, evidence, symbol, pair_patterns, raw_direction, final_direction, data)
    _add_theme_candidate(candidates, evidence, symbol, theme_aligned, jpy_alignment, dual_theme_status, pair_patterns)
    _add_metal_candidate(candidates, evidence, symbol, price_position, data)
    _add_major_context_candidate(candidates, evidence, symbol, data)

    selected_id = _select_candidate(candidates)
    selected = get_pattern(selected_id)
    matched = [pattern_id for pattern_id, _ in sorted(candidates.items(), key=lambda item: (item[1], item[0]), reverse=True)]
    score = _pattern_score(data, selected, candidates.get(selected_id or "", 0), evidence)
    block_reason = _block_reason_from_features(data)
    if selected and selected.block_reason:
        block_reason = selected.block_reason
    return {
        "matched_patterns": matched,
        "selected_pattern_id": selected.pattern_id if selected else None,
        "pattern_tier": selected.tier if selected else None,
        "pattern_family": selected.family if selected else None,
        "pattern_score": score,
        "golden_reference": selected.golden_source if selected else None,
        "pair_role": pair_role.get("default_role"),
        "entry_permission": selected.entry_permission if selected else _default_entry_permission(data),
        "management_action": selected.management_action if selected else None,
        "hold_policy": selected.hold_policy if selected else None,
        "chase_allowed": bool(selected.chase_allowed) if selected else False,
        "block_reason": block_reason,
        "pattern_evidence": evidence[:8],
    }


def _add_strategy_candidate(candidates: dict[str, int], evidence: list[str], strategy_pattern: str) -> None:
    pattern_id = _STRATEGY_TO_PATTERN.get(strategy_pattern)
    if pattern_id:
        _bump(candidates, pattern_id, 35)
        evidence.append(f"strategy_pattern={strategy_pattern}")


def _add_pressure_candidate(
    candidates: dict[str, int],
    evidence: list[str],
    data: Mapping[str, Any],
    pressure_temperature: str,
) -> None:
    events = _num(data.get("event_count") or data.get("events") or data.get("effective_ticks"))
    density = _num(data.get("density_per_minute") or data.get("effective_density_per_minute"))
    duration = _num(data.get("duration_seconds")) or _num(data.get("duration_minutes")) * 60.0
    if pressure_temperature == "SPARSE_ARCHIVE" or (events <= 3 and density < 0.5 and duration >= 300.0):
        _bump(candidates, "SPARSE_ARCHIVE", 80)
        evidence.append("sparse_pressure_archive")
    if duration >= 300.0 and 0.5 <= density < 4.0:
        _bump(candidates, "OPEN_LANE_TIMING_VALID", 12)
        evidence.append("duration_valid_low_to_moderate_density")
    if density >= 8.0:
        _bump(candidates, "HIGH_DENSITY_ACCELERATION", 10)
        evidence.append("high_density_pressure")


def _add_microboost_candidate(
    candidates: dict[str, int],
    evidence: list[str],
    phase_unpriced: str,
    phase_priced: str,
    price_position: str | None,
    data: Mapping[str, Any],
) -> None:
    if phase_unpriced in {"IGNITION_MICROBOOST", "DENSE_MICROBOOST", "NEAR_TIMING_GATE_MICROBOOST"}:
        if _optional_bool(data.get("is_late_pressure")) or phase_priced == "LATE_DENSE_PRESSURE":
            _bump(candidates, "LATE_MICROBOOST_DECISION_POINT", 32)
            evidence.append("late_microboost_decision_point")
        elif price_position == "MAIN_RESISTANCE":
            _bump(candidates, "LATE_UPPER_MICROBOOST", 28)
            evidence.append("microboost_at_upper_range")
        else:
            _bump(candidates, "DELAYED_IGNITION_MICROBOOST", 18)
            evidence.append("microboost_requires_structure_confirmation")
    if phase_priced in {"RESISTANCE_PRESSURE_WARNING", "EXHAUSTION_AT_RESISTANCE"}:
        _bump(candidates, "UPPER_ABSORPTION_WARNING", 35)
        evidence.append(f"phase_priced={phase_priced}")
    if phase_priced == "LATE_DENSE_PRESSURE":
        _bump(candidates, "LATE_DENSE_CONGESTION", 35)
        evidence.append("late_dense_pressure")


def _add_pair_role_candidate(
    candidates: dict[str, int],
    evidence: list[str],
    symbol: str,
    pair_patterns: set[str],
    raw_direction: str | None,
    final_direction: str | None,
    data: Mapping[str, Any],
) -> None:
    if symbol == "USDCAD" and str(data.get("signalwatch_status") or data.get("status") or "").upper().endswith("WATCH"):
        _bump(candidates, "SIGNALWATCH_LIFECYCLE_FINALIZER", 24)
        evidence.append("usdcad_signalwatch_lifecycle")
    if symbol == "USDCAD" and _optional_bool(data.get("m15_close_above_resistance")) and raw_direction == "SELL":
        _bump(candidates, "HIGH_DENSITY_ABSORPTION_WITH_RECLAIM", 42)
        evidence.append("usdcad_sell_watch_reclaimed")
    if symbol in {"CADCHF", "CADJPY"} and final_direction == "SELL":
        _bump(candidates, "INVERSE_MIRROR_BREAKDOWN_CONFIRMATION", 18)
        evidence.append("cad_base_inverse_sell_context")
    if "CONFIRMATION_PAIR_NOT_PRIMARY_ENTRY" in pair_patterns and not _optional_bool(data.get("own_clean_block")):
        _bump(candidates, "CONFIRMATION_PAIR_NOT_PRIMARY_ENTRY", 16)
        evidence.append("confirmation_pair_requires_own_trigger")
    if symbol == "GBPNZD":
        _bump(candidates, "SAME_PAIR_TAKEOVER", 12)
        evidence.append("gbpnzd_takeover_role")


def _add_theme_candidate(
    candidates: dict[str, int],
    evidence: list[str],
    symbol: str,
    theme_aligned: bool | None,
    jpy_alignment: str,
    dual_theme_status: str,
    pair_patterns: set[str],
) -> None:
    if symbol.endswith("JPY") or symbol.startswith("JPY"):
        _bump(candidates, "JPY_ALIGNMENT_REQUIRED", 20)
        evidence.append("jpy_cross_requires_alignment")
        if jpy_alignment in {"CONFLICT", "MIXED", "BLOCKED"} or dual_theme_status == "CONFLICT":
            _bump(candidates, "CLEAN_BLOCK_BUT_THEME_CONFLICT", 60)
            evidence.append("jpy_or_dual_theme_conflict")
    if theme_aligned is False:
        _bump(candidates, "CLEAN_BLOCK_BUT_THEME_CONFLICT", 50)
        evidence.append("theme_mismatch")
    if "MIRROR_BASKET_CONFIRMATION" in pair_patterns or symbol in {"NZDCAD", "CADCHF", "CADJPY"}:
        _bump(candidates, "MIRROR_BASKET_CONFIRMATION", 10)
        evidence.append("mirror_basket_role_available")


def _add_metal_candidate(
    candidates: dict[str, int],
    evidence: list[str],
    symbol: str,
    price_position: str | None,
    data: Mapping[str, Any],
) -> None:
    if not symbol.startswith(("XAU", "XAG")):
        return
    _bump(candidates, "METAL_SUSTAINED_PRESSURE_CONTEXT", 30)
    evidence.append("metal_pressure_hold_policy")
    if price_position == "MAIN_RESISTANCE" or _num(data.get("range_position")) >= 0.88:
        _bump(candidates, "METAL_NO_CHASE_AFTER_UPPER_SPIKE", 55)
        evidence.append("metal_upper_spike_no_chase")
    if _num(data.get("mfe_1h_pips")) > 0 and _num(data.get("mae_4h_pips")) >= _num(data.get("mfe_1h_pips")):
        _bump(candidates, "METAL_SHORT_WINDOW_CONTINUATION_THEN_WHIPSAW", 35)
        evidence.append("metal_fast_mfe_whipsaw_risk")


def _add_major_context_candidate(
    candidates: dict[str, int],
    evidence: list[str],
    symbol: str,
    data: Mapping[str, Any],
) -> None:
    if symbol == "EURUSD" and "PULLBACK" in _text(data.get("m15_phase")).upper():
        _bump(candidates, "PULLBACK_WITHIN_H4_EXPANSION", 18)
        evidence.append("major_pair_pullback_context")
    if symbol == "EURAUD":
        _bump(candidates, "MULTI_WAVE_PRIORITY", 12)
        evidence.append("euraud_multi_wave_role")


def _pattern_score(
    data: Mapping[str, Any],
    selected: GoldenPattern | None,
    candidate_score: int,
    evidence: list[str],
) -> int:
    if selected is None:
        return 0
    score = candidate_score
    score += {"S": 16, "A": 10, "B": 4}.get(selected.tier, 0)
    score += min(20, int(_num(data.get("density_per_minute") or data.get("effective_density_per_minute")) * 2))
    score += min(15, int((_num(data.get("duration_seconds")) or _num(data.get("duration_minutes")) * 60.0) / 60.0))
    if _optional_bool(data.get("theme_aligned")) is True:
        score += 10
    if _optional_bool(data.get("spread_normal")) is False:
        score -= 20
        evidence.append("spread_penalty")
    if selected.pattern_id == "SPARSE_ARCHIVE":
        score -= 50
        score = min(score, 39)
    if selected.family in {"THEME_CONFLICT_FILTER", "DAILY_CONFLICT_FILTER", "TRAP_FILTER"}:
        score -= 35
    if selected.entry_permission in {"NO_TRADE", "NO_SELL"}:
        score = min(score, 39)
    if selected.entry_permission in {"NO_NEW_ENTRY", "NO_MARKET_CHASE", "NO_NEW_BUY", "BLOCK_NEW_ENTRY"}:
        score -= 25
        score = min(score, 69)
    return max(0, min(100, int(score)))


def _select_candidate(candidates: dict[str, int]) -> str | None:
    if not candidates:
        return None
    return max(candidates.items(), key=lambda item: (item[1], item[0]))[0]


def _default_entry_permission(data: Mapping[str, Any]) -> str:
    final = _normalize_direction(data.get("final_direction"))
    if final in {"BUY", "SELL"}:
        return "RETEST_ONLY"
    return "WAIT_CONFIRMATION"


def _block_reason_from_features(data: Mapping[str, Any]) -> str | None:
    if _optional_bool(data.get("theme_aligned")) is False:
        return "THEME_MISMATCH"
    if _optional_bool(data.get("spread_normal")) is False:
        return "SPREAD_NOT_NORMAL"
    return None


def _bump(candidates: dict[str, int], pattern_id: str, amount: int) -> None:
    if get_pattern(pattern_id) is None:
        return
    candidates[pattern_id] = candidates.get(pattern_id, 0) + amount


def _as_mapping(value: Mapping[str, Any] | Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "__dict__"):
        return vars(value)
    return {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _num(value: Any) -> float:
    if value is None or isinstance(value, bool):
        return 0.0
    if isinstance(value, Real):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return 0.0


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on", "aligned"}:
        return True
    if text in {"0", "false", "no", "n", "off", "conflict", "mismatch"}:
        return False
    return None


def _normalize_direction(value: Any) -> str | None:
    text = _text(value).upper()
    if text in {"BUY", "BULL", "BULLISH", "LONG"}:
        return "BUY"
    if text in {"SELL", "BEAR", "BEARISH", "SHORT"}:
        return "SELL"
    return None


def _normalize_position(value: Any) -> str | None:
    text = _text(value).upper()
    if text in {"MAIN_RESISTANCE", "RESISTANCE", "NEAR_RESISTANCE", "UPPER_RANGE"}:
        return "MAIN_RESISTANCE"
    if text in {"MAIN_SUPPORT", "SUPPORT", "NEAR_SUPPORT", "LOWER_RANGE"}:
        return "MAIN_SUPPORT"
    if text in {"MID_RANGE", "VALUE_AREA", "RANGE_MID"}:
        return "MID_RANGE"
    return text or None
