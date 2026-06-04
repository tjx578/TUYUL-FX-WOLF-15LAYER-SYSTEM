"""Feature matcher for the Golden SignalThrottle pattern registry."""

from __future__ import annotations

import re
from collections.abc import Mapping
from numbers import Real
from typing import Any

from .registry import GOLDEN_PATTERNS, SCORING_MODEL, GoldenPattern, get_pattern, pair_role_for_symbol

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

_PATTERN_ID_SET = {pattern.pattern_id for pattern in GOLDEN_PATTERNS}
_PATTERN_TEXT_INDEX: dict[str, frozenset[str]] = {}
_EXACT_PATTERN_FIELDS = (
    "selected_pattern_id",
    "pattern_id",
    "strategy_pattern",
    "signal_archetype",
    "source_selected_pattern_id",
)
_PATTERN_LIST_FIELDS = (
    "matched_patterns",
    "pattern_candidates",
    "candidate_patterns",
)


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
    raw_direction = _normalize_direction(
        data.get("raw_allowed_direction") or data.get("raw_direction") or data.get("direction")
    )
    theme_aligned = _optional_bool(data.get("theme_aligned"))
    jpy_alignment = _text(data.get("jpy_alignment") or data.get("jpy_alignment_status")).upper()
    dual_theme_status = _text(data.get("dual_theme_status")).upper()
    candidates: dict[str, int] = {}
    evidence: list[str] = []
    diagnostics: dict[str, Any] = _new_pattern_diagnostics(symbol, pair_patterns)

    _add_exact_pattern_candidate(candidates, evidence, data, diagnostics)
    _add_strategy_candidate(candidates, evidence, strategy_pattern)
    _add_pressure_candidate(candidates, evidence, data, pressure_temperature)
    _add_microboost_candidate(candidates, evidence, phase_unpriced, phase_priced, price_position, data)
    _add_pair_role_candidate(candidates, evidence, symbol, pair_patterns, raw_direction, final_direction, data)
    _add_universal_reference_candidate(candidates, evidence, symbol, raw_direction, final_direction, data)
    _add_structural_universal_candidate(candidates, evidence, symbol, raw_direction, final_direction, data)
    _add_new_universal_pattern_candidates(candidates, evidence, data, symbol, raw_direction, final_direction)
    _add_theme_candidate(candidates, evidence, symbol, theme_aligned, jpy_alignment, dual_theme_status, pair_patterns)
    _add_metal_candidate(candidates, evidence, symbol, price_position, data)
    _add_major_context_candidate(candidates, evidence, symbol, data)
    _add_database_semantic_candidates(candidates, evidence, data, symbol, pair_patterns, diagnostics)

    selected_id = _select_candidate(candidates)
    selected = get_pattern(selected_id)
    selected_payload = selected.to_dict() if selected else {}
    matched = [
        pattern_id for pattern_id, _ in sorted(candidates.items(), key=lambda item: (item[1], item[0]), reverse=True)
    ]
    pattern_match_score = _pattern_match_score(data, selected, candidates.get(selected_id or "", 0))
    execution_readiness_score = _execution_readiness_score(data, selected, pattern_match_score, evidence)
    block_reason = _block_reason_from_features(data)
    if selected and selected.block_reason:
        block_reason = selected.block_reason
    alignment = _alignment_metadata(
        data,
        symbol=symbol,
        theme_aligned=theme_aligned,
        jpy_alignment=jpy_alignment,
        dual_theme_status=dual_theme_status,
    )
    diagnostics["candidates_scored"] = len(candidates)
    diagnostics["scoring_model"] = "analysis/signalthrottle_patterns/scoring_model.yaml"
    diagnostics["candidate_scores_top"] = dict(
        sorted(candidates.items(), key=lambda item: (item[1], item[0]), reverse=True)[:12]
    )
    bottlenecks = _pattern_bottlenecks(data, selected, pattern_match_score, execution_readiness_score, alignment)
    return {
        "matched_patterns": matched,
        "selected_pattern_id": selected.pattern_id if selected else None,
        "pattern_tier": selected.tier if selected else None,
        "pattern_family": selected.family if selected else None,
        # Backward-compatible score: execution/readiness aware.
        "pattern_score": execution_readiness_score,
        "pattern_match_score": pattern_match_score,
        "execution_readiness_score": execution_readiness_score,
        "golden_reference": selected.golden_source if selected else None,
        "pattern_scope": selected.scope if selected else None,
        "applies_to": selected.applies_to if selected else None,
        "golden_references": _string_list(selected_payload.get("golden_references")),
        "pair_specific_calibration": _string_list(selected_payload.get("pair_specific_calibration")),
        "pair_role": pair_role.get("default_role"),
        "entry_permission": selected.entry_permission if selected else _default_entry_permission(data),
        "management_action": selected.management_action if selected else None,
        "hold_policy": selected.hold_policy if selected else None,
        "chase_allowed": bool(selected.chase_allowed) if selected else False,
        "block_reason": block_reason,
        "pattern_evidence": evidence[:8],
        "pattern_search_space": _pattern_search_space(symbol, pair_patterns, matched),
        "pattern_db_candidates_scanned": len(GOLDEN_PATTERNS),
        "pattern_db_exact_matches": _string_list(diagnostics.get("exact_matches")),
        "pattern_db_fuzzy_matches": _string_list(diagnostics.get("fuzzy_matches")),
        "pattern_bottlenecks": bottlenecks,
        "pattern_match_diagnostics": diagnostics,
        **alignment,
    }


def _add_strategy_candidate(candidates: dict[str, int], evidence: list[str], strategy_pattern: str) -> None:
    pattern_id = _STRATEGY_TO_PATTERN.get(strategy_pattern)
    if pattern_id:
        _bump(candidates, pattern_id, 35)
        evidence.append(f"strategy_pattern={strategy_pattern}")


def _new_pattern_diagnostics(symbol: str, pair_patterns: set[str]) -> dict[str, Any]:
    return {
        "search_mode": "DATABASE_WIDE",
        "patterns_scanned": len(GOLDEN_PATTERNS),
        "symbol": symbol or None,
        "pair_role_patterns": sorted(pair_patterns),
        "exact_matches": [],
        "fuzzy_matches": [],
        "semantic_hits": {},
        "candidate_scores_top": {},
        "candidates_scored": 0,
    }


def _add_exact_pattern_candidate(
    candidates: dict[str, int],
    evidence: list[str],
    data: Mapping[str, Any],
    diagnostics: dict[str, Any],
) -> None:
    nested_context = _as_mapping(data.get("pattern_context"))
    exact_sources: list[tuple[str, Any, int]] = []
    for field in _EXACT_PATTERN_FIELDS:
        exact_sources.append((field, data.get(field), 96 if field in {"selected_pattern_id", "pattern_id"} else 84))
        if nested_context:
            exact_sources.append((f"pattern_context.{field}", nested_context.get(field), 96))
    for field in _PATTERN_LIST_FIELDS:
        exact_sources.append((field, data.get(field), 42))
        if nested_context:
            exact_sources.append((f"pattern_context.{field}", nested_context.get(field), 42))

    for source_name, value, score in exact_sources:
        for pattern_id in _pattern_ids_from_value(value):
            _bump(candidates, pattern_id, score)
            _append_unique(diagnostics["exact_matches"], pattern_id)
            evidence.append(f"exact_pattern_match={source_name}:{pattern_id}")

    searchable_text = " ".join(_iter_text_values(data))
    normalized_text = _normalize_token(searchable_text)
    for pattern_id in _PATTERN_ID_SET:
        if pattern_id in normalized_text:
            _bump(candidates, pattern_id, 72)
            _append_unique(diagnostics["exact_matches"], pattern_id)
            evidence.append(f"exact_pattern_text={pattern_id}")


def _add_database_semantic_candidates(
    candidates: dict[str, int],
    evidence: list[str],
    data: Mapping[str, Any],
    symbol: str,
    pair_patterns: set[str],
    diagnostics: dict[str, Any],
) -> None:
    if not _has_pattern_context(data):
        diagnostics.setdefault("bypassed_passes", []).append("semantic_db_scan_missing_market_context")
        return
    feature_tokens = _feature_tokens(data, symbol=symbol)
    if not feature_tokens:
        return
    for pattern in GOLDEN_PATTERNS:
        pattern_tokens = _pattern_text_index().get(pattern.pattern_id, frozenset())
        overlap = sorted(feature_tokens & pattern_tokens)
        if not overlap:
            continue
        score = min(24, len(overlap) * 4)
        if pattern.pattern_id in pair_patterns:
            score += 8
        if _normalize_token(pattern.family) in feature_tokens:
            score += 10
        if _normalize_token(pattern.entry_permission) in feature_tokens:
            score += 6
        if score < 12:
            continue
        _bump(candidates, pattern.pattern_id, score)
        _append_unique(diagnostics["fuzzy_matches"], pattern.pattern_id)
        diagnostics["semantic_hits"][pattern.pattern_id] = overlap[:8]
        if len(evidence) < 16:
            evidence.append(f"db_semantic_match={pattern.pattern_id}:{','.join(overlap[:4])}")


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
    _ = theme_aligned
    if symbol.endswith("JPY") or symbol.startswith("JPY"):
        _bump(candidates, "JPY_ALIGNMENT_REQUIRED", 20)
        evidence.append("jpy_cross_alignment_metadata")
        if jpy_alignment in {"CONFLICT", "MIXED", "BLOCKED"} or dual_theme_status == "CONFLICT":
            evidence.append("jpy_or_dual_theme_conflict_metadata_only")
    if "MIRROR_BASKET_CONFIRMATION" in pair_patterns or symbol in {"NZDCAD", "CADCHF", "CADJPY"}:
        _bump(candidates, "MIRROR_BASKET_CONFIRMATION", 10)
        evidence.append("mirror_basket_role_available")


def _add_universal_reference_candidate(
    candidates: dict[str, int],
    evidence: list[str],
    symbol: str,
    raw_direction: str | None,
    final_direction: str | None,
    data: Mapping[str, Any],
) -> None:
    direction = final_direction or raw_direction
    density = _num(data.get("density_per_minute") or data.get("effective_density_per_minute"))
    duration = _duration_seconds(data)
    m15_phase = _phase(data.get("m15_phase") or data.get("phase_m15"))
    h1_phase = _phase(data.get("h1_phase") or data.get("phase_h1") or data.get("h60_phase"))
    h4_phase = _phase(data.get("h4_phase") or data.get("phase_h4") or data.get("h240_phase"))
    d1_phase = _phase(data.get("d1_phase") or data.get("phase_d1") or data.get("h1440_phase"))
    phase_unpriced = _phase(data.get("phase_unpriced"))
    phase_priced = _phase(data.get("phase_priced"))
    price_position = _normalize_position(data.get("price_position"))
    jpy_alignment = _text(data.get("jpy_alignment") or data.get("jpy_alignment_status")).upper()
    close_pos_raw = data.get("m15_close_pos") if data.get("m15_close_pos") is not None else data.get("close_pos")
    close_pos = _num(close_pos_raw)
    block_delta_pips = _num(data.get("block_delta_pips"))
    bullish_reclaim_context = _is_bullish_or_reclaim(m15_phase) and _is_bullish_or_reclaim(h1_phase)
    bearish_context = _is_bearish_or_mixed_bearish(h1_phase) or _is_bearish_or_mixed_bearish(h4_phase)
    jpy_not_conflicting = not _is_jpy_cross(symbol) or jpy_alignment not in {"CONFLICT", "MIXED", "BLOCKED"}
    supportive_higher_tf = (
        _is_bullish_or_reclaim(h1_phase) or _is_bullish_or_reclaim(h4_phase) or _is_bullish_or_reclaim(d1_phase)
    )
    m15_pullback = m15_phase in {"PULLBACK", "BEARISH_PULLBACK", "MIXED", "BEARISH"} or (
        close_pos_raw is not None and close_pos <= 0.25
    )
    repeated_microburst = (
        phase_unpriced in {"REPEATED_MICROBOOST", "DENSE_MICROBOOST"}
        or _num(data.get("microburst_count") or data.get("repeated_microburst_count")) >= 2
        or _optional_bool(data.get("repeated_microburst")) is True
    )
    repeated_pressure = repeated_microburst or _optional_bool(data.get("repeated_pressure")) is True
    bearish_intraday = _is_bearish_or_mixed_bearish(m15_phase) or _is_bearish_or_mixed_bearish(h1_phase)
    failed_reclaim = (
        _optional_bool(data.get("price_fails_reclaim") or data.get("fails_reclaim")) is True
        or _optional_bool(data.get("m15_close_above_resistance")) is False
    )
    daily_conflict = _is_bullish_or_reclaim(d1_phase) and bearish_intraday
    first_60m_failed = (
        _optional_bool(data.get("first_60m_failed")) is True
        or _num(data.get("close_60m_pips") or data.get("close_60m")) < 0.0
    )
    microboost_like = (
        phase_unpriced in {"IGNITION_MICROBOOST", "DENSE_MICROBOOST", "MATURE_MICROBOOST", "REPEATED_MICROBOOST"}
        or density >= 10.0
    )
    late_upper = (
        price_position == "MAIN_RESISTANCE"
        or _num(data.get("range_position")) >= 0.85
        or block_delta_pips >= 8.0
        or _optional_bool(data.get("near_upper_resistance_without_reclaim")) is True
    )
    late_upper_extended = (
        _num(data.get("range_position")) >= 0.85
        or block_delta_pips >= 8.0
        or _optional_bool(data.get("near_upper_resistance_without_reclaim")) is True
    )
    upper_weak_close = late_upper and (
        (close_pos_raw is not None and close_pos <= 0.35) or _is_bearish_or_mixed_bearish(m15_phase)
    )

    if (
        direction == "BUY"
        and density >= 10.0
        and (
            150.0 <= duration <= 300.0
            or (300.0 < duration <= 600.0 and supportive_higher_tf and price_position != "MAIN_RESISTANCE")
        )
        and bullish_reclaim_context
        and jpy_not_conflicting
    ):
        _bump(candidates, "MICROBURST_FOLLOWTHROUGH_RECLAIM", 72)
        evidence.append("universal_microburst_followthrough_reclaim")

    if direction == "BUY" and duration >= 600.0 and supportive_higher_tf and jpy_not_conflicting and not late_upper:
        _bump(candidates, "OPEN_LANE_TIMING_VALID", 54)
        evidence.append("universal_open_lane_continuation")

    if direction == "BUY" and density >= 10.0 and bearish_context:
        _bump(candidates, "HIGH_DENSITY_CONTEXT_FILTER_NO_CHASE", 86)
        evidence.append("high_density_bearish_context_no_chase")

    if (
        direction == "BUY"
        and duration >= 300.0
        and density >= 8.0
        and (
            h4_phase in {"MIXED", "MIXED_BEARISH", "BEARISH", "DOWNTREND"}
            or price_position == "MAIN_RESISTANCE"
            or _optional_bool(data.get("near_upper_resistance_without_reclaim")) is True
        )
    ):
        _bump(candidates, "CLEAN_5M_TIMING_GATE_NOT_FINAL", 64)
        evidence.append("clean_5m_timing_gate_requires_reclaim")

    if (
        direction == "BUY"
        and (upper_weak_close or late_upper_extended)
        and (phase_priced not in {"RESISTANCE_PRESSURE_WARNING", "EXHAUSTION_AT_RESISTANCE"})
        and (h4_phase == "MIXED" or _is_bearish_or_mixed_bearish(d1_phase) or upper_weak_close)
    ):
        _bump(candidates, "HIGH_DENSITY_CONTEXT_FILTER_NO_CHASE", 88)
        evidence.append("late_upper_density_no_chase")

    if repeated_pressure and daily_conflict and duration >= 480.0:
        _bump(candidates, "REPEATED_PRESSURE_MANAGEMENT_ALERT", 78)
        evidence.append("repeated_pressure_m15_d1_conflict")

    if direction == "BUY" and repeated_microburst and bearish_intraday:
        _bump(candidates, "COUNTER_RECLAIM_WATCH_NOT_REVERSAL_FINAL", 76)
        evidence.append("repeated_microburst_counter_reclaim_watch")

    if density >= 10.5 and duration >= 300.0 and bearish_intraday and (failed_reclaim or direction == "BUY"):
        _bump(candidates, "BEARISH_OR_BULLISH_CONTINUATION_AFTER_HOT_BLOCK", 74)
        evidence.append("hot_block_phase_continuation")

    if (
        direction == "BUY"
        and density >= 8.0
        and 240.0 <= duration <= 600.0
        and m15_pullback
        and supportive_higher_tf
        and jpy_not_conflicting
        and not bearish_intraday
        and not failed_reclaim
    ):
        _bump(candidates, "MICROBURST_FOLLOWTHROUGH_RECLAIM", 78)
        evidence.append("high_density_pullback_then_expand")

    if direction == "BUY" and microboost_like and upper_weak_close:
        _bump(candidates, "HIGH_DENSITY_CONTEXT_FILTER_NO_CHASE", 82)
        evidence.append("upper_microboost_exhaustion_filter")

    if direction == "BUY" and microboost_like and duration <= 300.0 and first_60m_failed:
        _bump(candidates, "COUNTER_RECLAIM_WATCH_NOT_REVERSAL_FINAL", 76)
        evidence.append("mature_microboost_reclaim_required")

    delayed_higher_tf = _is_bullish_or_reclaim(h4_phase) or _is_bullish_or_reclaim(d1_phase)
    weak_lower_tf = (
        first_60m_failed or _is_bearish_or_mixed_bearish(m15_phase) or _is_bearish_or_mixed_bearish(h1_phase)
    )
    if direction == "BUY" and duration >= 600.0 and delayed_higher_tf and weak_lower_tf:
        _bump(candidates, "DELAYED_FOLLOWTHROUGH_WATCH", 72)
        evidence.append("delayed_followthrough_watch")


def _add_structural_universal_candidate(
    candidates: dict[str, int],
    evidence: list[str],
    symbol: str,
    raw_direction: str | None,
    final_direction: str | None,
    data: Mapping[str, Any],
) -> None:
    del symbol
    direction = final_direction or raw_direction
    density = _num(data.get("density_per_minute") or data.get("effective_density_per_minute"))
    events = _num(data.get("event_count") or data.get("events") or data.get("effective_ticks"))
    atr_ratio = _num(
        data.get("structure_atr_ratio")
        or data.get("h4_atr_ratio")
        or data.get("d1_atr_ratio")
        or data.get("m15_range_atr_ratio")
    )
    close_pos_raw = (
        data.get("structure_close_pos")
        if data.get("structure_close_pos") is not None
        else data.get("h4_close_pos")
        if data.get("h4_close_pos") is not None
        else data.get("d1_close_pos")
        if data.get("d1_close_pos") is not None
        else data.get("m15_close_pos")
        if data.get("m15_close_pos") is not None
        else data.get("close_pos")
    )
    close_pos = _num(close_pos_raw)
    near_extreme = close_pos_raw is not None and (close_pos <= 0.25 or close_pos >= 0.75)
    reclaim_confirmed = _optional_bool(data.get("reclaim_confirmed")) is True
    breakdown_confirmed = _optional_bool(data.get("breakdown_confirmed")) is True
    price_confirmed = (
        reclaim_confirmed
        or breakdown_confirmed
        or _optional_bool(data.get("price_confirmation")) is True
        or _optional_bool(data.get("m15_close_above_resistance")) is True
        or _optional_bool(data.get("m15_close_below_support")) is True
    )
    pressure_present = density > 0.0 or events > 0.0 or bool(_text(data.get("pressure_temperature")))

    if atr_ratio >= 3.0 and near_extreme and pressure_present and not price_confirmed:
        _bump(candidates, "LIQUIDATION_RECLAIM_REQUIRED", 92)
        evidence.append("extreme_liquidation_requires_reclaim")

    theme_context_only = _optional_bool(data.get("theme_context_only")) is True
    lower_tf_missing = _optional_bool(data.get("lower_timeframe_confirmation")) is False
    fragmented_run = (
        _optional_bool(data.get("fragmented_run")) is True or _optional_bool(data.get("weak_individual_run")) is True
    )
    missing_price_context = (
        _optional_bool(data.get("price_context_complete")) is False
        or _optional_bool(data.get("price_confirmation")) is False
    )
    if theme_context_only or ((lower_tf_missing or fragmented_run) and missing_price_context):
        _bump(candidates, "THEME_CONTEXT_ONLY_NOT_STANDALONE", 84)
        evidence.append("theme_context_only_not_standalone")

    mfe = abs(_num(data.get("forward_mfe_pips") or data.get("mfe_pips")))
    mae = abs(_num(data.get("forward_mae_pips") or data.get("mae_pips")))
    symmetry_risk = _optional_bool(data.get("mfe_mae_symmetry_risk")) is True or (
        mfe > 0.0 and mae > 0.0 and min(mfe, mae) / max(mfe, mae) >= 0.75
    )
    chase_rr_poor = (
        _optional_bool(data.get("chase_rr_poor")) is True
        or _optional_bool(data.get("near_recent_high_low_without_breakout_close")) is True
    )
    structure_strong = _optional_bool(data.get("structure_candle_strong_close")) is True or (
        close_pos_raw is not None and (close_pos >= 0.85 or close_pos <= 0.15)
    )
    mid_range_or_continuation = direction in {"BUY", "SELL"} or _optional_bool(data.get("continuation_context")) is True
    if structure_strong and near_extreme and mid_range_or_continuation and (symmetry_risk or chase_rr_poor):
        _bump(candidates, "MID_RANGE_CONTINUATION_PULLBACK_REQUIRED", 82)
        evidence.append("mid_range_continuation_pullback_required")


def _add_new_universal_pattern_candidates(
    candidates: dict[str, int],
    evidence: list[str],
    data: Mapping[str, Any],
    symbol: str,
    raw_direction: str | None,
    final_direction: str | None,
) -> None:
    """Detect universal pattern families migrated from historical audits."""
    direction = final_direction or raw_direction
    density = _num(data.get("density_per_minute") or data.get("effective_density_per_minute"))
    duration = _duration_seconds(data)
    events = _num(data.get("event_count") or data.get("events") or data.get("effective_ticks"))
    m15_phase = _phase(data.get("m15_phase") or data.get("phase_m15"))
    h1_phase = _phase(data.get("h1_phase") or data.get("phase_h1") or data.get("h60_phase"))
    h4_phase = _phase(data.get("h4_phase") or data.get("phase_h4") or data.get("h240_phase"))
    d1_phase = _phase(data.get("d1_phase") or data.get("phase_d1") or data.get("h1440_phase"))
    price_position = _normalize_position(data.get("price_position"))
    phase_priced_raw = _text(data.get("phase_priced")).upper()
    pressure_temp = _text(data.get("pressure_temperature")).upper()
    block_delta_pips = _num(data.get("block_delta_pips"))
    range_position = _num(data.get("range_position"))
    close_pos_raw = (
        data.get("m15_close_pos")
        if data.get("m15_close_pos") is not None
        else data.get("close_pos")
    )
    close_pos = _num(close_pos_raw)
    jpy_alignment = _text(data.get("jpy_alignment") or data.get("jpy_alignment_status")).upper()
    dual_theme_status = _text(data.get("dual_theme_status")).upper()
    latest_phase = _phase(
        data.get("latest_phase")
        or data.get("signal_throttle_phase")
        or data.get("theme_phase")
        or data.get("sequence_state")
    )
    session_phase = _phase(data.get("session_phase") or data.get("session_state") or data.get("session_window"))

    bullish_phase = _is_bullish_or_reclaim(m15_phase) or _is_bullish_or_reclaim(h1_phase)
    bearish_phase = _is_bearish_or_mixed_bearish(m15_phase) or _is_bearish_or_mixed_bearish(h1_phase)
    bullish_higher_tf = _is_bullish_or_reclaim(h4_phase)
    bullish_major_tf = _is_bullish_or_reclaim(h4_phase) and _is_bullish_or_reclaim(d1_phase)
    near_resistance = price_position == "MAIN_RESISTANCE" or range_position >= 0.85
    near_support = price_position == "MAIN_SUPPORT" or range_position <= 0.15
    near_extreme = near_resistance or near_support
    price_extended = block_delta_pips >= 8.0 or range_position >= 0.85
    price_followthrough = _optional_bool(data.get("price_followthrough")) is True
    net_delta_pips = abs(
        _num(
            data.get("net_delta_pips")
            or data.get("price_delta_during_window_pips")
            or data.get("window_delta_pips")
            or data.get("net_price_delta_pips")
            or data.get("net_price_delta")
        )
    )
    intrawindow_range_pips = abs(
        _num(data.get("intrawindow_range_pips") or data.get("window_range_pips") or data.get("during_range_pips"))
    )
    block_delta_raw = data.get("block_delta_pips")
    timing_valid = (
        pressure_temp in {"TIMING_VALID", "TIMING_GATE_VALID", "LOW_DENSITY_OPEN_LANE"}
        or phase_priced_raw in {"TIMING_VALID", "OPEN_LANE_TIMING", "OPEN_LANE_TIMING_VALID"}
        or _optional_bool(data.get("timing_valid")) is True
    )
    open_lane_context = (
        _optional_bool(data.get("open_lane")) is True
        or _optional_bool(data.get("price_unexpanded")) is True
        or phase_priced_raw in {"OPEN_LANE", "OPEN_LANE_TIMING", "OPEN_LANE_TIMING_VALID"}
        or (block_delta_raw is not None and abs(block_delta_pips) <= 3.0)
    )

    # 1. LOW_DENSITY_OPEN_LANE_TIMING_BLOCK
    # Low-density block (0.5-4 dpm), 5-10 min, continuation phase, not at resistance.
    # Complements OPEN_LANE_TIMING_VALID (which fires at 600+s).
    if (
        300.0 <= duration < 600.0
        and 0.5 <= density < 4.0
        and (events >= 15 or timing_valid)
        and not near_resistance
        and (open_lane_context or timing_valid)
        and (
            (direction == "BUY" and bullish_phase)
            or (direction == "SELL" and bearish_phase)
        )
    ):
        _bump(candidates, "LOW_DENSITY_OPEN_LANE_TIMING_BLOCK", 62)
        evidence.append("low_density_open_lane_continuation_block_5_10min")

    mfe = abs(_num(data.get("forward_mfe_pips") or data.get("mfe_pips") or data.get("max_favorable_excursion_pips")))
    mae = abs(_num(data.get("forward_mae_pips") or data.get("mae_pips") or data.get("max_adverse_excursion_pips")))
    zero_drawdown = (
        _optional_bool(data.get("zero_drawdown_followthrough")) is True
        or (mfe >= 10.0 and mae <= 1.0 and price_followthrough)
    )
    if zero_drawdown:
        _bump(candidates, "ZERO_DRAWDOWN_FOLLOWTHROUGH", 64)
        evidence.append("historical_zero_drawdown_followthrough_quality")

    # 2. ALLOWED_CANARY_QUORUM
    # 3+ allowed events for the same symbol/direction = confidence burst, not final direction.
    allowed_count = _num(data.get("allowed_count") or data.get("allowed_total"))
    allowed_quorum = _optional_bool(data.get("allowed_quorum")) is True
    if allowed_count >= 3 or allowed_quorum:
        _bump(candidates, "ALLOWED_CANARY_QUORUM", 44)
        evidence.append("allowed_canary_quorum_3_or_more_burst")

    # 3. FALSE_COUNTERFLOW_CANARY
    # Raw allowed direction opposite to strongly confirmed price phase = block false canary.
    m15_is_bullish = m15_phase in {"BULLISH", "PIVOT_RECLAIM", "RECLAIM", "BULLISH_RECLAIM"}
    h1_is_bullish = h1_phase in {"BULLISH", "UPTREND", "PIVOT_RECLAIM", "RECLAIM", "BULLISH_RECLAIM"}
    m15_is_bearish = _is_bearish_or_mixed_bearish(m15_phase)
    h1_is_bearish = _is_bearish_or_mixed_bearish(h1_phase)
    reclaim_confirmed = (
        _optional_bool(data.get("reclaim_confirmed")) is True
        or _optional_bool(data.get("m15_close_above_resistance")) is True
    )
    breakdown_confirmed = (
        _optional_bool(data.get("breakdown_confirmed")) is True
        or _optional_bool(data.get("m15_close_below_support")) is True
    )
    bullish_phase_confirmed = (m15_is_bullish and h1_is_bullish) or reclaim_confirmed
    bearish_phase_confirmed = (m15_is_bearish and h1_is_bearish) or breakdown_confirmed
    if raw_direction == "SELL" and bullish_phase_confirmed:
        _bump(candidates, "FALSE_COUNTERFLOW_CANARY", 78)
        evidence.append("false_sell_canary_price_confirms_bullish")
    elif raw_direction == "BUY" and bearish_phase_confirmed and not bullish_higher_tf:
        _bump(candidates, "FALSE_COUNTERFLOW_CANARY", 78)
        evidence.append("false_buy_canary_price_confirms_bearish")

    # 4. HIGH_DENSITY_ACCELERATION_CONTINUATION
    # High density (8+), price following through, structure not near exhaustion.
    exhaustion_phase = phase_priced_raw in {"RESISTANCE_PRESSURE_WARNING", "EXHAUSTION_AT_RESISTANCE", "LATE_DENSE_PRESSURE"}
    if (
        density >= 8.0
        and duration >= 300.0
        and not exhaustion_phase
        and not near_extreme
        and (
            (direction == "BUY" and bullish_phase)
            or (direction == "SELL" and bearish_phase)
            or price_followthrough
        )
    ):
        _bump(candidates, "HIGH_DENSITY_ACCELERATION_CONTINUATION", 44)
        evidence.append("high_density_acceleration_continuation_room_available")

    # 5. LATE_DENSE_PRESSURE_MANAGEMENT_ALERT
    # Short high-density burst (<=5min) near key level after move = protect/no-chase.
    if density >= 8.0 and duration <= 300.0 and (near_extreme or price_extended):
        _bump(candidates, "LATE_DENSE_PRESSURE_MANAGEMENT_ALERT", 58)
        evidence.append("late_dense_burst_near_key_level_protect_no_chase")

    # 6. CLEAN_SAME_PAIR_TAKEOVER
    # Same pair dominates run sequence without interruption and phase is aligned.
    same_pair_sequence = _optional_bool(data.get("same_pair_sequence")) is True
    pair_interruption = _optional_bool(data.get("pair_interruption")) is True
    if same_pair_sequence and not pair_interruption and duration >= 300.0 and events >= 30:
        _bump(candidates, "CLEAN_SAME_PAIR_TAKEOVER", 58)
        evidence.append("clean_same_pair_takeover_no_interruption_phase_aligned")

    # 7. BASKET_THEME_CONFIRMATION_CONTEXT
    # Multiple related pairs active with consistent basket = selection boost only, not execution gate.
    multiple_pairs_active = _optional_bool(data.get("multiple_pairs_active") or data.get("basket_active")) is True
    basket_consistent = _optional_bool(data.get("basket_direction_consistent")) is True
    dual_theme_status = _text(data.get("dual_theme_status")).upper()
    theme_aligned_local = _optional_bool(data.get("theme_aligned"))
    basket_boost = (multiple_pairs_active and basket_consistent) or (
        theme_aligned_local is True and dual_theme_status in {"ALIGNED", "FULL_ALIGNED"}
    )
    if basket_boost:
        _bump(candidates, "BASKET_THEME_CONFIRMATION_CONTEXT", 34)
        evidence.append("basket_theme_multiple_pairs_consistent_direction")

    basket_member = (
        _is_jpy_cross(symbol)
        or _optional_bool(data.get("jpy_basket_member")) is True
        or "JPY" in _text(data.get("basket_family") or data.get("basket_name")).upper()
    )
    same_pair_clean_block = (
        _optional_bool(data.get("same_pair_clean_block")) is True
        or _optional_bool(data.get("own_clean_block")) is True
        or _optional_bool(data.get("clean_same_pair_block")) is True
    )
    fragmented_rotation = (
        latest_phase in {"BROAD_ROTATION_FRAGMENTED", "FRAGMENTED_BASKET_ROTATION", "BROAD_ROTATION"}
        or ("FRAGMENTED" in latest_phase and "ROTATION" in latest_phase)
        or _optional_bool(data.get("fragmented_basket_rotation")) is True
        or _optional_bool(data.get("broad_rotation_fragmented")) is True
    )
    broad_rotation_active = (
        events >= 20.0
        or _num(data.get("basket_event_count") or data.get("theme_event_count")) >= 20.0
        or multiple_pairs_active
    )
    followthrough_status = _phase(
        data.get("theme_followthrough_status")
        or data.get("basket_followthrough_status")
        or data.get("followthrough_status")
    )
    basket_followthrough_confirmed = (
        followthrough_status in {"VALIDATED_THEME_FOLLOWTHROUGH", "VALIDATED_FOLLOWTHROUGH", "FOLLOWTHROUGH_VALIDATED"}
        or latest_phase == "VALIDATED_THEME_FOLLOWTHROUGH"
        or _optional_bool(data.get("theme_followthrough_confirmed")) is True
        or _optional_bool(data.get("basket_followthrough_confirmed")) is True
        or _optional_bool(data.get("ohlc_followthrough_confirmed")) is True
    )
    mfe_mae_validated = mfe >= 10.0 and (mae <= 1.0 or (mae > 0.0 and mfe / mae >= 2.0))
    own_pair_events = _num(
        data.get("own_pair_event_count")
        or data.get("own_event_count")
        or data.get("pair_event_count")
        or events
    )
    moderate_own_pair_events = (
        _optional_bool(data.get("own_pair_event_count_moderate")) is True
        or 20.0 <= own_pair_events <= 120.0
    )
    mae_controlled = _optional_bool(data.get("mae_controlled")) is True or (mae > 0.0 and mae <= 10.0)
    post_window_mfe_positive = _optional_bool(data.get("post_window_mfe_positive")) is True or mfe >= 10.0
    immediate_followthrough = _phase(
        data.get("immediate_followthrough")
        or data.get("during_window_followthrough")
        or data.get("window_followthrough")
    )
    immediate_followthrough_weak = (
        immediate_followthrough in {"WEAK", "NEGATIVE", "WEAK_OR_NEGATIVE", "DELAYED", "NOT_IMMEDIATE"}
        or _optional_bool(data.get("immediate_followthrough_weak")) is True
        or _optional_bool(data.get("during_window_negative")) is True
    )
    later_reclaim_or_recovery = (
        _optional_bool(data.get("later_reclaim_or_recovery")) is True
        or _optional_bool(data.get("later_recovery")) is True
        or _optional_bool(data.get("delayed_reclaim")) is True
        or _optional_bool(data.get("support_hold_or_reclaim")) is True
        or (post_window_mfe_positive and mae_controlled and immediate_followthrough_weak)
    )

    if fragmented_rotation and broad_rotation_active and not same_pair_clean_block and not basket_followthrough_confirmed:
        _bump(candidates, "FRAGMENTED_BASKET_ROTATION_NOT_ENTRY", 96)
        evidence.append("fragmented_basket_rotation_watchlist_only")

    if fragmented_rotation and broad_rotation_active and not same_pair_clean_block and later_reclaim_or_recovery:
        _bump(candidates, "FRAGMENTED_THEME_FOLLOWTHROUGH", 90)
        evidence.append("fragmented_theme_followthrough_delayed_reclaim_required")

    if (
        basket_member
        and moderate_own_pair_events
        and not same_pair_clean_block
        and post_window_mfe_positive
        and mae_controlled
    ):
        _bump(candidates, "JPY_BASKET_SECONDARY_CONFIRMATION", 76)
        evidence.append("jpy_basket_secondary_member_validated_by_mfe_mae")

    if basket_member and immediate_followthrough_weak and later_reclaim_or_recovery:
        _bump(candidates, "DELAYED_JPY_CROSS_CONTINUATION", 92)
        evidence.append("delayed_jpy_cross_continuation_requires_reclaim")

    if (
        basket_member
        and not fragmented_rotation
        and (
            basket_followthrough_confirmed
            or (
                jpy_alignment in {"ALIGNED", "VALIDATED", "WEAK_JPY", "JPY_WEAKNESS", "JPY_STRENGTH"}
                and price_followthrough
                and mfe_mae_validated
            )
        )
    ):
        _bump(candidates, "JPY_BASKET_THEME_FOLLOWTHROUGH", 84)
        evidence.append("jpy_basket_theme_followthrough_validated_not_auto_entry")

    lower_tf_pullback = (
        m15_phase in {"PULLBACK", "BEARISH_PULLBACK", "MIXED_PULLBACK", "SUPPORT_RETEST"}
        or h1_phase in {"PULLBACK", "BEARISH_PULLBACK", "MIXED_PULLBACK", "SUPPORT_RETEST"}
        or _optional_bool(data.get("h1_m15_pullback")) is True
        or _optional_bool(data.get("lower_tf_pullback")) is True
    )
    if bullish_major_tf and lower_tf_pullback and _optional_bool(data.get("h1_h4_breakdown")) is not True:
        _bump(candidates, "MTF_BULLISH_PULLBACK_DECISION", 88)
        evidence.append("mtf_bullish_higher_tf_lower_tf_pullback_decision")
    macro_bullish_intraday_pullback = (
        _optional_bool(data.get("macro_bullish_intraday_pullback")) is True
        or latest_phase == "MACRO_BULLISH_INTRADAY_PULLBACK_DECISION"
        or (
            symbol == "NZDJPY"
            and bullish_major_tf
            and lower_tf_pullback
            and _optional_bool(data.get("h1_h4_breakdown")) is not True
        )
    )
    if macro_bullish_intraday_pullback:
        _bump(candidates, "MACRO_BULLISH_INTRADAY_PULLBACK_DECISION", 94)
        evidence.append("macro_bullish_intraday_pullback_wait_reclaim_or_support_hold")

    late_session = (
        _optional_bool(data.get("late_session")) is True
        or "LATE" in session_phase
        or session_phase in {"NY_CLOSE", "SESSION_CLOSE", "END_SESSION", "ASIA_CLOSE"}
    )
    expansion_attempt = (
        _optional_bool(data.get("expansion_attempt")) is True
        or phase_priced_raw in {"EXPANSION_ATTEMPT", "LATE_EXPANSION", "FAILED_EXPANSION"}
    )
    expansion_failed = (
        _optional_bool(data.get("expansion_failed")) is True
        or phase_priced_raw in {"FAILED_EXPANSION", "EXPANSION_FAIL"}
        or (expansion_attempt and _optional_bool(data.get("price_followthrough")) is False)
    )
    weak_expansion_close = (
        _optional_bool(data.get("weak_expansion_close")) is True
        or (direction == "BUY" and close_pos_raw is not None and close_pos <= 0.35)
        or (direction == "SELL" and close_pos_raw is not None and close_pos >= 0.65)
    )
    if late_session and expansion_failed and (weak_expansion_close or near_extreme or price_extended):
        _bump(candidates, "LATE_SESSION_EXPANSION_FAIL", 92)
        evidence.append("late_session_failed_expansion_no_new_entry")
    prior_expansion = (
        _optional_bool(data.get("prior_expansion")) is True
        or _optional_bool(data.get("post_expansion")) is True
        or latest_phase == "POST_EXPANSION_NO_CHASE_FILTER"
    )
    intraday_repair_incomplete = (
        _optional_bool(data.get("intraday_repair_complete")) is False
        or _optional_bool(data.get("h1_or_m15_repair_not_complete")) is True
        or lower_tf_pullback
    )
    upper_range_pullback = near_resistance or range_position >= 0.65 or price_extended
    if prior_expansion and upper_range_pullback and intraday_repair_incomplete:
        _bump(candidates, "POST_EXPANSION_NO_CHASE_FILTER", 98)
        evidence.append("post_expansion_upper_range_pullback_no_chase")

    major_or_high_liquidity = (
        _is_major_pair(symbol)
        or _phase(data.get("pair_type")) in {"MAJOR", "MAJOR_PAIR", "HIGH_LIQUIDITY_PAIR"}
        or _optional_bool(data.get("major_pair")) is True
    )
    higher_tf_continuation = (
        bullish_major_tf
        or _is_bearish_or_mixed_bearish(h4_phase)
        or _is_bearish_or_mixed_bearish(d1_phase)
        or _phase(data.get("higher_tf_phase")) in {"BULLISH_CONTINUATION", "BEARISH_CONTINUATION", "CONTINUATION"}
    )
    low_density_major_block = (
        major_or_high_liquidity
        and duration >= 300.0
        and 0.1 <= density <= 2.0
        and (block_delta_raw is not None or net_delta_pips > 0.0)
        and abs(block_delta_pips if block_delta_raw is not None else net_delta_pips) <= 3.5
        and higher_tf_continuation
        and post_window_mfe_positive
        and mae_controlled
    )
    if low_density_major_block:
        _bump(candidates, "LOW_DENSITY_MAJOR_PAIR_CONTINUATION", 88)
        evidence.append("low_density_major_pair_continuation_validated_by_mfe_mae")

    broad_rotation_phase = (
        latest_phase in {"BROAD_ROTATION", "BROAD_ROTATION_OR_THEME_PRESSURE", "THEME_PRESSURE"}
        or _phase(data.get("market_phase")) in {"BROAD_ROTATION", "BROAD_ROTATION_OR_THEME_PRESSURE", "THEME_PRESSURE"}
        or _optional_bool(data.get("broad_rotation")) is True
    )
    high_event_count = events >= 200.0 or _num(data.get("total_event_count") or data.get("source_event_count")) >= 500.0
    many_pairs_active = multiple_pairs_active or _num(data.get("active_pair_count")) >= 4.0
    net_flat_range_large = (
        (net_delta_pips <= 5.0 and intrawindow_range_pips >= 30.0)
        or _optional_bool(data.get("net_delta_small_range_large")) is True
    )
    if high_event_count and many_pairs_active and broad_rotation_phase and net_flat_range_large:
        _bump(candidates, "BROAD_ROTATION_HIGH_EVENT_NOT_ENTRY", 99)
        evidence.append("broad_rotation_high_event_count_not_single_pair_entry")

    final_direction_text = _text(data.get("final_direction")).upper()
    delayed_gbp_context = (
        symbol.startswith("GBP")
        or symbol.endswith("GBP")
        or _phase(data.get("theme_family") or data.get("theme_name")) in {"GBP", "GBP_THEME", "GBP_STRENGTH"}
    )
    if delayed_gbp_context and final_direction_text == "WAIT" and immediate_followthrough_weak and later_reclaim_or_recovery:
        _bump(candidates, "DELAYED_GBP_CONTINUATION_AFTER_WAIT", 93)
        evidence.append("delayed_gbp_continuation_after_wait_requires_reclaim")

    prior_d1_expansion = (
        _optional_bool(data.get("prior_d1_expansion")) is True
        or _num(data.get("prior_d1_range_atr_ratio") or data.get("d1_range_atr_ratio")) >= 1.5
    )
    late_signal_block = _optional_bool(data.get("late_signal_block")) is True or _optional_bool(data.get("late_block")) is True
    expanded_major_location = _optional_bool(data.get("price_already_expanded")) is True or price_extended or near_resistance
    cooling_risk = (
        _optional_bool(data.get("next_day_rejection_or_cooling_risk")) is True
        or _optional_bool(data.get("next_day_rejection")) is True
        or _optional_bool(data.get("cooling_risk")) is True
    )
    if major_or_high_liquidity and prior_d1_expansion and (late_signal_block or expanded_major_location) and cooling_risk:
        _bump(candidates, "MAJOR_PAIR_POST_EXPANSION_NO_CHASE", 100)
        evidence.append("major_pair_post_expansion_no_chase_hold_or_trail")

    buy_mfe = abs(_num(data.get("mfe_buy_15m_pips") or data.get("mfe_buy_1h_pips") or data.get("mfe_buy_4h_pips") or data.get("buy_mfe_pips")))
    buy_mae = abs(_num(data.get("mae_buy_15m_pips") or data.get("mae_buy_1h_pips") or data.get("mae_buy_4h_pips") or data.get("buy_mae_pips")))
    sell_mfe = abs(_num(data.get("mfe_sell_15m_pips") or data.get("mfe_sell_1h_pips") or data.get("mfe_sell_4h_pips") or data.get("sell_mfe_pips")))
    sell_mae = abs(_num(data.get("mae_sell_15m_pips") or data.get("mae_sell_1h_pips") or data.get("mae_sell_4h_pips") or data.get("sell_mae_pips")))
    buy_followthrough_failed = (
        _optional_bool(data.get("buy_followthrough_failed")) is True
        or _phase(data.get("buy_followthrough_status")) in {"FAILED", "WEAK", "FALSE_CONTINUATION"}
        or (buy_mfe > 0.0 and buy_mae >= buy_mfe)
    )
    sell_fade_cleaner = (
        _optional_bool(data.get("sell_fade_cleaner")) is True
        or _optional_bool(data.get("fade_validated")) is True
        or (sell_mfe > 0.0 and (sell_mae == 0.0 or sell_mfe >= sell_mae))
    )
    leader_pair = _text(data.get("leader_pair") or data.get("theme_leader_pair")).upper()
    supporting_cross = (
        _optional_bool(data.get("supporting_cross")) is True
        or _optional_bool(data.get("supporting_pair")) is True
        or _num(data.get("supporting_event_count")) > 0.0
        or (bool(leader_pair) and leader_pair != symbol)
    )
    eur_cross_pressure = (
        symbol.startswith("EUR")
        and (
            _optional_bool(data.get("eur_cross_pressure")) is True
            or leader_pair.startswith("EUR")
            or _phase(data.get("theme_family") or data.get("theme_name")) in {"EUR", "EUR_CROSS", "EUR_CROSS_ROTATION"}
        )
    )
    upper_fade_context = (
        _optional_bool(data.get("upper_fade_candidate")) is True
        or _optional_bool(data.get("upper_rejection")) is True
        or near_resistance
        or range_position >= 0.75
    )
    own_phase_confirmed = (
        _optional_bool(data.get("own_price_phase_confirmed")) is True
        or _optional_bool(data.get("own_trigger_confirmed")) is True
        or reclaim_confirmed
        or breakdown_confirmed
    )

    if (
        symbol == "AUDNZD"
        and duration >= 300.0
        and 0.5 <= density <= 4.0
        and (buy_followthrough_failed or sell_fade_cleaner)
        and not own_phase_confirmed
    ):
        _bump(candidates, "LOW_DENSITY_BLOCK_FALSE_CONTINUATION", 110)
        evidence.append("audnzd_low_density_block_false_continuation_validated")

    if symbol == "AUDNZD" and (supporting_cross or _optional_bool(data.get("aud_nzd_relative_strength_decision")) is True):
        _bump(candidates, "AUDNZD_RELATIVE_STRENGTH_DECISION_PAIR", 92)
        evidence.append("audnzd_relative_strength_decision_requires_own_phase")

    if supporting_cross and not same_pair_clean_block and not own_phase_confirmed:
        _bump(candidates, "SUPPORTING_CROSS_NOT_PRIMARY_LEADER", 94)
        evidence.append("supporting_cross_not_primary_leader_requires_own_trigger")

    bullish_repair_upper = (
        symbol == "AUDNZD"
        and (
            _optional_bool(data.get("bullish_repair_upper_decision")) is True
            or _optional_bool(data.get("bullish_repair")) is True
            or latest_phase == "BULLISH_REPAIR_UPPER_DECISION_NO_CHASE"
        )
        and upper_fade_context
    )
    if bullish_repair_upper:
        _bump(candidates, "BULLISH_REPAIR_UPPER_DECISION_NO_CHASE", 112)
        evidence.append("audnzd_bullish_repair_upper_decision_no_chase")

    chf_weakness_context = (
        symbol.endswith("CHF")
        and (
            _optional_bool(data.get("chf_weakness_context")) is True
            or _optional_bool(data.get("chf_weakness")) is True
            or _phase(data.get("basket_context") or data.get("theme_family") or data.get("theme_name"))
            in {"CHF_WEAKNESS", "WEAK_CHF", "CHF_SELL_THEME"}
            or leader_pair in {"USDCHF", "CADCHF", "GBPCHF", "NZDCHF"}
        )
    )
    clean_chf_confirmation = (
        symbol == "AUDCHF"
        and (direction == "BUY" or _optional_bool(data.get("raw_direction_buy")) is True)
        and chf_weakness_context
        and (
            _optional_bool(data.get("clean_followthrough")) is True
            or _optional_bool(data.get("small_mae_positive_mfe")) is True
            or (buy_mfe > 0.0 and buy_mae <= 2.0)
        )
    )
    if clean_chf_confirmation:
        _bump(candidates, "CHF_WEAKNESS_SUPPORTING_PAIR_CLEAN_FOLLOWTHROUGH", 110)
        evidence.append("audchf_clean_chf_weakness_confirmation_followthrough")

    audchf_bullish_alignment = (
        symbol == "AUDCHF"
        and (
            _optional_bool(data.get("audchf_bullish_alignment_upper_no_chase")) is True
            or _optional_bool(data.get("bullish_alignment_upper_no_chase")) is True
            or (
                _optional_bool(data.get("d1_above_ema50")) is True
                and _optional_bool(data.get("h4_above_ema50")) is True
                and _optional_bool(data.get("h1_above_ema50")) is True
            )
        )
    )
    audchf_near_high = (
        _optional_bool(data.get("price_near_recent_high")) is True
        or _optional_bool(data.get("near_recent_high")) is True
        or near_resistance
        or range_position >= 0.75
    )
    audchf_micro_cooling = (
        _optional_bool(data.get("m1_micro_cooling")) is True
        or _optional_bool(data.get("micro_cooling")) is True
        or _phase(data.get("m1_phase")) in {"MIXED", "COOLING", "PULLBACK"}
    )
    if audchf_bullish_alignment and audchf_near_high and audchf_micro_cooling:
        _bump(candidates, "AUDCHF_BULLISH_ALIGNMENT_UPPER_NO_CHASE", 118)
        evidence.append("audchf_bullish_alignment_near_high_wait_retest")

    if symbol == "EURNZD" and eur_cross_pressure and supporting_cross and not same_pair_clean_block:
        _bump(candidates, "SUPPORTING_EUR_CROSS_NOT_LEADER", 104)
        evidence.append("eurnzd_supporting_eur_cross_not_leader")

    if symbol == "EURNZD" and upper_fade_context and buy_followthrough_failed and sell_fade_cleaner:
        _bump(candidates, "EURNZD_UPPER_FADE_AFTER_EUR_CROSS_PRESSURE", 116)
        evidence.append("eurnzd_upper_fade_after_eur_cross_pressure")

    if (
        symbol == "EURNZD"
        and leader_pair
        and leader_pair != symbol
        and supporting_cross
        and not own_phase_confirmed
    ):
        _bump(candidates, "CROSS_THEME_LEADER_DIVERGENCE", 100)
        evidence.append("cross_theme_leader_divergence_do_not_copy_leader_direction")

    macro_bearish_context = (
        _optional_bool(data.get("macro_bearish_context")) is True
        or (
            _optional_bool(data.get("d1_below_ema50")) is True
            and _optional_bool(data.get("d1_below_ema200")) is True
            and _optional_bool(data.get("h4_below_ema50")) is True
        )
        or (_is_bearish_or_mixed_bearish(d1_phase) and _is_bearish_or_mixed_bearish(h4_phase))
    )
    intraday_repair = (
        _optional_bool(data.get("intraday_repair")) is True
        or _optional_bool(data.get("h1_m15_intraday_repair")) is True
        or latest_phase == "MACRO_BEARISH_INTRADAY_REPAIR_DECISION"
    )
    if symbol == "EURNZD" and macro_bearish_context and intraday_repair and upper_fade_context:
        _bump(candidates, "MACRO_BEARISH_INTRADAY_REPAIR_DECISION", 114)
        evidence.append("eurnzd_macro_bearish_intraday_repair_no_buy_chase")

    # 8. TIMING_VALID_NOT_FINAL
    # Valid timing block (5+ min) but price phase not classified = watch only, not final signal.
    price_phase_missing = not phase_priced_raw or phase_priced_raw in {
        "",
        "UNKNOWN",
        "UNRESOLVED",
        "PRICE_PHASE_UNRESOLVED",
        "TIMING_VALID",
    }
    timing_valid_flag = pressure_temp == "TIMING_VALID" or phase_priced_raw == "TIMING_VALID"
    price_confirmed = (direction == "BUY" and bullish_phase and not near_resistance) or (
        direction == "SELL" and bearish_phase and not near_support
    )
    if duration >= 300.0 and (price_phase_missing or timing_valid_flag) and not price_confirmed:
        _bump(candidates, "TIMING_VALID_NOT_FINAL", 46)
        evidence.append("timing_valid_but_price_phase_unconfirmed_watch_only")

    # 9. SIGNAL_LIFECYCLE_CONFLICT_WATCH
    # Active signal + new opposing candidate = lifecycle conflict must be resolved first.
    active_signal_conflict = (
        _optional_bool(data.get("active_signal_conflict")) is True
        or _optional_bool(data.get("lifecycle_conflict")) is True
    )
    if active_signal_conflict:
        _bump(candidates, "SIGNAL_LIFECYCLE_CONFLICT_WATCH", 80)
        evidence.append("lifecycle_conflict_active_signal_vs_new_candidate")


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
    buy_mfe_1h = abs(_num(data.get("buy_mfe_1h") or data.get("mfe_buy_1h_pips") or data.get("mfe_1h_pips")))
    buy_mfe_4h = abs(_num(data.get("buy_mfe_4h") or data.get("mfe_buy_4h_pips") or data.get("mfe_4h_pips")))
    buy_mae_4h = abs(_num(data.get("buy_mae_4h") or data.get("mae_buy_4h_pips") or data.get("mae_4h_pips")))
    metal_whipsaw = (
        _optional_bool(data.get("metal_pressure_block_not_auto_direction")) is True
        or _optional_bool(data.get("broad_bias_intraday_block_whipsaw")) is True
        or _optional_bool(data.get("metal_block_whipsaw")) is True
        or (buy_mfe_1h > 0.0 and buy_mae_4h >= buy_mfe_1h)
    )
    if symbol == "XAGUSD" and (
        metal_whipsaw
        or _optional_bool(data.get("broad_metal_followthrough")) is True
        or buy_mfe_4h >= max(1.0, buy_mfe_1h)
    ):
        _bump(candidates, "METAL_PRESSURE_BROAD_FOLLOWTHROUGH_BUT_BLOCK_WHIPSAW", 108)
        evidence.append("xagusd_broad_followthrough_intraday_block_whipsaw")
    xag_repair_below_ema = (
        symbol == "XAGUSD"
        and (
            _optional_bool(data.get("xagusd_no_chase_below_ema_reclaim")) is True
            or _optional_bool(data.get("m15_recovery_below_key_ema")) is True
            or _optional_bool(data.get("reclaim_required")) is True
            or _phase(data.get("latest_phase")) == "XAGUSD_NO_CHASE_BELOW_EMA_RECLAIM"
            or (
                _optional_bool(data.get("d1_above_ema200")) is True
                and _optional_bool(data.get("d1_below_ema50")) is True
                and (
                    _optional_bool(data.get("h4_below_ema50")) is True
                    or _optional_bool(data.get("h1_below_ema50")) is True
                )
            )
        )
    )
    if xag_repair_below_ema:
        _bump(candidates, "XAGUSD_NO_CHASE_BELOW_EMA_RECLAIM", 116)
        evidence.append("xagusd_repair_below_key_ema_no_chase")
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


def _pattern_match_score(
    data: Mapping[str, Any],
    selected: GoldenPattern | None,
    candidate_score: int,
) -> int:
    if selected is None:
        return 0
    score = candidate_score
    score += _tier_weight(selected.tier)
    score += min(20, int(_num(data.get("density_per_minute") or data.get("effective_density_per_minute")) * 2))
    score += min(15, int((_num(data.get("duration_seconds")) or _num(data.get("duration_minutes")) * 60.0) / 60.0))
    return max(0, min(100, int(score)))


def _execution_readiness_score(
    data: Mapping[str, Any],
    selected: GoldenPattern | None,
    pattern_match_score: int,
    evidence: list[str],
) -> int:
    if selected is None:
        return 0
    score = pattern_match_score
    if _optional_bool(data.get("spread_normal")) is False:
        score -= 20
        evidence.append("spread_penalty")
    if selected.pattern_id == "SPARSE_ARCHIVE":
        score += _scoring_penalty("sparse_archive_penalty", -50)
        score = min(score, 39)
    if selected.family in {"THEME_CONFLICT_FILTER", "DAILY_CONFLICT_FILTER", "TRAP_FILTER"}:
        score += _scoring_penalty("theme_conflict_penalty", -35)
    if selected.entry_permission in {"NO_TRADE", "NO_SELL"}:
        score = min(score, 39)
    if selected.entry_permission in {
        "NO_NEW_ENTRY",
        "NO_MARKET_CHASE",
        "NO_NEW_BUY",
        "NO_BUY_CHASE",
        "BLOCK_NEW_ENTRY",
    }:
        score += _scoring_penalty("late_chase_penalty", -25)
        score = min(score, 69)
    if selected.entry_permission in {
        "ENTRY_WATCH_ONLY_WAIT_RECLAIM",
        "ENTRY_WATCH_WAIT_M15_CLOSE",
        "WAIT_BREAK_OR_RECLAIM",
        "WAIT_RECLAIM_OR_PULLBACK_HOLD",
        "RECLAIM_WATCH_OR_PARTIAL_EXIT",
        "WATCH_ONLY_UNTIL_RECLAIM",
        "PAIR_SELECTION_BOOST_ONLY",
        "BOOST_SCORE_ONLY",
        "WATCH_BOOST_ONLY",
        "WATCHLIST_ONLY",
        "VALIDATED_THEME_FOLLOWTHROUGH",
        "TRACK_ONLY",
        "PULLBACK_OR_RECLAIM_ONLY",
        "RECLAIM_OR_REJECTION_CONFIRMATION",
        "BUY_RETEST_OR_CONFIRMATION",
        "BUY_RETEST_OR_BREAKOUT_RETEST_ONLY",
        "DELAYED_BUY_WATCH",
        "DELAYED_WATCH",
    }:
        score -= 20
        score = min(score, 69)
    if selected.entry_permission in {
        "BUY_RECLAIM_WATCH_OR_EXIT_SHORT_PARTIAL",
        "PHASE_CONTINUATION_RETEST_OR_PROTECT",
        "BUY_RECLAIM_OR_SUPPORT_HOLD",
    }:
        score -= 15
        score = min(score, 79)
    if selected.entry_permission in {"NO_CHASE_PROTECT_OR_WAIT_RETEST", "NO_CHASE_NEAR_RESISTANCE"}:
        score += _scoring_penalty("late_chase_penalty", -25)
        score = min(score, 69)
    if _tradeplan_incomplete(data):
        score += _scoring_penalty("incomplete_tradeplan_penalty", -40)
        evidence.append("incomplete_tradeplan_penalty")
        score = min(score, 69)
    return max(0, min(100, int(score)))


def _alignment_metadata(
    data: Mapping[str, Any],
    *,
    symbol: str,
    theme_aligned: bool | None,
    jpy_alignment: str,
    dual_theme_status: str,
) -> dict[str, str | None]:
    theme_text = _text(data.get("theme_alignment") or data.get("counter_entry_theme_alignment")).upper()
    status_text = _text(data.get("theme_alignment_status")).upper()
    if not theme_text and status_text and status_text != "ALIGNED":
        theme_text = status_text
    if not theme_text:
        theme_text = "MISMATCH" if theme_aligned is False else "NOT_AVAILABLE"

    jpy_pair = symbol.endswith("JPY") or symbol.startswith("JPY")
    jpy_status = jpy_alignment or ("UNKNOWN" if jpy_pair else None)
    missing: list[str] = []
    if theme_text in {"UNKNOWN", "NOT_AVAILABLE"}:
        missing.append("basket_snapshot_missing_or_not_computed")
    if jpy_pair and jpy_status == "UNKNOWN":
        missing.append("jpy_alignment")
    if jpy_pair and not dual_theme_status:
        missing.append("dual_theme_status")
    return {
        "theme_alignment_status": theme_text,
        "jpy_alignment_status": jpy_status,
        "dual_theme_status": dual_theme_status or None,
        "alignment_missing_reason": ",".join(missing) if missing else None,
    }


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
    if _optional_bool(data.get("spread_normal")) is False:
        return "SPREAD_NOT_NORMAL"
    return None


def _bump(candidates: dict[str, int], pattern_id: str, amount: int) -> None:
    if get_pattern(pattern_id) is None:
        return
    candidates[pattern_id] = candidates.get(pattern_id, 0) + amount


def _pattern_search_space(symbol: str, pair_patterns: set[str], matched: list[str]) -> list[str] | None:
    search_space = set(pair_patterns)
    search_space.update(matched[:12])
    if symbol.startswith(("XAU", "XAG")):
        search_space.update(pattern.pattern_id for pattern in GOLDEN_PATTERNS if pattern.family.startswith("METAL"))
    if symbol.endswith("JPY") or symbol.startswith("JPY"):
        search_space.add("JPY_ALIGNMENT_REQUIRED")
    return sorted(search_space) or None


def _has_pattern_context(data: Mapping[str, Any]) -> bool:
    for field in _EXACT_PATTERN_FIELDS + _PATTERN_LIST_FIELDS:
        if _pattern_ids_from_value(data.get(field)):
            return True
    strategy_pattern = _normalize_token(data.get("strategy_pattern"))
    if strategy_pattern and strategy_pattern not in {"PRICE_PHASE_UNRESOLVED", "UNRESOLVED"}:
        return True
    for field in (
        "phase_priced",
        "phase_unpriced",
        "pressure_temperature",
        "price_position",
        "signal_archetype",
        "target_mode",
        "tp_status",
        "status",
    ):
        if _text(data.get(field)):
            return True
    return any(
        _num(data.get(field)) > 0.0
        for field in (
            "density_per_minute",
            "effective_density_per_minute",
            "duration_seconds",
            "duration_minutes",
            "event_count",
            "events",
            "effective_ticks",
        )
    )


def _pattern_bottlenecks(
    data: Mapping[str, Any],
    selected: GoldenPattern | None,
    pattern_match_score: int,
    execution_readiness_score: int,
    alignment: Mapping[str, Any],
) -> list[str] | None:
    bottlenecks: list[str] = []
    if selected is None:
        bottlenecks.append("NO_PATTERN_CANDIDATE_FROM_DATABASE")
    if pattern_match_score >= 75 and execution_readiness_score <= 69:
        bottlenecks.append("PATTERN_MATCHED_BUT_EXECUTION_READINESS_BLOCKED")
    if selected and selected.entry_permission in {
        "BOOST_SCORE_ONLY",
        "PAIR_SELECTION_BOOST_ONLY",
        "WATCH_BOOST_ONLY",
        "WATCHLIST_ONLY",
        "VALIDATED_THEME_FOLLOWTHROUGH",
        "TRACK_ONLY",
    }:
        bottlenecks.append("PATTERN_CONTEXT_ONLY_NOT_FINAL_SIGNAL")
    if selected and selected.pattern_id == "JPY_BASKET_THEME_FOLLOWTHROUGH":
        bottlenecks.append("THEME_FOLLOWTHROUGH_REQUIRES_OWN_TRIGGER")
    if selected and selected.pattern_id == "JPY_BASKET_SECONDARY_CONFIRMATION":
        bottlenecks.append("JPY_SECONDARY_REQUIRES_OWN_TRIGGER")
    if selected and selected.pattern_id == "FRAGMENTED_BASKET_ROTATION_NOT_ENTRY":
        bottlenecks.append("FRAGMENTED_ROTATION_WATCHLIST_ONLY")
    if selected and selected.pattern_id == "FRAGMENTED_THEME_FOLLOWTHROUGH":
        bottlenecks.append("FRAGMENTED_THEME_REQUIRES_RECLAIM")
    if selected and selected.pattern_id == "DELAYED_JPY_CROSS_CONTINUATION":
        bottlenecks.append("DELAYED_CONTINUATION_REQUIRES_RECLAIM")
    if selected and selected.pattern_id == "MTF_BULLISH_PULLBACK_DECISION":
        bottlenecks.append("PULLBACK_DECISION_NEEDS_RECLAIM_OR_BREAKDOWN")
    if selected and selected.pattern_id == "MACRO_BULLISH_INTRADAY_PULLBACK_DECISION":
        bottlenecks.append("MACRO_PULLBACK_NEEDS_RECLAIM_OR_SUPPORT_HOLD")
    if selected and selected.pattern_id == "ZERO_DRAWDOWN_FOLLOWTHROUGH":
        bottlenecks.append("HISTORICAL_OUTCOME_VALIDATION_TRACK_ONLY")
    if selected and selected.pattern_id == "LATE_SESSION_EXPANSION_FAIL":
        bottlenecks.append("REVALIDATE_NEXT_SESSION_BEFORE_NEW_ENTRY")
    if selected and selected.pattern_id == "POST_EXPANSION_NO_CHASE_FILTER":
        bottlenecks.append("POST_EXPANSION_NO_CHASE")
    if selected and selected.pattern_id == "LOW_DENSITY_MAJOR_PAIR_CONTINUATION":
        bottlenecks.append("MAJOR_PAIR_CONTINUATION_NEEDS_STRUCTURE_AND_RR")
    if selected and selected.pattern_id == "BROAD_ROTATION_HIGH_EVENT_NOT_ENTRY":
        bottlenecks.append("BROAD_ROTATION_NOT_SINGLE_PAIR_ENTRY")
    if selected and selected.pattern_id == "DELAYED_GBP_CONTINUATION_AFTER_WAIT":
        bottlenecks.append("DELAYED_GBP_CONTINUATION_REQUIRES_RECLAIM")
    if selected and selected.pattern_id == "MAJOR_PAIR_POST_EXPANSION_NO_CHASE":
        bottlenecks.append("MAJOR_PAIR_POST_EXPANSION_NO_CHASE")
    if selected and selected.pattern_id == "LOW_DENSITY_BLOCK_FALSE_CONTINUATION":
        bottlenecks.append("LOW_DENSITY_BLOCK_FALSE_CONTINUATION_RISK")
    if selected and selected.pattern_id == "AUDNZD_RELATIVE_STRENGTH_DECISION_PAIR":
        bottlenecks.append("RELATIVE_STRENGTH_DECISION_NOT_AUTO_ENTRY")
    if selected and selected.pattern_id == "SUPPORTING_CROSS_NOT_PRIMARY_LEADER":
        bottlenecks.append("SUPPORTING_CROSS_NOT_PRIMARY_LEADER")
    if selected and selected.pattern_id == "BULLISH_REPAIR_UPPER_DECISION_NO_CHASE":
        bottlenecks.append("BULLISH_REPAIR_UPPER_DECISION_NO_CHASE")
    if selected and selected.pattern_id == "SUPPORTING_EUR_CROSS_NOT_LEADER":
        bottlenecks.append("SUPPORTING_EUR_CROSS_NOT_LEADER")
    if selected and selected.pattern_id == "EURNZD_UPPER_FADE_AFTER_EUR_CROSS_PRESSURE":
        bottlenecks.append("EUR_CROSS_UPPER_FADE_RISK")
    if selected and selected.pattern_id == "CROSS_THEME_LEADER_DIVERGENCE":
        bottlenecks.append("CROSS_THEME_LEADER_DIVERGENCE")
    if selected and selected.pattern_id == "MACRO_BEARISH_INTRADAY_REPAIR_DECISION":
        bottlenecks.append("MACRO_BEARISH_INTRADAY_REPAIR_DECISION")
    if selected and selected.pattern_id == "METAL_PRESSURE_BROAD_FOLLOWTHROUGH_BUT_BLOCK_WHIPSAW":
        bottlenecks.append("METAL_RECLAIM_OR_REJECTION_CONFIRMATION_REQUIRED")
    if selected and selected.pattern_id == "XAGUSD_NO_CHASE_BELOW_EMA_RECLAIM":
        bottlenecks.append("XAGUSD_REPAIR_BELOW_EMA_NO_CHASE")
    if selected and selected.pattern_id == "CHF_WEAKNESS_SUPPORTING_PAIR_CLEAN_FOLLOWTHROUGH":
        bottlenecks.append("SUPPORTING_CONFIRMATION_REQUIRES_OWN_TRIGGER")
    if selected and selected.pattern_id == "AUDCHF_BULLISH_ALIGNMENT_UPPER_NO_CHASE":
        bottlenecks.append("AUDCHF_UPPER_ALIGNMENT_NO_CHASE")
    if _optional_bool(data.get("support_ladder_ready")) is False:
        bottlenecks.append("SUPPORT_LADDER_MISSING")
    if _optional_bool(data.get("resistance_ladder_ready")) is False:
        bottlenecks.append("RESISTANCE_LADDER_MISSING")
    if _optional_bool(data.get("structure_targets_available")) is False:
        bottlenecks.append("STRUCTURE_TARGETS_MISSING")
    if _optional_bool(data.get("targets_execution_usable")) is False:
        bottlenecks.append("TARGETS_NOT_EXECUTION_USABLE")
    if str(data.get("target_mode") or "").upper() == "PROVISIONAL_RR_FALLBACK":
        bottlenecks.append("PROVISIONAL_RR_FALLBACK_NOT_FINAL_TARGET")
    if _optional_bool(data.get("valid_for_execution")) is False:
        bottlenecks.append("VALID_FOR_EXECUTION_FALSE")
    if _optional_bool(data.get("requires_m15_close")) is True:
        bottlenecks.append(_m15_confirmation_bottleneck(data, selected))
    if str(data.get("final_direction") or "").upper() == "WAIT":
        bottlenecks.append("FINAL_DIRECTION_WAIT")
    return bottlenecks or None


def _m15_confirmation_bottleneck(data: Mapping[str, Any], selected: GoldenPattern | None) -> str:
    status = str(data.get("status") or data.get("signalwatch_status") or "").upper()
    family = str(data.get("signal_family") or "").upper()
    phase_priced = str(data.get("phase_priced") or "").upper()
    action = str(data.get("action") or "").upper()
    pattern_family = str(selected.family if selected else "").upper()
    if "REVERSAL" in status or "REVERSAL" in family or "REVERSAL" in pattern_family:
        return "REVERSAL_WATCH_NEEDS_REJECTION"
    if (
        "ABSORPTION" in status
        or "COUNTER" in family
        or phase_priced in {"RESISTANCE_PRESSURE_WARNING", "SUPPORT_PRESSURE_WARNING"}
        or "REJECTION" in action
        or "BREAKDOWN" in action
    ):
        return "COUNTER_ENTRY_NEEDS_CONFIRMATION"
    if (
        _optional_bool(data.get("active_signal_conflict")) is True
        or _optional_bool(data.get("lifecycle_conflict")) is True
    ):
        return "LIFECYCLE_CONFLICT_NEEDS_DECISION"
    return "PRICE_PHASE_AMBIGUOUS"


def _pattern_ids_from_value(value: Any) -> list[str]:
    ids: list[str] = []
    for text in _iter_text_values(value):
        normalized = _normalize_token(text)
        if normalized in _PATTERN_ID_SET:
            _append_unique(ids, normalized)
            continue
        for token in re.split(r"[^A-Z0-9_]+", normalized):
            if token in _PATTERN_ID_SET:
                _append_unique(ids, token)
    return ids


def _pattern_text_index() -> dict[str, frozenset[str]]:
    global _PATTERN_TEXT_INDEX
    if not _PATTERN_TEXT_INDEX:
        _PATTERN_TEXT_INDEX = {pattern.pattern_id: frozenset(_pattern_tokens(pattern)) for pattern in GOLDEN_PATTERNS}
    return _PATTERN_TEXT_INDEX


def _pattern_tokens(pattern: GoldenPattern) -> set[str]:
    token_text = " ".join(
        str(value or "")
        for value in (
            pattern.pattern_id,
            pattern.family,
            pattern.function,
            pattern.entry_permission,
            pattern.management_action,
            pattern.hold_policy,
            pattern.block_reason,
            pattern.golden_source,
        )
    )
    tokens = _tokens_from_text(token_text)
    tokens.add(_normalize_token(pattern.pattern_id))
    tokens.add(_normalize_token(pattern.family))
    tokens.add(_normalize_token(pattern.entry_permission))
    return tokens


def _feature_tokens(data: Mapping[str, Any], *, symbol: str) -> set[str]:
    text = " ".join(_iter_text_values(data))
    tokens = _tokens_from_text(text)
    normalized_symbol = _normalize_token(symbol)
    if normalized_symbol:
        tokens.add(normalized_symbol)
    price_position = _normalize_position(data.get("price_position"))
    if price_position:
        tokens.add(_normalize_token(price_position))
    for field in (
        "phase_unpriced",
        "phase_priced",
        "m15_phase",
        "h1_phase",
        "h4_phase",
        "d1_phase",
        "pressure_temperature",
        "target_mode",
        "tp_status",
        "entry_permission",
        "management_action",
        "block_reason",
    ):
        value = _text(data.get(field))
        if value:
            tokens.add(_normalize_token(value))
            tokens.update(_tokens_from_text(value))
    density = _num(data.get("density_per_minute") or data.get("effective_density_per_minute"))
    duration = _duration_seconds(data)
    if density >= 10.0:
        tokens.update({"HIGH", "DENSITY", "HIGH_DENSITY", "MICROBURST"})
    elif density >= 8.0:
        tokens.update({"DENSE", "DENSITY"})
    if duration >= 600.0:
        tokens.update({"LONG", "SUSTAINED", "DELAYED"})
    elif duration >= 300.0:
        tokens.update({"CLEAN", "TIMING", "GATE"})
    if (
        _optional_bool(data.get("reclaim_confirmed")) is True
        or _optional_bool(data.get("m15_close_above_resistance")) is True
    ):
        tokens.add("RECLAIM")
    if (
        _optional_bool(data.get("breakdown_confirmed")) is True
        or _optional_bool(data.get("m15_close_below_support")) is True
    ):
        tokens.add("BREAKDOWN")
    return tokens


def _tokens_from_text(value: Any) -> set[str]:
    normalized = _normalize_token(value)
    if not normalized:
        return set()
    raw_tokens = [token for token in re.split(r"[^A-Z0-9]+", normalized) if len(token) >= 3]
    tokens = {
        token
        for token in raw_tokens
        if token not in {"AND", "THE", "FOR", "WITH", "NOT", "ONLY", "AFTER", "BEFORE", "THEN"}
    }
    tokens.add(normalized)
    for idx in range(len(raw_tokens) - 1):
        tokens.add(f"{raw_tokens[idx]}_{raw_tokens[idx + 1]}")
    for idx in range(len(raw_tokens) - 2):
        tokens.add(f"{raw_tokens[idx]}_{raw_tokens[idx + 1]}_{raw_tokens[idx + 2]}")
    return tokens


def _normalize_token(value: Any) -> str:
    text = str(value or "").strip().upper()
    text = text.replace("-", "_").replace("/", "_").replace("+", "_")
    text = re.sub(r"[^A-Z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text


def _iter_text_values(value: Any, *, _depth: int = 0) -> list[str]:
    if value is None or _depth > 4:
        return []
    if isinstance(value, Mapping):
        texts: list[str] = []
        for item in value.values():
            texts.extend(_iter_text_values(item, _depth=_depth + 1))
        return texts
    if isinstance(value, (list, tuple, set)):
        texts = []
        for item in value:
            texts.extend(_iter_text_values(item, _depth=_depth + 1))
        return texts
    if isinstance(value, (str, int, float, bool)):
        text = str(value).strip()
        return [text] if text else []
    return []


def _append_unique(items: list[str], value: str) -> None:
    if value and value not in items:
        items.append(value)


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


def _string_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple, set)):
        items = [str(item) for item in value if item is not None and str(item)]
        return items or None
    text = str(value)
    return [text] if text else None


def _duration_seconds(data: Mapping[str, Any]) -> float:
    return _num(data.get("duration_seconds")) or _num(data.get("duration_minutes")) * 60.0


def _phase(value: Any) -> str:
    return _text(value).upper().replace(" ", "_").replace("-", "_")


def _is_bullish_or_reclaim(value: str) -> bool:
    return value in {"BULLISH", "UPTREND", "PIVOT_RECLAIM", "RECLAIM", "BULLISH_RECLAIM"} or "RECLAIM" in value


def _is_bearish_or_mixed_bearish(value: str) -> bool:
    return value in {"BEARISH", "DOWNTREND", "MIXED_BEARISH", "DISTRIBUTION_BREAKDOWN", "SUPPORT_BREAK"} or (
        "BEAR" in value or "BREAKDOWN" in value
    )


def _is_jpy_cross(symbol: str) -> bool:
    return symbol.endswith("JPY") or symbol.startswith("JPY")


def _is_major_pair(symbol: str) -> bool:
    return symbol in {"EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD"}


def _tradeplan_incomplete(data: Mapping[str, Any]) -> bool:
    target_mode = str(data.get("target_mode") or "").upper()
    if target_mode == "PROVISIONAL_RR_FALLBACK":
        return True
    return any(
        _optional_bool(data.get(field)) is False
        for field in (
            "tradeplan_context_ready",
            "structure_targets_available",
            "targets_execution_usable",
        )
    )


def _scoring_penalty(name: str, default: int) -> int:
    penalties = SCORING_MODEL.get("penalties") if isinstance(SCORING_MODEL, dict) else None
    if isinstance(penalties, dict):
        value = penalties.get(name)
        if isinstance(value, int | float):
            return int(value)
    return default


def _tier_weight(tier: str) -> int:
    text = _text(tier).upper()
    weights = SCORING_MODEL.get("tier_weights") if isinstance(SCORING_MODEL, dict) else None
    if isinstance(weights, dict):
        value = weights.get(text)
        if isinstance(value, int | float):
            return int(value)
    return {"S": 50, "A": 35, "B": 20}.get(text[:1], 0)


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
