from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from analysis.source_lineage_guard import (
    emit_signal_throttle_state_snapshot,
    emit_source_guard_diagnostic,
    guard_microboost_source,
    signal_throttle_state_snapshot_payload,
    signal_watch_source_diagnostic,
    source_freshness_state,
)


def _report(*, age_seconds=60.0, source_clean_block_id="USDCAD_BLOCK_1", end_age_seconds=30.0):
    now = datetime(2026, 6, 26, 4, 0, tzinfo=UTC)
    latest_seen = now - timedelta(seconds=age_seconds)
    micro_end = now - timedelta(seconds=end_age_seconds)
    return {
        "counts": {"total_events": 24},
        "symbol_activity": {
            "USDCAD": {
                "latest_event_utc": latest_seen.isoformat(),
                "idle_seconds": age_seconds,
            }
        },
        "clean_watch_candidates": [
            {
                "symbol": "USDCAD",
                "source_clean_block_id": "USDCAD_BLOCK_1",
                "clean_block_end_utc": micro_end.isoformat(),
            }
        ],
        "microboost_summary": {
            "count_total": 1,
            "latest": {
                "symbol": "USDCAD",
                "cluster_id": "USDCAD_20260626T035930Z",
                "phase_unpriced": "NEAR_TIMING_GATE_MICROBOOST",
                "end_utc": micro_end.isoformat(),
                "source_clean_block_id": source_clean_block_id,
            },
        },
    }, now


def test_source_freshness_state_flags_stale_symbol():
    report, now = _report(age_seconds=360.0)

    state = source_freshness_state(report, "USDCAD", now=now, max_age_seconds=300)

    assert state.fresh_signal_throttle_seen is False
    assert state.reason == "STALE_SIGNAL_THROTTLE_SOURCE"
    assert state.source_age_seconds == 360.0


def test_microboost_source_guard_requires_source_clean_block_id():
    report, now = _report(source_clean_block_id=None)

    result = guard_microboost_source(report, now=now, max_age_seconds=300)

    assert result.can_emit_microboost is False
    assert result.diagnostics[0]["event"] == "microboost_source_diagnostic"
    assert "SOURCE_CLEAN_BLOCK_ID_MISSING" in result.diagnostics[0]["blocked_by"]


def test_microboost_source_guard_rejects_cross_pair_clean_block_id():
    report, now = _report(source_clean_block_id="AUDCAD_20260708T093150Z_20260708T093801Z")

    result = guard_microboost_source(report, now=now, max_age_seconds=300)

    assert result.can_emit_microboost is False
    assert result.diagnostics[0]["event"] == "microboost_source_diagnostic"
    assert result.diagnostics[0]["blocked_by"] == ["SOURCE_CLEAN_BLOCK_SYMBOL_MISMATCH"]
    assert result.diagnostics[0]["source_clean_block_symbol"] == "AUDCAD"


def test_microboost_source_guard_blocks_stale_cluster():
    report, now = _report(end_age_seconds=420.0)

    result = guard_microboost_source(report, now=now, max_age_seconds=300)

    assert result.can_emit_microboost is False
    assert {diag["event"] for diag in result.diagnostics} == {"microboost_stale_diagnostic"}


def test_microboost_source_guard_separates_source_freshness_from_active_timing():
    report, now = _report(age_seconds=5.0, end_age_seconds=150.0)

    result = guard_microboost_source(
        report,
        now=now,
        max_age_seconds=300,
        microboost_active_timing_max_age_seconds=120,
    )

    assert result.can_emit_microboost is False
    diagnostic = result.diagnostics[0]
    assert diagnostic["event"] == "microboost_stale_diagnostic"
    assert diagnostic["fresh_signal_throttle_seen"] is True
    assert diagnostic["source_age_seconds"] == 5.0
    assert diagnostic["microboost_timing_age_seconds"] == 150.0
    assert diagnostic["microboost_active_timing_max_age_seconds"] == 120
    assert diagnostic["microboost_timing_fresh"] is False
    assert diagnostic["microboost_history_status"] == "HISTORICAL_EVIDENCE_ONLY"


def test_signal_watch_source_diagnostic_requires_clean_block_id():
    diagnostic = signal_watch_source_diagnostic(
        {
            "symbol": "CADJPY",
            "status": "MICROBOOST_WATCH",
            "signal_family": "MICROBOOST_WATCH",
            "valid_for_execution": False,
        }
    )

    assert diagnostic is not None
    assert diagnostic["event"] == "signal_watch_promotion_diagnostic"
    assert diagnostic["blocked_by"] == ["SOURCE_CLEAN_BLOCK_ID_MISSING"]
    assert diagnostic["source_lookup_stage"] == "SIGNAL_THROTTLE_V1_CLEAN_BLOCK_LEDGER"
    assert diagnostic["source_lookup_key"] == "CADJPY"
    assert diagnostic["nearest_clean_block_candidate"] is None
    assert diagnostic["why_not_attached"] == "WATCH_PAYLOAD_MISSING_SOURCE_CLEAN_BLOCK_ID"


def test_signal_watch_source_diagnostic_carries_lineage_resolution():
    diagnostic = signal_watch_source_diagnostic(
        {
            "symbol": "EURNZD",
            "status": "MICROBOOST_WATCH",
            "signal_family": "MICROBOOST_WATCH",
            "source_clean_block_lineage_resolution": {
                "status": "NO_SAFE_PAIR_LOCAL_MATCH",
                "reason": "TIME_WINDOW_MISMATCH",
                "lineage_candidate_count": 3,
                "lineage_time_overlap_count": 0,
            },
        }
    )

    assert diagnostic is not None
    assert diagnostic["source_clean_block_lineage_resolution"] == {
        "status": "NO_SAFE_PAIR_LOCAL_MATCH",
        "reason": "TIME_WINDOW_MISMATCH",
        "lineage_candidate_count": 3,
        "lineage_time_overlap_count": 0,
    }


def test_signal_watch_source_diagnostic_rejects_cross_pair_clean_block_id():
    diagnostic = signal_watch_source_diagnostic(
        {
            "symbol": "CADJPY",
            "status": "EARLY_SELL_WATCH",
            "signal_family": "MICROBOOST_COUNTER_ENTRY",
            "source_clean_block_id": "AUDCAD_20260708T093150Z_20260708T093801Z",
            "valid_for_execution": False,
        }
    )

    assert diagnostic is not None
    assert diagnostic["blocked_by"] == ["SOURCE_CLEAN_BLOCK_SYMBOL_MISMATCH"]
    assert diagnostic["source_clean_block_symbol"] == "AUDCAD"
    assert diagnostic["source_lookup_key"] == "CADJPY"
    assert diagnostic["reason"] == "signal_watch_requires_pair_local_source_clean_block_id"


def test_signal_throttle_state_snapshot_summarizes_freshness():
    report, now = _report(age_seconds=45.0)

    payload = signal_throttle_state_snapshot_payload(report, now=now, max_age_seconds=300)

    assert payload["event"] == "signal_throttle_state_snapshot"
    assert payload["fresh_symbols"] == ["USDCAD"]
    assert payload["stale_symbols"] == []
    assert payload["last_clean_block_id"] == "USDCAD_BLOCK_1"
    assert payload["record_buffer_size"] == 24


def test_signal_throttle_state_snapshot_reads_v1_clean_block_ledger():
    report, now = _report(age_seconds=45.0)
    report["clean_watch_candidates"] = []
    report["v1_clean_block_count"] = 1
    report["data_quality"] = {
        "scanner_cycle_ids": ["SCAN_20260708T082000Z_300S", "SCAN_20260708T082500Z_300S"],
    }
    report["v1_clean_block_ledger"] = [
        {
            "symbol": "USDCAD",
            "source_clean_block_id": "USDCAD_V1_BLOCK_1",
            "clean_block_end_utc": (now - timedelta(seconds=20)).isoformat(),
            "clean_block_duration_seconds": 360.0,
        }
    ]

    payload = signal_throttle_state_snapshot_payload(report, now=now, max_age_seconds=300)

    assert payload["last_clean_block_id"] == "USDCAD_V1_BLOCK_1"
    assert payload["last_valid_clean_block_id"] == "USDCAD_V1_BLOCK_1"
    assert payload["active_clean_block_id"] == "USDCAD_V1_BLOCK_1"
    assert payload["active_clean_blocks"] == 1
    assert payload["clean_block_count"] == 1
    assert payload["v1_clean_block_count"] == 1
    assert payload["max_clean_block_minutes"] == 6.0
    assert payload["clean_block_ledger_source"] == "SIGNAL_THROTTLE_V1_CLEAN_BLOCK_LEDGER"
    assert payload["scanner_cycle_id_count"] == 2
    assert payload["scanner_cycle_ids"] == ["SCAN_20260708T082000Z_300S", "SCAN_20260708T082500Z_300S"]


def test_signal_throttle_state_snapshot_emits_on_observability_logger(caplog):
    caplog.set_level(logging.WARNING, logger="signal_json")
    caplog.set_level(logging.WARNING, logger="signal_throttle_observability")
    report, now = _report(age_seconds=45.0)
    payload = signal_throttle_state_snapshot_payload(report, now=now, max_age_seconds=300)

    assert emit_signal_throttle_state_snapshot(payload, prefix="[SignalThrottleStateSnapshot]") is True

    observability_records = [record for record in caplog.records if record.name == "signal_throttle_observability"]
    signal_json_records = [record for record in caplog.records if record.name == "signal_json"]
    assert observability_records
    assert "[SignalThrottleStateSnapshot]" in observability_records[0].getMessage()
    assert not any("SignalThrottleStateSnapshot" in record.getMessage() for record in signal_json_records)


def test_signal_throttle_freshness_diagnostic_emits_on_observability_logger(caplog):
    caplog.set_level(logging.WARNING, logger="signal_json")
    caplog.set_level(logging.WARNING, logger="signal_throttle_observability")

    assert (
        emit_source_guard_diagnostic(
            {
                "event": "signal_throttle_freshness_diagnostic",
                "symbol": "XAGUSD",
                "blocked_stage": "MICROBOOST",
                "reason": "STALE_SIGNAL_THROTTLE_SOURCE",
            },
            prefix="[SignalThrottleFreshnessDiagnostic]",
        )
        is True
    )

    observability_records = [record for record in caplog.records if record.name == "signal_throttle_observability"]
    signal_json_records = [record for record in caplog.records if record.name == "signal_json"]
    assert observability_records
    assert "[SignalThrottleFreshnessDiagnostic]" in observability_records[0].getMessage()
    assert not any("SignalThrottleFreshnessDiagnostic" in record.getMessage() for record in signal_json_records)


def test_microboost_source_diagnostic_emits_on_microboost_observability_logger(caplog):
    caplog.set_level(logging.WARNING, logger="signal_json")
    caplog.set_level(logging.WARNING, logger="signal_throttle_observability")
    caplog.set_level(logging.WARNING, logger="microboost_observability")

    assert (
        emit_source_guard_diagnostic(
            {
                "event": "microboost_source_diagnostic",
                "symbol": "XAGUSD",
                "blocked_stage": "MICROBOOST",
                "reason": "MICROBOOST_REQUIRES_SOURCE_CLEAN_BLOCK_ID",
            },
            prefix="[MicroboostSourceDiagnostic]",
        )
        is True
    )

    microboost_records = [record for record in caplog.records if record.name == "microboost_observability"]
    signal_throttle_records = [record for record in caplog.records if record.name == "signal_throttle_observability"]
    signal_json_records = [record for record in caplog.records if record.name == "signal_json"]
    assert microboost_records
    assert "[MicroboostSourceDiagnostic]" in microboost_records[0].getMessage()
    assert not any("MicroboostSourceDiagnostic" in record.getMessage() for record in signal_throttle_records)
    assert not any("MicroboostSourceDiagnostic" in record.getMessage() for record in signal_json_records)
