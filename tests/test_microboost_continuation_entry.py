from __future__ import annotations

from analysis.microboost_continuation_entry import MicroboostContinuationEngine
from analysis.signal_execution_gates import evaluate_signal_execution_gates
from analysis.signal_json_emitter import SignalJsonEmitter, build_signal_json_event, should_emit_signal_json
from analysis.signal_json_gate_adapter import SignalJsonGateAdapter, SignalJsonGateConfig


def _cluster(**overrides):
    payload = {
        "cluster_id": "USDCAD_20260520T024532Z",
        "symbol": "USDCAD",
        "direction": "BUY",
        "phase_unpriced": "IGNITION_MICROBOOST",
        "phase_priced": "TREND_CONTINUATION_MICROBOOST",
        "effective_density_per_minute": 31.68,
        "effective_tick_count": 11,
        "duration_seconds": 20.833,
        "start_utc": "2026-05-20T02:45:32+00:00",
        "end_utc": "2026-05-20T02:45:52+00:00",
        "price_position": "MID_RANGE",
        "market_context_snapshot": {
            "symbol": "USDCAD",
            "raw_allowed_direction": "BUY",
            "pip_value": 0.0001,
            "price_at_signal_start": 1.37560,
            "price_at_5m_confirm": 1.375675,
            "price_at_signal_end": 1.375675,
            "m15_phase": "BULLISH_PULLBACK",
            "h1_phase": "BULLISH",
            "theme_aligned": True,
            "spread_normal": True,
            "price_position": "MID_RANGE",
            "main_support": 1.3720,
            "main_resistance": 1.3850,
            "minor_resistance": 1.3785,
            "tp1_resistance": 1.3785,
            "tp2_resistance": 1.3810,
            "tp3_resistance": 1.3850,
        },
    }
    payload.update(overrides)
    return payload


def _quorum(**overrides):
    payload = {
        "symbol": "USDCAD",
        "direction": "BUY",
        "streak": 3,
        "quorum_size": 3,
        "quorum_reached": True,
    }
    payload.update(overrides)
    return payload


def test_usdcad_short_mid_range_quorum_microboost_is_not_continuation_signal():
    result = MicroboostContinuationEngine().evaluate(_cluster(), allowed_quorum=_quorum())

    assert result.enabled is False
    assert result.status == "NONE"
    assert result.final_direction == "WAIT"
    assert result.action == "NO_CONTINUATION_ENTRY"


def test_usdcad_mid_range_quorum_microboost_after_one_minute_becomes_buy_continuation_valid():
    result = MicroboostContinuationEngine().evaluate(
        _cluster(
            duration_seconds=62.0,
            effective_tick_count=32,
            end_utc="2026-05-20T02:46:34+00:00",
        ),
        allowed_quorum=_quorum(),
    )

    assert result.enabled is True
    assert result.status == "BUY_TIMING_VALID_BY_QUORUM_CONTINUATION"
    assert result.signal_family == "MICROBOOST_TREND_CONTINUATION"
    assert result.validated_direction == "BUY"
    assert result.final_direction == "BUY"
    assert result.action == "BUY_SIGNAL_ZONE_OR_RETEST"
    assert result.direction_status == "MICROBOOST_QUORUM_CONTINUATION_VALIDATED"
    assert result.allowed_quorum is True
    assert result.signal_valid_price == 1.375675
    assert result.entry_zone == [1.3756, 1.37567]
    assert result.sl_safe == 1.3712
    assert result.tp1 == 1.3785
    assert result.tp2 == 1.381
    assert result.tp3 == 1.385
    assert result.rr_status == "VALID"
    assert result.target_mode == "FINAL_MARKET_STRUCTURE"
    assert result.valid_for_execution is True
    assert result.rr_to_tp3_tight is not None
    assert result.min_rr_required is not None
    assert result.rr_to_tp3_tight >= result.min_rr_required
    assert result.key_support == 1.3720
    assert result.key_resistance == 1.3850
    assert result.structure_zones == {
        "price_position": "MID_RANGE",
        "entry_zone": [1.3756, 1.37567],
        "key_support": 1.3720,
        "key_resistance": 1.3850,
        "range_low": 1.3720,
        "range_high": 1.3850,
    }
    assert result.execution_quality == {
        "spread_normal": True,
        "spread_pips": None,
        "max_allowed_spread_pips": None,
    }
    assert result.rr_to_valid_target is not None
    assert result.min_rr_required is not None
    assert result.rr_to_valid_target >= result.min_rr_required
    assert result.promotion_path is None
    assert result.direct_valid_reason is None
    assert result.parent_watch_required is True

    gate_decision = evaluate_signal_execution_gates(result.to_dict())
    assert gate_decision.decision == "ALLOW"


def test_continuation_ignores_unready_or_opposite_quorum():
    result = MicroboostContinuationEngine().evaluate(
        _cluster(),
        allowed_quorum=_quorum(direction="SELL", quorum_reached=True),
    )

    assert result.enabled is False
    assert result.status == "NONE"
    assert result.final_direction == "WAIT"


def test_continuation_fallback_targets_wait_for_structure_or_retest():
    cluster = _cluster(
        duration_seconds=62.0,
        effective_tick_count=32,
        end_utc="2026-05-20T02:46:34+00:00",
        market_context_snapshot={
            "symbol": "USDCAD",
            "raw_allowed_direction": "BUY",
            "pip_value": 0.0001,
            "price_at_signal_start": 1.37560,
            "price_at_5m_confirm": 1.375675,
            "price_at_signal_end": 1.375675,
            "m15_phase": "BULLISH_PULLBACK",
            "h1_phase": "BULLISH",
            "price_position": "MID_RANGE",
        },
    )

    result = MicroboostContinuationEngine().evaluate(cluster, allowed_quorum=_quorum())

    assert result.enabled is True
    assert result.status == "WAIT_M15_CLOSE_OR_STRUCTURE_TARGET"
    assert result.final_direction == "WAIT"
    assert result.action == "WAIT_STRUCTURE_TARGET_OR_RETEST"
    assert result.direction_status == "MICROBOOST_QUORUM_CONTINUATION_AWAITS_STRUCTURE_TARGET"
    assert result.target_mode == "PROVISIONAL_RR_FALLBACK"
    assert result.rr_status == "WAIT_TARGET_STRUCTURE"
    assert result.valid_for_execution is False
    assert result.tradeplan_context_ready is False
    assert result.sl_safe == 1.3736
    assert result.tp1_rr == 1.5
    assert result.tp2_rr == 2.5
    assert result.tp3_rr == 3.5
    assert result.rr_to_valid_target is None
    assert result.promotion_path is None
    assert result.direct_valid_reason is None
    assert result.parent_watch_required is False

    event = build_signal_json_event(result.to_dict())
    assert event is not None
    assert event.event == "signal_decision_update_json"
    assert event.is_final_signal is False
    assert should_emit_signal_json(event) is True


def test_continuation_fallback_terminalizes_as_valid_wait_structure(caplog):
    cluster = _cluster(
        duration_seconds=62.0,
        effective_tick_count=32,
        end_utc="2026-05-20T02:46:34+00:00",
        market_context_snapshot={
            "symbol": "USDCAD",
            "raw_allowed_direction": "BUY",
            "pip_value": 0.0001,
            "price_at_signal_start": 1.37560,
            "price_at_5m_confirm": 1.375675,
            "price_at_signal_end": 1.375675,
            "m15_phase": "BULLISH_PULLBACK",
            "h1_phase": "BULLISH",
            "price_position": "MID_RANGE",
        },
    )
    result = MicroboostContinuationEngine().evaluate(cluster, allowed_quorum=_quorum())
    adapter = SignalJsonGateAdapter(SignalJsonGateConfig(enabled=True, enforce=True, emit_sidecar=False))
    emitter = SignalJsonEmitter(enabled=True)

    gated = adapter.apply(result.to_dict())
    event = build_signal_json_event(gated)

    assert gated["status"] == "FINAL_VALID_WAIT_STRUCTURE_TARGET"
    assert gated["source_status"] == "WAIT_M15_CLOSE_OR_STRUCTURE_TARGET"
    # Role contract: a deferred-but-valid continuation keeps its direction in
    # validated_direction / watch_direction, but final_direction stays WAIT — a
    # non-executable signal must never surface an actionable BUY/SELL. It
    # terminalizes as a SignalDecisionUpdateJSON (terminal bridge), not a
    # [SignalJSON], because execution_valid_now is False.
    assert gated["final_direction"] == "WAIT"
    assert gated["validated_direction"] == "BUY"
    assert gated["watch_direction"] == "BUY"
    assert gated["signal_valid"] is True
    assert gated["direction_valid"] is True
    assert gated["tradeplan_valid"] is False
    assert gated["valid_for_execution"] is False
    assert gated["execution_valid_now"] is False
    assert event is not None
    assert event.event == "signal_decision_update_json"
    assert event.is_final_signal is False
    assert should_emit_signal_json(event) is True
    assert emitter.emit(event) is True
    assert "[SignalDecisionUpdateJSON]" in caplog.text
    assert "[SignalJSON]" not in caplog.text


def test_schema_v1_continuation_retains_provisional_rr_ladder():
    cluster = _cluster(
        duration_seconds=62.0,
        market_context_snapshot={
            **_cluster()["market_context_snapshot"],
            "main_resistance": None,
            "minor_resistance": None,
            "tp1_resistance": None,
            "tp2_resistance": None,
            "tp3_resistance": None,
        },
    )

    result = MicroboostContinuationEngine(tp1_rr_required=1.0).evaluate(cluster, allowed_quorum=_quorum())

    assert result.status == "WAIT_M15_CLOSE_OR_STRUCTURE_TARGET"
    assert result.valid_for_execution is False
    assert result.rr_status == "WAIT_TARGET_STRUCTURE"
    assert result.tp1_rr == 1.5
