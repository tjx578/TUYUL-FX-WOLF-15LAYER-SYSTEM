from __future__ import annotations

import analysis.signal_json_emitter as signal_json_emitter
from analysis.signal_json_emitter import (
    UNIVERSAL_PATTERN_SCHEMA_VERSION,
    SignalJsonEmitter,
    SignalJsonEvent,
    build_signal_json_event,
    should_emit_signal_json,
)


def _event(**overrides):
    payload = {
        "event": "signal_json",
        "schema_version": UNIVERSAL_PATTERN_SCHEMA_VERSION,
        "symbol": "USDCAD",
        "signal_family": "MICROBOOST_COUNTER_ENTRY",
        "status": "NANO_ABSORPTION_SELL_WATCH",
        "raw_direction": "BUY",
        "candidate_direction": "SELL",
        "validated_direction": "SELL",
        "final_direction": "WAIT",
        "action": "WAIT_REJECTION_OR_MINOR_SUPPORT_BREAK",
        "signal_valid_time_utc": "2026-05-19T14:56:05Z",
        "signal_valid_time_wita": "2026-05-19 22:56:05",
        "signal_valid_price": 1.37696,
        "entry_reference_price": 1.37696,
        "entry_zone": [1.37696, 1.37696],
        "price_position": "MAIN_RESISTANCE",
        "m15_phase": "BEARISH_PULLBACK",
        "h1_phase": "BULLISH",
        "phase_unpriced": "REPEATED_MICROBOOST",
        "phase_priced": "RESISTANCE_PRESSURE_WARNING",
        "effective_ticks": 6,
        "effective_density": 43.61,
        "duration_minutes": 0.14,
        "sl_safe": 1.3790,
        "tp1": 1.3756,
        "tp2": 1.3735,
        "tp3": 1.3718,
        "tp4": 1.3700,
        "rr_to_tp1_tight": 1.1,
        "rr_to_tp2_tight": 2.8,
        "rr_to_tp3_tight": 4.2,
        "rr_status": "WATCH",
        "market_context_applied": True,
        "confidence_bucket": "B_COUNTER_ENTRY_WATCH",
        "reason": "BUY microboost density 43.61/m at main resistance with zero price expansion.",
        "invalidation": "M15 close above resistance high",
    }
    payload.update(overrides)
    return SignalJsonEvent(**payload)


def test_signal_json_emits_counter_entry_watch(caplog):
    emitter = SignalJsonEmitter(enabled=True, emit_watch=True)
    event = _event(cluster_id="USDCAD_20260519T145605Z")

    assert emitter.emit(event) is True
    assert "[SignalWatchJSON]" in caplog.text
    assert f'"schema_version":"{UNIVERSAL_PATTERN_SCHEMA_VERSION}"' in caplog.text
    assert '"symbol":"USDCAD"' in caplog.text
    assert '"candidate_direction":"SELL"' in caplog.text
    assert '"status":"NANO_ABSORPTION_SELL_WATCH"' in caplog.text


def test_signal_json_emits_generic_microboost_watch(caplog):
    emitter = SignalJsonEmitter(enabled=True, emit_watch=True)
    event = _event(
        cluster_id="CADJPY_20260518T133000Z",
        symbol="CADJPY",
        signal_family="MICROBOOST_WATCH",
        status="MICROBOOST_WATCH",
        raw_direction="BUY",
        candidate_direction="BUY",
        validated_direction=None,
        watch_direction="BUY",
        final_direction="WAIT",
        action="WAIT_M15_RECLAIM_OR_PULLBACK_COMPLETION",
        phase_priced="BULLISH_PULLBACK_MICROBOOST",
        rr_status="WATCH",
        market_context_applied=True,
        valid_for_execution=False,
    )

    assert emitter.emit(event) is True
    assert "[SignalWatchJSON]" in caplog.text
    assert '"signal_family":"MICROBOOST_WATCH"' in caplog.text
    assert '"status":"MICROBOOST_WATCH"' in caplog.text
    assert '"watch_direction":"BUY"' in caplog.text


def test_signal_json_does_not_emit_watch_by_default(caplog):
    emitter = SignalJsonEmitter(enabled=True)
    event = _event(cluster_id="USDCAD_20260519T145605Z")

    assert emitter.emit(event) is False
    assert "[SignalWatchJSON]" not in caplog.text
    assert "[SignalJSON]" not in caplog.text


def test_signal_json_deduplicates_same_event(caplog):
    emitter = SignalJsonEmitter(enabled=True, dedup_ttl_seconds=300, emit_watch=True)
    event = _event(cluster_id="USDCAD_20260519T145605Z")

    assert emitter.emit(event) is True
    assert emitter.emit(event) is False
    assert caplog.text.count("[SignalWatchJSON]") == 1


def test_final_signal_dedup_prefers_signal_id_across_stream_extracts(caplog):
    emitter = SignalJsonEmitter(enabled=True, dedup_ttl_seconds=300)
    first = _event(
        cluster_id="NZDJPY_20260603T132500Z_A",
        symbol="NZDJPY",
        status="SELL_BREAKDOWN_CONTINUATION_VALID",
        final_direction="SELL",
        rr_status="VALID",
        target_mode="FINAL_MARKET_STRUCTURE",
        valid_for_execution=True,
        signal_id="NZDJPY_SELL_20260603_132500",
    )
    duplicate_extract = _event(
        cluster_id="NZDJPY_20260603T132500Z_B",
        symbol="NZDJPY",
        status="SELL_BREAKDOWN_CONTINUATION_VALID",
        final_direction="SELL",
        rr_status="VALID",
        target_mode="FINAL_MARKET_STRUCTURE",
        valid_for_execution=True,
        signal_id="NZDJPY_SELL_20260603_132500",
    )

    assert emitter.emit(first) is True
    assert emitter.emit(duplicate_extract) is False
    assert caplog.text.count("[SignalJSON]") == 1


def test_signal_json_emits_watch_only_on_state_transition(caplog):
    emitter = SignalJsonEmitter(enabled=True, emit_watch=True)
    first = _event(
        cluster_id="USDCAD_20260519T145605Z",
        signal_valid_time_utc="2026-05-19T14:56:05Z",
        effective_ticks=6,
    )
    rolling_update = _event(
        cluster_id="USDCAD_20260519T145605Z",
        signal_valid_time_utc="2026-05-19T14:56:10Z",
        effective_ticks=10,
    )
    heartbeat_update = _event(
        cluster_id="USDCAD_20260519T145605Z",
        signal_valid_time_utc="2026-05-19T14:56:20Z",
        effective_ticks=16,
    )
    promoted = _event(
        cluster_id="USDCAD_20260519T145605Z",
        status="SELL_TIMING_WATCH",
        signal_valid_time_utc="2026-05-19T14:56:40Z",
    )

    assert emitter.emit(first) is True
    assert emitter.emit(rolling_update) is False
    assert emitter.emit(heartbeat_update) is True
    assert emitter.emit(promoted) is True
    assert caplog.text.count("[SignalWatchJSON]") == 3


def test_signal_watch_heartbeat_updates_even_when_source_timestamp_stalls(caplog, monkeypatch):
    current_time = [1_000.0]
    monkeypatch.setattr(signal_json_emitter.time, "time", lambda: current_time[0])
    emitter = SignalJsonEmitter(enabled=True, emit_watch=True, watch_update_interval_seconds=15)
    first = _event(cluster_id="USDCAD_20260519T145605Z", effective_ticks=6)
    stalled_short = _event(cluster_id="USDCAD_20260519T145605Z", effective_ticks=10)
    stalled_heartbeat = _event(cluster_id="USDCAD_20260519T145605Z", effective_ticks=18)

    assert emitter.emit(first) is True
    current_time[0] = 1_010.0
    assert emitter.emit(stalled_short) is False
    current_time[0] = 1_016.0
    assert emitter.emit(stalled_heartbeat) is True
    assert caplog.text.count("[SignalWatchJSON]") == 2


def test_absorption_timing_valid_is_lifecycle_signal_not_final(caplog):
    emitter = SignalJsonEmitter(enabled=True)
    event = _event(
        cluster_id="CADJPY_20260519T061520Z",
        symbol="CADJPY",
        status="SELL_TIMING_VALID_BY_ABSORPTION",
        final_direction="WAIT",
        action="WAIT_STRUCTURE_TARGET_OR_RETEST",
        signal_valid_price=115.7055,
        entry_reference_price=115.7055,
        entry_zone=[115.7055, 115.7055],
        rr_status="WATCH_PROVISIONAL",
        target_mode="PROVISIONAL_RR_FALLBACK",
        valid_for_execution=False,
    )

    assert should_emit_signal_json(event) is True
    assert emitter.emit(event) is True
    assert "[SignalWatchJSON]" in caplog.text
    assert "[SignalJSON]" not in caplog.text
    assert '"status":"SELL_TIMING_VALID_BY_ABSORPTION"' in caplog.text
    assert '"emit_reason":"TIMING_VALID_CONDITIONAL"' in caplog.text


def test_absorption_watch_emits_without_enabling_generic_watch(caplog):
    emitter = SignalJsonEmitter(enabled=True)
    event = _event(
        cluster_id="USDCAD_20260519T145605Z",
        status="SELL_ABSORPTION_WATCH",
        action="WAIT_M15_CLOSE_CONFIRMATION",
        rr_status="WATCH",
        target_mode="FINAL_MARKET_STRUCTURE",
    )

    assert should_emit_signal_json(event) is True
    assert emitter.emit(event) is True
    assert "[SignalWatchJSON]" in caplog.text
    assert "[SignalJSON]" not in caplog.text
    assert '"status":"SELL_ABSORPTION_WATCH"' in caplog.text
    assert '"emit_reason":"ABSORPTION_WATCH"' in caplog.text
    assert '"signal_quality":"ABSORPTION_WATCH"' in caplog.text


def test_absorption_timing_valid_can_be_disabled(caplog):
    emitter = SignalJsonEmitter(enabled=True, emit_conditional=False)
    event = _event(
        cluster_id="CADJPY_20260519T061520Z",
        symbol="CADJPY",
        status="SELL_TIMING_VALID_BY_ABSORPTION",
        rr_status="WATCH_PROVISIONAL",
        target_mode="PROVISIONAL_RR_FALLBACK",
    )

    assert should_emit_signal_json(event, emit_conditional=False) is False
    assert emitter.emit(event) is False
    assert "[SignalWatchJSON]" not in caplog.text


def test_do_not_emit_when_market_context_false():
    assert should_emit_signal_json(_event(market_context_applied=False)) is False


def test_do_not_emit_valid_signal_without_rr():
    assert should_emit_signal_json(_event(status="SELL_TIMING_VALID", rr_status="UNVALIDATED")) is False


def test_build_signal_json_event_from_counter_entry_payload():
    payload = _event(cluster_id="USDCAD_20260519T145605Z").to_dict()

    event = build_signal_json_event(payload)

    assert event is not None
    assert event.symbol == "USDCAD"
    assert event.status == "NANO_ABSORPTION_SELL_WATCH"
    assert event.entry_reference_price == 1.37696
    assert event.signal_family == "MICROBOOST_COUNTER_ENTRY"
    assert event.validated_direction is None
    assert event.watch_direction == "SELL"
    assert event.direction_validation_status == "WATCH_ONLY_PENDING_CONFIRMATION"
    assert event.cluster_id == "USDCAD_20260519T145605Z"
    assert event.event == "signal_watch_json"
    assert event.is_final_signal is False
    assert event.signal_quality == "WATCH_ONLY"
    assert event.schema_version == UNIVERSAL_PATTERN_SCHEMA_VERSION


def test_build_signal_json_event_retains_golden_pattern_contract_fields():
    payload = _event(
        cluster_id="USDJPY_20260519T145605Z",
        symbol="USDJPY",
        matched_patterns=["UPPER_ABSORPTION_WARNING", "JPY_ALIGNMENT_REQUIRED"],
        selected_pattern_id="UPPER_ABSORPTION_WARNING",
        pattern_tier="S",
        pattern_family="EXHAUSTION_MANAGEMENT",
        pattern_score=58,
        pattern_match_score=92,
        execution_readiness_score=58,
        golden_reference="USDJPY",
        pair_role="PHASE_SENSITIVE_JPY_MAJOR",
        entry_permission="NO_NEW_BUY",
        management_action="PROTECT_LONG_OR_SELL_WATCH",
        chase_allowed=False,
        jpy_alignment_status="UNKNOWN",
        theme_alignment_status="ALIGNED",
        alignment_missing_reason="jpy_alignment,dual_theme_status",
        pattern_evidence=["strategy_pattern=UPPER_RANGE_EXHAUSTION"],
    ).to_dict()

    event = build_signal_json_event(payload)

    assert event is not None
    assert event.selected_pattern_id == "UPPER_ABSORPTION_WARNING"
    assert event.matched_patterns == ["UPPER_ABSORPTION_WARNING", "JPY_ALIGNMENT_REQUIRED"]
    assert event.entry_permission == "NO_NEW_BUY"
    assert event.pattern_score == 58
    assert event.pattern_match_score == 92
    assert event.execution_readiness_score == 58
    assert event.jpy_alignment_status == "UNKNOWN"
    assert event.theme_alignment_status == "NOT_AVAILABLE"
    assert event.alignment_missing_reason == "basket_snapshot_missing_or_not_computed,jpy_alignment,dual_theme_status"
    assert event.reference_cases == [
        {
            "symbol": "USDJPY",
            "role": "GOLDEN_REFERENCE_CASE",
            "note": "Reference only; pattern is universal, not pair-locked.",
            "reason": "historical validation source for UPPER_ABSORPTION_WARNING",
        }
    ]
    assert event.pair_calibration is not None
    assert event.pair_calibration["symbol"] == "USDJPY"
    assert event.pair_calibration["pair_specific_logic_locked"] is False
    assert event.pattern_context is not None
    assert event.pattern_context["pattern_scope"] == "UNIVERSAL"
    assert event.signal_id == "USDJPY_SELL_WATCH_20260519_145605"


def test_emitted_payload_uses_universal_pattern_context_not_pair_owned_fields(caplog):
    emitter = SignalJsonEmitter(enabled=True, emit_watch=True)
    event = _event(
        cluster_id="USDCAD_20260601T084153Z",
        symbol="USDCAD",
        selected_pattern_id="UPPER_ABSORPTION_WARNING",
        pattern_family="EXHAUSTION_MANAGEMENT",
        pattern_scope="UNIVERSAL",
        golden_reference="USDJPY",
        pair_role="MACRO_ANCHOR_AND_SIGNALWATCH_LIFECYCLE",
        theme_alignment=None,
        theme_alignment_status="ALIGNED",
        support_ladder_ready=False,
        structure_targets_available=False,
        tradeplan_context_ready=False,
        targets_execution_usable=False,
        target_mode="PROVISIONAL_RR_FALLBACK",
    )

    assert emitter.emit(event) is True
    assert '"reference_cases":[{"symbol":"USDJPY"' in caplog.text
    assert '"pair_calibration":{"symbol":"USDCAD"' in caplog.text
    assert '"pattern_context":{"selected_pattern_id":"UPPER_ABSORPTION_WARNING"' in caplog.text
    assert '"theme_context"' not in caplog.text
    assert '"theme_alignment_status"' not in caplog.text
    assert '"tradeplan_preview":{"target_mode":"PROVISIONAL_RR_FALLBACK"' in caplog.text
    assert '"golden_reference"' not in caplog.text
    assert '"pair_role"' not in caplog.text


def test_chfjpy_reference_pattern_emits_as_universal_context_not_pair_lock(caplog):
    emitter = SignalJsonEmitter(enabled=True, emit_watch=True)
    event = _event(
        cluster_id="EURJPY_20260602T081500Z",
        symbol="EURJPY",
        selected_pattern_id="JPY_BASKET_THEME_FOLLOWTHROUGH",
        matched_patterns=["JPY_BASKET_THEME_FOLLOWTHROUGH", "BASKET_THEME_CONFIRMATION_CONTEXT"],
        pattern_tier="A",
        pattern_family="BASKET_THEME_CONFIRMATION",
        pattern_scope="UNIVERSAL",
        applies_to="ALL_PAIRS_IF_CONDITIONS_MATCH",
        pattern_score=64,
        pattern_match_score=100,
        execution_readiness_score=64,
        golden_references=["CHFJPY"],
        pair_specific_calibration=[
            "JPY_BASKET_MEMBER_REFERENCE",
            "MFE_MAE_VALIDATION_REQUIRED",
            "NOT_PAIR_LOCKED",
        ],
        pair_role="JPY_BASKET_GOLDEN_REFERENCE",
        entry_permission="VALIDATED_THEME_FOLLOWTHROUGH",
        management_action="WATCH_PRICE_PHASE_AND_OWN_TRIGGER",
        block_reason="THEME_FOLLOWTHROUGH_REQUIRES_OWN_TRIGGER",
        pattern_bottlenecks=[
            "PATTERN_CONTEXT_ONLY_NOT_FINAL_SIGNAL",
            "THEME_FOLLOWTHROUGH_REQUIRES_OWN_TRIGGER",
        ],
        pattern_evidence=["jpy_basket_theme_followthrough_validated_not_auto_entry"],
    )

    assert emitter.emit(event) is True
    assert '"reference_cases":[{"symbol":"CHFJPY"' in caplog.text
    assert '"pair_calibration":{"symbol":"EURJPY"' in caplog.text
    assert '"pair_specific_logic_locked":false' in caplog.text
    assert '"pair_specific_calibration":["JPY_BASKET_MEMBER_REFERENCE","MFE_MAE_VALIDATION_REQUIRED","NOT_PAIR_LOCKED"]' in caplog.text
    assert '"pattern_context":{"selected_pattern_id":"JPY_BASKET_THEME_FOLLOWTHROUGH"' in caplog.text
    assert '"pattern_bottlenecks":["PATTERN_CONTEXT_ONLY_NOT_FINAL_SIGNAL","THEME_FOLLOWTHROUGH_REQUIRES_OWN_TRIGGER"]' in caplog.text
    assert '"golden_references"' not in caplog.text
    assert '"pair_role"' not in caplog.text


def test_production_signal_json_omits_null_duplicates_and_heavy_pattern_debug(caplog):
    emitter = SignalJsonEmitter(enabled=True, emit_watch=True)
    event = _event(
        cluster_id="USDJPY_20260601T125149Z",
        symbol="USDJPY",
        selected_pattern_id="UPPER_ABSORPTION_WARNING",
        matched_patterns=["UPPER_ABSORPTION_WARNING", "JPY_ALIGNMENT_REQUIRED", "LATE_UPPER_MICROBOOST"],
        pattern_family="EXHAUSTION_MANAGEMENT",
        pattern_scope="UNIVERSAL",
        pattern_tier="S",
        pattern_match_score=100,
        execution_readiness_score=69,
        target_mode="PROVISIONAL_RR_FALLBACK",
        support_ladder_ready=False,
        structure_targets_available=False,
        targets_execution_usable=False,
        pattern_db_fuzzy_matches=["LATE_UPPER_MICROBOOST"],
        pattern_match_diagnostics={
            "search_mode": "DATABASE_WIDE",
            "patterns_scanned": 52,
            "semantic_hits": {"LATE_UPPER_MICROBOOST": ["microboost"]},
            "candidate_scores_top": {"UPPER_ABSORPTION_WARNING": 223},
        },
        linked_previous_signal=None,
    )

    assert emitter.emit(event) is True
    assert "[SignalWatchJSON]" in caplog.text
    assert '"linked_previous_signal":null' not in caplog.text
    assert '"selected_pattern_id":"UPPER_ABSORPTION_WARNING"' in caplog.text
    assert caplog.text.count('"selected_pattern_id":"UPPER_ABSORPTION_WARNING"') == 1
    assert '"pattern_db_fuzzy_matches"' not in caplog.text
    assert '"pattern_match_diagnostics"' not in caplog.text
    assert '"semantic_hits"' not in caplog.text
    assert '"top_supporting_patterns":["JPY_ALIGNMENT_REQUIRED","LATE_UPPER_MICROBOOST"]' in caplog.text
    assert '"tradeplan_preview":{"target_mode":"PROVISIONAL_RR_FALLBACK"' in caplog.text
    assert '"support_ladder_ready":false' in caplog.text


def test_pattern_match_debug_sidecar_is_opt_in(caplog):
    emitter = SignalJsonEmitter(enabled=True, emit_watch=True, emit_pattern_debug=True)
    event = _event(
        cluster_id="USDJPY_20260601T125149Z",
        symbol="USDJPY",
        selected_pattern_id="UPPER_ABSORPTION_WARNING",
        matched_patterns=["UPPER_ABSORPTION_WARNING", "JPY_ALIGNMENT_REQUIRED"],
        pattern_db_exact_matches=["UPPER_ABSORPTION_WARNING"],
        pattern_db_fuzzy_matches=["LATE_UPPER_MICROBOOST"],
        pattern_match_diagnostics={
            "search_mode": "DATABASE_WIDE",
            "patterns_scanned": 52,
            "semantic_hits": {"LATE_UPPER_MICROBOOST": ["microboost"]},
            "candidate_scores_top": {"UPPER_ABSORPTION_WARNING": 223},
        },
    )

    assert emitter.emit(event) is True
    assert "[PatternMatchDebugJSON]" in caplog.text
    assert '"event":"pattern_match_debug_json"' in caplog.text
    assert '"patterns_scanned":52' in caplog.text
    assert '"exact_matches":["UPPER_ABSORPTION_WARNING"]' in caplog.text
    assert '"fuzzy_matches":["LATE_UPPER_MICROBOOST"]' in caplog.text
    assert '"semantic_hits":{"LATE_UPPER_MICROBOOST":["microboost"]}' in caplog.text


def test_build_signal_json_event_marks_absorption_as_conditional_quality():
    payload = _event(
        status="SELL_TIMING_VALID_BY_ABSORPTION",
        rr_status="WATCH_PROVISIONAL",
        target_mode="PROVISIONAL_RR_FALLBACK",
        valid_for_execution=False,
    ).to_dict()

    event = build_signal_json_event(payload)

    assert event is not None
    assert event.event == "signal_watch_json"
    assert event.is_final_signal is False
    assert event.signal_quality == "TIMING_VALID_CONDITIONAL"


def test_build_signal_json_event_marks_absorption_watch_quality():
    payload = _event(
        status="SELL_ABSORPTION_WATCH",
        action="WAIT_M15_CLOSE_CONFIRMATION",
        rr_status="WATCH",
    ).to_dict()

    event = build_signal_json_event(payload)

    assert event is not None
    assert event.event == "signal_watch_json"
    assert event.is_final_signal is False
    assert event.emit_reason == "ABSORPTION_WATCH"
    assert event.signal_quality == "ABSORPTION_WATCH"


def test_final_signal_uses_signal_json_prefix(caplog):
    emitter = SignalJsonEmitter(enabled=True)
    event = _event(
        cluster_id="USDCAD_20260519T145605Z",
        status="SELL_TIMING_VALID",
        final_direction="SELL",
        rr_status="VALID",
        target_mode="FINAL_MARKET_STRUCTURE",
        valid_for_execution=True,
    )

    assert emitter.emit(event) is True
    assert "[SignalJSON]" in caplog.text
    assert "[SignalWatchJSON]" not in caplog.text
    assert "[SignalDecisionUpdateJSON]" not in caplog.text


def test_terminal_valid_wait_structure_emits_signal_json_without_execution(caplog):
    emitter = SignalJsonEmitter(enabled=True)
    event = _event(
        cluster_id="NZDJPY_20260603T132500Z",
        symbol="NZDJPY",
        status="FINAL_VALID_WAIT_STRUCTURE_TARGET",
        terminal_status="FINAL_VALID_WAIT_STRUCTURE_TARGET",
        raw_direction="SELL",
        candidate_direction="SELL",
        validated_direction="SELL",
        final_direction="SELL",
        action="WAIT_STRUCTURE_TARGET_OR_RETEST",
        next_action="WAIT_STRUCTURE_TARGET_OR_RETEST",
        rr_status="VALID",
        target_mode="PROVISIONAL_RR_FALLBACK",
        signal_valid=True,
        direction_valid=True,
        analysis_valid=True,
        tradeplan_valid=False,
        valid_for_execution=False,
        execution_valid_now=False,
        terminal_decision_confirmed=True,
        is_final_signal=True,
    )

    assert should_emit_signal_json(event) is True
    assert emitter.emit(event) is True
    assert "[SignalJSON]" in caplog.text
    assert "[SignalWatchJSON]" not in caplog.text
    assert "[SignalDecisionUpdateJSON]" not in caplog.text
    assert '"status":"FINAL_VALID_WAIT_STRUCTURE_TARGET"' in caplog.text
    assert '"signal_valid":true' in caplog.text
    assert '"direction_valid":true' in caplog.text
    assert '"tradeplan_valid":false' in caplog.text
    assert '"execution_valid_now":false' in caplog.text
    assert '"valid_for_execution":false' in caplog.text


def test_continuation_valid_with_rr_fallback_defaults_to_decision_update(caplog):
    emitter = SignalJsonEmitter(enabled=True)
    event = _event(
        cluster_id="USDCAD_20260520T024532Z",
        symbol="USDCAD",
        signal_family="MICROBOOST_TREND_CONTINUATION",
        status="BUY_TIMING_VALID_BY_QUORUM_CONTINUATION",
        raw_direction="BUY",
        candidate_direction="BUY",
        validated_direction="BUY",
        final_direction="BUY",
        action="BUY_SIGNAL_ZONE_OR_RETEST",
        rr_status="VALID",
        target_mode="PROVISIONAL_RR_FALLBACK",
        valid_for_execution=True,
        allowed_quorum=True,
        allowed_quorum_streak=3,
        reclaim_trigger=1.3785,
        risk_pips=12.0,
    )

    assert should_emit_signal_json(event) is True
    assert emitter.emit(event) is True
    assert "[SignalDecisionUpdateJSON]" in caplog.text
    assert "[SignalJSON]" not in caplog.text
    assert "PROVISIONAL_RR_NOT_EXECUTION_GRADE" in caplog.text


def test_continuation_valid_with_rr_fallback_can_be_explicitly_enabled(caplog):
    emitter = SignalJsonEmitter(enabled=True, allow_provisional_rr_execution=True)
    event = _event(
        cluster_id="USDCAD_20260520T024532Z",
        symbol="USDCAD",
        signal_family="MICROBOOST_TREND_CONTINUATION",
        status="BUY_TIMING_VALID_BY_QUORUM_CONTINUATION",
        raw_direction="BUY",
        candidate_direction="BUY",
        validated_direction="BUY",
        final_direction="BUY",
        action="BUY_SIGNAL_ZONE_OR_RETEST",
        rr_status="VALID",
        target_mode="PROVISIONAL_RR_FALLBACK",
        valid_for_execution=True,
        allowed_quorum=True,
        allowed_quorum_streak=3,
        reclaim_trigger=1.3785,
        risk_pips=12.0,
    )

    assert should_emit_signal_json(event) is True
    assert emitter.emit(event) is True
    assert "[SignalJSON]" in caplog.text
    assert "[SignalWatchJSON]" not in caplog.text
    assert '"signal_family":"MICROBOOST_TREND_CONTINUATION"' in caplog.text
    assert '"emit_reason":"QUORUM_CONTINUATION_VALID"' in caplog.text
    assert '"signal_quality":"TREND_CONTINUATION_VALID"' in caplog.text


def test_strict_lifecycle_blocks_unready_final_as_decision_update(caplog):
    emitter = SignalJsonEmitter(
        enabled=True,
        strict_lifecycle=True,
        require_parent_watch=False,
        require_final_market_structure=True,
        allow_provisional_rr_execution=False,
        require_theme_alignment=False,
        require_terminal_decision_update=False,
    )
    event = _event(
        cluster_id="USDCAD_20260520T024532Z",
        symbol="USDCAD",
        signal_family="MICROBOOST_TREND_CONTINUATION",
        status="BUY_TIMING_VALID_BY_QUORUM_CONTINUATION",
        raw_direction="BUY",
        candidate_direction="BUY",
        validated_direction="BUY",
        final_direction="BUY",
        action="BUY_SIGNAL_ZONE_OR_RETEST",
        rr_status="VALID",
        target_mode="PROVISIONAL_RR_FALLBACK",
        valid_for_execution=True,
        allowed_quorum=True,
        allowed_quorum_streak=3,
        reclaim_trigger=1.3785,
        risk_pips=12.0,
    )

    assert emitter.emit(event) is True
    assert "[SignalDecisionUpdateJSON]" in caplog.text
    assert "[SignalJSON]" not in caplog.text
    assert '"status":"WAIT_STRUCTURE_OR_NEXT_M15"' in caplog.text
    assert '"final_direction":"WAIT"' in caplog.text
    assert "PROVISIONAL_RR_NOT_EXECUTION_GRADE" in caplog.text


def test_universal_pattern_log_omits_raw_structure_aware_export_fields(caplog):
    emitter = SignalJsonEmitter(enabled=True)
    event = _event(
        status="SELL_TIMING_VALID",
        final_direction="SELL",
        rr_status="VALID",
        target_mode="FINAL_MARKET_STRUCTURE",
        valid_for_execution=True,
        targets=[{"id": "TP1", "level": 1.3735}],
        structure_zones={"key_support": 1.3735},
        audit_valid=True,
    )

    assert emitter.emit(event) is True
    assert f'"schema_version":"{UNIVERSAL_PATTERN_SCHEMA_VERSION}"' in caplog.text
    assert '"targets"' not in caplog.text
    assert '"structure_zones"' not in caplog.text
    assert '"audit_valid"' not in caplog.text
