"""Patch B -- clean-block direction fallback Watch (flag-guarded, default OFF).

Contract: a valid clean SignalThrottle block (>= clean_block_seconds) carrying its OWN BUY/SELL
direction MUST still emit a SignalWatchJSON (CLEAN_BLOCK_*_WATCH) + a PENDING market_structure when
the microboost direction is MISSING. An OPPOSITE microboost direction stays a conflict (no fallback).
Watch-only: final_direction=WAIT, valid_for_execution=false, never a SignalJSON. Threshold unchanged.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from analysis.signal_json_emitter import build_signal_json_event
from analysis.signal_throttle_log_analyzer import (
    PressureBlock,
    _candidate_from_blocks,
    _microboost_watch_payload,
    _signal_watch_gate,
)

_FLAG = "SIGNAL_WATCH_ALLOW_CLEAN_BLOCK_DIRECTION_FALLBACK"


def _candidate(direction="BUY", symbol="EURUSD"):
    return {
        "symbol": symbol,
        "direction": direction,
        "valid_since_utc": "2026-06-18T08:00:00+00:00",
        "block_start_utc": "2026-06-18T07:55:00+00:00",
        "block_end_utc": "2026-06-18T08:00:00+00:00",
    }


def _summary(latest_direction=None, symbol="EURUSD"):
    return {
        "latest": {
            "symbol": symbol,
            "direction": latest_direction,
            "cluster_id": "c1",
            "end_utc": "2026-06-18T08:00:00+00:00",
            "market_context_snapshot": {
                "price_at_signal_start": 1.0990,
                "price_at_signal_end": 1.1000,
                "price_position": "MAIN_RESISTANCE",
            },
        }
    }


def _fallback_gate():
    return {
        "eligible": True,
        "source": "SIGNAL_THROTTLE_CLEAN_BLOCK",
        "reason": "CLEAN_BLOCK_DIRECTION_FALLBACK",
        "symbol": "EURUSD",
        "direction": "BUY",
        "clean_block_fallback": True,
    }


# --------------------------- gate ---------------------------


def test_gate_fallback_eligible_when_microboost_direction_missing(monkeypatch):
    monkeypatch.setenv(_FLAG, "true")
    gate = _signal_watch_gate(_candidate("BUY"), _summary(latest_direction=None))
    assert gate["eligible"] is True
    assert gate["clean_block_fallback"] is True
    assert gate["direction"] == "BUY"
    assert gate["reason"] == "CLEAN_BLOCK_DIRECTION_FALLBACK"


def test_gate_fallback_disabled_by_default(monkeypatch):
    monkeypatch.delenv(_FLAG, raising=False)
    gate = _signal_watch_gate(_candidate("BUY"), _summary(latest_direction=None))
    assert gate["eligible"] is False
    assert gate["reason"] == "MICROBOOST_DIRECTION_NOT_CLEAN_BLOCK_DIRECTION"


def test_gate_opposite_microboost_direction_still_rejected(monkeypatch):
    monkeypatch.setenv(_FLAG, "true")
    gate = _signal_watch_gate(_candidate("BUY"), _summary(latest_direction="SELL"))
    assert gate["eligible"] is False
    assert "clean_block_fallback" not in gate


def test_gate_normal_match_has_no_fallback_marker(monkeypatch):
    monkeypatch.setenv(_FLAG, "true")
    gate = _signal_watch_gate(_candidate("BUY"), _summary(latest_direction="BUY"))
    assert gate["eligible"] is True
    assert "clean_block_fallback" not in gate


# --------------------------- payload branding ---------------------------


def test_payload_emits_clean_block_watch():
    payload = _microboost_watch_payload(
        _summary(latest_direction=None), _fallback_gate(), continuation_entry=None, counter_entry=None
    )
    assert payload is not None
    assert payload["status"] == "CLEAN_BLOCK_BUY_WATCH"
    assert payload["signal_family"] == "CLEAN_BLOCK_BUY_WATCH"
    assert payload["raw_direction"] == "BUY"
    assert payload["candidate_direction"] == "BUY"
    assert payload["watch_direction"] == "BUY"
    assert payload["direction_validation_status"] == "CLEAN_BLOCK_DIRECTION_FALLBACK_PENDING_STRUCTURE"


def test_payload_market_structure_pending_object():
    payload = _microboost_watch_payload(
        _summary(latest_direction=None), _fallback_gate(), continuation_entry=None, counter_entry=None
    )
    ms = payload["market_structure"]
    assert ms["structure_ready"] is False
    assert ms["structure_source"] == "CLEAN_BLOCK_CONTEXT"
    assert ms["market_structure_status"] == "PENDING_PRICE_THEME_STRUCTURE"
    assert ms["structure_bias"] == "BUY_WATCH"


def test_clean_block_watch_is_never_executable():
    payload = _microboost_watch_payload(
        _summary(latest_direction=None), _fallback_gate(), continuation_entry=None, counter_entry=None
    )
    assert payload["final_direction"] == "WAIT"
    assert payload["valid_for_execution"] is False
    assert payload["is_final_signal"] is False
    assert payload["execution_valid_now"] is False


def test_clean_block_watch_emits_as_watch_not_signaljson():
    payload = _microboost_watch_payload(
        _summary(latest_direction=None), _fallback_gate(), continuation_entry=None, counter_entry=None
    )
    event = build_signal_json_event(payload)
    assert event is not None
    out = event.to_dict()
    assert out["event"] == "signal_watch_json"  # NOT signal_json
    assert out["valid_for_execution"] is False


# --------------------------- threshold preserved (skip #2 unchanged) ---------------------------


def _block(duration_seconds, symbol="EURUSD", direction="BUY"):
    end = datetime(2026, 6, 18, 8, 0, tzinfo=UTC)
    return PressureBlock(
        symbol=symbol,
        start=end - timedelta(seconds=duration_seconds),
        end=end,
        events=5,
        duration_seconds=duration_seconds,
        density_per_minute=8.0,
        max_gap_seconds=0.0,
        direction=direction,
        effective_ticks=5,
        effective_density_per_minute=8.0,
    )


def test_block_below_300s_is_not_clean_block():
    assert _candidate_from_blocks([_block(120)], 300) is None  # threshold NOT lowered


def test_block_at_threshold_is_clean_block():
    cand = _candidate_from_blocks([_block(305)], 300)
    assert cand is not None
    assert cand["direction"] == "UNRESOLVED"
    assert cand["raw_pressure_direction"] == "BUY"
    assert cand["candidate_direction"] is None
