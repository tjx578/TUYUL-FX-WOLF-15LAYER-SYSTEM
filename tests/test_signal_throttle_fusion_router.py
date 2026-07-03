from __future__ import annotations

from analysis.signal_throttle_fusion_router import build_signal_throttle_fusion_v3_diagnostic


def test_fusion_v3_missing_direction_emits_pure_radar_only():
    diagnostic = build_signal_throttle_fusion_v3_diagnostic(
        {
            "symbol": "USDJPY",
            "events": 14,
            "raw_pressure_direction": "NONE",
            "source_pressure_block_id": "USDJPY_20260701T000000Z_20260701T001000Z",
        },
        radar_context_validation={"radar_context_ready": True},
        execution_context_validation={"direction_validated": False, "final_direction": "WAIT"},
        microboost_summary={},
    )

    assert diagnostic["status"] == "PURE_RADAR_ONLY"
    assert diagnostic["pressure_seen"] is True
    assert diagnostic["final_direction"] == "WAIT"
    assert diagnostic["valid_for_execution"] is False
    assert diagnostic["execution_valid_now"] is False
    assert diagnostic["is_final_signal"] is False


def test_fusion_v3_never_turns_ready_context_into_execution_signal():
    diagnostic = build_signal_throttle_fusion_v3_diagnostic(
        {"symbol": "USDJPY", "events": 14, "raw_pressure_direction": "BUY"},
        radar_context_validation={"radar_context_ready": True},
        execution_context_validation={"direction_validated": True, "final_direction": "BUY"},
        microboost_summary={"latest": {"symbol": "USDJPY"}},
    )

    assert diagnostic["status"] == "CLEAN_BLOCK_WATCH_PENDING_EXECUTION_FIREWALL"
    assert diagnostic["next_stage"] == "SIGNALJSON_GATE"
    assert diagnostic["valid_for_execution"] is False
    assert diagnostic["execution_tier"] == "WAIT"
