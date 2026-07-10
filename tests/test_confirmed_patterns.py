"""Distinguish confirmed patterns from the candidate scan.

Production context keeps count/confirmed/supporting patterns; the full matched-pattern
ledger is debug-only so SignalWatchJSON stays readable.
"""
from __future__ import annotations

from analysis.signal_json_emitter import SignalJsonEvent, build_signal_json_event

_MATCHED = ["UPPER_ABSORPTION_WARNING", "JPY_ALIGNMENT_REQUIRED", "LATE_UPPER_MICROBOOST", "FOO_BAR_FILTER"]


def _event() -> SignalJsonEvent:
    event = build_signal_json_event(
        {
            "symbol": "NZDCHF",
            "signal_family": "MICROBOOST_WATCH",
            "status": "MICROBOOST_WATCH",
            "raw_direction": "BUY",
            "watch_direction": "BUY",
            "final_direction": "WAIT",
            "signal_valid_time_utc": "2026-06-10T08:35:37+00:00",
            "signal_valid_price": 115.127,
            "entry_reference_price": 115.127,
            "entry_zone": [115.127],
            "market_context_applied": True,
            "cluster_id": "NZDCHF_20260610T083535Z",
            "valid_for_execution": False,
            "selected_pattern_id": "UPPER_ABSORPTION_WARNING",
            "matched_patterns": _MATCHED,
            "pattern_evidence": [
                "STRATEGY_PATTERN=UPPER_RANGE_EXHAUSTION",
                "DB_SEMANTIC_MATCH=LATE_UPPER_MICROBOOST:PULLBACK",
            ],
        }
    )
    assert event is not None
    return event


def test_confirmed_patterns_are_evidence_backed():
    ctx = _event().pattern_context
    assert ctx is not None
    confirmed = ctx["confirmed_patterns"]
    assert "UPPER_ABSORPTION_WARNING" in confirmed  # selected -> always confirmed
    assert "LATE_UPPER_MICROBOOST" in confirmed  # referenced in evidence
    assert "FOO_BAR_FILTER" not in confirmed  # only in candidate scan, no evidence
    assert "JPY_ALIGNMENT_REQUIRED" not in confirmed  # no evidence reference


def test_candidate_count_kept_and_matched_scan_debug_only():
    ctx = _event().pattern_context
    assert ctx is not None
    assert ctx["candidate_patterns_count"] == 4
    assert ctx["debug_pattern_ledger_available"] is True
    assert "matched_patterns" not in ctx
