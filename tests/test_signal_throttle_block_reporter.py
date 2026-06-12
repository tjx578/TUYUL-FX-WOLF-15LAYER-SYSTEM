"""Pure-stage SignalThrottle block reporter contract (ST-001..ST-010)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from analysis.signal_throttle_block_reporter import (
    build_block_event,
    build_finalized_block_events,
    classify_duration,
    is_price_check_required,
    is_timing_valid,
)
from analysis.signal_throttle_log_analyzer import SignalThrottleLogEvent, build_pressure_blocks

_START = datetime(2026, 5, 8, 12, 0, tzinfo=UTC)


def _event(offset_seconds: int, symbol: str, direction: str | None = None) -> SignalThrottleLogEvent:
    verdict = f"EXECUTE_{direction}" if direction else None
    return SignalThrottleLogEvent(
        timestamp=_START + timedelta(seconds=offset_seconds),
        severity="error",
        message=f"[SignalThrottle] {symbol} THROTTLED",
        symbol=symbol,
        event_type="THROTTLED",
        verdict=verdict,
        direction=direction,
    )


# ST-004: a large time gap does NOT split a same-pair block.
def test_same_pair_large_gap_stays_one_block():
    events = [
        _event(0, "USDJPY"),
        _event(60, "USDJPY"),
        _event(300, "USDJPY"),  # 240s gap (> 75s) must not split
        _event(540, "USDJPY"),
    ]

    result = build_finalized_block_events(events)

    assert len(result) == 1
    block = result[0]
    assert block["symbol"] == "USDJPY"
    assert block["event_count"] == 4
    assert block["interrupted_by_pair"] is None
    assert block["max_gap_seconds"] == 240.0


# ST-003: a different pair ends the block and is recorded as the interrupter.
def test_other_pair_interrupts_block():
    events = [
        _event(0, "USDJPY"),
        _event(60, "USDJPY"),
        _event(120, "EURJPY"),
        _event(180, "EURJPY"),
    ]

    result = build_finalized_block_events(events)
    by_symbol = {event["symbol"]: event for event in result}

    assert by_symbol["USDJPY"]["interrupted_by_pair"] == "EURJPY"
    assert by_symbol["USDJPY"]["event"] == "signal_throttle_block_finalized"
    assert by_symbol["EURJPY"]["interrupted_by_pair"] is None


# ST-005 / tier ladder.
def test_classify_duration_tiers():
    assert classify_duration(299) == "PRE_VALID"
    assert classify_duration(300) == "TIMING_VALID"
    assert classify_duration(600) == "SUSTAINED"
    assert classify_duration(1200) == "DOMINANT"
    assert classify_duration(1800) == "MAJOR"
    assert classify_duration(7200) == "MAJOR"


def test_is_timing_valid_gate():
    assert is_timing_valid(299.9) is False
    assert is_timing_valid(300.0) is True


# ST-007: direction is ALWAYS UNRESOLVED, raw pressure preserved separately.
def test_direction_always_unresolved_raw_preserved():
    events = [
        _event(0, "GBPCAD", direction="BUY"),
        _event(120, "GBPCAD", direction="BUY"),
        _event(330, "GBPCAD", direction="BUY"),  # >= 5m block
    ]

    block = build_finalized_block_events(events)[0]

    assert block["direction"] == "UNRESOLVED"
    assert block["raw_pressure_direction"] == "BUY"
    assert block["timing_valid"] is True
    assert block["block_status"] == "TIMING_VALID"


def test_raw_pressure_direction_none_when_absent():
    events = [_event(0, "USDCAD"), _event(330, "USDCAD")]

    block = build_finalized_block_events(events)[0]

    assert block["direction"] == "UNRESOLVED"
    assert block["raw_pressure_direction"] == "NONE"


# ST-008 / price-check gating.
def test_price_check_required_matrix():
    assert is_price_check_required(900, finalized=False) is False
    assert is_price_check_required(299, finalized=True) is False
    assert is_price_check_required(300, finalized=True) is True


def test_finalized_below_gate_defers_price_check():
    [block] = build_pressure_blocks(
        [_event(0, "EURCHF"), _event(120, "EURCHF")],  # 2m, below gate
        max_gap_seconds=None,
    )
    event = build_block_event(block, finalized=True)

    assert event["price_check_required"] is False
    assert event["next_stage"] == "WAIT_MORE_PRESSURE"
    assert event["block_status"] == "PRE_VALID"


def test_finalized_above_gate_requests_price_check():
    [block] = build_pressure_blocks(
        [_event(0, "EURCHF"), _event(360, "EURCHF")],  # 6m, above gate
        max_gap_seconds=None,
    )
    event = build_block_event(block, finalized=True)

    assert event["price_check_required"] is True
    assert event["next_stage"] == "PRICE_STRUCTURE_ANALYSIS"
    assert event["timing_valid"] is True


# Forming block (update) never requests a price check, even when timing-valid.
def test_forming_block_update_never_requests_price_check():
    [block] = build_pressure_blocks(
        [_event(0, "USDCHF"), _event(360, "USDCHF")],
        max_gap_seconds=None,
    )
    event = build_block_event(block, finalized=False)

    assert event["event"] == "signal_throttle_block_update"
    assert event["price_check_required"] is False
    assert event["direction"] == "UNRESOLVED"
