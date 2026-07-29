from __future__ import annotations

from datetime import UTC, datetime, timedelta

from analysis.signal_throttle_log_analyzer import SignalThrottleLiveAnalyzer


def test_pressure_canary_alone_does_not_auto_promote_to_microboost():
    """Risiko 1: canary murni (tanpa blok matang) tidak boleh jadi microboost valid."""
    analyzer = SignalThrottleLiveAnalyzer()
    base = datetime(2026, 6, 8, 3, 0, 0, tzinfo=UTC)
    for i in range(3):
        analyzer.record_pressure_canary(
            symbol="USDCAD",
            verdict="NO_TRADE",
            direction="BUY",
            reason="non_execute_verdict",
            timestamp=base + timedelta(seconds=i * 20),
        )
    report = analyzer.snapshot()

    # Pressure tercatat sebagai radar...
    assert report["counts"]["total_events"] == 3
    # ...tetapi TIDAK auto-promote ke entry microboost yang executable.
    assert (
        report.get("microboost_continuation_entry") in (None, {})
        or report["microboost_continuation_entry"].get("status") == "NONE"
    )
    assert (
        report.get("microboost_counter_entry") in (None, {})
        or report["microboost_counter_entry"].get("status") == "NONE"
    )
