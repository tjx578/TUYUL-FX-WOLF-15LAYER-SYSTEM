"""Patch 1/2 — Microboost watch-miss + shadow diagnostics (flag-guarded, default OFF).

When a deployment produces no SignalWatchJSON, these diagnostics EXPLAIN why: the latest
microboost block fell below the watch threshold (effective_ticks>=5, density>=8.0,
duration>=18s), and whether it WOULD have qualified under the looser shadow thresholds.
Diagnostic-only: never executable, never a SignalJSON.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from analysis.signal_throttle_log_analyzer import (
    PressureBlock,
    _is_ignition_watch_block,
    _microboost_watch_miss_diagnostic,
)
from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline

_P1 = "MICROBOOST_WATCH_MISS_DIAGNOSTIC_ENABLED"
_P2 = "MICROBOOST_SHADOW_DIAGNOSTIC_ENABLED"


def _block(ticks=4, density=7.2, duration=13.0, end=None, symbol="GBPAUD", direction="BUY"):
    block_end = end or datetime(2026, 6, 11, 8, 30, tzinfo=UTC)
    return PressureBlock(
        symbol=symbol,
        start=block_end - timedelta(seconds=duration),
        end=block_end,
        events=ticks,
        max_gap_seconds=0.0,
        direction=direction,
        duration_seconds=duration,
        effective_ticks=ticks,
        effective_density_per_minute=density,
        density_per_minute=density,
    )


# --------------------------------------------------------------------------- #
# Analyzer: _microboost_watch_miss_diagnostic (pure)
# --------------------------------------------------------------------------- #


def test_below_threshold_block_produces_diagnostic():
    diag = _microboost_watch_miss_diagnostic([_block(ticks=4, density=7.2, duration=13.0)], clean_block_seconds=300)
    assert diag is not None
    assert diag["eligible_for_watch"] is False
    assert diag["symbol"] == "GBPAUD"
    assert diag["raw_direction"] == "BUY"
    assert diag["threshold_ticks"] == 5
    assert diag["threshold_density"] == 8.0
    assert diag["threshold_duration_seconds"] == 18.0
    assert set(diag["blocked_by"]) == {
        "MICROBOOST_TICKS_BELOW_THRESHOLD",
        "MICROBOOST_DENSITY_BELOW_THRESHOLD",
        "MICROBOOST_DURATION_BELOW_THRESHOLD",
    }
    # 4>=3, 7.2>=5.0, 13>=10  -> would qualify under shadow thresholds
    assert diag["shadow_watch_candidate"] is True


def test_qualifying_block_yields_no_diagnostic():
    # 6 ticks, 9.0 density, 20s, clean_block_seconds 300 -> passes _is_ignition_watch_block
    block = _block(ticks=6, density=9.0, duration=20.0)
    assert _is_ignition_watch_block(block, 300) is True
    assert _microboost_watch_miss_diagnostic([block], clean_block_seconds=300) is None


def test_below_shadow_threshold_is_not_shadow_candidate():
    diag = _microboost_watch_miss_diagnostic([_block(ticks=2, density=3.0, duration=8.0)], clean_block_seconds=300)
    assert diag is not None
    assert diag["shadow_watch_candidate"] is False


def test_empty_blocks_yield_no_diagnostic():
    assert _microboost_watch_miss_diagnostic([], clean_block_seconds=300) is None


def test_latest_block_is_diagnosed():
    older = _block(ticks=4, end=datetime(2026, 6, 11, 8, 0, tzinfo=UTC), symbol="OLD")
    newer = _block(ticks=4, end=datetime(2026, 6, 11, 9, 0, tzinfo=UTC), symbol="GBPAUD")
    diag = _microboost_watch_miss_diagnostic([older, newer], clean_block_seconds=300)
    assert diag is not None
    assert diag["symbol"] == "GBPAUD"


# --------------------------------------------------------------------------- #
# Pipeline: _emit_microboost_watch_miss_diagnostic (flag-gated, deduped)
# --------------------------------------------------------------------------- #


def _pipeline() -> WolfConstitutionalPipeline:
    return WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)


def _report(**diag_overrides) -> dict:
    diag = {
        "symbol": "GBPAUD",
        "raw_direction": "BUY",
        "effective_ticks": 4,
        "effective_density": 7.2,
        "duration_seconds": 13.0,
        "threshold_ticks": 5,
        "threshold_density": 8.0,
        "threshold_duration_seconds": 18.0,
        "eligible_for_watch": False,
        "blocked_by": ["MICROBOOST_TICKS_BELOW_THRESHOLD", "MICROBOOST_DURATION_BELOW_THRESHOLD"],
        "shadow_watch_candidate": True,
        "shadow_thresholds": {"ticks": 3, "density": 5.0, "duration_seconds": 10.0},
    }
    diag.update(diag_overrides)
    return {"microboost_watch_miss_diagnostic": diag}


def test_flags_off_no_emit(monkeypatch, caplog):
    monkeypatch.delenv(_P1, raising=False)
    monkeypatch.delenv(_P2, raising=False)
    p = _pipeline()
    with caplog.at_level(logging.WARNING):
        p._emit_microboost_watch_miss_diagnostic(_report())
    assert "[MicroboostWatchDiagnostic]" not in caplog.text
    assert "[MicroboostShadowDiagnostic]" not in caplog.text


def test_patch1_emits_watch_miss(monkeypatch, caplog):
    monkeypatch.setenv(_P1, "true")
    monkeypatch.delenv(_P2, raising=False)
    p = _pipeline()
    with caplog.at_level(logging.WARNING):
        p._emit_microboost_watch_miss_diagnostic(_report())
    assert "[MicroboostWatchDiagnostic]" in caplog.text
    assert '"event":"microboost_watch_candidate_diagnostic"' in caplog.text
    assert '"eligible_for_watch":false' in caplog.text
    assert '"valid_for_execution":false' in caplog.text
    assert '"is_final_signal":false' in caplog.text
    assert "[MicroboostShadowDiagnostic]" not in caplog.text  # P2 off


def test_patch2_emits_shadow_when_candidate(monkeypatch, caplog):
    monkeypatch.delenv(_P1, raising=False)
    monkeypatch.setenv(_P2, "true")
    p = _pipeline()
    with caplog.at_level(logging.WARNING):
        p._emit_microboost_watch_miss_diagnostic(_report(shadow_watch_candidate=True))
    assert "[MicroboostShadowDiagnostic]" in caplog.text
    assert '"would_have_been_watch_under_shadow_threshold":true' in caplog.text
    assert '"valid_for_execution":false' in caplog.text


def test_patch2_no_shadow_when_not_candidate(monkeypatch, caplog):
    monkeypatch.delenv(_P1, raising=False)
    monkeypatch.setenv(_P2, "true")
    p = _pipeline()
    with caplog.at_level(logging.WARNING):
        p._emit_microboost_watch_miss_diagnostic(_report(shadow_watch_candidate=False))
    assert "[MicroboostShadowDiagnostic]" not in caplog.text


def test_dedup_suppresses_unchanged_repeat(monkeypatch, caplog):
    monkeypatch.setenv(_P1, "true")
    p = _pipeline()
    with caplog.at_level(logging.WARNING):
        p._emit_microboost_watch_miss_diagnostic(_report())
        p._emit_microboost_watch_miss_diagnostic(_report())  # identical -> suppressed
    assert caplog.text.count("[MicroboostWatchDiagnostic]") == 1
    # a material change (different blocked_by) re-emits
    with caplog.at_level(logging.WARNING):
        p._emit_microboost_watch_miss_diagnostic(_report(blocked_by=["MICROBOOST_DENSITY_BELOW_THRESHOLD"]))
    assert caplog.text.count("[MicroboostWatchDiagnostic]") == 2


# --------------------------------------------------------------------------- #
# P2D'-B' (case-q): direction recovery on the miss diagnostic (flag-gated OFF)
# --------------------------------------------------------------------------- #

_RECOV = "MICROBOOST_WATCH_MISS_DIRECTION_RECOVERY_ENABLED"


def _report_q(quorum, **diag_overrides) -> dict:
    rpt = _report(**diag_overrides)
    rpt["allowed_quorum"] = quorum
    return rpt


def test_recovery_off_is_byte_identical(monkeypatch, caplog):
    # Miss diagnostic ON, recovery flag OFF -> no new field, block direction untouched.
    monkeypatch.setenv(_P1, "true")
    monkeypatch.delenv(_RECOV, raising=False)
    p = _pipeline()
    with caplog.at_level(logging.WARNING):
        p._emit_microboost_watch_miss_diagnostic(
            _report_q({"symbol": "GBPAUD", "direction": "BUY"}, raw_direction=None)
        )
    assert "[MicroboostWatchDiagnostic]" in caplog.text
    assert "direction_recovery_source" not in caplog.text
    assert '"raw_direction":null' in caplog.text


def test_recovery_stamps_symbol_matched_quorum_direction(monkeypatch, caplog):
    monkeypatch.setenv(_P1, "true")
    monkeypatch.setenv(_RECOV, "true")
    p = _pipeline()
    with caplog.at_level(logging.WARNING):
        p._emit_microboost_watch_miss_diagnostic(
            _report_q({"symbol": "GBPAUD", "direction": "BUY"}, raw_direction=None)
        )
    assert '"raw_direction":"BUY"' in caplog.text
    assert '"direction_recovery_source":"ALLOWED_QUORUM_REPORT"' in caplog.text


def test_recovery_symbol_mismatch_does_not_stamp(monkeypatch, caplog):
    # Quorum direction belongs to another pair -> never stamp it onto this symbol.
    monkeypatch.setenv(_P1, "true")
    monkeypatch.setenv(_RECOV, "true")
    p = _pipeline()
    with caplog.at_level(logging.WARNING):
        p._emit_microboost_watch_miss_diagnostic(
            _report_q({"symbol": "EURUSD", "direction": "BUY"}, raw_direction=None)
        )
    assert '"raw_direction":null' in caplog.text
    assert '"direction_recovery_source":null' in caplog.text


def test_recovery_block_direct_never_overwritten_by_quorum(monkeypatch, caplog):
    # Block already has a real direction -> keep it, label BLOCK_DIRECT, ignore opposing quorum.
    monkeypatch.setenv(_P1, "true")
    monkeypatch.setenv(_RECOV, "true")
    p = _pipeline()
    with caplog.at_level(logging.WARNING):
        p._emit_microboost_watch_miss_diagnostic(
            _report_q({"symbol": "GBPAUD", "direction": "SELL"}, raw_direction="BUY")
        )
    assert '"raw_direction":"BUY"' in caplog.text
    assert '"direction_recovery_source":"BLOCK_DIRECT"' in caplog.text


def test_recovery_stays_non_executable(monkeypatch, caplog):
    monkeypatch.setenv(_P1, "true")
    monkeypatch.setenv(_RECOV, "true")
    p = _pipeline()
    with caplog.at_level(logging.WARNING):
        p._emit_microboost_watch_miss_diagnostic(
            _report_q({"symbol": "GBPAUD", "direction": "BUY"}, raw_direction=None)
        )
    assert '"valid_for_execution":false' in caplog.text
    assert '"is_final_signal":false' in caplog.text
    assert '"eligible_for_watch":false' in caplog.text
