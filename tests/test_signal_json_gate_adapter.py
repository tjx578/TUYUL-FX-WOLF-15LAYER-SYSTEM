from __future__ import annotations

import logging

from analysis.signal_execution_gates import evaluate_signal_execution_gates
from analysis.signal_json_emitter import SignalJsonEmitter, build_signal_json_event
from analysis.signal_json_gate_adapter import SignalJsonGateAdapter, SignalJsonGateConfig


def _final_payload(**overrides):
    payload = {
        "event": "signal_json",
        "schema_version": "1.0",
        "symbol": "USDCAD",
        "signal_family": "MICROBOOST_COUNTER_ENTRY",
        "status": "BUY_BREAKOUT_CONTINUATION_VALID",
        "raw_direction": "BUY",
        "candidate_direction": "BUY",
        "validated_direction": "BUY",
        "final_direction": "BUY",
        "action": "BUY_BREAKOUT_RETEST",
        "signal_valid_time_utc": "2026-05-21T07:20:59+00:00",
        "signal_valid_time_wita": "2026-05-21 15:20:59",
        "signal_valid_price": 1.2000,
        "entry_reference_price": 1.2000,
        "entry_zone": [1.2000, 1.2000],
        "price_position": "MAIN_RESISTANCE",
        "m15_phase": "BULLISH_PULLBACK",
        "h1_phase": "BULLISH",
        "phase_unpriced": "DENSE_MICROBOOST",
        "phase_priced": "TREND_CONTINUATION_MICROBOOST",
        "sl_tight": 1.1988,
        "sl_safe": 1.1980,
        "selected_sl": 1.1980,
        "tp1": 1.2020,
        "tp2": 1.2040,
        "tp3": 1.2060,
        "tp_min_rr": 1.2060,
        "tp_min_rr_value": 2.5,
        "tp1_rr": 1.0,
        "tp2_rr": 2.0,
        "tp3_rr": 3.0,
        "rr_status": "VALID",
        "market_context_applied": True,
        "target_mode": "FINAL_MARKET_STRUCTURE",
        "valid_for_execution": True,
        "min_rr_required": 2.5,
        "key_support": 1.1980,
        "key_resistance": 1.2060,
        "structure_zones": {"key_support": 1.1980, "key_resistance": 1.2060},
        "targets": [{"id": "TP2", "type": "STRUCTURE_TARGET", "level": 1.2060, "rr": 3.0}],
        "execution_quality": {"spread_normal": True},
        "bid": 1.20009,
        "ask": 1.20011,
        "reason": "test final candidate",
    }
    payload.update(overrides)
    return payload


def test_execution_gate_allows_complete_structure_payload():
    decision = evaluate_signal_execution_gates(_final_payload())

    assert decision.decision == "ALLOW"
    assert decision.execution_status == "EXECUTION_GATE_ALLOWED"
    assert decision.live_rr is not None
    assert decision.live_rr["rr"] >= 2.5


def test_gate_adapter_disabled_is_strict_noop(caplog):
    caplog.set_level(logging.WARNING, logger="signal_json")
    payload = _final_payload(target_mode="PROVISIONAL_RR_FALLBACK", targets=[])
    adapter = SignalJsonGateAdapter(SignalJsonGateConfig(enabled=False, enforce=False))

    assert adapter.apply(payload) is payload
    assert "[SignalExecutionGateJSON]" not in caplog.text


def test_gate_adapter_from_env_defaults_to_official_enforce_barrier():
    adapter = SignalJsonGateAdapter.from_env({})

    assert adapter.config.final_barrier is True
    assert adapter.config.enabled is True
    assert adapter.config.enforce is True
    assert adapter.config.emit_continuation is True


def test_removed_rr_fallback_env_cannot_bypass_execution_contract():
    adapter = SignalJsonGateAdapter.from_env({"SIGNAL_JSON_RR_FALLBACK_VALIDATES_SIGNAL": "true"})

    gated = adapter.apply(
        _final_payload(
            target_mode="PROVISIONAL_RR_FALLBACK",
            targets=[],
            targets_execution_usable=True,
        )
    )

    assert gated["event"] == "signal_decision_update_json"
    assert gated["valid_for_execution"] is False


def test_official_final_barrier_overrides_legacy_shadow_flags():
    adapter = SignalJsonGateAdapter.from_env(
        {
            "SIGNAL_JSON_EXEC_GATES_ENABLED": "false",
            "SIGNAL_JSON_EXEC_GATES_ENFORCE": "false",
        }
    )

    assert adapter.config.final_barrier is True
    assert adapter.config.enabled is True
    assert adapter.config.enforce is True


def test_final_barrier_can_be_disabled_for_explicit_shadow_mode():
    adapter = SignalJsonGateAdapter.from_env(
        {
            "SIGNAL_JSON_FINAL_BARRIER_ENABLED": "false",
            "SIGNAL_JSON_EXEC_GATES_ENABLED": "true",
            "SIGNAL_JSON_EXEC_GATES_ENFORCE": "false",
        }
    )

    assert adapter.config.final_barrier is False
    assert adapter.config.enabled is True
    assert adapter.config.enforce is False


def test_continuation_emission_can_be_disabled_explicitly():
    adapter = SignalJsonGateAdapter.from_env({"SIGNAL_JSON_EXEC_GATES_EMIT_CONTINUATION": "false"})

    assert adapter.config.emit_continuation is False


def test_gate_adapter_shadow_logs_sidecar_without_changing_signal(caplog):
    caplog.set_level(logging.WARNING, logger="signal_json")
    payload = _final_payload(target_mode="PROVISIONAL_RR_FALLBACK", targets=[], tp_min_rr=1.2070)
    adapter = SignalJsonGateAdapter(SignalJsonGateConfig(enabled=True, enforce=False))
    emitter = SignalJsonEmitter(enabled=True)

    gated = adapter.apply(payload)
    event = build_signal_json_event(gated)

    assert gated is payload
    assert event is not None
    assert emitter.emit(event) is True
    assert "[SignalExecutionGateJSON]" in caplog.text
    assert '"enforcement_mode":"SHADOW"' in caplog.text
    assert '"decision":"BLOCK"' in caplog.text  # Patch 3: PROVISIONAL_RR_FALLBACK is a hard BLOCK
    assert "[SignalDecisionUpdateJSON]" in caplog.text
    assert "[SignalJSON]" not in caplog.text


def test_gate_adapter_enforce_hard_blocks_provisional_rr_final(caplog):
    """Patch 3: a PROVISIONAL_RR_FALLBACK final is a hard BLOCK (was DEFER) -- it becomes a
    blocked terminal decision update, never executable, never a SignalJSON."""
    caplog.set_level(logging.WARNING, logger="signal_json")
    payload = _final_payload(target_mode="PROVISIONAL_RR_FALLBACK", targets=[], bid=None, ask=None)
    adapter = SignalJsonGateAdapter(SignalJsonGateConfig(enabled=True, enforce=True))
    emitter = SignalJsonEmitter(enabled=True)

    gated = adapter.apply(payload)
    event = build_signal_json_event(gated)

    assert gated["event"] == "signal_decision_update_json"
    assert gated["status"] == "WAIT_STRUCTURE_OR_NEXT_M15"
    assert gated["final_direction"] == "WAIT"
    assert gated["valid_for_execution"] is False
    assert gated["execution_valid_now"] is False
    assert "PROVISIONAL_RR_FALLBACK_NOT_EXECUTABLE" in gated["reason"]
    assert "PROVISIONAL_RR_FALLBACK_NOT_EXECUTABLE" in gated["audit_block_reasons"]
    assert event is not None
    assert event.is_final_signal is False
    assert emitter.emit(event) is True
    assert "[SignalExecutionGateJSON]" in caplog.text
    assert '"enforcement_mode":"ENFORCE"' in caplog.text
    assert '"decision":"BLOCK"' in caplog.text
    assert "[SignalDecisionUpdateJSON]" in caplog.text
    assert "[SignalJSON]" not in caplog.text


def test_provisional_rr_fallback_is_not_execution_final_by_default():
    payload = _final_payload(
        target_mode="PROVISIONAL_RR_FALLBACK",
        target_source="rr_projection_only",
        targets=[],
        targets_execution_usable=True,
        tradeplan_context_ready=False,
        structure_targets_available=False,
    )
    adapter = SignalJsonGateAdapter(SignalJsonGateConfig(enabled=True, enforce=True, emit_sidecar=False))

    gated = adapter.apply(payload)

    assert gated["event"] == "signal_decision_update_json"
    assert gated["status"] == "WAIT_STRUCTURE_OR_NEXT_M15"
    assert gated["final_direction"] == "WAIT"
    assert gated["valid_for_execution"] is False
    assert gated["execution_valid_now"] is False
    assert "PROVISIONAL_RR_FALLBACK_NOT_EXECUTABLE" in gated["audit_block_reasons"]


def test_provisional_rr_fallback_cannot_pass_with_removed_explicit_policy():
    payload = _final_payload(
        target_mode="PROVISIONAL_RR_FALLBACK",
        target_source="rr_projection_only",
        targets=[],
        targets_execution_usable=True,
        structure_targets_available=False,
    )
    adapter = SignalJsonGateAdapter(SignalJsonGateConfig(enabled=True, enforce=True, emit_sidecar=False))

    gated = adapter.apply(payload)

    assert gated["event"] == "signal_decision_update_json"
    assert gated["final_direction"] == "WAIT"
    assert gated["validated_direction"] == "BUY"
    assert gated["valid_for_execution"] is False
    assert gated["execution_valid_now"] is False


def test_execution_ready_terminal_survives_strict_lifecycle_direct_bypass(caplog):
    payload = _final_payload()
    adapter = SignalJsonGateAdapter(SignalJsonGateConfig(enabled=True, enforce=True, emit_sidecar=False))
    emitter = SignalJsonEmitter(
        enabled=True,
        strict_lifecycle=True,
        require_parent_watch=False,
        allow_direct_bypass=True,
        require_final_market_structure=True,
        require_terminal_decision_update=True,
    )

    gated = adapter.apply(payload)
    event = build_signal_json_event(gated)

    assert gated["status"] == "FINAL_EXECUTION_READY"
    assert gated["promotion_path"] == "DIRECT_BYPASS"
    assert gated["parent_watch_required"] is False
    assert event is not None
    assert emitter.emit(event) is True
    assert "[SignalJSON]" in caplog.text
    assert "[SignalDecisionUpdateJSON]" not in caplog.text


def test_nested_execution_gate_false_overrides_top_level_valid():
    payload = _final_payload(
        tradeplan_valid=True,
        execution_valid_now=False,
        execution_gate={"execution_valid_now": False},
    )
    adapter = SignalJsonGateAdapter(SignalJsonGateConfig(enabled=True, enforce=True, emit_sidecar=False))

    gated = adapter.apply(payload)

    assert gated["event"] == "signal_decision_update_json"
    assert gated["status"] == "FINAL_VALID_EXECUTION_DEFERRED"
    assert gated["final_direction"] == "WAIT"
    assert gated["validated_direction"] == "BUY"
    assert gated["signal_valid"] is True
    assert gated["valid_for_execution"] is False
    assert gated["execution_valid_now"] is False
    assert "EXECUTION_VALID_NOW_FALSE" in gated["audit_block_reasons"]


def test_nzdusd_counter_entry_final_uses_signal_price_when_live_quote_missing(caplog):
    caplog.set_level(logging.WARNING, logger="signal_json")
    payload = _final_payload(
        symbol="NZDUSD",
        signal_family="MICROBOOST_COUNTER_ENTRY",
        status="BUY_TIMING_VALID",
        raw_direction="SELL",
        candidate_direction="BUY",
        validated_direction="BUY",
        final_direction="BUY",
        action="BUY_AT_SIGNAL_VALID_PRICE_OR_RETEST",
        signal_valid_time_utc="2026-06-01T14:50:56.938106+00:00",
        signal_valid_time_wita="2026-06-01 22:50:56",
        signal_valid_price=0.591595,
        entry_reference_price=0.591595,
        entry_zone=[0.59159, 0.59159],
        price_position="MAIN_SUPPORT",
        m15_phase="BULLISH_PULLBACK",
        h1_phase="BEARISH",
        phase_unpriced="REPEATED_MICROBOOST",
        phase_priced="SUPPORT_PRESSURE_WARNING",
        sl_tight=0.59066,
        sl_safe=0.58986,
        selected_sl=0.58986,
        tp1=0.5921,
        tp2=0.59561,
        tp3=0.59693,
        tp4=0.59818,
        tp_min_rr=0.59561,
        tp_min_rr_value=2.5,
        rr_to_valid_target=4.29,
        rr_status="VALID",
        target_mode="STRUCTURE_LADDER_TARGET",
        target_source="support_resistance_ladder",
        tp_status="VALID",
        key_support=0.59162,
        key_resistance=0.59889,
        structure_zones={"key_support": 0.59162, "key_resistance": 0.59889},
        targets=[],
        execution_quality={"spread_normal": True},
        m15_confirmation_status="M15_CLOSE_REJECTION_CONFIRMED",
        market_context_applied=True,
        valid_for_execution=True,
        bid=None,
        ask=None,
        current_price=None,
        last_price=None,
    )
    adapter = SignalJsonGateAdapter.from_env({})
    emitter = SignalJsonEmitter(enabled=True)

    gated = adapter.apply(payload)
    event = build_signal_json_event(gated)

    assert gated["status"] == "FINAL_EXECUTION_READY"
    assert gated["source_status"] == "BUY_TIMING_VALID"
    assert gated["terminal_status"] == "FINAL_EXECUTION_READY"
    assert gated["signal_valid"] is True
    assert gated["direction_valid"] is True
    assert gated["tradeplan_valid"] is True
    assert gated["valid_for_execution"] is True
    assert gated["execution_valid_now"] is True
    assert event is not None
    assert emitter.emit(event) is True
    assert "[SignalExecutionGateJSON]" in caplog.text
    assert '"decision":"ALLOW"' in caplog.text
    assert '"rr":4.29' in caplog.text
    assert "[SignalJSON]" in caplog.text
    assert "[SignalDecisionUpdateJSON]" not in caplog.text


def test_microboost_timing_gate_blocks_late_pressure_entry():
    payload = _final_payload(
        phase_unpriced="REPEATED_MICROBOOST",
        phase_priced="LATE_DENSE_PRESSURE",
        action="PROTECT_PROFIT",
    )

    decision = evaluate_signal_execution_gates(payload)

    assert decision.decision == "BLOCK"
    assert "MicroBoostTimingGate" in decision.blocked_by
    assert "MICROBOOST_NO_NEW_ENTRY_PROTECT_PROFIT" in decision.reasons


def test_microboost_timing_gate_defers_pullback_until_reclaim():
    payload = _final_payload(
        phase_unpriced="REPEATED_MICROBOOST",
        phase_priced="BULLISH_PULLBACK_MICROBOOST",
        action="WAIT_M15_RECLAIM_OR_PULLBACK_COMPLETION",
    )

    decision = evaluate_signal_execution_gates(payload)

    assert decision.decision == "DEFER"
    assert "MicroBoostTimingGate" in decision.blocked_by
    assert "MICROBOOST_WAIT_M15_RECLAIM_OR_PULLBACK_COMPLETION" in decision.reasons

    confirmed = evaluate_signal_execution_gates(
        _final_payload(
            phase_unpriced="REPEATED_MICROBOOST",
            phase_priced="BULLISH_PULLBACK_MICROBOOST",
            action="BUY_SIGNAL_ZONE_OR_RETEST",
            m15_reclaim_confirmed=True,
        )
    )
    assert confirmed.decision == "ALLOW"


def test_microboost_timing_gate_requires_breakout_confirmation_for_pressure_warning():
    payload = _final_payload(
        phase_unpriced="NEAR_TIMING_GATE_MICROBOOST",
        phase_priced="RESISTANCE_PRESSURE_WARNING",
    )

    decision = evaluate_signal_execution_gates(payload)

    assert decision.decision == "DEFER"
    assert "MicroBoostTimingGate" in decision.blocked_by
    assert "MICROBOOST_PRESSURE_WARNING_CONFIRMATION_REQUIRED" in decision.reasons

    confirmed = evaluate_signal_execution_gates(
        _final_payload(
            phase_unpriced="NEAR_TIMING_GATE_MICROBOOST",
            phase_priced="RESISTANCE_PRESSURE_WARNING",
            m15_confirmation_status="M15_CLOSE_ABOVE_RESISTANCE",
        )
    )
    assert confirmed.decision == "ALLOW"


def test_reinforcement_shadow_logs_management_only_without_changing_signal(caplog):
    caplog.set_level(logging.WARNING, logger="signal_json")
    payload = _final_payload(
        lifecycle_status="REINFORCES_ACTIVE_SIGNAL",
        linked_previous_signal="USDCAD_BUY_20260521_152059",
        previous_signal_status="REINFORCED",
        action="HOLD_BUY_OR_BUY_RETEST",
    )
    adapter = SignalJsonGateAdapter(SignalJsonGateConfig(enabled=True, enforce=False))
    emitter = SignalJsonEmitter(enabled=True)

    decision = evaluate_signal_execution_gates(payload)
    gated = adapter.apply(payload)
    event = build_signal_json_event(gated)

    assert decision.decision == "DEFER"
    assert "ReinforcementManagementGate" in decision.blocked_by
    assert "REINFORCEMENT_MANAGEMENT_ONLY" in decision.reasons
    assert gated is payload
    assert event is not None
    assert emitter.emit(event) is True
    assert "[SignalExecutionGateJSON]" in caplog.text
    assert '"enforcement_mode":"SHADOW"' in caplog.text
    assert '"REINFORCEMENT_MANAGEMENT_ONLY"' in caplog.text
    assert "[SignalDecisionUpdateJSON]" in caplog.text
    assert "[SignalJSON]" not in caplog.text


def test_reinforcement_enforce_emits_management_only_terminal_signal(caplog):
    caplog.set_level(logging.WARNING, logger="signal_json")
    payload = _final_payload(
        lifecycle_status="REINFORCES_ACTIVE_SIGNAL",
        linked_previous_signal="USDCAD_BUY_20260521_152059",
        previous_signal_status="REINFORCED",
        action="HOLD_BUY_OR_BUY_RETEST",
    )
    adapter = SignalJsonGateAdapter(SignalJsonGateConfig(enabled=True, enforce=True))
    emitter = SignalJsonEmitter(enabled=True)

    gated = adapter.apply(payload)
    event = build_signal_json_event(gated)

    assert gated["event"] == "signal_decision_update_json"
    assert gated["status"] == "FINAL_VALID_MANAGEMENT_ONLY"
    assert gated["terminal_status"] == "FINAL_VALID_MANAGEMENT_ONLY"
    assert gated["final_direction"] == "WAIT"
    assert gated["validated_direction"] == "BUY"
    assert gated["signal_valid"] is True
    assert gated["direction_valid"] is True
    assert gated["valid_for_execution"] is False
    assert gated["execution_valid_now"] is False
    assert gated["execution_status"] == "REINFORCEMENT_MANAGEMENT_ONLY"
    assert gated["action"] == "HOLD_TRAIL_OR_ADD_ONLY_ON_RETEST"
    assert gated["next_action"] == "MANAGE_ACTIVE_SIGNAL_OR_WAIT_RETEST"
    assert "REINFORCEMENT_MANAGEMENT_ONLY" in gated["audit_block_reasons"]
    assert event is not None
    assert emitter.emit(event) is True
    assert "[SignalExecutionGateJSON]" in caplog.text
    assert '"enforcement_mode":"ENFORCE"' in caplog.text
    assert "[SignalDecisionUpdateJSON]" in caplog.text
    assert "[SignalJSON]" not in caplog.text


def test_reinforcement_add_on_retest_ready_can_pass_gate():
    payload = _final_payload(
        lifecycle_status="REINFORCES_ACTIVE_SIGNAL",
        linked_previous_signal="USDCAD_BUY_20260521_152059",
        add_position_allowed=True,
        add_on_retest_ready=True,
    )

    decision = evaluate_signal_execution_gates(payload)

    assert decision.decision == "ALLOW"
