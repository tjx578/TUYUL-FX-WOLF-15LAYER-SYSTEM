"""Microboost pure-stage contract (timing + location evidence, never execution)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from analysis.microboost_core_event import (
    MICROBOOST_CORE_EVENT_FIELDS,
    MICROBOOST_DOWNSTREAM_METADATA_FIELDS,
    to_microboost_core_event,
)
from analysis.microboost_detector import build_microboost_summary
from analysis.signal_throttle_log_analyzer import _signal_watch_gate

_START = datetime(2026, 5, 21, 3, 30, 6, tzinfo=UTC)


def _block(symbol: str, direction: str, *, duration_seconds: float = 120.0, events: int = 30) -> dict:
    return {
        "symbol": symbol,
        "direction": direction,
        "start": _START,
        "end": _START + timedelta(seconds=duration_seconds),
        "duration_seconds": duration_seconds,
        "events": events,
        "density_per_minute": 15.0,
        "effective_ticks": events,
        "suppressed_ticks": 0,
        "effective_density_per_minute": 15.0,
    }


def _context(price_position: str) -> dict:
    return {
        "price_position": price_position,
        "market_bias": "BUY",
        "trend_direction": "BUY",
        "m15_phase": "PIVOT_RECLAIM",
        "h1_phase": "BULLISH",
        "bid": 1.3760,
        "ask": 1.3761,
        "pip_value": 0.0001,
        "price_at_signal_start": 1.3760,
        "price_at_5m_confirm": 1.3760,
        "price_at_signal_end": 1.3760,
        "main_support": 1.3700,
        "main_resistance": 1.3800,
        "range_position": 0.5,
        "spread_normal": True,
        "spread_pips": 1.0,
        "max_allowed_spread_pips": 3.0,
    }


def _latest(symbol: str, direction: str, market_contexts: dict | None = None) -> dict:
    summary = build_microboost_summary(
        [_block(symbol, direction)],
        window_minutes=15,
        market_contexts=market_contexts or {},
    )
    assert summary["latest"] is not None
    return summary["latest"]


# Test 1 -- unpriced microboost stays timing-only without market context.
def test_unpriced_microboost_is_timing_only():
    latest = _latest("EURUSD", "BUY", market_contexts={})

    assert latest["phase_unpriced"] is not None
    assert latest["phase_priced"] is None
    assert latest["requires_market_context"] is True

    event = to_microboost_core_event(latest)
    assert event["direction"] == "UNRESOLVED"
    assert event["raw_pressure_direction"] == "BUY"


# Test 2 -- location-gated support: BUY pressure at support = buy timing evidence.
def test_location_gated_support_bounce():
    latest = _latest("EURUSD", "BUY", market_contexts={"EURUSD": _context("MAIN_SUPPORT")})

    assert latest["phase_priced"] == "SUPPORT_BOUNCE_MICROBOOST"

    event = to_microboost_core_event(latest)
    assert event["price_position"] == "MAIN_SUPPORT"
    assert event["valid_for_execution"] is False
    assert event["next_stage"] == "SIGNAL_WATCH"


# Test 3 -- location-gated resistance (USDCAD case): BUY at resistance is NOT a buy final.
def test_location_gated_resistance_is_not_buy_final():
    latest = _latest("USDCAD", "BUY", market_contexts={"USDCAD": _context("MAIN_RESISTANCE")})

    assert latest["phase_priced"] in {"RESISTANCE_PRESSURE_WARNING", "EXHAUSTION_AT_RESISTANCE"}

    event = to_microboost_core_event(latest)
    assert event["direction"] == "UNRESOLVED"
    assert event["raw_pressure_direction"] == "BUY"
    assert event["valid_for_execution"] is False


# Test 4 -- clean-block gate: microboost is not eligible without a matching clean-block pair.
def test_clean_block_gate_required():
    no_candidate = _signal_watch_gate(None, {"latest": {"symbol": "USDCAD", "direction": "BUY"}})
    assert no_candidate["eligible"] is False
    assert no_candidate["reason"] == "SIGNAL_THROTTLE_CLEAN_BLOCK_REQUIRED"

    wrong_pair = _signal_watch_gate(
        {"symbol": "USDCAD", "direction": "BUY"},
        {"latest": {"symbol": "EURUSD", "direction": "BUY"}},
    )
    assert wrong_pair["eligible"] is False
    assert wrong_pair["reason"] == "MICROBOOST_PAIR_NOT_CLEAN_BLOCK_CANDIDATE"
    assert wrong_pair["source_clean_block_id"] is None

    eligible = _signal_watch_gate(
        {"symbol": "USDCAD", "direction": "BUY", "valid_since_utc": "x"},
        {"latest": {"symbol": "USDCAD", "direction": "BUY"}},
    )
    assert eligible["eligible"] is True

    attached_lineage = _signal_watch_gate(
        {"symbol": "AUDCAD", "direction": "SELL"},
        {
            "latest": {
                "symbol": "CADJPY",
                "direction": "BUY",
                "source_clean_block_id": "CADJPY_20260708T093151Z_20260708T093654Z",
                "source_pressure_block_id": "CADJPY_20260708T093151Z_20260708T093654Z",
                "clean_block_valid": True,
                "clean_block_direction": "BUY",
                "clean_block_start_utc": "2026-07-08T09:31:51+00:00",
                "clean_block_end_utc": "2026-07-08T09:36:54+00:00",
                "clean_block_duration_seconds": 303.0,
                "clean_block_event_count": 21,
            }
        },
    )
    assert attached_lineage["eligible"] is True
    assert attached_lineage["symbol"] == "CADJPY"
    assert attached_lineage["source_clean_block_id"].startswith("CADJPY_")


# Test 5 -- no phase may ever mark the core event executable.
@pytest.mark.parametrize(
    "phase_priced",
    [
        None,
        "SUPPORT_BOUNCE_MICROBOOST",
        "RESISTANCE_PRESSURE_WARNING",
        "EXHAUSTION_AT_RESISTANCE",
        "TREND_CONTINUATION_MICROBOOST",
        "LATE_DENSE_PRESSURE",
    ],
)
def test_core_event_never_executable(phase_priced):
    event = to_microboost_core_event(
        {"symbol": "USDCAD", "direction": "BUY", "phase_priced": phase_priced}
    )
    assert event["valid_for_execution"] is False
    assert event["direction"] == "UNRESOLVED"
    assert event["next_stage"] == "SIGNAL_WATCH"


# Test 6 -- validator pass-through metadata can never leak into the core event.
def test_core_event_excludes_downstream_metadata():
    polluted = {
        "symbol": "USDCAD",
        "direction": "SELL",
        "phase_unpriced": "DENSE_MICROBOOST",
        "phase_priced": "RESISTANCE_REJECTION_MICROBOOST",
        "pattern_score": 99,
        "pattern_family": "RESISTANCE_REJECTION",
        "golden_reference": "GBPCAD_20260521",
        "execution_readiness_score": 80,
        "pattern_match_diagnostics": {"scanned": 12},
        "score_components": {"density_score": 30},
    }

    event = to_microboost_core_event(polluted)

    assert set(event).issubset(MICROBOOST_CORE_EVENT_FIELDS)
    assert MICROBOOST_DOWNSTREAM_METADATA_FIELDS.isdisjoint(event)
    assert event["raw_pressure_direction"] == "SELL"


def test_raw_pressure_direction_none_when_absent():
    event = to_microboost_core_event({"symbol": "EURUSD"})
    assert event["raw_pressure_direction"] == "NONE"
    assert event["direction"] == "UNRESOLVED"
