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
        "tp3_support": 1.8370,
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
        _market(h1_phase="BEARISH", m15_rejection_from_resistance=True, m15_close_below_minor_support=True),
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
    assert result.tradeplan_context_ready is True
    assert result.key_resistance == 1.8478
    assert result.key_support == 1.845
    assert result.selected_sl_mode == "SAFE"
    assert result.selected_risk_pips is not None
    assert result.invalidation_rules is not None
    assert result.invalidation_rules["hard_invalid_level"] == result.selected_sl


def test_m15_breakout_confirms_buy_continuation_from_resistance_watch():
    result = MicroboostCounterEntryEngine().evaluate(
        _cluster(),
        _market(m15_close_above_resistance=True),
    )

    assert result.enabled is True
    assert result.status == CounterEntryStatus.BUY_BREAKOUT_CONTINUATION_VALID
    assert result.candidate_direction == "BUY"
    assert result.final_direction == "BUY"
    assert result.action == "BUY_BREAKOUT_RETEST"
    assert result.rr_status == "VALID"
    assert result.target_mode == "PROVISIONAL_RR_FALLBACK"
    assert result.valid_for_execution is True
    assert result.tp1_rr == 2.0
    assert result.tp2_rr == 2.5


def test_initial_microboost_pass_stays_watch_only_even_when_m15_breakout_is_present():
    result = MicroboostCounterEntryEngine().evaluate(
        _cluster(
            phase_unpriced="NEAR_TIMING_GATE_MICROBOOST",
            duration_seconds=181.0,
            effective_density_per_minute=20.0,
            price_at_signal_start=1.846005,
            price_at_signal_end=1.846005,
        ),
        _market(m15_close_above_resistance=True),
        watch_only=True,
    )

    assert result.status == CounterEntryStatus.SELL_ABSORPTION_WATCH
    assert result.final_direction == "WAIT"
    assert result.valid_for_execution is False
    assert result.requires_m15_close is True


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
    assert result.tp1 == 1.37288
    assert result.tp2 == 1.3718
    assert result.tp3 == 1.37
    assert result.tp4 is None
    assert result.tp1_rr == 2.0
    assert result.rr_to_tp2_tight == pytest.approx(4.16)
    assert result.rr_to_tp3_tight == pytest.approx(5.61)


def test_audcad_mature_near_timing_gate_stalled_at_resistance_waits_for_m15_close():
    cluster = _cluster(
        symbol="AUDCAD",
        phase_unpriced="NEAR_TIMING_GATE_MICROBOOST",
        effective_density_per_minute=28.76,
        effective_tick_count=87,
        duration_seconds=181.502,
        price_at_signal_start=0.98504,
        price_at_signal_end=0.98504,
        h1_phase="BEARISH",
        end_utc="2026-05-18T20:33:08+00:00",
    )
    market = _market(
        symbol="AUDCAD",
        price_at_signal_start=0.98504,
        price_at_5m_confirm=0.98504,
        price_at_signal_end=0.98504,
        h1_phase="BEARISH",
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

    assert result.status == CounterEntryStatus.SELL_ABSORPTION_WATCH
    assert result.validated_direction == "SELL"
    assert result.final_direction == "WAIT"
    assert result.direction_status == "MICROBOOST_COUNTER_ENTRY_ABSORPTION_WATCH"
    assert result.action == "WAIT_M15_CLOSE_CONFIRMATION"
    assert result.requires_rejection_or_breakdown is True
    assert result.signal_valid_price == 0.98504
    assert result.sl_tight == 0.9865
    assert result.tp1 == 0.98012
    assert result.tp2 == 0.978
    assert result.tp3 == 0.9746
    assert result.rr_to_tp2_tight == pytest.approx(4.82)
    assert result.rr_status == "WATCH"
    assert result.signal_valid_time_wita == "2026-05-19 04:33:08"


def test_audcad_complete_absorption_with_theme_and_structure_direct_validates_without_m15_close():
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
        h1_phase="BEARISH",
        theme_alignment="STRONG_SELL",
        m15_close=None,
        m15_rejection_from_resistance=False,
        m15_close_below_minor_support=False,
        sl_buffer=0.0006,
        tp1_support=0.9820,
        tp2_support=0.9780,
        tp3_support=0.9746,
        tp4_support=0.9700,
    )

    result = MicroboostCounterEntryEngine().evaluate(cluster, market)

    assert result.status == CounterEntryStatus.SELL_TIMING_VALID_BY_DIRECT_ABSORPTION
    assert result.validated_direction == "SELL"
    assert result.final_direction == "SELL"
    assert result.action == "SELL_AT_SIGNAL_VALID_PRICE_OR_RETEST"
    assert result.confirmation_policy == "DIRECT_ABSORPTION_NO_M15_WAIT"
    assert result.requires_m15_close is False
    assert result.direct_valid_reason == "mature_absorption_with_theme_structure_and_rr"
    assert result.pending_decision_id is None
    assert result.structure_ready is True
    assert result.rr_status == "VALID"
    assert result.valid_for_execution is True


def test_audcad_m15_close_confirms_absorption_as_sell_timing_valid():
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
        price_at_5m_confirm=0.9848,
        price_at_signal_end=0.9848,
        h1_phase="BEARISH",
        m15_close=0.9848,
        resistance_low=0.9850,
        resistance_high=0.9859,
        minor_support=0.9845,
        major_support=0.9820,
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
    assert result.rr_status == "VALID"
    assert result.valid_for_execution is True


def test_cadjpy_near_timing_gate_absorption_waits_for_m15_close_without_final_execution():
    cluster = _cluster(
        symbol="CADJPY",
        phase_unpriced="NEAR_TIMING_GATE_MICROBOOST",
        effective_density_per_minute=24.84,
        effective_tick_count=75,
        duration_seconds=181.183,
        price_at_signal_start=115.7055,
        price_at_signal_end=115.7055,
        end_utc="2026-05-19T06:18:21+00:00",
    )
    market = _market(
        symbol="CADJPY",
        pip_value=0.01,
        price_at_signal_start=115.7055,
        price_at_5m_confirm=115.7055,
        price_at_signal_end=115.7055,
        price_position="MAIN_RESISTANCE",
        resistance_low=None,
        resistance_high=None,
        minor_support=None,
        major_support=None,
        m15_rejection_from_resistance=False,
        m15_close_below_minor_support=False,
        sl_buffer=None,
        tp1_support=None,
        tp2_support=None,
        tp3_support=None,
        tp4_support=None,
        support_ladder_ready=False,
        support_ladder_missing_reason="NO_M15_H1_SUPPORT_LEVELS",
    )

    result = MicroboostCounterEntryEngine().evaluate(cluster, market)

    assert result.status == CounterEntryStatus.SELL_ABSORPTION_WATCH
    assert result.direction_status == "MICROBOOST_COUNTER_ENTRY_ABSORPTION_WATCH"
    assert result.validated_direction == "SELL"
    assert result.final_direction == "WAIT"
    assert result.action == "WAIT_M15_CLOSE_CONFIRMATION"
    assert result.requires_rejection_or_breakdown is True
    assert result.valid_for_execution is False
    assert result.tradeplan_context_ready is False
    assert result.target_mode == "PROVISIONAL_RR_FALLBACK"
    assert result.tp_status == "WATCH_PROVISIONAL"
    assert result.tp_missing_reason == "NO_M15_H1_SUPPORT_LEVELS"
    assert result.rr_status == "WATCH_PROVISIONAL"
    assert result.confirmation_policy == "M15_CLOSE_REQUIRED"
    assert result.requires_m15_close is True
    assert result.pending_decision_id == "CADJPY_M15_DECISION"
    assert result.signal_valid_price == 115.7055
    assert result.sl_tight == 115.8255
    assert result.tp1 == 115.3055
    assert result.tp2 is None
    assert result.tp3 is None
    assert result.tp4 is None
    assert result.tp_min_rr == 115.2055
    assert result.tp1_rr == 2.0
    assert result.confidence_bucket == "B_ABSORPTION_WATCH"
    assert result.signal_valid_time_wita == "2026-05-19 14:18:21"


def test_cadjpy_m15_close_confirms_absorption_but_missing_structure_keeps_execution_wait():
    cluster = _cluster(
        symbol="CADJPY",
        phase_unpriced="NEAR_TIMING_GATE_MICROBOOST",
        effective_density_per_minute=24.84,
        effective_tick_count=75,
        duration_seconds=181.183,
        price_at_signal_start=115.7055,
        price_at_signal_end=115.7055,
        end_utc="2026-05-19T06:18:21+00:00",
    )
    market = _market(
        symbol="CADJPY",
        pip_value=0.01,
        price_at_signal_start=115.7055,
        price_at_5m_confirm=115.695,
        price_at_signal_end=115.695,
        m15_close=115.695,
        price_position="MAIN_RESISTANCE",
        resistance_low=None,
        resistance_high=None,
        minor_support=None,
        major_support=None,
        m15_rejection_from_resistance=False,
        m15_close_below_minor_support=False,
        sl_buffer=None,
        tp1_support=None,
        tp2_support=None,
        tp3_support=None,
        tp4_support=None,
        support_ladder_ready=False,
        support_ladder_missing_reason="NO_M15_H1_SUPPORT_LEVELS",
    )

    result = MicroboostCounterEntryEngine().evaluate(cluster, market)

    assert result.status == CounterEntryStatus.SELL_TIMING_VALID_BY_ABSORPTION
    assert result.direction_status == "MICROBOOST_COUNTER_ENTRY_TIMING_VALID"
    assert result.validated_direction == "SELL"
    assert result.final_direction == "WAIT"
    assert result.action == "WAIT_STRUCTURE_TARGET_OR_RETEST"
    assert result.requires_rejection_or_breakdown is False
    assert result.valid_for_execution is False
    assert result.target_mode == "PROVISIONAL_RR_FALLBACK"
    assert result.rr_status == "WATCH_PROVISIONAL"
    assert result.confirmation_policy == "M15_CLOSE_CONFIRMED"
    assert result.requires_m15_close is False
    assert result.pending_decision_id is None
    assert result.confidence_bucket == "B_TIMING_VALID_CONDITIONAL"


def test_nzdjpy_mature_resistance_absorption_watch_waits_for_m15_close():
    cluster = _cluster(
        symbol="NZDJPY",
        phase_unpriced="NEAR_TIMING_GATE_MICROBOOST",
        effective_density_per_minute=19.25,
        effective_tick_count=61,
        duration_seconds=190.0,
        price_at_signal_start=92.8825,
        price_at_signal_end=92.8825,
        end_utc="2026-05-20T08:48:20+00:00",
    )
    market = _market(
        symbol="NZDJPY",
        pip_value=0.01,
        price_at_signal_start=92.8825,
        price_at_5m_confirm=92.8825,
        price_at_signal_end=92.8825,
        price_position="MAIN_RESISTANCE",
        resistance_low=92.88,
        resistance_high=93.10,
        key_resistance=93.10,
        key_support=92.70,
        buy_pullback_low=92.65,
        buy_pullback_high=92.78,
        breakout_retest_low=92.95,
        breakout_retest_high=93.10,
        sell_rejection_low=92.95,
        sell_rejection_high=93.10,
        minor_support=None,
        major_support=None,
        m15_close=None,
        m15_rejection_from_resistance=False,
        m15_close_below_minor_support=False,
        sl_buffer=None,
        tp1_support=None,
        tp2_support=None,
        tp3_support=None,
        tp4_support=None,
        support_ladder_ready=False,
        support_ladder_missing_reason="NO_M15_H1_SUPPORT_LEVELS",
    )

    result = MicroboostCounterEntryEngine().evaluate(cluster, market)

    assert result.status == CounterEntryStatus.SELL_ABSORPTION_WATCH
    assert result.final_direction == "WAIT"
    assert result.action == "WAIT_M15_CLOSE_CONFIRMATION"
    assert result.valid_for_execution is False
    assert result.target_mode == "PROVISIONAL_RR_FALLBACK"
    assert result.rr_status == "WATCH_PROVISIONAL"
    assert result.confirmation_policy == "M15_CLOSE_REQUIRED"
    assert result.requires_m15_close is True
    assert result.pending_decision_id == "NZDJPY_M15_DECISION"
    assert result.decision_watch_type == "BREAKOUT_OR_REJECTION_WATCH"
    assert result.key_resistance == 93.1
    assert result.key_support == 92.7
    assert result.breakout_reclaim_level == 93.1
    assert result.support_reclaim_level == 92.7
    assert result.pullback_buy_zone == [92.65, 92.78]
    assert result.breakout_buy_zone == [92.95, 93.1]
    assert result.sell_rejection_zone == [92.95, 93.1]
    assert "BUY valid only after pullback support hold" in str(result.buy_condition)
    assert "SELL valid only after failed breakout" in str(result.sell_condition)


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
    assert result.tp1 == 115.285
    assert result.tp2 is None
    assert result.tp3 is None
    assert result.tp4 is None
    assert result.tp_min_rr == 115.185
    assert result.tp1_rr == 2.0


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


def test_audnzd_counter_sell_exports_structure_and_waits_for_spread_normalization():
    cluster = _cluster(
        symbol="AUDNZD",
        price_at_signal_start=1.22158,
        price_at_signal_end=1.22158,
        end_utc="2026-05-25T16:59:36+00:00",
    )
    market = _market(
        symbol="AUDNZD",
        bid=1.2215,
        ask=1.2219,
        pip_value=0.0001,
        price_at_signal_start=1.22158,
        price_at_5m_confirm=1.22158,
        price_at_signal_end=1.22158,
        m15_phase="BEARISH_PULLBACK",
        h1_phase="BEARISH",
        price_position="MAIN_RESISTANCE",
        spread_normal=False,
        max_allowed_spread_pips=3.0,
        main_support=1.2170,
        main_resistance=1.2222,
        key_support=1.2170,
        key_resistance=1.2222,
        resistance_low=1.2215,
        resistance_high=1.2222,
        sell_rejection_low=1.2215,
        sell_rejection_high=1.2225,
        minor_support=1.2170,
        major_support=1.21562,
        m15_rejection_from_resistance=True,
        sl_tight=1.22295,
        sl_safe=1.22375,
        tp1_support=1.2170,
        tp2_support=1.21562,
        tp3_support=1.21492,
        tp4_support=None,
        support_ladder_ready=True,
    )

    result = MicroboostCounterEntryEngine().evaluate(cluster, market)

    assert result.analysis_valid is True
    assert result.tradeplan_valid is True
    assert result.execution_valid_now is False
    assert result.final_direction == "WAIT"
    assert result.execution_status == "WAIT_SPREAD_NORMALIZATION"
    assert result.action == "WAIT_SPREAD_NORMALIZATION"
    assert result.selected_sl_mode == "SAFE"
    assert result.selected_sl == 1.22375
    assert result.risk_pips_tight == 13.7
    assert result.risk_pips_safe == 21.7
    assert result.tp1 == 1.21724
    assert result.tp2 == 1.21562
    assert result.tp3 == 1.21492
    assert result.targets is not None
    assert [target["id"] for target in result.targets] == ["TP1", "TP2", "TP3"]
    assert result.structure_zones is not None
    assert result.structure_zones["key_resistance"] == 1.2222
    assert result.structure_zones["key_support"] == 1.2170
    assert result.invalidation_rules is not None
    assert result.invalidation_rules["hard_invalid_level"] == 1.22375


def test_sell_counter_entry_with_bullish_h1_stays_execution_wait():
    result = MicroboostCounterEntryEngine().evaluate(
        _cluster(),
        _market(m15_rejection_from_resistance=True, m15_close_below_minor_support=True),
    )

    assert result.tradeplan_valid is True
    assert result.execution_valid_now is False
    assert result.final_direction == "WAIT"
    assert result.execution_status == "WAIT_TIMEFRAME_ALIGNMENT"
    assert result.phase_coherence is not None
    assert result.phase_coherence["status"] == "H1_DIRECTION_CONFLICT"
