from __future__ import annotations

from datetime import UTC, datetime

from analysis.market_context_validator import MarketContext
from analysis.signal_block_finalizer import SignalBlockFinalizer


def _watch(**overrides):
    payload = {
        "symbol": "USDCAD",
        "cluster_id": "USDCAD_20260521T030620Z",
        "status": "SELL_ABSORPTION_WATCH",
        "signal_family": "MICROBOOST_COUNTER_ENTRY",
        "raw_direction": "BUY",
        "candidate_direction": "SELL",
        "validated_direction": "SELL",
        "final_direction": "WAIT",
        "action": "WAIT_M15_CLOSE_CONFIRMATION",
        "signal_valid_time_utc": "2026-05-21T03:09:22+00:00",
        "signal_valid_time_wita": "2026-05-21 11:09:22",
        "signal_valid_price": 1.37633,
        "entry_reference_price": 1.37633,
        "entry_zone": [1.37633, 1.37647],
        "phase_unpriced": "NEAR_TIMING_GATE_MICROBOOST",
        "phase_priced": "RESISTANCE_PRESSURE_WARNING",
        "price_position": "MAIN_RESISTANCE",
        "m15_phase": "BEARISH_PULLBACK",
        "h1_phase": "BULLISH",
        "effective_density": 45.45,
        "effective_ticks": 138,
        "duration_seconds": 182.0,
        "duration_minutes": 3.04,
        "price_delta_pips": 0.0,
        "rr_status": "WATCH",
        "target_mode": "PROVISIONAL_RR_FALLBACK",
        "market_context_applied": True,
        "valid_for_execution": False,
        "confirmation_policy": "M15_CLOSE_REQUIRED",
        "requires_m15_close": True,
        "pending_decision_id": "USDCAD_USDCAD_20260521T030620Z_M15_DECISION",
    }
    payload.update(overrides)
    return payload


def _report():
    return {
        "symbol_activity": {
            "USDCAD": {
                "latest_event_utc": "2026-05-21T03:15:04+00:00",
                "latest_block_end_utc": "2026-05-21T03:15:04+00:00",
            }
        }
    }


def _resistance_context(**overrides):
    payload = {
        "symbol": "USDCAD",
        "raw_allowed_direction": "BUY",
        "pip_value": 0.0001,
        "price_at_signal_start": 1.37647,
        "price_at_5m_confirm": 1.37633,
        "price_at_signal_end": 1.37633,
        "m15_phase": "BEARISH_PULLBACK",
        "h1_phase": "BULLISH",
        "theme_aligned": True,
        "spread_normal": True,
        "price_position": "MAIN_RESISTANCE",
        "main_resistance": 1.37647,
        "resistance_low": 1.37633,
        "resistance_high": 1.37647,
        "m15_open": 1.37650,
        "m15_high": 1.37660,
        "m15_low": 1.37610,
        "m15_close": 1.37620,
        "resistance_ladder_ready": True,
    }
    payload.update(overrides)
    return MarketContext(**payload)


def test_idle_resistance_watch_emits_decision_update_when_support_ladder_missing():
    finalizer = SignalBlockFinalizer(idle_finalize_seconds=75)
    finalizer.track(_watch())

    outputs = finalizer.finalize(
        report=_report(),
        market_contexts={
            "USDCAD": _resistance_context(
                support_ladder_ready=False,
                support_ladder_missing_reason="NO_M15_H1_SUPPORT_LEVELS",
            )
        },
        now=datetime(2026, 5, 21, 3, 16, 30, tzinfo=UTC),
    )

    assert len(outputs) == 1
    update = outputs[0]
    assert update["event"] == "signal_decision_update_json"
    assert update["status"] == "WAIT_STRUCTURE_OR_NEXT_M15"
    assert update["previous_status"] == "SELL_ABSORPTION_WATCH"
    assert update["final_direction"] == "WAIT"
    assert update["valid_for_execution"] is False
    assert update["confirmation_policy"] == "M15_CLOSE_REJECTION_CONFIRMED"
    assert update["support_ladder_ready"] is False
    assert update["target_mode"] == "PROVISIONAL_RR_FALLBACK"
    assert update["block_end_wita"] == "2026-05-21 11:15:04"


def test_idle_resistance_watch_promotes_to_final_sell_after_m15_rejection_and_ladder_ready():
    finalizer = SignalBlockFinalizer(idle_finalize_seconds=75)
    finalizer.track(
        _watch(
            signal_watch_source="SIGNAL_THROTTLE_CLEAN_BLOCK",
            source_clean_block_confirmed=True,
            source_clean_block_valid_since_utc="2026-05-21T03:05:00+00:00",
            microboost_validation_status="PASSED",
        )
    )

    outputs = finalizer.finalize(
        report=_report(),
        market_contexts={
            "USDCAD": _resistance_context(
                main_support=1.3730,
                h1_phase="BEARISH",
                minor_support=1.3738,
                major_support=1.3730,
                tp1_support=1.3738,
                tp2_support=1.3730,
                tp3_support=1.3715,
                support_ladder_ready=True,
            )
        },
        now=datetime(2026, 5, 21, 3, 16, 30, tzinfo=UTC),
    )

    assert len(outputs) == 1
    signal = outputs[0]
    assert signal["event"] != "signal_decision_update_json"
    assert signal["status"] == "SELL_TIMING_VALID"
    assert signal["final_direction"] == "SELL"
    assert signal["valid_for_execution"] is True
    assert signal["target_mode"] == "FINAL_MARKET_STRUCTURE"
    assert signal["tp1_rr"] == 2.0
    assert signal["m15_confirmation_status"] == "M15_CLOSE_REJECTION_CONFIRMED"
    assert signal["signal_watch_source"] == "SIGNAL_THROTTLE_CLEAN_BLOCK"
    assert signal["source_clean_block_confirmed"] is True
    assert signal["microboost_validation_status"] == "PASSED"
    assert finalizer.pending_symbols() == []


def test_idle_resistance_watch_holds_buy_breakout_until_structure_target_exists():
    finalizer = SignalBlockFinalizer(idle_finalize_seconds=75)
    finalizer.track(_watch())

    outputs = finalizer.finalize(
        report=_report(),
        market_contexts={
            "USDCAD": _resistance_context(
                m15_open=1.37640,
                m15_high=1.37672,
                m15_close=1.37662,
                support_ladder_ready=False,
            )
        },
        now=datetime(2026, 5, 21, 3, 16, 30, tzinfo=UTC),
    )

    assert len(outputs) == 1
    signal = outputs[0]
    assert signal["event"] == "signal_decision_update_json"
    assert signal["status"] == "WAIT_STRUCTURE_OR_NEXT_M15"
    assert signal["final_direction"] == "WAIT"
    assert signal["validated_direction"] == "SELL"
    assert signal["source_status"] == "BUY_BREAKOUT_CONTINUATION_VALID"
    assert signal["source_final_direction"] == "BUY"
    assert signal["valid_for_execution"] is False
    assert signal["target_mode"] == "PROVISIONAL_RR_FALLBACK"
    assert signal["tp1_rr"] == 2.0
    assert signal["m15_confirmation_status"] == "M15_CLOSE_ABOVE_RESISTANCE"
    assert signal["parent_watch_id"] == "USDCAD_USDCAD_20260521T030620Z_M15_DECISION"
    assert finalizer.pending_symbols() == ["USDCAD"]


def test_pending_watch_expires_after_three_m15_bars_without_confirmation():
    finalizer = SignalBlockFinalizer(idle_finalize_seconds=75, expires_after_m15_bars=3)
    finalizer.track(_watch())

    outputs = finalizer.finalize(
        report=_report(),
        market_contexts={
            "USDCAD": _resistance_context(
                m15_open=1.37630,
                m15_high=1.37642,
                m15_close=1.37634,
                support_ladder_ready=True,
            )
        },
        now=datetime(2026, 5, 21, 4, 0, 0, tzinfo=UTC),
    )

    assert len(outputs) == 1
    update = outputs[0]
    assert update["event"] == "signal_decision_update_json"
    assert update["status"] == "PENDING_WATCH_EXPIRED"
    assert update["action"] == "EXPIRE_PENDING_WATCH"
    assert update["final_direction"] == "WAIT"
    assert finalizer.pending_symbols() == []


def test_confirmed_breakout_expires_when_structure_tradeplan_never_completes():
    finalizer = SignalBlockFinalizer(idle_finalize_seconds=75, expires_after_m15_bars=3)
    finalizer.track(_watch())

    outputs = finalizer.finalize(
        report=_report(),
        market_contexts={
            "USDCAD": _resistance_context(
                m15_open=1.37640,
                m15_high=1.37672,
                m15_close=1.37662,
                support_ladder_ready=False,
            )
        },
        now=datetime(2026, 5, 21, 4, 0, 0, tzinfo=UTC),
    )

    assert len(outputs) == 1
    update = outputs[0]
    assert update["status"] == "PENDING_WATCH_EXPIRED"
    assert "tradeplan remained incomplete" in update["reason"]
    assert update["final_direction"] == "WAIT"
    assert finalizer.pending_symbols() == []
