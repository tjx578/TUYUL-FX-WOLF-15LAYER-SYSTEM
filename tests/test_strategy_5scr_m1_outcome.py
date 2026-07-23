from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from analysis.strategy_5scr_m1_outcome import classify_strategy_5scr_m1_outcome
from analysis.strategy_5scr_replay import Strategy5SCRReplay
from contracts.canonical_candle import CanonicalCandle
from contracts.strategy_5scr_pressure import Strategy5SCRTradePlan

DECISION_AT = datetime(2026, 7, 24, 8, 0, tzinfo=UTC)


def _plan(*, direction: str = "BUY") -> Strategy5SCRTradePlan:
    prices = (
        {"entry": 1.1000, "stop_loss": 1.0990, "tp1": 1.1015}
        if direction == "BUY"
        else {"entry": 1.1000, "stop_loss": 1.1010, "tp1": 1.0985}
    )
    # The classifier deliberately needs only the immutable price path fields.
    return Strategy5SCRTradePlan.model_construct(
        tradeplan_id="5scr-plan:" + "a" * 32,
        symbol="EURUSD",
        direction=direction,
        decision_at_utc=DECISION_AT,
        **prices,
    )


def _m1(
    minute: int,
    *,
    high: float = 1.1005,
    low: float = 1.0995,
    provider: str = "mt5_history",
    complete: bool = True,
) -> CanonicalCandle:
    open_time = DECISION_AT + timedelta(minutes=minute)
    return CanonicalCandle(
        symbol="EURUSD",
        timeframe="M1",
        open_time=open_time,
        close_time=open_time + timedelta(minutes=1),
        open=1.1000,
        high=high,
        low=low,
        close=1.1001,
        volume=100,
        tick_count=20,
        complete=complete,
        provider=provider,
        provider_timestamp_semantics="CANONICAL_WINDOW",
    )


def test_buy_tp1_is_classified_at_first_touch_and_stops_scanning() -> None:
    outcome = classify_strategy_5scr_m1_outcome(
        _plan(),
        [_m1(0), _m1(1, high=1.1016), _m1(2, low=1.0988)],
    )

    assert outcome.status == "TP1_FIRST"
    assert outcome.realized_r == pytest.approx(1.5)
    assert outcome.bars_evaluated == 2
    assert outcome.terminal_candle == _m1(1, high=1.1016)
    assert outcome.valid_for_execution is False


def test_sell_stop_is_classified_at_first_touch() -> None:
    outcome = classify_strategy_5scr_m1_outcome(
        _plan(direction="SELL"),
        [_m1(0), _m1(1, high=1.1011)],
    )

    assert outcome.status == "SL_FIRST"
    assert outcome.realized_r == -1.0
    assert outcome.bars_evaluated == 2


def test_same_candle_tp1_and_stop_is_explicitly_ambiguous() -> None:
    outcome = classify_strategy_5scr_m1_outcome(
        _plan(),
        [_m1(0, high=1.1016, low=1.0989)],
    )

    assert outcome.status == "AMBIGUOUS_SAME_CANDLE"
    assert outcome.realized_r is None
    assert outcome.terminal_candle is not None


def test_no_touch_at_horizon_is_timeout() -> None:
    until = DECISION_AT + timedelta(minutes=2)
    outcome = classify_strategy_5scr_m1_outcome(
        _plan(),
        [_m1(0), _m1(1), _m1(2, high=1.1016)],
        until_utc=until,
    )

    assert outcome.status == "TIMEOUT"
    assert outcome.bars_evaluated == 2
    assert outcome.evaluated_until_utc == until
    assert outcome.terminal_candle is None


def test_empty_legal_horizon_is_no_data() -> None:
    outcome = classify_strategy_5scr_m1_outcome(_plan(), [])

    assert outcome.status == "NO_DATA"
    assert outcome.bars_evaluated == 0
    assert outcome.first_bar_open_utc is None
    assert outcome.last_bar_close_utc is None


def test_replay_excludes_candle_that_started_before_decision() -> None:
    straddling = _m1(0).model_copy(
        update={
            "open_time": DECISION_AT - timedelta(seconds=30),
            "close_time": DECISION_AT + timedelta(seconds=30),
            "high": 1.1016,
        }
    )
    replay = Strategy5SCRReplay([straddling, _m1(1)])

    outcome = replay.classify_m1_outcome(tradeplan=_plan())

    assert outcome.status == "TIMEOUT"
    assert outcome.bars_evaluated == 1
    assert outcome.first_bar_open_utc == DECISION_AT + timedelta(minutes=1)


def test_incomplete_and_wrong_symbol_candles_are_not_outcome_data() -> None:
    incomplete = _m1(0, high=1.1016, complete=False)
    wrong_symbol = _m1(1, high=1.1016).model_copy(update={"symbol": "GBPUSD"})

    outcome = classify_strategy_5scr_m1_outcome(_plan(), [incomplete, wrong_symbol])

    assert outcome.status == "NO_DATA"


def test_conflicting_canonical_candles_fail_closed() -> None:
    first = _m1(0, provider="finnhub")
    conflicting = _m1(0, high=1.1007, provider="mt5_history")

    with pytest.raises(ValueError, match="conflicting canonical M1 candles"):
        classify_strategy_5scr_m1_outcome(_plan(), [first, conflicting])


def test_outcome_id_is_deterministic_for_same_frozen_inputs() -> None:
    plan = _plan()
    candles = [_m1(0), _m1(1, high=1.1016)]

    first = classify_strategy_5scr_m1_outcome(plan, candles)
    second = classify_strategy_5scr_m1_outcome(plan, reversed(candles))

    assert first == second
    assert first.outcome_id.startswith("5scr-outcome:")
