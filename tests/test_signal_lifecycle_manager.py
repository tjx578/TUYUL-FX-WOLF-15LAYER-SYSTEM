from __future__ import annotations

import pytest

from analysis.signal_lifecycle_manager import (
    ACTIVE_LIFECYCLE_STATUSES,
    SignalLifecycleManager,
    build_lifecycle_preview,
    classify_active_lifecycle_status,
    record_active_if_execution_grade,
    shadow_preview_event,
)

# P1A: each condition is asserted for BOTH directions so every BUY status has a
# verified SELL mirror (and vice versa). (active, opposite) drives the template.
_DIRECTIONS = [("BUY", "SELL"), ("SELL", "BUY")]


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
        "parent_event_exists": True,
        "parent_watch_id": "USDCAD_BUY_PARENT",
        "parent_watch_required": True,
        "promotion_path": "WATCH_TO_FINAL",
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
        "parent_event_exists": True,
        "parent_watch_id": "USDCAD_SELL_PARENT",
        "parent_watch_required": True,
        "promotion_path": "WATCH_TO_FINAL",
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
    assert follow_up["validated_direction"] is None
    assert follow_up["watch_direction"] == "SELL"
    assert follow_up["active_position_policy"] == "PROTECT_ACTIVE_BUY_NO_AUTO_REVERSAL"
    assert follow_up["active_signal_management"]["policy"] == "PROTECT_PROFIT_ONLY_WAIT_M15_CLOSE"


@pytest.mark.parametrize(("active_direction", "counter_direction"), [("BUY", "SELL"), ("SELL", "BUY")])
def test_nested_conditional_counter_scenario_protects_same_raw_direction_active_signal(
    active_direction: str,
    counter_direction: str,
):
    manager = SignalLifecycleManager()
    active_payload = _buy_signal(
        status=f"{active_direction}_TIMING_VALID",
        raw_direction=active_direction,
        validated_direction=active_direction,
        final_direction=active_direction,
    )
    manager.apply(active_payload)
    watch = _buy_signal(
        status="COUNTER_SCENARIO_WATCH",
        raw_direction=active_direction,
        candidate_direction=active_direction,
        validated_direction=None,
        final_direction="WAIT",
        valid_for_execution=False,
        counter_watch_direction=counter_direction,
        counter_scenario={
            "status": "CONDITIONAL",
            "direction": counter_direction,
            "requires_m15_close": True,
            "valid_for_execution": False,
        },
    )

    follow_up = manager.apply(watch)

    assert follow_up["final_direction"] == "WAIT"
    assert follow_up["counter_monitor_direction"] == counter_direction
    assert follow_up["lifecycle_status"] == f"CONFLICT_PROTECT_ACTIVE_{active_direction}"
    assert follow_up["active_position_policy"] == f"PROTECT_ACTIVE_{active_direction}_NO_AUTO_REVERSAL"


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
        m15_confirmation_status="M15_CLOSE_REJECTION_CONFIRMED",
        cooldown_m15_bars_elapsed=1,
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
        m15_confirmation_status="M15_CLOSE_REJECTION_CONFIRMED",
        cooldown_m15_bars_elapsed=1,
    )

    follow_up = manager.apply(confirmed_absorption)

    assert follow_up["status"] == "SELL_REVERSAL_VALID"
    assert follow_up["action"] == "EXIT_BUY_AND_SELL_RETEST"
    assert follow_up["linked_previous_signal"] == active["signal_id"]
    assert follow_up["previous_signal_status"] == "SUPERSEDED"


def test_unconfirmed_opposing_final_waits_without_superseding_active_buy():
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
    assert follow_up["status"] == "SELL_TIMING_VALID"
    assert follow_up["source_final_direction"] == "SELL"
    assert follow_up["lifecycle_status"] == "CONFLICT_WAIT_REVERSAL_CONFIRMATION_AND_COOLDOWN"
    assert follow_up["valid_for_execution"] is False
    current_active = manager.active_signal("USDCAD")
    assert current_active is not None
    assert current_active["direction"] == "BUY"


def test_schema_v1_opposing_final_waits_without_m15_confirmation():
    manager = SignalLifecycleManager()
    manager.apply(_buy_signal())
    unconfirmed_sell = _sell_watch(
        status="SELL_TIMING_VALID",
        final_direction="SELL",
        action="SELL_AT_SIGNAL_VALID_PRICE_OR_RETEST",
        rr_status="VALID",
        valid_for_execution=True,
        execution_valid_now=True,
    )

    follow_up = manager.apply(unconfirmed_sell)

    assert follow_up["status"] == "SELL_TIMING_VALID"
    assert follow_up["final_direction"] == "WAIT"
    assert follow_up["source_final_direction"] == "SELL"
    assert follow_up["lifecycle_status"] == "CONFLICT_WAIT_REVERSAL_CONFIRMATION_AND_COOLDOWN"
    assert follow_up["direction_validation_status"] == "REVERSAL_WATCH_PENDING_COOLDOWN"
    current_active = manager.active_signal("USDCAD")
    assert current_active is not None
    assert current_active["direction"] == "BUY"


def test_confirmed_opposing_final_waits_until_one_m15_bar_elapsed():
    manager = SignalLifecycleManager()
    manager.apply(_buy_signal())
    confirmed_sell = _sell_watch(
        status="SELL_TIMING_VALID",
        final_direction="SELL",
        valid_for_execution=True,
        execution_valid_now=True,
        m15_confirmation_status="M15_CLOSE_REJECTION_CONFIRMED",
        cooldown_m15_bars_elapsed=0,
    )

    follow_up = manager.apply(confirmed_sell)

    assert follow_up["final_direction"] == "WAIT"
    assert follow_up["reversal_confirmed"] is True
    assert follow_up["cooldown_m15_bars_elapsed"] == 0
    assert manager.active_signal("USDCAD")["direction"] == "BUY"


def test_confirmed_opposing_final_without_explicit_cooldown_defaults_to_zero():
    manager = SignalLifecycleManager()
    manager.apply(_buy_signal())
    confirmed_sell = _sell_watch(
        status="SELL_TIMING_VALID",
        final_direction="SELL",
        valid_for_execution=True,
        execution_valid_now=True,
        m15_confirmation_status="M15_CLOSE_REJECTION_CONFIRMED",
    )

    follow_up = manager.apply(confirmed_sell)

    assert follow_up["final_direction"] == "WAIT"
    assert follow_up["reversal_confirmed"] is True
    assert follow_up["cooldown_m15_bars_elapsed"] == 0
    assert manager.active_signal("USDCAD")["direction"] == "BUY"


def test_lifecycle_id_is_stable_across_direction_revisions_in_same_clean_block():
    manager = SignalLifecycleManager()
    source_id = "USDCAD_20260520T024500Z_20260520T080000Z"
    active = manager.apply(
        _buy_signal(
            cluster_id="USDCAD_BUY_REVISION_1",
            source_clean_block_id=source_id,
        )
    )
    reversed_signal = manager.apply(
        _sell_watch(
            cluster_id="USDCAD_SELL_REVISION_2",
            source_clean_block_id=source_id,
            status="SELL_TIMING_VALID",
            final_direction="SELL",
            valid_for_execution=True,
            execution_valid_now=True,
            m15_confirmation_status="M15_CLOSE_REJECTION_CONFIRMED",
            cooldown_m15_bars_elapsed=1,
        )
    )

    assert active["lifecycle_id"] == source_id
    assert reversed_signal["lifecycle_id"] == source_id
    assert reversed_signal["linked_previous_lifecycle_id"] == source_id
    assert active["signal_id"].startswith("USDCAD_BUY_")
    assert reversed_signal["signal_id"].startswith("USDCAD_SELL_")
    assert active["signal_id"] != reversed_signal["signal_id"]


def test_lifecycle_id_uses_cluster_when_clean_block_lineage_is_absent():
    manager = SignalLifecycleManager()
    cluster_id = "USDCAD_PRESSURE_EPISODE_42"

    active = manager.apply(_buy_signal(cluster_id=cluster_id))
    opposing_watch = manager.apply(_sell_watch(cluster_id=cluster_id))

    assert active["lifecycle_id"] == cluster_id
    assert opposing_watch["lifecycle_id"] == cluster_id
    assert opposing_watch["linked_previous_lifecycle_id"] == cluster_id


def test_four_clusters_in_eleven_minutes_share_one_raw_pressure_lifecycle():
    manager = SignalLifecycleManager()
    events = [
        {
            "symbol": "CHFJPY",
            "cluster_id": f"CHFJPY_CLUSTER_{index}",
            "status": "MICROBOOST_WATCH",
            "raw_direction": "SELL",
            "candidate_direction": candidate,
            "final_direction": "WAIT",
            "valid_for_execution": False,
            "signal_valid_time_utc": timestamp,
        }
        for index, candidate, timestamp in (
            (1, "SELL", "2026-07-10T08:15:00+00:00"),
            (2, "BUY", "2026-07-10T08:16:00+00:00"),
            (3, "SELL", "2026-07-10T08:21:00+00:00"),
            (4, "BUY", "2026-07-10T08:26:00+00:00"),
        )
    ]

    applied = [manager.apply(event) for event in events]

    assert {event["lifecycle_id"] for event in applied} == {"CHFJPY_CLUSTER_1"}


def test_opposite_raw_pressure_starts_new_lifecycle_inside_episode_window():
    manager = SignalLifecycleManager()
    sell_episode = manager.apply(
        {
            "symbol": "CHFJPY",
            "cluster_id": "CHFJPY_SHARED_CLUSTER",
            "status": "MICROBOOST_WATCH",
            "raw_direction": "SELL",
            "candidate_direction": "SELL",
            "final_direction": "WAIT",
            "valid_for_execution": False,
            "signal_valid_time_utc": "2026-07-10T08:15:00+00:00",
        }
    )
    buy_episode = manager.apply(
        {
            "symbol": "CHFJPY",
            "cluster_id": "CHFJPY_SHARED_CLUSTER",
            "status": "MICROBOOST_WATCH",
            "raw_direction": "BUY",
            "candidate_direction": "BUY",
            "final_direction": "WAIT",
            "valid_for_execution": False,
            "signal_valid_time_utc": "2026-07-10T08:20:00+00:00",
        }
    )

    assert sell_episode["lifecycle_id"] == "CHFJPY_SHARED_CLUSTER"
    assert buy_episode["lifecycle_id"] == "CHFJPY_SHARED_CLUSTER_BUY"
    assert buy_episode["lifecycle_id"] != sell_episode["lifecycle_id"]


def test_explicit_lifecycle_id_is_never_overridden_by_episode_coalescing():
    manager = SignalLifecycleManager()
    payload = {
        "symbol": "CHFJPY",
        "cluster_id": "CHFJPY_CLUSTER_NEW",
        "lifecycle_id": "CHFJPY_OPERATOR_ASSIGNED_EPISODE",
        "status": "MICROBOOST_WATCH",
        "raw_direction": "SELL",
        "candidate_direction": "SELL",
        "final_direction": "WAIT",
        "valid_for_execution": False,
        "signal_valid_time_utc": "2026-07-10T08:17:00+00:00",
    }

    assert manager.apply(payload)["lifecycle_id"] == "CHFJPY_OPERATOR_ASSIGNED_EPISODE"


def test_schema_v1_valid_continuation_does_not_require_fixed_two_r_tp1():
    manager = SignalLifecycleManager()

    signal = manager.apply(_buy_signal(tp1_rr=1.99))

    assert signal["lifecycle_status"] == "ACTIVE_BUY_VALID"
    assert manager.active_signal("USDCAD") is not None


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


# ── P1A: pure lifecycle mapper, BUY/SELL symmetric ──────────────────────────


@pytest.mark.parametrize("active, opposite", _DIRECTIONS)
def test_mapper_monitor_counter_pressure_symmetric(active, opposite):
    payload = {
        "validated_direction": opposite,
        "status": f"{opposite}_TIMING_WATCH",
        "phase_priced": "RESISTANCE_PRESSURE_WARNING" if active == "BUY" else "SUPPORT_PRESSURE_WARNING",
        "valid_for_execution": False,
    }
    assert classify_active_lifecycle_status(active, payload) == f"ACTIVE_{active}_MONITOR_COUNTER_PRESSURE"


@pytest.mark.parametrize("active, opposite", _DIRECTIONS)
def test_mapper_protect_profit_symmetric(active, opposite):
    payload = {
        "validated_direction": opposite,
        "status": f"{opposite}_ABSORPTION_WATCH",
        "phase_priced": "EXHAUSTION_AT_RESISTANCE" if active == "BUY" else "EXHAUSTION_AT_SUPPORT",
        "valid_for_execution": False,
    }
    assert classify_active_lifecycle_status(active, payload) == f"ACTIVE_{active}_PROTECT_PROFIT"


@pytest.mark.parametrize("active, opposite", _DIRECTIONS)
def test_mapper_exit_alert_symmetric(active, opposite):
    payload = {
        "phase_priced": "RESISTANCE_REJECTION_MICROBOOST" if active == "BUY" else "SUPPORT_BOUNCE_MICROBOOST",
        "valid_for_execution": False,
    }
    assert classify_active_lifecycle_status(active, payload) == f"ACTIVE_{active}_EXIT_ALERT"


@pytest.mark.parametrize("active, opposite", _DIRECTIONS)
def test_mapper_invalidated_symmetric(active, opposite):
    payload = {"structure_flip": True, "valid_for_execution": False}
    assert classify_active_lifecycle_status(active, payload) == f"ACTIVE_{active}_INVALIDATED"


@pytest.mark.parametrize("active, opposite", _DIRECTIONS)
def test_mapper_reversed_to_opposite_watch_symmetric(active, opposite):
    payload = {
        "structure_flip": True,
        "validated_direction": opposite,
        "status": f"{opposite}_TIMING_VALID",
        "valid_for_execution": False,
    }
    assert classify_active_lifecycle_status(active, payload) == f"ACTIVE_{active}_REVERSED_TO_{opposite}_WATCH"


@pytest.mark.parametrize("active, opposite", _DIRECTIONS)
def test_mapper_no_new_add_symmetric(active, opposite):
    payload = {
        "validated_direction": active,
        "price_position": "MAIN_RESISTANCE" if active == "BUY" else "MAIN_SUPPORT",
        "valid_for_execution": False,
    }
    assert classify_active_lifecycle_status(active, payload) == f"ACTIVE_{active}_NO_NEW_ADD"


@pytest.mark.parametrize("active, opposite", _DIRECTIONS)
def test_mapper_returns_none_when_no_lifecycle_change(active, opposite):
    payload = {"validated_direction": active, "price_position": "MID_RANGE", "valid_for_execution": False}
    assert classify_active_lifecycle_status(active, payload) is None


def test_mapper_ignores_unknown_active_direction():
    assert classify_active_lifecycle_status("WAIT", {"structure_flip": True}) is None
    assert classify_active_lifecycle_status(None, {"structure_flip": True}) is None


@pytest.mark.parametrize("active, opposite", _DIRECTIONS)
def test_mapper_never_marks_executable_and_uses_known_status(active, opposite):
    # Every condition that yields a status must yield one from the closed taxonomy.
    payloads = [
        {"validated_direction": opposite, "status": f"{opposite}_TIMING_WATCH",
         "phase_priced": "RESISTANCE_PRESSURE_WARNING" if active == "BUY" else "SUPPORT_PRESSURE_WARNING"},
        {"phase_priced": "EXHAUSTION_AT_RESISTANCE" if active == "BUY" else "EXHAUSTION_AT_SUPPORT"},
        {"structure_flip": True},
        {"structure_flip": True, "validated_direction": opposite, "status": f"{opposite}_TIMING_VALID"},
    ]
    for payload in payloads:
        status = classify_active_lifecycle_status(active, payload)
        assert status in ACTIVE_LIFECYCLE_STATUSES


# ── P1B: shadow preview (pure, never executable) ────────────────────────────


@pytest.mark.parametrize("active, opposite", _DIRECTIONS)
def test_shadow_preview_symmetric_protect_profit(active, opposite):
    payload = {
        "symbol": "USDCAD",
        "validated_direction": opposite,
        "status": f"{opposite}_ABSORPTION_WATCH",
        "phase_priced": "EXHAUSTION_AT_RESISTANCE" if active == "BUY" else "EXHAUSTION_AT_SUPPORT",
        "valid_for_execution": False,
    }
    preview = build_lifecycle_preview(active, payload)
    assert preview is not None
    assert preview["suggested_lifecycle_status"] == f"ACTIVE_{active}_PROTECT_PROFIT"
    assert preview["suggested_management_action"] == f"PROTECT_{active}_PROFIT"
    assert preview["active_signal_direction"] == active
    assert preview["counter_direction"] == opposite
    assert preview["live_applied"] is False
    assert preview["confidence"] == "SHADOW_ONLY"
    assert preview["source"] == "SignalLifecycleManagerShadow"
    assert "valid_for_execution" not in preview  # preview never carries an execution flag


def test_shadow_preview_none_when_no_lifecycle_change():
    payload = {"symbol": "USDCAD", "validated_direction": "BUY", "price_position": "MID_RANGE"}
    assert build_lifecycle_preview("BUY", payload) is None


def test_shadow_preview_event_requires_active_signal():
    counter = {
        "symbol": "USDCAD",
        "validated_direction": "SELL",
        "phase_priced": "EXHAUSTION_AT_RESISTANCE",
        "status": "SELL_ABSORPTION_WATCH",
        "valid_for_execution": False,
    }
    assert shadow_preview_event({}, counter) is None
    event = shadow_preview_event({"USDCAD": "BUY"}, counter)
    assert event is not None
    assert event["event"] == "signal_lifecycle_shadow_preview"
    assert event["lifecycle_preview"]["suggested_lifecycle_status"] == "ACTIVE_BUY_PROTECT_PROFIT"
    assert event["lifecycle_preview"]["live_applied"] is False


def test_record_active_only_for_execution_grade_finals():
    active: dict[str, str] = {}
    assert record_active_if_execution_grade(active, _sell_watch()) is False  # a watch is not execution-grade
    assert active == {}
    assert record_active_if_execution_grade(active, _buy_signal()) is True  # execution-grade BUY final
    assert active["USDCAD"] == "BUY"
