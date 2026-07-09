"""P1 — Signal-intelligence flag snapshot (startup diagnostic, default ON).

Emits one [SignalIntelligenceFlagSnapshot] line per deployment with the effective
intelligence/canary flag state so a capture can tell "flag OFF" from "logic failing".
Observability-only: never touches execution.
"""
from __future__ import annotations

import json
import logging

from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline

_TAG = "[SignalIntelligenceFlagSnapshot]"
_GATE = "SIGNAL_INTELLIGENCE_FLAG_SNAPSHOT_ENABLED"


def _pipeline() -> WolfConstitutionalPipeline:
    return WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)


def _emitted_payload(caplog) -> dict:
    line = next(rec.message for rec in caplog.records if _TAG in rec.message)
    return json.loads(line.split(_TAG, 1)[1].strip())


def test_snapshot_emits_with_flag_state(monkeypatch, caplog):
    monkeypatch.delenv(_GATE, raising=False)  # default ON
    monkeypatch.setenv("SIGNAL_THROTTLE_PRESSURE_DIRECTION_FROM_DIAGNOSTICS", "true")
    monkeypatch.setenv("MICROBOOST_WATCH_MISS_DIRECTION_RECOVERY_ENABLED", "true")
    monkeypatch.setenv("SIGNAL_FAMILY_LINEAGE_ENABLED", "false")
    monkeypatch.setenv("SIGNAL_WATCH_MARKET_STRUCTURE_PREVIEW_ENABLED", "true")
    monkeypatch.setenv("SIGNAL_JSON_LOG_ENABLED", "true")
    monkeypatch.setenv("SIGNAL_JSON_EMIT_WATCH", "true")
    monkeypatch.setenv("SIGNAL_JSON_EXEC_GATES_ENABLED", "true")
    monkeypatch.setenv("RAILWAY_DEPLOYMENT_ID", "dep-123")
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "abc123")
    with caplog.at_level(logging.WARNING, logger="signal_json"):
        _pipeline()._emit_signal_intelligence_flag_snapshot()
    p = _emitted_payload(caplog)
    assert p["event"] == "signal_intelligence_flag_snapshot"
    assert p["deployment_id"] == "dep-123"
    assert p["commit_sha"] == "abc123"
    assert p["SIGNAL_THROTTLE_PRESSURE_DIRECTION_FROM_DIAGNOSTICS"] is True
    assert p["MICROBOOST_WATCH_MISS_DIRECTION_RECOVERY_ENABLED"] is True
    assert p["SIGNAL_FAMILY_LINEAGE_ENABLED"] is False
    assert p["SIGNAL_WATCH_MARKET_STRUCTURE_PREVIEW_ENABLED"] is True
    assert p["SIGNAL_JSON_LOG_ENABLED"] is True
    assert p["SIGNAL_JSON_EMIT_WATCH"] is True
    assert p["SIGNAL_JSON_EXEC_GATES_ENABLED"] is True
    # safety gates surfaced and default-protective
    assert p["SIGNAL_JSON_STRICT_LIFECYCLE"] is True
    assert p["SIGNAL_JSON_EXEC_GATES_ENFORCE"] is True
    assert p["SIGNAL_JSON_REQUIRE_TERMINAL_DECISION_UPDATE"] is True


def test_snapshot_reflects_all_off_baseline(monkeypatch, caplog):
    for f in (
        "SIGNAL_THROTTLE_PRESSURE_DIRECTION_FROM_DIAGNOSTICS",
        "MICROBOOST_WATCH_MISS_DIRECTION_RECOVERY_ENABLED",
        "SIGNAL_FAMILY_LINEAGE_ENABLED",
    ):
        monkeypatch.delenv(f, raising=False)
    monkeypatch.delenv("RAILWAY_DEPLOYMENT_ID", raising=False)
    with caplog.at_level(logging.WARNING, logger="signal_json"):
        _pipeline()._emit_signal_intelligence_flag_snapshot()
    p = _emitted_payload(caplog)
    assert p["SIGNAL_THROTTLE_PRESSURE_DIRECTION_FROM_DIAGNOSTICS"] is False
    assert p["MICROBOOST_WATCH_MISS_DIRECTION_RECOVERY_ENABLED"] is False
    assert p["SIGNAL_FAMILY_LINEAGE_ENABLED"] is False
    assert p["deployment_id"] == "unknown"


def test_snapshot_can_be_disabled(monkeypatch, caplog):
    monkeypatch.setenv(_GATE, "false")
    with caplog.at_level(logging.WARNING, logger="signal_json"):
        _pipeline()._emit_signal_intelligence_flag_snapshot()
    assert _TAG not in caplog.text


def test_snapshot_reports_patch_b_clean_block_flag(monkeypatch, caplog):
    # The clean-block fallback flag MUST be visible so a capture can confirm Patch B is enabled.
    monkeypatch.delenv(_GATE, raising=False)
    monkeypatch.setenv("SIGNAL_WATCH_ALLOW_CLEAN_BLOCK_DIRECTION_FALLBACK", "true")
    with caplog.at_level(logging.WARNING, logger="signal_json"):
        _pipeline()._emit_signal_intelligence_flag_snapshot()
    p = _emitted_payload(caplog)
    assert p["SIGNAL_WATCH_ALLOW_CLEAN_BLOCK_DIRECTION_FALLBACK"] is True


def test_snapshot_patch_b_flag_defaults_false(monkeypatch, caplog):
    monkeypatch.delenv(_GATE, raising=False)
    monkeypatch.delenv("SIGNAL_WATCH_ALLOW_CLEAN_BLOCK_DIRECTION_FALLBACK", raising=False)
    with caplog.at_level(logging.WARNING, logger="signal_json"):
        _pipeline()._emit_signal_intelligence_flag_snapshot()
    p = _emitted_payload(caplog)
    assert p["SIGNAL_WATCH_ALLOW_CLEAN_BLOCK_DIRECTION_FALLBACK"] is False


def test_snapshot_reports_signal_throttle_intel_bridge_window(monkeypatch, caplog):
    monkeypatch.delenv(_GATE, raising=False)
    monkeypatch.setenv("SIGNAL_THROTTLE_INTEL_DIRECTION_BRIDGE_WINDOW_SECONDS", "300")
    with caplog.at_level(logging.WARNING, logger="signal_json"):
        _pipeline()._emit_signal_intelligence_flag_snapshot()
    p = _emitted_payload(caplog)
    assert p["SIGNAL_THROTTLE_INTEL_DIRECTION_BRIDGE_WINDOW_SECONDS"] == 300.0


def test_snapshot_reports_candidate_market_context_hydration(monkeypatch, caplog):
    monkeypatch.delenv(_GATE, raising=False)
    monkeypatch.setenv("SIGNAL_THROTTLE_CANDIDATE_MARKET_CONTEXT_ENABLED", "true")
    monkeypatch.setenv("SIGNAL_THROTTLE_CANDIDATE_MARKET_CONTEXT_MAX_SYMBOLS", "3")
    monkeypatch.setenv("SIGNAL_THROTTLE_FOLLOWTHROUGH_SCORE_LOG_ENABLED", "true")
    monkeypatch.setenv("SIGNAL_THROTTLE_FOLLOWTHROUGH_SCORE_MAX_SYMBOLS", "5")
    monkeypatch.setenv("SIGNAL_WATCH_FOLLOWTHROUGH_CONTEXT_ENABLED", "true")
    with caplog.at_level(logging.WARNING, logger="signal_json"):
        _pipeline()._emit_signal_intelligence_flag_snapshot()
    p = _emitted_payload(caplog)
    assert p["SIGNAL_THROTTLE_CANDIDATE_MARKET_CONTEXT_ENABLED"] is True
    assert p["SIGNAL_THROTTLE_CANDIDATE_MARKET_CONTEXT_MAX_SYMBOLS"] == 3.0
    assert p["SIGNAL_THROTTLE_FOLLOWTHROUGH_SCORE_LOG_ENABLED"] is True
    assert p["SIGNAL_THROTTLE_FOLLOWTHROUGH_SCORE_MAX_SYMBOLS"] == 5.0
    assert p["SIGNAL_WATCH_FOLLOWTHROUGH_CONTEXT_ENABLED"] is True


def test_snapshot_bridge_window_defaults_to_canary_ttl(monkeypatch, caplog):
    monkeypatch.delenv(_GATE, raising=False)
    monkeypatch.delenv("SIGNAL_THROTTLE_INTEL_DIRECTION_BRIDGE_WINDOW_SECONDS", raising=False)
    with caplog.at_level(logging.WARNING, logger="signal_json"):
        _pipeline()._emit_signal_intelligence_flag_snapshot()
    p = _emitted_payload(caplog)
    assert p["SIGNAL_THROTTLE_INTEL_DIRECTION_BRIDGE_WINDOW_SECONDS"] == 600.0
