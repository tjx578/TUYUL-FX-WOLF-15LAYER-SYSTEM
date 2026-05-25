from __future__ import annotations

from analysis.signal_lifecycle_manager import SignalLifecycleManager


def _buy_signal(**overrides):
    payload = {
        "symbol": "USDCAD",
        "status": "BUY_TIMING_VALID_BY_QUORUM_CONTINUATION",
        "signal_family": "MICROBOOST_TREND_CONTINUATION",
        "raw_direction": "BUY",
        "validated_direction": "BUY",
        "final_direction": "BUY",
        "action": "BUY_SIGNAL_ZONE_OR_RETEST",
        "signal_valid_time_utc": "2026-05-20T02:45:52+00:00",
        "signal_valid_time_wita": "2026-05-20 10:45:52",
        "signal_valid_price": 1.375675,
        "entry_reference_price": 1.375675,
        "entry_zone": [1.3745, 1.3758],
        "sl_tight": 1.3720,
        "tp1": 1.3785,
        "tp2": 1.3810,
        "tp3": 1.3850,
        "tp1_rr": 2.0,
        "rr_status": "VALID",
        "target_mode": "FINAL_MARKET_STRUCTURE",
        "valid_for_execution": True,
    }
    payload.update(overrides)
    return payload


def _sell_watch(**overrides):
    payload = {
        "symbol": "USDCAD",
        "status": "SELL_ABSORPTION_WATCH",
        "signal_family": "MICROBOOST_COUNTER_ENTRY",
        "raw_direction": "BUY",
        "candidate_direction": "SELL",
        "validated_direction": "SELL",
        "final_direction": "WAIT",
        "action": "WAIT_M15_CLOSE_CONFIRMATION",
        "signal_valid_time_utc": "2026-05-20T08:00:00+00:00",
        "signal_valid_time_wita": "2026-05-20 16:00:00",
        "signal_valid_price": 1.3772,
        "entry_reference_price": 1.3772,
        "entry_zone": [1.3772, 1.3772],
        "rr_status": "WATCH",
        "target_mode": "FINAL_MARKET_STRUCTURE",
        "tradeplan_valid": True,
        "execution_valid_now": False,
        "selected_sl": 1.3790,
        "selected_risk_pips": 18.0,
        "tp_min_rr": 1.3718,
        "tp1_rr": 2.0,
        "targets": [{"id": "TP1", "level": 1.3736, "type": "FIXED_RR", "rr": 2.0}],
        "structure_zones": {"key_resistance": 1.3774, "key_support": 1.3735},
        "invalidation_rules": {"hard_invalid_level": 1.3790},
        "execution_quality": {"spread_normal": True},
        "phase_coherence": {"h1": "BEARISH", "status": "EXECUTION_COMPATIBLE"},
        "signal_expiry": {"expires_at_utc": "2026-05-20T08:30:00+00:00"},
        "valid_for_execution": False,
        "reason": "BUY microboost stalled at main resistance.",
    }
    payload.update(overrides)
    return payload


def test_opposing_absorption_watch_protects_active_buy_without_reversal():
    manager = SignalLifecycleManager()
    active = manager.apply(_buy_signal())

    follow_up = manager.apply(_sell_watch())

    assert active["lifecycle_status"] == "ACTIVE_BUY_VALID"
    assert follow_up["status"] == "SELL_ABSORPTION_WATCH"
    assert follow_up["final_direction"] == "WAIT"
    assert follow_up["action"] == "PROTECT_BUY_PROFIT_WAIT_M15_CLOSE"
    assert follow_up["linked_previous_signal"] == active["signal_id"]
    assert follow_up["previous_signal_status"] == "ACTIVE_BUY_VALID"
    assert follow_up["lifecycle_status"] == "CONFLICT_PROTECT_ACTIVE_BUY"
    assert follow_up["valid_for_execution"] is False


def test_confirmed_opposing_sell_supersedes_active_buy_as_reversal():
    manager = SignalLifecycleManager()
    active = manager.apply(_buy_signal())
    confirmed_sell = _sell_watch(
        status="SELL_TIMING_VALID",
        final_direction="SELL",
        action="SELL_AT_SIGNAL_VALID_PRICE_OR_RETEST",
        rr_status="VALID",
        valid_for_execution=True,
        execution_valid_now=True,
    )

    follow_up = manager.apply(confirmed_sell)

    assert follow_up["status"] == "SELL_REVERSAL_VALID"
    assert follow_up["final_direction"] == "SELL"
    assert follow_up["action"] == "EXIT_BUY_AND_SELL_RETEST"
    assert follow_up["linked_previous_signal"] == active["signal_id"]
    assert follow_up["previous_signal_status"] == "SUPERSEDED"
    assert follow_up["lifecycle_status"] == "SUPERSEDES_ACTIVE_BUY"
    current_active = manager.active_signal("USDCAD")
    assert current_active is not None
    assert current_active["direction"] == "SELL"


def test_absorption_timing_valid_can_supersede_active_buy_when_execution_valid():
    manager = SignalLifecycleManager()
    active = manager.apply(_buy_signal())
    confirmed_absorption = _sell_watch(
        status="SELL_TIMING_VALID_BY_ABSORPTION",
        final_direction="SELL",
        action="SELL_AT_SIGNAL_VALID_PRICE_OR_RETEST",
        rr_status="VALID",
        valid_for_execution=True,
        execution_valid_now=True,
    )

    follow_up = manager.apply(confirmed_absorption)

    assert follow_up["status"] == "SELL_REVERSAL_VALID"
    assert follow_up["action"] == "EXIT_BUY_AND_SELL_RETEST"
    assert follow_up["linked_previous_signal"] == active["signal_id"]
    assert follow_up["previous_signal_status"] == "SUPERSEDED"


def test_incomplete_counter_entry_contract_cannot_supersede_active_buy():
    manager = SignalLifecycleManager()
    manager.apply(_buy_signal())
    incomplete_sell = _sell_watch(
        status="SELL_TIMING_VALID",
        final_direction="SELL",
        rr_status="VALID",
        valid_for_execution=True,
        execution_valid_now=False,
    )

    follow_up = manager.apply(incomplete_sell)

    assert follow_up["final_direction"] == "WAIT"
    assert follow_up["lifecycle_status"] == "CONFLICT_WAIT_M15_CLOSE"
    current_active = manager.active_signal("USDCAD")
    assert current_active is not None
    assert current_active["direction"] == "BUY"


def test_continuation_below_two_r_does_not_become_active():
    manager = SignalLifecycleManager()

    signal = manager.apply(_buy_signal(tp1_rr=1.99))

    assert "lifecycle_status" not in signal
    assert manager.active_signal("USDCAD") is None


def test_same_direction_signal_reinforces_active_signal():
    manager = SignalLifecycleManager()
    manager.apply(_buy_signal())

    reinforced = manager.apply(_buy_signal(signal_valid_time_wita="2026-05-20 11:00:00"))

    assert reinforced["previous_signal_status"] == "REINFORCED"
    assert reinforced["lifecycle_status"] == "REINFORCES_ACTIVE_SIGNAL"


def test_breakout_after_absorption_watch_reinforces_active_buy():
    manager = SignalLifecycleManager()
    active = manager.apply(_buy_signal())
    breakout = _sell_watch(
        status="BREAKOUT_CONTINUATION_BUY",
        candidate_direction="BUY",
        validated_direction="BUY",
        final_direction="WAIT",
        action="WAIT_RETEST_BUY",
        rr_status="UNVALIDATED",
        valid_for_execution=False,
    )

    follow_up = manager.apply(breakout)

    assert follow_up["status"] == "BUY_BREAKOUT_CONTINUATION_VALID"
    assert follow_up["final_direction"] == "BUY"
    assert follow_up["action"] == "HOLD_BUY_OR_BUY_RETEST"
    assert follow_up["previous_signal_status"] == "REINFORCED"
    assert follow_up["linked_previous_signal"] == active["signal_id"]
    assert follow_up["valid_for_execution"] is True
