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
    assert '"schema_version":"1.0"' in caplog.text
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
    assert event.schema_version == "1.0"


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


def test_continuation_valid_with_rr_fallback_uses_signal_json_prefix(caplog):
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
    assert "[SignalJSON]" in caplog.text
    assert "[SignalWatchJSON]" not in caplog.text
    assert '"signal_family":"MICROBOOST_TREND_CONTINUATION"' in caplog.text
    assert '"emit_reason":"QUORUM_CONTINUATION_VALID"' in caplog.text
    assert '"signal_quality":"TREND_CONTINUATION_VALID"' in caplog.text


def test_schema_v1_log_omits_structure_aware_export_fields(caplog):
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
    assert '"schema_version":"1.0"' in caplog.text
    assert '"targets"' not in caplog.text
    assert '"structure_zones"' not in caplog.text
    assert '"audit_valid"' not in caplog.text
