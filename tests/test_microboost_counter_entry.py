from __future__ import annotations

import pytest

from analysis.market_context_validator import MarketContext
from analysis.microboost_counter_entry import CounterEntryStatus, MicroboostCounterEntryEngine


def _cluster(**overrides):
    payload = {
        "symbol": "GBPCAD",
        "direction": "BUY",
        "phase_unpriced": "NEAR_TIMING_GATE_MICROBOOST",
        "phase_priced": "RESISTANCE_PRESSURE_WARNING",
        "effective_density_per_minute": 15.58,
        "effective_tick_count": 47,
        "duration_seconds": 180.989,
        "price_at_signal_start": 1.84556,
        "price_at_signal_end": 1.846005,
        "end_utc": "2026-05-19T10:24:13+00:00",
    }
    payload.update(overrides)
    return payload


def _market(**overrides):
    payload = {
        "symbol": "GBPCAD",
        "raw_allowed_direction": "BUY",
        "pip_value": 0.0001,
        "price_at_signal_start": 1.84556,
        "price_at_5m_confirm": 1.846005,
        "price_at_signal_end": 1.846005,
        "m15_phase": "BULLISH_PULLBACK",
        "h1_phase": "BULLISH",
        "theme_aligned": True,
        "spread_normal": True,
        "price_position": "MAIN_RESISTANCE",
        "resistance_low": 1.8460,
        "resistance_high": 1.8478,
        "minor_support": 1.8450,
        "major_support": 1.8409,
        "m15_close_above_resistance": False,
        "m15_rejection_from_resistance": False,
        "m15_close_below_minor_support": False,
        "sl_buffer": 0.0007,
        "tp1_support": 1.8420,
        "tp2_support": 1.8409,
        "tp3_support": 1.8378,
    }
    payload.update(overrides)
    return MarketContext(**payload)


def test_buy_microboost_at_main_resistance_becomes_sell_watch():
    result = MicroboostCounterEntryEngine().evaluate(_cluster(duration_seconds=120.0), _market())

    assert result.enabled is True
    assert result.status == CounterEntryStatus.SELL_TIMING_WATCH
    assert result.candidate_direction == "SELL"
    assert result.final_direction == "WAIT"
    assert result.action == "WAIT_REJECTION_OR_MINOR_SUPPORT_BREAK"
    assert result.aggressive_trigger == 1.845
    assert result.conservative_trigger == 1.8409
    assert result.sl_tight == 1.8485


def test_rejection_confirms_sell_timing_valid():
    result = MicroboostCounterEntryEngine().evaluate(
        _cluster(),
        _market(m15_rejection_from_resistance=True, m15_close_below_minor_support=True),
    )

    assert result.enabled is True
    assert result.status == CounterEntryStatus.SELL_TIMING_VALID
    assert result.candidate_direction == "SELL"
    assert result.final_direction == "SELL"
    assert result.direction_status == "MICROBOOST_COUNTER_ENTRY_VALIDATED"
    assert result.action == "SELL_AT_SIGNAL_VALID_PRICE_OR_RETEST"
    assert result.trade_plan is not None
    assert result.trade_plan["direction"] == "SELL"
    assert result.rr_status == "VALID"


def test_breakout_blocks_counter_sell():
    result = MicroboostCounterEntryEngine().evaluate(
        _cluster(),
        _market(m15_close_above_resistance=True),
    )

    assert result.enabled is False
    assert result.status == CounterEntryStatus.BREAKOUT_CONTINUATION_BUY
    assert result.candidate_direction == "BUY"
    assert result.action == "WAIT_RETEST_BUY"


def test_usdcad_zero_expansion_density_becomes_nano_absorption_sell_watch():
    cluster = _cluster(
        symbol="USDCAD",
        phase_unpriced="REPEATED_MICROBOOST",
        effective_density_per_minute=43.61,
        effective_tick_count=6,
        duration_seconds=8.255,
        price_at_signal_start=1.37696,
        price_at_signal_end=1.37696,
        end_utc="2026-05-19T14:56:05.369128+00:00",
    )
    market = _market(
        symbol="USDCAD",
        price_at_signal_start=1.37696,
        price_at_5m_confirm=1.37696,
        price_at_signal_end=1.37696,
        m15_phase="BEARISH_PULLBACK",
        resistance_low=1.3760,
        resistance_high=1.3774,
        minor_support=1.3756,
        major_support=1.3735,
        sl_buffer=0.0008,
        tp1_support=1.3756,
        tp2_support=1.3735,
        tp3_support=1.3718,
        tp4_support=1.3700,
    )

    result = MicroboostCounterEntryEngine().evaluate(cluster, market)

    assert result.status == CounterEntryStatus.NANO_ABSORPTION_SELL_WATCH
    assert result.candidate_direction == "SELL"
    assert result.entry_reference_price == 1.37696
    assert result.entry_zone == [1.37696, 1.37696]
    assert result.sl_tight == 1.3782
    assert result.sl_safe == 1.379
    assert result.tp1 == 1.3756
    assert result.tp2 == 1.3735
    assert result.tp3 == 1.3718
    assert result.tp4 == 1.37
    assert result.rr_to_tp2_tight == pytest.approx(2.79)
    assert result.rr_to_tp3_tight == pytest.approx(4.16)


def test_audcad_mature_near_timing_gate_stalled_at_resistance_is_sell_timing_valid():
    cluster = _cluster(
        symbol="AUDCAD",
        phase_unpriced="NEAR_TIMING_GATE_MICROBOOST",
        effective_density_per_minute=28.76,
        effective_tick_count=87,
        duration_seconds=181.502,
        price_at_signal_start=0.98504,
        price_at_signal_end=0.98504,
        end_utc="2026-05-18T20:33:08+00:00",
    )
    market = _market(
        symbol="AUDCAD",
        price_at_signal_start=0.98504,
        price_at_5m_confirm=0.98504,
        price_at_signal_end=0.98504,
        resistance_low=0.9850,
        resistance_high=0.9859,
        minor_support=0.9845,
        major_support=0.9820,
        m15_rejection_from_resistance=False,
        m15_close_below_minor_support=False,
        sl_buffer=0.0006,
        tp1_support=0.9820,
        tp2_support=0.9780,
        tp3_support=0.9746,
        tp4_support=0.9700,
    )

    result = MicroboostCounterEntryEngine().evaluate(cluster, market)

    assert result.status == CounterEntryStatus.SELL_TIMING_VALID
    assert result.validated_direction == "SELL"
    assert result.final_direction == "SELL"
    assert result.action == "SELL_AT_SIGNAL_VALID_PRICE_OR_RETEST"
    assert result.signal_valid_price == 0.98504
    assert result.sl_tight == 0.9865
    assert result.tp1 == 0.982
    assert result.tp2 == 0.978
    assert result.tp3 == 0.9746
    assert result.rr_to_tp2_tight == pytest.approx(4.82)
    assert result.rr_status == "VALID"
    assert result.signal_valid_time_wita == "2026-05-19 04:33:08"


def test_cadjpy_missing_support_ladder_uses_rr_fallback_without_validating():
    cluster = _cluster(
        symbol="CADJPY",
        phase_unpriced="NEAR_TIMING_GATE_MICROBOOST",
        effective_density_per_minute=13.31,
        effective_tick_count=55,
        duration_seconds=247.8,
        price_at_signal_start=115.685,
        price_at_signal_end=115.685,
        end_utc="2026-05-19T20:05:57.041112+00:00",
    )
    market = _market(
        symbol="CADJPY",
        pip_value=0.01,
        price_at_signal_start=115.685,
        price_at_5m_confirm=115.685,
        price_at_signal_end=115.685,
        price_position="MAIN_RESISTANCE",
        resistance_low=None,
        resistance_high=None,
        minor_support=None,
        major_support=None,
        m15_rejection_from_resistance=True,
        m15_close_below_minor_support=True,
        tp1_support=None,
        tp2_support=None,
        tp3_support=None,
        tp4_support=None,
        support_ladder_ready=False,
        support_ladder_missing_reason="NO_M15_H1_SUPPORT_LEVELS",
    )

    result = MicroboostCounterEntryEngine().evaluate(cluster, market)

    assert result.status == CounterEntryStatus.SELL_TIMING_WATCH
    assert result.final_direction == "WAIT"
    assert result.valid_for_execution is False
    assert result.target_mode == "PROVISIONAL_RR_FALLBACK"
    assert result.tp_status == "WATCH_PROVISIONAL"
    assert result.tp_missing_reason == "NO_M15_H1_SUPPORT_LEVELS"
    assert result.rr_status == "WATCH_PROVISIONAL"
    assert result.support_ladder_ready is False
    assert result.sl_tight == 115.805
    assert result.tp1 == 115.565
    assert result.tp2 == 115.445
    assert result.tp3 == 115.385
    assert result.tp4 == 115.325
    assert result.tp_min_rr == 115.385
    assert result.tp3_rr == 2.5


def test_structure_targets_below_min_rr_do_not_promote_to_valid():
    cluster = _cluster(
        symbol="CADJPY",
        phase_unpriced="NEAR_TIMING_GATE_MICROBOOST",
        effective_density_per_minute=13.31,
        duration_seconds=247.8,
        price_at_signal_start=115.685,
        price_at_signal_end=115.685,
    )
    market = _market(
        symbol="CADJPY",
        pip_value=0.01,
        price_at_signal_start=115.685,
        price_at_5m_confirm=115.685,
        price_at_signal_end=115.685,
        price_position="MAIN_RESISTANCE",
        resistance_high=None,
        minor_support=115.60,
        major_support=115.50,
        m15_rejection_from_resistance=True,
        m15_close_below_minor_support=True,
        sl_buffer=None,
        tp1_support=115.60,
        tp2_support=115.50,
        tp3_support=None,
        tp4_support=None,
    )

    result = MicroboostCounterEntryEngine().evaluate(cluster, market)

    assert result.status == CounterEntryStatus.SELL_TIMING_WATCH
    assert result.final_direction == "WAIT"
    assert result.rr_status == "FAIL_MIN_RR"
    assert result.target_mode == "FINAL_MARKET_STRUCTURE"
    assert result.structure_targets_available is True
    assert result.valid_for_execution is False
