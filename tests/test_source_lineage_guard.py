from __future__ import annotations

from datetime import UTC, datetime, timedelta

from analysis.source_lineage_guard import (
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


def test_microboost_source_guard_blocks_stale_cluster():
    report, now = _report(end_age_seconds=420.0)

    result = guard_microboost_source(report, now=now, max_age_seconds=300)

    assert result.can_emit_microboost is False
    assert {diag["event"] for diag in result.diagnostics} == {"microboost_stale_diagnostic"}


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


def test_signal_throttle_state_snapshot_summarizes_freshness():
    report, now = _report(age_seconds=45.0)

    payload = signal_throttle_state_snapshot_payload(report, now=now, max_age_seconds=300)

    assert payload["event"] == "signal_throttle_state_snapshot"
    assert payload["fresh_symbols"] == ["USDCAD"]
    assert payload["stale_symbols"] == []
    assert payload["last_clean_block_id"] == "USDCAD_BLOCK_1"
    assert payload["record_buffer_size"] == 24
