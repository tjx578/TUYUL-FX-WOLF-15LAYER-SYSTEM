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
    assert result.tp1 == 1.3785
    assert result.tp2 == 1.381
    assert result.tp3 == 1.385
    assert result.rr_status == "VALID"
    assert result.target_mode == "FINAL_MARKET_STRUCTURE"
    assert result.valid_for_execution is True
    assert result.rr_to_tp3_tight is not None
    assert result.rr_to_tp3_tight >= 2.5
    assert result.key_support == 1.3720
    assert result.key_resistance == 1.3850
    assert result.structure_zones == {
        "price_position": "MID_RANGE",
        "entry_zone": [1.3756, 1.37567],
        "key_support": 1.3720,
        "key_resistance": 1.3850,
        "range_low": 1.3720,
        "range_high": 1.3850,
    }
    assert result.execution_quality == {
        "spread_normal": True,
        "spread_pips": None,
        "max_allowed_spread_pips": None,
    }
    assert result.promotion_path is None
    assert result.direct_valid_reason is None
    assert result.parent_watch_required is True


def test_continuation_ignores_unready_or_opposite_quorum():
    result = MicroboostContinuationEngine().evaluate(
        _cluster(),
        allowed_quorum=_quorum(direction="SELL", quorum_reached=True),
    )

    assert result.enabled is False
    assert result.status == "NONE"
    assert result.final_direction == "WAIT"


def test_continuation_fallback_targets_can_validate_fast_trend_setup():
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
    assert result.status == "BUY_TIMING_VALID_BY_QUORUM_CONTINUATION"
    assert result.target_mode == "PROVISIONAL_RR_FALLBACK"
    assert result.rr_status == "VALID"
    assert result.valid_for_execution is True
    assert result.sl_tight == 1.3744
    assert result.tp1_rr == 1.0
    assert result.tp2_rr == 2.0
    assert result.tp3_rr == 2.5
    assert result.promotion_path is None
    assert result.direct_valid_reason is None


def test_schema_v1_continuation_retains_provisional_rr_ladder():
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

    assert result.valid_for_execution is True
    assert result.tp1_rr == 1.0
