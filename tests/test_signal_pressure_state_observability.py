from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from analysis.signal_pressure_state_emitter import (
    emit_signal_pressure_state,
    emit_signal_pressure_state_summary,
    signal_pressure_runtime_identity,
)
from analysis.signal_pressure_state_observability import PressureStateSummaryTracker


def test_pressure_state_summary_tracks_emits_suppressions_and_top_pressure():
    tracker = PressureStateSummaryTracker(now=100.0)
    payload = {
        "symbol": "USDCAD",
        "source_stage": "SIGNAL_THROTTLE_INTEL",
        "source_family": "SIGNAL_THROTTLE_PRESSURE",
        "raw_direction": "BUY",
        "session_symbol_event_count": 9,
        "block_event_count": 5,
        "block_effective_ticks": 4,
        "block_duration_seconds": 72.5,
        "block_density": 3.31,
    }

    assert tracker.record(payload, emitted=True) == {
        "pressure_state_attempted": 1,
        "pressure_state_emitted": 1,
        "pressure_state_suppressed": 0,
    }
    assert tracker.record(payload, emitted=False, suppression_reason="SEMANTIC_RATE_LIMIT") == {
        "pressure_state_attempted": 2,
        "pressure_state_emitted": 1,
        "pressure_state_suppressed": 1,
    }
    tracker.record(
        {"symbol": "AUDUSD", "source_stage": "SIGNAL_THROTTLE_INTEL"},
        emitted=False,
        suppression_reason="BELOW_MIN_EVENTS",
    )

    summary = tracker.roll_if_due(interval_seconds=60.0, now=161.0)

    assert summary is not None
    assert summary["attempted"] == 3
    assert summary["emitted"] == 1
    assert summary["suppressed"] == 2
    assert summary["active_symbols"] == 2
    assert summary["by_source_stage"] == {"SIGNAL_THROTTLE_INTEL": 3}
    assert summary["by_suppression_reason"] == {
        "SEMANTIC_RATE_LIMIT": 1,
        "BELOW_MIN_EVENTS": 1,
    }
    assert summary["top_pressure"][0]["symbol"] == "USDCAD"
    assert summary["top_pressure"][0]["events"] == 9
    assert summary["valid_for_execution"] is False
    assert tracker.roll_if_due(interval_seconds=60.0, now=222.0) is None


def test_pressure_state_emitters_include_runtime_identity(monkeypatch, caplog):
    monkeypatch.setenv("RAILWAY_DEPLOYMENT_ID", "deploy-123")
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "abcdef123456")
    monkeypatch.setenv("RAILWAY_REPLICA_ID", "replica-2")
    generated_at = datetime(2026, 7, 16, 1, 2, 3, tzinfo=UTC)

    identity = signal_pressure_runtime_identity(generated_at=generated_at)

    assert identity == {
        "deployment_id": "deploy-123",
        "commit_sha": "abcdef123456",
        "replica_id": "replica-2",
        "generated_at_utc": "2026-07-16T01:02:03+00:00",
    }

    caplog.set_level(logging.WARNING, logger="signal_json")
    assert emit_signal_pressure_state({"symbol": "USDCAD"}) is True
    assert emit_signal_pressure_state_summary({"attempted": 1, "emitted": 1, "suppressed": 0}) is True

    state_message = next(record.message for record in caplog.records if "[SignalPressureStateJSON]" in record.message)
    summary_message = next(
        record.message for record in caplog.records if "[SignalPressureStateSummary]" in record.message
    )
    state = json.loads(state_message.split("[SignalPressureStateJSON]", 1)[1].strip())
    summary = json.loads(summary_message.split("[SignalPressureStateSummary]", 1)[1].strip())
    for payload in (state, summary):
        assert payload["deployment_id"] == "deploy-123"
        assert payload["commit_sha"] == "abcdef123456"
        assert payload["replica_id"] == "replica-2"
        assert payload["valid_for_execution"] is False
        assert payload["execution_valid_now"] is False
        assert payload["final_direction"] == "WAIT"
    assert state["schema_version"] == "2.0-pressure-state"
    assert summary["schema_version"] == "1.0-pressure-state-summary"
