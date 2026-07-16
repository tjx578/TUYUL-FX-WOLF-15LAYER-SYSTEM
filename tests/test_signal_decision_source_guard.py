from __future__ import annotations

from analysis.signal_decision_source_guard import (
    can_emit_signal_decision,
    convert_to_signal_pressure_state,
    route_decision_or_pressure,
)


def test_signal_throttle_pressure_routes_to_pressure_state(monkeypatch):
    monkeypatch.setenv("RAILWAY_DEPLOYMENT_ID", "deploy-guard")
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "commit-guard")
    monkeypatch.setenv("RAILWAY_REPLICA_ID", "replica-guard")
    payload = {
        "source_stage": "SIGNAL_THROTTLE_INTEL",
        "symbol": "USDCAD",
        "signal_family": "SIGNAL_THROTTLE_PRESSURE",
        "pressure_seen": True,
        "allowed_quorum_seen": True,
        "htf_structure_context": {
            "price_location": "PREMIUM",
            "liquidity_resolution": "BUY_SIDE_TESTING",
        },
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
    assert routed.payload["deployment_id"] == "deploy-guard"
    assert routed.payload["commit_sha"] == "commit-guard"
    assert routed.payload["replica_id"] == "replica-guard"
    assert routed.payload["schema_version"] == "2.0-pressure-state"
    assert routed.payload["schema_contract_complete"] is True
    assert routed.payload["observed_price"] is None
    assert routed.payload["reference_price"] is None
    assert routed.payload["reference_price_status"] == "MISSING"
    assert routed.payload["structural_price_location"] == "PREMIUM"
    assert routed.payload["price_location"] == "UNKNOWN"
    assert routed.payload["raw_direction_direct_entry_eligible"] is False
    assert routed.payload["raw_direction_swing_eligible"] is False
    assert routed.payload["strategy_5scr_required"] is True
    assert routed.payload["context_version"].startswith("pressure-context-v2:")


def test_pressure_contract_resolves_direction_but_never_promotes_raw_pressure():
    payload = convert_to_signal_pressure_state(
        {
            "source_stage": "SIGNAL_THROTTLE_INTEL",
            "symbol": "NZDCAD",
            "cluster_id": "NZDCAD_CLUSTER_1",
            "signal_family": "SIGNAL_THROTTLE_PRESSURE",
            "raw_direction": "BUY",
            "reference_price_used_for_decision_update": 0.81234,
            "price_source": "LIVE_TICK_MID",
            "price_snapshot_time_utc": "2026-07-16T01:00:00+00:00",
            "price_age_seconds": 1.25,
            "price_freshness_status": "LIVE",
            "reference_price_is_live": True,
            "htf_structure_context": {
                "price_location": "PREMIUM",
                "liquidity_resolution": "BUY_SIDE_ACCEPTED",
            },
        }
    )

    assert payload["observed_price"] == 0.81234
    assert payload["observed_price_source"] == "LIVE_TICK_MID"
    assert payload["observed_price_time"] == "2026-07-16T01:00:00+00:00"
    assert payload["reference_price"] == 0.81234
    assert payload["reference_price_status"] == "LIVE"
    assert payload["price_location"] == "PREMIUM"
    assert payload["pressure_direction_resolution"] == "ACCEPTED"
    assert payload["pressure_resolution_direction"] == "BUY"
    assert payload["raw_direction_direct_entry_eligible"] is False
    assert payload["raw_direction_swing_eligible"] is False
    assert payload["final_direction"] == "WAIT"
    assert payload["valid_for_execution"] is False


def test_pressure_contract_expires_raw_direction_before_swing_horizon(monkeypatch):
    monkeypatch.setenv("SIGNAL_PRESSURE_RAW_DIRECTION_MAX_AGE_SECONDS", "14400")

    payload = convert_to_signal_pressure_state(
        {
            "source_stage": "SIGNAL_THROTTLE_INTEL",
            "symbol": "NZDCHF",
            "raw_direction": "BUY",
            "signal_valid_time_utc": "2020-01-01T00:00:00Z",
            "htf_structure_context": {"liquidity_resolution": "BUY_SIDE_ACCEPTED"},
        }
    )

    assert payload["raw_direction_status"] == "STALE"
    assert payload["pressure_direction_resolution"] == "EXPIRED"
    assert payload["pressure_resolution_direction"] is None
    assert payload["raw_direction_24h_eligible"] is False


def test_pressure_context_version_ignores_age_only_changes():
    base = {
        "source_stage": "SIGNAL_THROTTLE_INTEL",
        "symbol": "NZDCAD",
        "cluster_id": "NZDCAD_CLUSTER_2",
        "raw_direction": "BUY",
        "htf_structure_context": {
            "daily_bias": "BULLISH",
            "daily_bias_source_candle": "2026-07-15T00:00:00+00:00",
            "daily_bias_freshness_status": "FRESH",
            "daily_bias_snapshot_time": "2026-07-16T01:00:00+00:00",
            "daily_bias_age_seconds": 90_000.0,
            "liquidity_resolution": "BUY_SIDE_TESTING",
        },
    }
    later = {
        **base,
        "htf_structure_context": {
            **base["htf_structure_context"],
            "daily_bias_snapshot_time": "2026-07-16T01:01:00+00:00",
            "daily_bias_age_seconds": 90_060.0,
        },
    }

    first = convert_to_signal_pressure_state(base)
    second = convert_to_signal_pressure_state(later)

    assert first["context_version"] == second["context_version"]


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
