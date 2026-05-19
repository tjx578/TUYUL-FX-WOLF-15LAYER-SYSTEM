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
    emitter = SignalJsonEmitter(enabled=True)
    event = _event()

    assert emitter.emit(event) is True
    assert "[SignalJSON]" in caplog.text
    assert '"symbol":"USDCAD"' in caplog.text
    assert '"candidate_direction":"SELL"' in caplog.text
    assert '"status":"NANO_ABSORPTION_SELL_WATCH"' in caplog.text


def test_signal_json_deduplicates_same_event(caplog):
    emitter = SignalJsonEmitter(enabled=True, dedup_ttl_seconds=300)
    event = _event()

    assert emitter.emit(event) is True
    assert emitter.emit(event) is False
    assert caplog.text.count("[SignalJSON]") == 1


def test_do_not_emit_when_market_context_false():
    assert should_emit_signal_json(_event(market_context_applied=False)) is False


def test_do_not_emit_valid_signal_without_rr():
    assert should_emit_signal_json(_event(status="SELL_TIMING_VALID", rr_status="UNVALIDATED")) is False


def test_build_signal_json_event_from_counter_entry_payload():
    payload = _event().to_dict()

    event = build_signal_json_event(payload)

    assert event is not None
    assert event.symbol == "USDCAD"
    assert event.status == "NANO_ABSORPTION_SELL_WATCH"
    assert event.entry_reference_price == 1.37696
    assert event.signal_family == "MICROBOOST_COUNTER_ENTRY"
    assert event.validated_direction == "SELL"
