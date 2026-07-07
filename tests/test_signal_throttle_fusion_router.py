from __future__ import annotations

import logging

from analysis.signal_throttle_fusion_router import (
    build_signal_throttle_fusion_v3_diagnostic,
    emit_signal_throttle_fusion_v3_diagnostic,
)


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
    assert diagnostic["block_type"] == "PURE_PRESSURE_BLOCK"
    assert diagnostic["raw_pressure_direction"] is None
    assert diagnostic["direction_status"] == "UNRESOLVED"
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


def test_fusion_v3_diagnostic_shape_matches_pure_block_contract():
    diagnostic = build_signal_throttle_fusion_v3_diagnostic(
        {
            "symbol": "USDJPY",
            "events": 105,
            "block_start_utc": "2026-04-30T03:16:31+00:00",
            "block_end_utc": "2026-04-30T05:27:57+00:00",
            "duration_minutes": 131.44,
            "density_per_minute": 0.80,
            "max_gap_seconds": 3775.56,
            "gap_split_applied": False,
            "split_rule": "PAIR_ROTATION_ONLY",
            "pure_pressure_score": 92,
            "heat_score": 38,
            "pressure_class": "LONG_CONTEXTUAL_RADAR",
            "raw_pressure_direction": "NONE",
            "source_pressure_block_id": "USDJPY_20260430T031631Z_20260430T052757Z",
        },
        radar_context_validation={"radar_context_ready": False},
        execution_context_validation={"direction_validated": False, "final_direction": "WAIT"},
        microboost_summary={},
    )

    assert diagnostic["event"] == "signal_throttle_fusion_v3"
    assert diagnostic["block_type"] == "PURE_PRESSURE_BLOCK"
    assert diagnostic["block_id"] == "USDJPY_20260430T031631Z_20260430T052757Z"
    assert diagnostic["start_ts"] == "2026-04-30T03:16:31+00:00"
    assert diagnostic["end_ts"] == "2026-04-30T05:27:57+00:00"
    assert diagnostic["duration_minutes"] == 131.44
    assert diagnostic["event_count"] == 105
    assert diagnostic["density_per_minute"] == 0.8
    assert diagnostic["max_gap_seconds"] == 3775.56
    assert diagnostic["gap_split_applied"] is False
    assert diagnostic["split_rule"] == "PAIR_ROTATION_ONLY"
    assert diagnostic["pure_pressure_score"] == 92.0
    assert diagnostic["heat_score"] == 38.0
    assert diagnostic["pressure_class"] == "LONG_CONTEXTUAL_RADAR"
    assert diagnostic["direction_status"] == "UNRESOLVED"
    assert diagnostic["market_structure_status"] == "PENDING"
    assert diagnostic["next_stage"] == "SIGNAL_WATCH"
    assert diagnostic["valid_for_execution"] is False


def test_fusion_v3_emits_on_dedicated_logger_only(caplog):
    caplog.set_level(logging.WARNING, logger="signal_json")
    caplog.set_level(logging.WARNING, logger="signal_throttle_observability")
    caplog.set_level(logging.WARNING, logger="signal_throttle_fusion_v3")
    diagnostic = build_signal_throttle_fusion_v3_diagnostic(
        {"symbol": "USDJPY", "events": 14, "raw_pressure_direction": "NONE"},
        radar_context_validation={"radar_context_ready": True},
        execution_context_validation={"direction_validated": False, "final_direction": "WAIT"},
        microboost_summary={},
    )

    assert emit_signal_throttle_fusion_v3_diagnostic(diagnostic) is True

    fusion_records = [record for record in caplog.records if record.name == "signal_throttle_fusion_v3"]
    signal_json_records = [record for record in caplog.records if record.name == "signal_json"]
    observability_records = [record for record in caplog.records if record.name == "signal_throttle_observability"]
    assert fusion_records
    assert "[SignalThrottleFusionV3]" in fusion_records[0].getMessage()
    assert '"event":"signal_throttle_fusion_v3"' in fusion_records[0].getMessage()
    assert not signal_json_records
    assert not observability_records
