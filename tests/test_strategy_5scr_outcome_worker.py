from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from contracts.canonical_candle import CanonicalCandle
from contracts.strategy_5scr import Strategy5SCRProof
from contracts.strategy_5scr_pressure import Strategy5SCRTradePlan
from services.pressure_outbox.outcome_worker import (
    CandidateWorkItem,
    OutcomeRuntimeConfig,
    Strategy5SCROutcomeWorker,
)

DECISION = datetime(2026, 7, 24, 8, 0, tzinfo=UTC)


def _proof() -> Strategy5SCRProof:
    return Strategy5SCRProof.model_validate(
        {
            "strategy_model": "STRATEGY_5S_CR_FINAL",
            "rule_version": "5scr.final.2026-07-19",
            "rule_status": "FROZEN",
            "validation_status": "STRONG_PROVISIONAL",
            "out_of_sample_status": "NOT_YET_VALIDATED",
            "production_proven": False,
            "confirmation_policy": "H1_CLOSED_PLUS_M15_BREAK_ACCEPTANCE_OR_FAILED_RECLAIM_RETEST",
            "authority_chain": [
                "PRESSURE",
                "CONTEXT_RESOLUTION",
                "H4",
                "H1",
                "M15",
                "M1",
                "RISK",
            ],
            "pressure": {
                "selected_pair": "EURUSD",
                "lifecycle_id": "EURUSD-campaign",
                "selection_confirmed": True,
            },
            "context_resolution": {
                "status": "RESOLVED",
                "origin": "DIRECT_CONTEXT",
                "price_location": "H4_DISCOUNT",
                "liquidity_context": "SELL_SIDE_LIQUIDITY_RECLAIMED",
                "daily_bias": "BULLISH",
                "h4_structure": "BULLISH_PULLBACK",
                "allowed_playbook": "BUY_ON_CONFIRMED_BREAK_RETEST",
                "selected_playbook": "BUY_ON_CONFIRMED_BREAK_RETEST",
                "blocked_playbook": ["SELL_BREAKOUT_CHASE"],
                "scenario_allowed": True,
            },
            "h4": {
                "target_mode": "FINAL_MARKET_STRUCTURE",
                "structural_tp1": 1.1015,
                "target_room_valid": True,
            },
            "h1": {
                "direction": "BUY",
                "structure_state": "BUY_CLOSED_BREAK_CONFIRMED",
                "structure_confirmed": True,
                "candle_closed": True,
                "confirmed_at_utc": DECISION - timedelta(minutes=20),
            },
            "m15": {
                "direction": "BUY",
                "structural_break": True,
                "candle_closed": True,
                "acceptance_confirmed": True,
                "failed_reclaim_or_retest_confirmed": False,
                "rejection_candle_only": False,
                "confirmed_at_utc": DECISION - timedelta(minutes=5),
            },
            "m1": {
                "box_id": "EURUSD:m1:test",
                "box_low": 1.0998,
                "box_high": 1.1002,
                "fill_price": 1.1000,
                "return_to_box_invalidated": False,
                "formed_at_utc": DECISION - timedelta(minutes=1),
            },
            "risk": {
                "structural_sl": 1.0990,
                "sizing_basis": "STRUCTURAL_SL",
            },
        }
    )


def _tradeplan() -> Strategy5SCRTradePlan:
    return Strategy5SCRTradePlan(
        tradeplan_id="5scr-plan:" + "a" * 32,
        campaign_id="EURUSD-campaign",
        symbol="EURUSD",
        direction="BUY",
        decision_at_utc=DECISION,
        entry=1.1000,
        stop_loss=1.0990,
        tp1=1.1015,
        target_mode="FINAL_MARKET_STRUCTURE",
        rr=1.5,
        target_distance_price=0.0015,
        execution_floor_price=0.0006,
        pip_size=0.0001,
        spread_price=0.0001,
        source_pressure_event_ids=("sha256:" + "b" * 64,),
        proof=_proof(),
    )


def _m1(minute: int, *, high: float = 1.1005, low: float = 1.0995) -> CanonicalCandle:
    opened = DECISION + timedelta(minutes=minute)
    return CanonicalCandle(
        symbol="EURUSD",
        timeframe="M1",
        open_time=opened,
        close_time=opened + timedelta(minutes=1),
        open=1.1000,
        high=high,
        low=low,
        close=1.1001,
        complete=True,
        provider="finnhub_ws_tick_builder",
        provider_timestamp_semantics="CANONICAL_WINDOW",
    )


class _Repository:
    def __init__(self) -> None:
        self.outcomes: list[Any] = []

    async def load_pending(self, *, limit: int) -> tuple[CandidateWorkItem, ...]:
        assert limit == 10
        return (CandidateWorkItem(_tradeplan()),)

    async def record_outcome(self, outcome: Any) -> bool:
        self.outcomes.append(outcome)
        return True


class _CandleStore:
    def __init__(self, candles: list[CanonicalCandle]) -> None:
        self.candles = candles

    async def load_outcome_candles(self, **_: Any) -> tuple[CanonicalCandle, ...]:
        return tuple(self.candles)


def _config() -> OutcomeRuntimeConfig:
    return OutcomeRuntimeConfig(
        enabled=True,
        poll_seconds=1,
        batch_size=10,
        horizon_minutes=240,
    )


@pytest.mark.asyncio
async def test_terminal_tp1_is_persisted_before_horizon() -> None:
    repository = _Repository()
    worker = Strategy5SCROutcomeWorker(
        repository=repository,
        candle_store=_CandleStore([_m1(0), _m1(1, high=1.1016)]),
        config=_config(),
        clock=lambda: DECISION + timedelta(minutes=2),
    )

    assert await worker.process_once() == 1
    assert repository.outcomes[0].status == "TP1_FIRST"
    assert repository.outcomes[0].valid_for_execution is False


@pytest.mark.asyncio
async def test_open_path_is_not_persisted_before_horizon() -> None:
    repository = _Repository()
    worker = Strategy5SCROutcomeWorker(
        repository=repository,
        candle_store=_CandleStore([_m1(0), _m1(1)]),
        config=_config(),
        clock=lambda: DECISION + timedelta(minutes=2),
    )

    assert await worker.process_once() == 0
    assert repository.outcomes == []


@pytest.mark.asyncio
async def test_no_data_is_persisted_only_at_bounded_horizon() -> None:
    repository = _Repository()
    worker = Strategy5SCROutcomeWorker(
        repository=repository,
        candle_store=_CandleStore([]),
        config=_config(),
        clock=lambda: DECISION + timedelta(minutes=240),
    )

    assert await worker.process_once() == 1
    assert repository.outcomes[0].status == "NO_DATA"
