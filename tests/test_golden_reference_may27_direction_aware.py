"""Golden reference tests — May 27 2026 direction-aware microboost counter behavior.

These lock the *intelligence* the system showed on 27 May (the owner's golden
reference): a high-density microboost stalled at a main extreme is read as a
COUNTER absorption watch in the opposite direction, while staying non-executable.

They also lock the v2 safety contract that must survive any "restore v1 language"
work: a watch is never an executable final signal.

Brain = MicroboostCounterEntryEngine (intact since 2 Jun). If direction reaches
it, it must keep producing these directional watches. See the direction-propagation
regression (Jun 8-9) where blocks reached the engine directionless and collapsed to
raw_direction_missing MICROBOOST_WATCH fallbacks.
"""

from __future__ import annotations

from analysis.microboost_counter_entry import MicroboostCounterEntryEngine
from analysis.signal_json_emitter import build_signal_json_event


def _status(result) -> str:
    return str(getattr(result.status, "value", result.status))


def _cluster(direction: str, phase_priced: str, price_position: str) -> dict:
    return {
        "symbol": "NZDCHF",
        "direction": direction,
        "phase_priced": phase_priced,
        "price_position": price_position,
        "market_context_applied": True,
        "market_context_snapshot": {
            "price_at_signal_start": 0.46490,
            "price_at_signal_end": 0.46504,
            "price_position": price_position,
            "m15_phase": "BULLISH_PULLBACK",
            "h1_phase": "BEARISH",
        },
        "m15_phase": "BULLISH_PULLBACK",
        "h1_phase": "BEARISH",
        "effective_density": 45.17,
        "effective_ticks": 8,
        "duration_seconds": 14.0,
        "end_utc": "2026-05-27T15:26:50+00:00",
        "cluster_id": "NZDCHF_20260527T152650Z",
    }


def test_golden_buy_microboost_at_resistance_is_sell_absorption_watch():
    """27 May: raw BUY pressure stalled at main resistance -> SELL timing watch, WAIT, not executable."""
    result = MicroboostCounterEntryEngine().evaluate(
        _cluster("BUY", "RESISTANCE_PRESSURE_WARNING", "MAIN_RESISTANCE"),
        watch_only=True,
    )
    assert result.signal_family == "MICROBOOST_COUNTER_ENTRY"
    assert _status(result) == "EARLY_SELL_WATCH"
    assert result.raw_direction == "BUY"
    assert result.candidate_direction == "SELL"
    assert result.final_direction == "WAIT"
    assert result.valid_for_execution is False
    assert result.requires_m15_close is True
    assert "stalled at main resistance" in (result.reason or "").lower()


def test_golden_sell_microboost_at_support_is_buy_absorption_watch():
    """Inverse: raw SELL pressure stalled at main support -> BUY timing watch, WAIT, not executable."""
    result = MicroboostCounterEntryEngine().evaluate(
        _cluster("SELL", "SUPPORT_PRESSURE_WARNING", "MAIN_SUPPORT"),
        watch_only=True,
    )
    assert result.signal_family == "MICROBOOST_COUNTER_ENTRY"
    assert _status(result) == "EARLY_BUY_WATCH"
    assert result.raw_direction == "SELL"
    assert result.candidate_direction == "BUY"
    assert result.final_direction == "WAIT"
    assert result.valid_for_execution is False
    assert result.requires_m15_close is True
    assert "stalled at main support" in (result.reason or "").lower()


def test_directionless_block_cannot_produce_counter_entry():
    """Regression contract: a directionless block starves the counter engine (NONE),
    which is why the Jun 8-10 raw_direction_missing fallback appeared. The fix
    (C2) belongs upstream — direction must reach the block, not be faked here.
    """
    result = MicroboostCounterEntryEngine().evaluate(
        _cluster("", "RESISTANCE_PRESSURE_WARNING", "MAIN_RESISTANCE"),
        watch_only=True,
    )
    assert _status(result) == "NONE"
    assert result.direction_status == "NO_COUNTER_ENTRY_CONDITION"
    assert result.candidate_direction is None


def test_golden_counter_watch_is_never_executable_signal():
    """v2 safety contract: the directional absorption watch must emit as a watch,
    never as an executable final SignalJSON (valid_for_execution stays False)."""
    result = MicroboostCounterEntryEngine().evaluate(
        _cluster("BUY", "RESISTANCE_PRESSURE_WARNING", "MAIN_RESISTANCE"),
        watch_only=True,
    )
    event = build_signal_json_event(result.to_dict())
    assert event is not None
    assert event.is_final_signal is False
    assert event.valid_for_execution is False
    assert event.final_direction == "WAIT"
    # direction-aware fields survive into the emitted envelope (v1 language)
    assert event.raw_direction == "BUY"
    assert event.candidate_direction == "SELL"
