from __future__ import annotations

from datetime import UTC, datetime

from analysis.market_context_validator import MarketContext
from analysis.microboost_counter_entry import CounterEntryStatus, MicroboostCounterEntryEngine
from analysis.signal_lifecycle_manager import SignalLifecycleManager
from analysis.signal_price_integrity import (
    PRICE_CONTEXT_OUT_OF_RANGE,
    ObservedPrice,
    ObservedPriceRange,
    ReferencePriceLevels,
    SignalPriceContext,
    validate_signal_price_integrity,
)
from analysis.signal_throttle_log_analyzer import resolve_signal_watch_headline_from_pattern


def test_chfjpy_reference_resistance_cannot_become_current_signal_price():
    # Evaluate at the end of the observed minute so the supplied M1 range is
    # contemporaneous rather than a full-candle lookahead at 08:15:00.
    event_time = datetime(2026, 7, 10, 8, 15, 59, tzinfo=UTC)
    context = SignalPriceContext(
        symbol="CHFJPY",
        observed=ObservedPrice(
            bid=200.661,
            ask=200.663,
            mid=200.662,
            observed_at=event_time,
        ),
        market_range=ObservedPriceRange(low=200.640, high=200.673),
        references=ReferencePriceLevels(resistance=200.7375),
    )

    valid = validate_signal_price_integrity(context, evaluated_at=event_time)
    stale_reference_as_quote = validate_signal_price_integrity(
        SignalPriceContext(
            symbol="CHFJPY",
            observed=ObservedPrice(
                bid=200.7365,
                ask=200.7385,
                mid=200.7375,
                observed_at=event_time,
            ),
            market_range=context.market_range,
            references=context.references,
        ),
        evaluated_at=event_time,
    )

    assert valid.valid is True
    assert valid.signal_valid_price == 200.662
    assert valid.references.resistance == 200.7375
    assert stale_reference_as_quote.valid is False
    assert stale_reference_as_quote.reason == PRICE_CONTEXT_OUT_OF_RANGE


def test_chfjpy_raw_sell_at_support_keeps_sell_primary_and_buy_conditional():
    resolved = resolve_signal_watch_headline_from_pattern(
        raw_direction="SELL",
        price_position="MAIN_SUPPORT",
        phase_priced="SUPPORT_PRESSURE_WARNING",
        selected_pattern_id="LOWER_ABSORPTION_WARNING",
        duration_seconds=90.0,
    )

    assert resolved["status"] == "COUNTER_SCENARIO_WATCH"
    assert resolved["legacy_watch_status"] == "BUY_TIMING_WATCH"
    assert resolved["candidate_direction"] == "SELL"
    assert resolved["watch_direction"] == "SELL"
    assert resolved["counter_watch_direction"] == "BUY"
    assert resolved["counter_scenario"]["status"] == "CONDITIONAL"
    assert resolved["counter_scenario"]["requires_m15_close"] is True
    assert resolved["valid_for_execution"] is False


def test_gbpcad_absorption_without_explicit_m15_rejection_stays_wait():
    cluster = {
        "symbol": "GBPCAD",
        "direction": "BUY",
        "phase_unpriced": "NEAR_TIMING_GATE_MICROBOOST",
        "phase_priced": "RESISTANCE_PRESSURE_WARNING",
        "effective_density_per_minute": 18.0,
        "effective_tick_count": 55,
        "duration_seconds": 220.0,
        "price_at_signal_start": 1.90152,
        "price_at_signal_end": 1.90152,
        "end_utc": "2026-07-10T06:05:00+00:00",
    }
    market = MarketContext(
        symbol="GBPCAD",
        raw_allowed_direction="BUY",
        pip_value=0.0001,
        price_at_signal_start=1.90152,
        price_at_5m_confirm=1.90152,
        price_at_signal_end=1.90152,
        price_position="MAIN_RESISTANCE",
        h1_phase="BULLISH",
        resistance_low=1.9015,
        # Only the resistance known by 06:05 belongs in this fixture. The later
        # 1.90231 high from 06:19 would be future leakage.
        resistance_high=1.90180,
        minor_support=1.9010,
        major_support=1.89799,
        m15_rejection_from_resistance=False,
        m15_close_below_minor_support=False,
        sl_buffer=0.0007,
        tp1_support=1.89799,
        tp2_support=1.8965,
        support_ladder_ready=True,
    )

    result = MicroboostCounterEntryEngine().evaluate(cluster, market)

    assert result.status in {
        CounterEntryStatus.SELL_TIMING_WATCH,
        CounterEntryStatus.SELL_ABSORPTION_WATCH,
    }
    assert result.final_direction == "WAIT"
    assert result.valid_for_execution is False
    assert result.requires_m15_close is True


def test_chfjpy_direction_revisions_share_one_pressure_episode_lifecycle():
    manager = SignalLifecycleManager()
    source_clean_block_id = "CHFJPY_20260710T081500Z_PRESSURE_EPISODE"
    common = {
        "symbol": "CHFJPY",
        "source_clean_block_id": source_clean_block_id,
        "cluster_id": "CHFJPY_20260710T081500Z",
        "status": "MICROBOOST_WATCH",
        "final_direction": "WAIT",
        "valid_for_execution": False,
    }

    revisions = [
        manager.apply({**common, "raw_direction": "SELL", "candidate_direction": direction})
        for direction in ("SELL", "BUY", "SELL", "BUY")
    ]

    assert {revision["lifecycle_id"] for revision in revisions} == {source_clean_block_id}
