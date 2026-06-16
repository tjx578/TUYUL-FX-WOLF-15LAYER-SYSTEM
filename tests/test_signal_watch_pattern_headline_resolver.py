"""Increment C — Pattern-Aware SignalWatch Headline Resolver.

A generic ``MICROBOOST_WATCH`` whose pattern context already reads as a counter
absorption setup (e.g. raw BUY pressure stalled at MAIN_RESISTANCE with
UPPER_ABSORPTION_WARNING / NO_NEW_BUY) should surface with the directional
counter headline the brain already implies — EARLY_SELL_WATCH / SELL_TIMING_WATCH —
reusing the existing ``MicroboostCounterEntryEngine`` vocabulary.

Strict guardrails (this is a live trading verdict path):
- flag default OFF  -> payload byte-for-byte unchanged
- insufficient pattern -> stays a generic MICROBOOST_WATCH
- valid_for_execution stays False, final_direction stays WAIT (never promoted)
- raw_direction (pressure side) is preserved; only candidate/watch direction flip
- ``latest["direction"]`` is never overwritten
"""
from __future__ import annotations

from typing import Any

from analysis.signal_throttle_log_analyzer import (
    _empty_signal_watch_gate,
    _microboost_watch_payload,
    resolve_signal_watch_headline_from_pattern,
)

_FLAG = "SIGNAL_WATCH_PATTERN_HEADLINE_RESOLVE_ENABLED"


def _latest(
    *,
    direction: str,
    price_position: str,
    phase_priced: str,
    selected_pattern_id: str | None = None,
    entry_permission: str | None = None,
    management_action: str | None = None,
    duration_minutes: float = 0.03,
) -> dict[str, Any]:
    return {
        "symbol": "GBPCHF",
        "direction": direction,
        "price_position": price_position,
        "phase_priced": phase_priced,
        "selected_pattern_id": selected_pattern_id,
        "pattern_family": "EXHAUSTION_MANAGEMENT" if selected_pattern_id else None,
        "entry_permission": entry_permission,
        "management_action": management_action,
        "duration_minutes": duration_minutes,
        "effective_density_per_minute": 170.05,
        "effective_tick_count": 6,
        "cluster_id": "GBPCHF_20260610T0500Z",
        "end_utc": "2026-06-10T05:00:00+00:00",
        "market_context_snapshot": {
            "price_at_signal_start": 1.12340,
            "price_at_signal_end": 1.12348,
            "price_position": price_position,
            "m15_phase": "BULLISH_PULLBACK",
            "h1_phase": "BEARISH",
        },
    }


def _build_watch(latest: dict[str, Any]) -> dict[str, Any]:
    summary = {"latest": latest}
    gate = _empty_signal_watch_gate("MICROBOOST_NOT_CLEAN_BLOCK", {"symbol": "GBPCHF", "direction": "BUY"})
    payload = _microboost_watch_payload(summary, gate, continuation_entry=None, counter_entry=None)
    assert payload is not None
    return payload


# --- direct unit tests on the pure resolver -------------------------------------------------


def test_resolver_buy_at_resistance_resolves_to_sell_watch():
    out = resolve_signal_watch_headline_from_pattern(
        raw_direction="BUY",
        price_position="MAIN_RESISTANCE",
        phase_priced="RESISTANCE_PRESSURE_WARNING",
        selected_pattern_id="UPPER_ABSORPTION_WARNING",
        entry_permission="NO_NEW_BUY",
        management_action="PROTECT_LONG_OR_SELL_WATCH",
        duration_seconds=1.8,
    )
    assert out["resolved"] is True
    assert out["signal_family"] == "MICROBOOST_COUNTER_ENTRY"
    assert out["status"] == "EARLY_SELL_WATCH"
    assert out["candidate_direction"] == "SELL"
    assert out["watch_direction"] == "SELL"
    assert "raw_direction" not in out  # caller preserves raw pressure side
    assert "valid_for_execution" not in out  # never promotes execution
    assert "final_direction" not in out  # never touches WAIT


def test_resolver_long_stall_resolves_to_timing_watch():
    out = resolve_signal_watch_headline_from_pattern(
        raw_direction="BUY",
        price_position="MAIN_RESISTANCE",
        phase_priced="RESISTANCE_PRESSURE_WARNING",
        duration_seconds=90.0,
    )
    assert out["status"] == "SELL_TIMING_WATCH"


def test_resolver_sell_at_support_resolves_to_buy_watch():
    out = resolve_signal_watch_headline_from_pattern(
        raw_direction="SELL",
        price_position="MAIN_SUPPORT",
        phase_priced="SUPPORT_PRESSURE_WARNING",
        duration_seconds=1.8,
    )
    assert out["status"] == "EARLY_BUY_WATCH"
    assert out["candidate_direction"] == "BUY"


def test_resolver_midrange_stays_generic():
    out = resolve_signal_watch_headline_from_pattern(
        raw_direction="BUY",
        price_position="MID_RANGE",
        phase_priced="NEUTRAL",
    )
    assert out == {"resolved": False}


def test_resolver_missing_direction_stays_generic():
    out = resolve_signal_watch_headline_from_pattern(
        raw_direction=None,
        price_position="MAIN_RESISTANCE",
        phase_priced="RESISTANCE_PRESSURE_WARNING",
    )
    assert out == {"resolved": False}


# --- integration tests through _microboost_watch_payload (the 5 owner-specified cases) ------


def test_flag_off_is_a_noop(monkeypatch):
    """Test 1 — flag OFF: the generic MICROBOOST_WATCH headline is unchanged."""
    monkeypatch.delenv(_FLAG, raising=False)
    payload = _build_watch(
        _latest(
            direction="BUY",
            price_position="MAIN_RESISTANCE",
            phase_priced="RESISTANCE_PRESSURE_WARNING",
            selected_pattern_id="UPPER_ABSORPTION_WARNING",
            entry_permission="NO_NEW_BUY",
        )
    )
    assert payload["status"] == "MICROBOOST_WATCH"
    assert payload["signal_family"] == "MICROBOOST_WATCH"
    assert payload["candidate_direction"] == "BUY"
    assert payload["valid_for_execution"] is False


def test_flag_on_buy_at_resistance_resolves_to_sell_watch(monkeypatch):
    """Test 2 — BUY at resistance resolves to a SELL-side counter watch."""
    monkeypatch.setenv(_FLAG, "true")
    latest = _latest(
        direction="BUY",
        price_position="MAIN_RESISTANCE",
        phase_priced="RESISTANCE_PRESSURE_WARNING",
        selected_pattern_id="UPPER_ABSORPTION_WARNING",
        entry_permission="NO_NEW_BUY",
        management_action="PROTECT_LONG_OR_SELL_WATCH",
    )
    payload = _build_watch(latest)
    assert payload["signal_family"] == "MICROBOOST_COUNTER_ENTRY"
    assert payload["status"] in {"EARLY_SELL_WATCH", "SELL_TIMING_WATCH"}
    assert payload["raw_direction"] == "BUY"
    assert payload["candidate_direction"] == "SELL"
    assert payload["watch_direction"] == "SELL"
    assert payload["final_direction"] == "WAIT"
    assert payload["valid_for_execution"] is False
    # guardrail #6: the source block direction is never overwritten
    assert latest["direction"] == "BUY"


def test_flag_on_sell_at_support_resolves_to_buy_watch(monkeypatch):
    """Test 3 — inverse: SELL at support resolves to a BUY-side counter watch."""
    monkeypatch.setenv(_FLAG, "true")
    payload = _build_watch(
        _latest(
            direction="SELL",
            price_position="MAIN_SUPPORT",
            phase_priced="SUPPORT_PRESSURE_WARNING",
            selected_pattern_id="LOWER_ABSORPTION_WARNING",
            entry_permission="NO_NEW_SELL",
        )
    )
    assert payload["signal_family"] == "MICROBOOST_COUNTER_ENTRY"
    assert payload["status"] in {"EARLY_BUY_WATCH", "BUY_TIMING_WATCH"}
    assert payload["raw_direction"] == "SELL"
    assert payload["candidate_direction"] == "BUY"
    assert payload["final_direction"] == "WAIT"
    assert payload["valid_for_execution"] is False


def test_flag_on_no_execution_leak(monkeypatch):
    """Test 4 — even with a strong pattern, the resolved watch never becomes executable."""
    monkeypatch.setenv(_FLAG, "true")
    payload = _build_watch(
        _latest(
            direction="BUY",
            price_position="MAIN_RESISTANCE",
            phase_priced="EXHAUSTION_AT_RESISTANCE",
            selected_pattern_id="UPPER_ABSORPTION_WARNING",
            entry_permission="NO_NEW_BUY",
            management_action="PROTECT_LONG_OR_SELL_WATCH",
        )
    )
    assert payload["valid_for_execution"] is False
    assert payload["final_direction"] == "WAIT"
    assert payload["rr_status"] == "WATCH"
    assert payload["confidence_bucket"] == "MICROBOOST_WATCH_ONLY"


def test_flag_on_insufficient_pattern_stays_generic(monkeypatch):
    """Test 5 — a directional block with no counter context stays a generic MICROBOOST_WATCH."""
    monkeypatch.setenv(_FLAG, "true")
    payload = _build_watch(
        _latest(
            direction="BUY",
            price_position="MID_RANGE",
            phase_priced="NEUTRAL",
        )
    )
    assert payload["status"] == "MICROBOOST_WATCH"
    assert payload["signal_family"] == "MICROBOOST_WATCH"
    assert payload["candidate_direction"] == "BUY"
