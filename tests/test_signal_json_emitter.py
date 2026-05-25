from __future__ import annotations

from analysis.signal_json_emitter import (
    SignalJsonEmitter,
    SignalJsonEvent,
    build_signal_json_event,
    should_emit_signal_json,
)


def _event(**overrides):
    payload = {
        "event": "signal_json",
        "schema_version": "1.0",
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
        "sl_tight": 1.3782,
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
    assert '"symbol":"USDCAD"' in caplog.text
    assert '"candidate_direction":"SELL"' in caplog.text
    assert '"status":"NANO_ABSORPTION_SELL_WATCH"' in caplog.text


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


def test_signal_json_emits_watch_only_on_state_transition(caplog):
    emitter = SignalJsonEmitter(enabled=True, emit_watch=True)
    first = _event(
        cluster_id="USDCAD_20260519T145605Z",
        signal_valid_time_utc="2026-05-19T14:56:05Z",
        effective_ticks=6,
    )
    rolling_update = _event(
        cluster_id="USDCAD_20260519T145605Z",
        signal_valid_time_utc="2026-05-19T14:56:20Z",
        effective_ticks=10,
    )
    promoted = _event(
        cluster_id="USDCAD_20260519T145605Z",
        status="SELL_TIMING_WATCH",
        signal_valid_time_utc="2026-05-19T14:56:40Z",
    )

    assert emitter.emit(first) is True
    assert emitter.emit(rolling_update) is False
    assert emitter.emit(promoted) is True
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
    assert event.validated_direction == "SELL"
    assert event.cluster_id == "USDCAD_20260519T145605Z"
    assert event.event == "signal_watch_json"
    assert event.is_final_signal is False
    assert event.signal_quality == "WATCH_ONLY"
    assert event.schema_version == "1.1-structure-aware"


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
    assert emitter.emit(
        _event(
            cluster_id="USDCAD_20260519T145605Z",
            status="SELL_ABSORPTION_WATCH",
            pending_decision_id="USDCAD_M15_DECISION",
        )
    ) is True
    caplog.clear()
    event = _event(
        cluster_id="USDCAD_20260519T145605Z",
        status="SELL_TIMING_VALID",
        final_direction="SELL",
        h1_phase="BEARISH",
        rr_status="VALID",
        target_mode="FINAL_MARKET_STRUCTURE",
        valid_for_execution=True,
        tradeplan_valid=True,
        execution_valid_now=True,
        selected_sl=1.3790,
        selected_risk_pips=20.4,
        tp_min_rr=1.3718,
        tp1_rr=2.0,
        targets=[{"id": "TP2", "level": 1.3700, "type": "STRUCTURE_TARGET", "rr": 3.41}],
        structure_zones={"key_resistance": 1.3774, "key_support": 1.3735},
        invalidation_rules={"hard_invalid_level": 1.3790},
        execution_quality={"spread_normal": True},
        phase_coherence={"h1": "BEARISH", "status": "EXECUTION_COMPATIBLE"},
        signal_expiry={"expires_at_utc": "2026-05-19T15:26:05+00:00"},
        pending_decision_id="USDCAD_M15_DECISION",
    )

    assert emitter.emit(event) is True
    assert "[SignalJSON]" in caplog.text
    assert "[SignalWatchJSON]" not in caplog.text
    assert '"valid_for_execution":true' in caplog.text


def test_continuation_with_rr_fallback_emits_decision_update_not_final_signal(caplog):
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
        tp1_rr=2.0,
        allowed_quorum=True,
        allowed_quorum_streak=3,
        reclaim_trigger=1.3785,
        risk_pips=12.0,
    )

    assert should_emit_signal_json(event) is True
    assert emitter.emit(event) is True
    assert "[SignalDecisionUpdateJSON]" in caplog.text
    assert "[SignalJSON]" not in caplog.text
    assert '"source_final_direction":"BUY"' in caplog.text
    assert '"source_valid_for_execution":true' in caplog.text
    assert '"valid_for_execution":false' in caplog.text
    assert '"execution_status":"BLOCKED_SIGNAL_JSON_STRICT_GATE"' in caplog.text
    assert '"PROVISIONAL_RR_NOT_EXECUTION_GRADE"' in caplog.text


def test_structure_aware_breakout_continuation_can_emit_final_signal(caplog):
    emitter = SignalJsonEmitter(enabled=True)
    assert emitter.emit(
        _event(
            cluster_id="GBPCAD_20260525T165847Z",
            symbol="GBPCAD",
            status="SELL_ABSORPTION_WATCH",
            pending_decision_id="GBPCAD_M15_DECISION",
        )
    ) is True
    caplog.clear()
    event = _event(
        cluster_id="GBPCAD_20260525T165847Z",
        symbol="GBPCAD",
        signal_family="MICROBOOST_COUNTER_ENTRY",
        status="BUY_BREAKOUT_CONTINUATION_VALID",
        raw_direction="BUY",
        candidate_direction="BUY",
        validated_direction="BUY",
        final_direction="BUY",
        action="BUY_BREAKOUT_RETEST_ENTRY",
        m15_phase="BULLISH_PULLBACK",
        h1_phase="BULLISH",
        signal_valid_price=1.8636,
        entry_reference_price=1.8636,
        entry_zone=[1.8628, 1.8640],
        sl_tight=1.8624,
        sl_safe=1.8616,
        rr_status="VALID",
        target_mode="FINAL_MARKET_STRUCTURE",
        valid_for_execution=True,
        analysis_valid=True,
        tradeplan_valid=True,
        execution_valid_now=True,
        selected_sl=1.8616,
        selected_risk_pips=20.0,
        tp_min_rr=1.8686,
        tp1_rr=2.0,
        targets=[{"id": "TP2", "level": 1.8690, "type": "STRUCTURE_TARGET", "rr": 2.7}],
        structure_zones={"key_resistance": 1.8650, "key_support": 1.8616},
        invalidation_rules={"hard_invalid_level": 1.8616},
        execution_quality={"spread_normal": True},
        phase_coherence={"h1": "BULLISH", "status": "EXECUTION_COMPATIBLE"},
        signal_expiry={"expires_at_utc": "2026-05-25T17:43:47+00:00"},
        pending_decision_id="GBPCAD_M15_DECISION",
    )

    assert should_emit_signal_json(event) is True
    assert emitter.emit(event) is True
    assert "[SignalJSON]" in caplog.text
    assert '"status":"BUY_BREAKOUT_CONTINUATION_VALID"' in caplog.text
    assert '"final_direction":"BUY"' in caplog.text
    assert '"valid_for_execution":true' in caplog.text


def test_signal_decision_update_uses_decision_update_prefix(caplog):
    emitter = SignalJsonEmitter(enabled=True)
    event = _event(
        event="signal_decision_update_json",
        cluster_id="USDCAD_20260521T030620Z",
        status="WAIT_STRUCTURE_OR_NEXT_M15",
        action="WAIT_STRUCTURE_TARGET_OR_SUPPORT_LADDER",
        rr_status="WATCH_PROVISIONAL",
        target_mode="PROVISIONAL_RR_FALLBACK",
        confirmation_policy="M15_CLOSE_REJECTION_CONFIRMED",
        m15_confirmation_status="M15_CLOSE_REJECTION_CONFIRMED",
        block_end_utc="2026-05-21T03:15:04+00:00",
        block_end_wita="2026-05-21 11:15:04",
        block_idle_seconds=86.0,
        valid_for_execution=False,
    )

    assert should_emit_signal_json(event) is True
    assert emitter.emit(event) is True
    assert "[SignalDecisionUpdateJSON]" in caplog.text
    assert "[SignalWatchJSON]" not in caplog.text
    assert "[SignalJSON]" not in caplog.text
    assert '"event":"signal_decision_update_json"' in caplog.text
    assert '"signal_quality":"DECISION_UPDATE"' in caplog.text


def test_signal_decision_update_deduplicates_by_default_and_can_be_disabled(caplog):
    event = _event(
        event="signal_decision_update_json",
        cluster_id="USDCAD_DEDUP",
        status="WAIT_STRUCTURE_OR_NEXT_M15",
        pending_decision_id="USDCAD_DEDUP_M15_DECISION",
        block_end_wita="2026-05-21 11:15:04",
    )
    strict = SignalJsonEmitter(enabled=True)
    relaxed = SignalJsonEmitter(enabled=True, decision_dedup_enabled=False, decision_state_monotonic=False)

    assert strict.emit(event) is True
    assert strict.emit(event) is False
    caplog.clear()
    assert relaxed.emit(event) is True
    assert relaxed.emit(event) is True
    assert caplog.text.count("[SignalDecisionUpdateJSON]") == 2


def test_final_counter_entry_preserves_direction_and_blocks_incomplete_execution_contract():
    event = build_signal_json_event(_event(
        status="SELL_TIMING_VALID",
        final_direction="SELL",
        rr_status="VALID",
        target_mode="FINAL_MARKET_STRUCTURE",
        valid_for_execution=True,
    ).to_dict())

    assert event is not None
    assert event.status == "SELL_TIMING_VALID"
    assert event.final_direction == "SELL"
    assert event.source_valid_for_execution is True
    assert event.valid_for_execution is False
    assert event.signal_quality == "DIRECTION_VALID_TRADEPLAN_INCOMPLETE"


def test_final_continuation_enrichment_recalculates_tp1_at_two_r():
    event = build_signal_json_event(_event(
        signal_family="MICROBOOST_TREND_CONTINUATION",
        status="BUY_TIMING_VALID_BY_QUORUM_CONTINUATION",
        final_direction="BUY",
        m15_phase="BULLISH_PULLBACK",
        h1_phase="BULLISH",
        sl_tight=1.3750,
        sl_safe=1.3742,
        rr_status="VALID",
        target_mode="PROVISIONAL_RR_FALLBACK",
        valid_for_execution=True,
        tp1_rr=1.99,
    ).to_dict())

    assert event is not None
    assert event.final_direction == "BUY"
    assert event.tp1_rr == 2.0
    assert event.valid_for_execution is False


def test_counter_entry_breakout_is_logged_as_decision_update_when_rr_is_provisional(caplog):
    emitter = SignalJsonEmitter(enabled=True)
    event = _event(
        cluster_id="USDCAD_20260521T030620Z",
        status="BUY_BREAKOUT_CONTINUATION_VALID",
        raw_direction="BUY",
        candidate_direction="BUY",
        validated_direction="BUY",
        final_direction="BUY",
        action="BUY_BREAKOUT_RETEST",
        rr_status="VALID",
        target_mode="PROVISIONAL_RR_FALLBACK",
        valid_for_execution=True,
        tp1_rr=2.0,
    )

    assert should_emit_signal_json(event) is True
    assert emitter.emit(event) is True
    assert "[SignalDecisionUpdateJSON]" in caplog.text
    assert "[SignalJSON]" not in caplog.text
    assert '"source_status":"BUY_BREAKOUT_CONTINUATION_VALID"' in caplog.text
    assert '"source_final_direction":"BUY"' in caplog.text
    assert '"valid_for_execution":false' in caplog.text


def test_direct_bypass_requires_explicit_policy_and_complete_structure(caplog):
    emitter = SignalJsonEmitter(enabled=True, allow_direct_bypass=True)
    event = _event(
        symbol="GBPCAD",
        status="BUY_BREAKOUT_CONTINUATION_VALID",
        raw_direction="BUY",
        candidate_direction="BUY",
        validated_direction="BUY",
        final_direction="BUY",
        m15_phase="BULLISH_PULLBACK",
        h1_phase="BULLISH",
        signal_valid_price=1.8636,
        entry_reference_price=1.8636,
        entry_zone=[1.8628, 1.8640],
        sl_tight=1.8624,
        sl_safe=1.8616,
        target_mode="FINAL_MARKET_STRUCTURE",
        targets=[{"id": "TP2", "level": 1.8690, "type": "STRUCTURE_TARGET", "rr": 2.7}],
        structure_zones={"key_resistance": 1.8650, "key_support": 1.8616},
        execution_quality={"spread_normal": True},
        valid_for_execution=True,
        promotion_path="DIRECT_BYPASS",
        bypass_reason="QUORUM_CONTINUATION_MID_RANGE",
        parent_watch_required=False,
    )

    assert emitter.emit(event) is True
    assert "[SignalJSON]" in caplog.text
    assert '"promotion_path":"DIRECT_BYPASS"' in caplog.text
    assert '"audit_valid":true' in caplog.text


def test_theme_conflict_downgrades_final_even_with_parent_and_structure(caplog):
    emitter = SignalJsonEmitter(enabled=True)
    pending_id = "GBPCAD_THEME_DECISION"
    assert emitter.emit(_event(cluster_id="GBPCAD_THEME", status="SELL_ABSORPTION_WATCH", pending_decision_id=pending_id)) is True
    caplog.clear()

    event = _event(
        cluster_id="GBPCAD_THEME",
        symbol="GBPCAD",
        status="BUY_BREAKOUT_CONTINUATION_VALID",
        final_direction="BUY",
        m15_phase="BULLISH_PULLBACK",
        h1_phase="BULLISH",
        theme_alignment="SELL_BIAS",
        signal_valid_price=1.8636,
        entry_reference_price=1.8636,
        entry_zone=[1.8628, 1.8640],
        sl_tight=1.8624,
        sl_safe=1.8616,
        target_mode="FINAL_MARKET_STRUCTURE",
        targets=[{"id": "TP2", "level": 1.8690, "type": "STRUCTURE_TARGET", "rr": 2.7}],
        structure_zones={"key_resistance": 1.8650, "key_support": 1.8616},
        execution_quality={"spread_normal": True},
        valid_for_execution=True,
        pending_decision_id=pending_id,
    )

    assert emitter.emit(event) is True
    assert "[SignalDecisionUpdateJSON]" in caplog.text
    assert '"THEME_CONFLICT_REQUIRES_SECOND_M15_CONFIRMATION"' in caplog.text


def test_final_emission_makes_pending_decision_terminal(caplog):
    emitter = SignalJsonEmitter(enabled=True)
    pending_id = "USDCAD_FINAL_DECISION"
    cluster_id = "USDCAD_FINAL"
    assert emitter.emit(_event(cluster_id=cluster_id, status="SELL_ABSORPTION_WATCH", pending_decision_id=pending_id)) is True
    caplog.clear()
    final = _event(
        cluster_id=cluster_id,
        status="SELL_TIMING_VALID",
        final_direction="SELL",
        h1_phase="BEARISH",
        target_mode="FINAL_MARKET_STRUCTURE",
        valid_for_execution=True,
        selected_sl=1.3790,
        targets=[{"id": "TP2", "level": 1.3700, "type": "STRUCTURE_TARGET", "rr": 3.41}],
        structure_zones={"key_resistance": 1.3774, "key_support": 1.3735},
        execution_quality={"spread_normal": True},
        pending_decision_id=pending_id,
    )
    late_wait = _event(
        event="signal_decision_update_json",
        cluster_id=cluster_id,
        status="WAIT_STRUCTURE_OR_NEXT_M15",
        pending_decision_id=pending_id,
    )

    assert emitter.emit(final) is True
    assert emitter.emit(late_wait) is False
    assert caplog.text.count("[SignalJSON]") == 1
    assert "[SignalDecisionUpdateJSON]" not in caplog.text
