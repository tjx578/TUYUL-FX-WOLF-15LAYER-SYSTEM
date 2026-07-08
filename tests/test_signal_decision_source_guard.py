from __future__ import annotations

from analysis.signal_decision_source_guard import (
    can_emit_signal_decision,
    route_decision_or_pressure,
)


def test_signal_throttle_pressure_routes_to_pressure_state():
    payload = {
        "source_stage": "SIGNAL_THROTTLE_INTEL",
        "symbol": "USDCAD",
        "signal_family": "SIGNAL_THROTTLE_PRESSURE",
        "pressure_seen": True,
        "allowed_quorum_seen": True,
    }

    routed = route_decision_or_pressure(payload)

    assert routed.route == "SIGNAL_PRESSURE_STATE"
    assert routed.can_emit_signal_decision is False
    assert routed.payload["event"] == "signal_pressure_state_json"
    assert routed.payload["eligible_for_signal_decision"] is False
    assert routed.payload["valid_for_execution"] is False
    assert routed.payload["execution_valid_now"] is False
    assert routed.payload["is_final_signal"] is False
    assert routed.payload["signal_valid"] is False
    assert routed.payload["tradeplan_valid"] is False


def test_signal_watch_can_emit_signal_decision():
    payload = {
        "source_stage": "SIGNAL_WATCH",
        "source_watch_id": "USDCAD_20260625T120000Z",
        "symbol": "USDCAD",
        "status": "WAIT_M15_CONFIRMATION",
    }

    assert can_emit_signal_decision(payload) is True
    assert route_decision_or_pressure(payload).route == "SIGNAL_DECISION_UPDATE"


def test_block_finalizer_can_emit_signal_decision():
    payload = {
        "source_stage": "BLOCK_FINALIZER",
        "source_clean_block_id": "USDCAD_BLOCK_001",
        "symbol": "USDCAD",
        "status": "WAIT_STRUCTURE_OR_NEXT_M15",
    }

    assert route_decision_or_pressure(payload).route == "SIGNAL_DECISION_UPDATE"


def test_execution_gate_block_can_emit_signal_decision():
    payload = {
        "source_stage": "EXECUTION_GATE",
        "pending_decision_id": "USDCAD_PENDING_001",
        "symbol": "USDCAD",
        "status": "EXECUTION_GATE_BLOCKED",
        "block_reason": "PROVISIONAL_RR_FALLBACK_NOT_EXECUTABLE",
    }

    assert route_decision_or_pressure(payload).route == "SIGNAL_DECISION_UPDATE"


def test_allowed_source_without_anchor_routes_to_pressure_state_when_required():
    payload = {
        "source_stage": "SIGNAL_WATCH",
        "symbol": "USDCAD",
        "status": "WAIT_M15_CONFIRMATION",
    }

    routed = route_decision_or_pressure(payload, require_lifecycle_anchor=True)

    assert routed.route == "SIGNAL_PRESSURE_STATE"
    assert routed.reason == "missing_lifecycle_anchor"
