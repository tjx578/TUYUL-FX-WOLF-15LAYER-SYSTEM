"""Increment B - suppress identical watch re-emits (flag-guarded).

The transition logic rate-limits watches but still re-emits an unchanged watch each
interval (revision bump -> new dedup key). With SIGNAL_WATCH_SUPPRESS_IDENTICAL=true,
byte-identical watch content for the same cluster is collapsed until something
materially changes. Default OFF -> behavior unchanged.

The tests neutralize the other two dedup layers (transition state + TTL key store)
between emits so only the content-dedup can suppress, isolating Increment B.
"""
from __future__ import annotations

from analysis.signal_json_emitter import SignalJsonEmitter, build_signal_json_event


def _fresh_emitter() -> SignalJsonEmitter:
    return SignalJsonEmitter(
        enabled=True,
        emit_watch=True,
        watch_transition_only=False,
        require_market_context=False,
        strict_lifecycle=False,
        dedup_ttl_seconds=300,
    )


def _reset_non_content(em: SignalJsonEmitter) -> None:
    em._emitted.clear()
    em._cluster_state.clear()
    em._cluster_watch_revisions.clear()
    em._cluster_watch_wall_seconds.clear()
    em._cluster_watch_event_seconds.clear()


def _watch_event():
    return build_signal_json_event(
        {
            "symbol": "NZDCHF",
            "signal_family": "MICROBOOST_WATCH",
            "status": "MICROBOOST_WATCH",
            "raw_direction": "BUY",
            "candidate_direction": "BUY",
            "watch_direction": "BUY",
            "final_direction": "WAIT",
            "signal_valid_time_utc": "2026-06-10T08:35:37+00:00",
            "signal_valid_price": 115.127,
            "entry_reference_price": 115.127,
            "entry_zone": [115.127],
            "market_context_applied": True,
            "reason": "buy_microboost_at_main_resistance_requires_rejection_or_breakout_confirmation",
            "cluster_id": "NZDCHF_20260610T083535Z",
            "valid_for_execution": False,
        }
    )


def test_flag_on_suppresses_identical_reemit(monkeypatch):
    monkeypatch.setenv("SIGNAL_WATCH_SUPPRESS_IDENTICAL", "true")
    em = _fresh_emitter()
    event = _watch_event()
    assert em.emit(event) is True
    _reset_non_content(em)  # defeat transition + TTL layers; only content-dedup remains
    assert em.emit(event) is False


def test_flag_off_allows_reemit(monkeypatch):
    monkeypatch.setenv("SIGNAL_WATCH_SUPPRESS_IDENTICAL", "false")
    em = _fresh_emitter()
    event = _watch_event()
    assert em.emit(event) is True
    _reset_non_content(em)
    assert em.emit(event) is True  # no content-dedup -> re-emits


def test_flag_on_allows_changed_content(monkeypatch):
    monkeypatch.setenv("SIGNAL_WATCH_SUPPRESS_IDENTICAL", "true")
    em = _fresh_emitter()
    assert em.emit(_watch_event()) is True
    _reset_non_content(em)
    changed = build_signal_json_event(
        {
            "symbol": "NZDCHF",
            "signal_family": "MICROBOOST_WATCH",
            "status": "MICROBOOST_WATCH",
            "raw_direction": "BUY",
            "candidate_direction": "BUY",
            "watch_direction": "BUY",
            "final_direction": "WAIT",
            "signal_valid_time_utc": "2026-06-10T08:40:00+00:00",
            "signal_valid_price": 115.200,
            "entry_reference_price": 115.200,  # price moved -> content changed
            "entry_zone": [115.200],
            "market_context_applied": True,
            "reason": "buy_microboost_at_main_resistance_requires_rejection_or_breakout_confirmation",
            "cluster_id": "NZDCHF_20260610T083535Z",
            "valid_for_execution": False,
        }
    )
    assert em.emit(changed) is True
