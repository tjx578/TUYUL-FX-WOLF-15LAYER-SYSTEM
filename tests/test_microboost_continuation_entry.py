from __future__ import annotations

from analysis.microboost_continuation_entry import MicroboostContinuationEngine


def _cluster(**overrides):
    payload = {
        "cluster_id": "USDCAD_20260520T024532Z",
        "symbol": "USDCAD",
        "direction": "BUY",
        "phase_unpriced": "IGNITION_MICROBOOST",
        "phase_priced": "TREND_CONTINUATION_MICROBOOST",
        "effective_density_per_minute": 31.68,
        "effective_tick_count": 11,
        "duration_seconds": 20.833,
        "start_utc": "2026-05-20T02:45:32+00:00",
        "end_utc": "2026-05-20T02:45:52+00:00",
        "price_position": "MID_RANGE",
        "market_context_snapshot": {
            "symbol": "USDCAD",
            "raw_allowed_direction": "BUY",
            "pip_value": 0.0001,
            "price_at_signal_start": 1.37560,
            "price_at_5m_confirm": 1.375675,
            "price_at_signal_end": 1.375675,
            "m15_phase": "BULLISH_PULLBACK",
            "h1_phase": "BULLISH",
            "theme_aligned": True,
            "spread_normal": True,
            "price_position": "MID_RANGE",
            "main_support": 1.3720,
            "main_resistance": 1.3850,
            "minor_resistance": 1.3785,
            "tp1_resistance": 1.3785,
            "tp2_resistance": 1.3810,
            "tp3_resistance": 1.3850,
            "tp4_resistance": 1.3880,
        },
    }
    payload.update(overrides)
    return payload


def _quorum(**overrides):
    payload = {
        "symbol": "USDCAD",
        "direction": "BUY",
        "streak": 3,
        "quorum_size": 3,
        "quorum_reached": True,
    }
    payload.update(overrides)
    return payload


def test_usdcad_short_mid_range_quorum_microboost_is_not_continuation_signal():
    result = MicroboostContinuationEngine().evaluate(_cluster(), allowed_quorum=_quorum())

    assert result.enabled is False
    assert result.status == "NONE"
    assert result.final_direction == "WAIT"
    assert result.action == "NO_CONTINUATION_ENTRY"


def test_usdcad_mid_range_quorum_microboost_after_one_minute_becomes_buy_continuation_valid():
    result = MicroboostContinuationEngine().evaluate(
        _cluster(
            duration_seconds=62.0,
            effective_tick_count=32,
            end_utc="2026-05-20T02:46:34+00:00",
        ),
        allowed_quorum=_quorum(),
    )

    assert result.enabled is True
    assert result.status == "BUY_TIMING_VALID_BY_QUORUM_CONTINUATION"
    assert result.signal_family == "MICROBOOST_TREND_CONTINUATION"
    assert result.validated_direction == "BUY"
    assert result.final_direction == "BUY"
    assert result.action == "BUY_SIGNAL_ZONE_OR_RETEST"
    assert result.direction_status == "MICROBOOST_QUORUM_CONTINUATION_VALIDATED"
    assert result.allowed_quorum is True
    assert result.signal_valid_price == 1.375675
    assert result.entry_zone == [1.3756, 1.37567]
    assert result.sl_tight == 1.372
    assert result.sl_safe == 1.3712
    assert result.selected_sl == 1.3712
    assert result.tp1 == 1.38462
    assert result.tp2 == 1.385
    assert result.tp3 == 1.388
    assert result.tp1_rr == 2.0
    assert result.rr_status == "VALID"
    assert result.target_mode == "FINAL_MARKET_STRUCTURE"
    assert result.valid_for_execution is True
    assert result.rr_to_tp2_tight is not None
    assert result.rr_to_tp2_tight >= 2.0
    assert result.targets is not None
    assert result.targets[2]["level"] == 1.388
    assert result.targets[2]["rr"] >= 2.5


def test_continuation_ignores_unready_or_opposite_quorum():
    result = MicroboostContinuationEngine().evaluate(
        _cluster(),
        allowed_quorum=_quorum(direction="SELL", quorum_reached=True),
    )

    assert result.enabled is False
    assert result.status == "NONE"
    assert result.final_direction == "WAIT"


def test_continuation_fallback_targets_remain_watch_without_structure_target():
    cluster = _cluster(
        duration_seconds=62.0,
        effective_tick_count=32,
        end_utc="2026-05-20T02:46:34+00:00",
        market_context_snapshot={
            "symbol": "USDCAD",
            "raw_allowed_direction": "BUY",
            "pip_value": 0.0001,
            "price_at_signal_start": 1.37560,
            "price_at_5m_confirm": 1.375675,
            "price_at_signal_end": 1.375675,
            "m15_phase": "BULLISH_PULLBACK",
            "h1_phase": "BULLISH",
            "price_position": "MID_RANGE",
        },
    )

    result = MicroboostContinuationEngine().evaluate(cluster, allowed_quorum=_quorum())

    assert result.enabled is True
    assert result.status == "BUY_CONTINUATION_TRADEPLAN_WATCH"
    assert result.target_mode == "PROVISIONAL_RR_FALLBACK"
    assert result.rr_status == "WATCH_PROVISIONAL"
    assert result.tradeplan_valid is False
    assert result.execution_valid_now is False
    assert result.valid_for_execution is False
    assert result.sl_tight == 1.3744
    assert result.tp1_rr == 2.0
    assert result.tp2_rr == 2.5
    assert result.tp3_rr == 3.0


def test_continuation_tp1_rr_floor_cannot_be_configured_below_two_r():
    cluster = _cluster(
        duration_seconds=62.0,
        market_context_snapshot={
            **_cluster()["market_context_snapshot"],
            "main_resistance": None,
            "minor_resistance": None,
            "tp1_resistance": None,
            "tp2_resistance": None,
            "tp3_resistance": None,
        },
    )

    result = MicroboostContinuationEngine(tp1_rr_required=1.0).evaluate(cluster, allowed_quorum=_quorum())

    assert result.valid_for_execution is False
    assert result.tp1_rr == 2.0
    assert result.target_policy is not None
    assert result.target_policy["tp1_rr"] == 2.0


def _gbpcad_breakout_cluster(*, retest_held: bool):
    return _cluster(
        cluster_id="GBPCAD_20260525T165847Z",
        symbol="GBPCAD",
        direction="BUY",
        phase_priced="RESISTANCE_PRESSURE_WARNING",
        duration_seconds=92.0,
        price_position="MAIN_RESISTANCE",
        price_at_signal_start=1.8636,
        price_at_signal_end=1.8636,
        end_utc="2026-05-25T16:58:47+00:00",
        market_context_snapshot={
            "symbol": "GBPCAD",
            "raw_allowed_direction": "BUY",
            "pip_value": 0.0001,
            "price_at_signal_start": 1.8636,
            "price_at_5m_confirm": 1.8641,
            "price_at_signal_end": 1.8636,
            "m15_phase": "BULLISH_PULLBACK",
            "h1_phase": "BULLISH",
            "spread_normal": True,
            "spread_pips": 3.0,
            "max_allowed_spread_pips": 4.0,
            "price_position": "MAIN_RESISTANCE",
            "main_support": 1.8569,
            "main_resistance": 1.8650,
            "key_support": 1.8616,
            "key_resistance": 1.8650,
            "breakout_retest_low": 1.8628,
            "breakout_retest_high": 1.8640,
            "continuation_sl_tight": 1.8624,
            "continuation_sl_safe": 1.8616,
            "m15_close_above_resistance": True,
            "m15_breakout_retest_held": retest_held,
            "tp1_resistance": 1.8650,
            "tp2_resistance": 1.8690,
            "tp3_resistance": 1.8730,
            "tp4_resistance": 1.8780,
            "support_ladder_ready": True,
            "resistance_ladder_ready": True,
        },
    )


def _gbpcad_quorum():
    return _quorum(symbol="GBPCAD")


def test_gbpcad_breakout_direction_builds_safe_tradeplan_but_waits_for_retest_hold():
    result = MicroboostContinuationEngine().evaluate(
        _gbpcad_breakout_cluster(retest_held=False),
        allowed_quorum=_gbpcad_quorum(),
    )

    assert result.signal_family == "MICROBOOST_BREAKOUT_CONTINUATION"
    assert result.signal_archetype == "BULLISH_BREAKOUT_RETEST_CONTINUATION"
    assert result.status == "BUY_BREAKOUT_RETEST_WATCH"
    assert result.final_direction == "WAIT"
    assert result.tradeplan_valid is True
    assert result.execution_valid_now is False
    assert result.execution_status == "WAIT_RETEST_OR_BREAKOUT_HOLD"
    assert result.selected_sl == 1.8616
    assert result.selected_risk_pips == 20.0
    assert result.tp1 == 1.8676
    assert result.tp1_rr == 2.0
    assert result.tp2 == 1.869
    assert result.tp2_rr == 2.7


def test_gbpcad_breakout_retest_hold_promotes_complete_continuation_signal():
    result = MicroboostContinuationEngine().evaluate(
        _gbpcad_breakout_cluster(retest_held=True),
        allowed_quorum=_gbpcad_quorum(),
    )

    assert result.status == "BUY_BREAKOUT_RETEST_VALID"
    assert result.final_direction == "BUY"
    assert result.tradeplan_valid is True
    assert result.execution_valid_now is True
    assert result.valid_for_execution is True
    assert result.target_mode == "FINAL_MARKET_STRUCTURE"
    assert result.invalidation_rules is not None
    assert result.invalidation_rules["hard_invalid_level"] == 1.8616
