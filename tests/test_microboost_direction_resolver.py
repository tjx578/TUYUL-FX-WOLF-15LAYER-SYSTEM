"""Tests for the microboost direction resolver (Step 5-6).

Pure-function tests. Inheritance NEVER promotes execution; these lock the guards
from design addendum v2 (11.1 confidence, 11.2 recent/stale/opposite, 11.3 price phase).
Events are lightweight stand-ins (only ``.symbol``/``.direction``/``.timestamp`` used).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from analysis.signal_throttle_log_analyzer import (
    _price_phase_consistency,
    resolve_microboost_direction,
)

NOW = datetime(2026, 6, 8, 4, 0, 0, tzinfo=UTC)


def _ev(symbol: str, direction: str, *, ago_seconds: float):
    return SimpleNamespace(symbol=symbol, direction=direction, timestamp=NOW - timedelta(seconds=ago_seconds))


# --------------------------------------------------------------------------- #
# resolve_microboost_direction
# --------------------------------------------------------------------------- #


def test_block_direct_high_confidence():
    out = resolve_microboost_direction({"symbol": "EURNZD", "direction": "BUY"}, events=[], now=NOW)
    assert out["direction_source"] == "BLOCK_DIRECT"
    assert out["direction_confidence"] == "HIGH"
    assert out["inherited_direction"] == "BUY"


def test_inherited_consistent_phase_is_medium():
    latest = {"symbol": "EURNZD", "direction": None, "h1_phase": "BULLISH"}
    out = resolve_microboost_direction(latest, events=[_ev("EURNZD", "BUY", ago_seconds=120)], now=NOW)
    assert out["inherited_direction"] == "BUY"
    assert out["direction_source"] == "INHERITED_FROM_PRESSURE_INTEL"
    assert out["direction_confidence"] == "MEDIUM"


def test_opposite_recent_intel_is_conflict():
    latest = {"symbol": "EURNZD", "direction": None, "h1_phase": "BULLISH"}
    events = [_ev("EURNZD", "BUY", ago_seconds=300), _ev("EURNZD", "SELL", ago_seconds=60)]
    out = resolve_microboost_direction(latest, events=events, now=NOW, window_seconds=600)
    assert out["direction_source"] == "DIRECTION_CONFLICT_RECENT_INTEL"
    assert out["direction_confidence"] == "REJECTED"
    assert out["inherited_direction"] is None


def test_stale_intel_outside_window_is_stale_not_missing():
    # Directional intel exists for the symbol but is older than the window.
    latest = {"symbol": "EURNZD", "direction": None, "h1_phase": "BULLISH"}
    out = resolve_microboost_direction(
        latest, events=[_ev("EURNZD", "BUY", ago_seconds=1200)], now=NOW, window_seconds=600
    )
    assert out["direction_source"] == "DIRECTION_STALE_INTEL"
    assert out["direction_confidence"] == "NONE"
    assert out["inherited_direction"] is None


def test_no_directional_intel_at_all_is_missing():
    latest = {"symbol": "EURNZD", "direction": None, "h1_phase": "BULLISH"}
    out = resolve_microboost_direction(latest, events=[], now=NOW, window_seconds=600)
    assert out["direction_source"] == "DIRECTION_MISSING"


def test_price_phase_conflict_rejects_inheritance():
    latest = {
        "symbol": "EURNZD",
        "direction": None,
        "price_position": "MAIN_RESISTANCE",
        "phase_priced": "RESISTANCE_PRESSURE_WARNING",
    }
    out = resolve_microboost_direction(latest, events=[_ev("EURNZD", "BUY", ago_seconds=120)], now=NOW)
    assert out["direction_source"] == "DIRECTION_CONFLICT_PRICE_PHASE"
    assert out["inherited_direction"] is None


def test_ambiguous_phase_is_low_and_requires_m15():
    latest = {"symbol": "EURNZD", "direction": None}  # no phase info -> ambiguous
    out = resolve_microboost_direction(latest, events=[_ev("EURNZD", "BUY", ago_seconds=120)], now=NOW)
    assert out["inherited_direction"] == "BUY"
    assert out["direction_source"] == "INHERITED_BUT_PHASE_AMBIGUOUS"
    assert out["direction_confidence"] == "LOW"
    assert out.get("requires_m15_close") is True


def test_other_symbol_intel_is_ignored():
    latest = {"symbol": "EURNZD", "direction": None, "h1_phase": "BULLISH"}
    out = resolve_microboost_direction(latest, events=[_ev("XAUUSD", "BUY", ago_seconds=60)], now=NOW)
    assert out["direction_source"] == "DIRECTION_MISSING"


# --------------------------------------------------------------------------- #
# _price_phase_consistency
# --------------------------------------------------------------------------- #


def test_price_phase_buy_conflict_at_resistance():
    assert (
        _price_phase_consistency(
            "BUY", m15_phase=None, h1_phase=None, price_position="MAIN_RESISTANCE", phase_priced="RESISTANCE_PRESSURE_WARNING"
        )
        == "CONFLICT"
    )


def test_price_phase_sell_conflict_at_support():
    assert (
        _price_phase_consistency(
            "SELL", m15_phase=None, h1_phase=None, price_position="MAIN_SUPPORT", phase_priced="SUPPORT_RECLAIM_WARNING"
        )
        == "CONFLICT"
    )


def test_price_phase_buy_consistent_with_bullish_h1():
    assert (
        _price_phase_consistency("BUY", m15_phase=None, h1_phase="BULLISH", price_position="MID_RANGE", phase_priced=None)
        == "CONSISTENT"
    )


def test_price_phase_ambiguous_when_neutral():
    assert (
        _price_phase_consistency("BUY", m15_phase=None, h1_phase=None, price_position="MID_RANGE", phase_priced=None)
        == "AMBIGUOUS"
    )
