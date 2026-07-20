from __future__ import annotations

import json
from copy import deepcopy

import pytest

from analysis.strategy_5scr_pressure_to_tradeplan import (
    PressureEventNormalizer,
    PressureInputError,
    PressureLifecycleAccumulator,
    PressureToTradePlanBuilder,
    replay_pressure_records,
)
from contracts.strategy_5scr_pressure import Strategy5SCRMarketEvidence


def _pressure_payload(**overrides):
    payload = {
        "event": "signal_pressure_state_json",
        "schema_version": "1.0-pressure-state",
        "symbol": "CHFJPY",
        "cluster_id": "CHFJPY_20260717T130500Z_ALLOWED_QUORUM",
        "promotion_stage": "PRESSURE_ONLY",
        "raw_direction": "BUY",
        "final_direction": "WAIT",
        "signal_valid_time_utc": "2026-07-17T13:05:00+00:00",
        "signal_valid_price": 190.0,
        "entry_reference_price": 190.0,
        "price_source": "M15_CLOSE",
        "valid_for_execution": False,
        "execution_valid_now": False,
        "is_final_signal": False,
        "pressure_seen": True,
        "pressure_event_count": 4,
        "pressure_level": "PRESSURE_CANARY",
        "pressure_strength": "CANARY",
        "allowed_quorum": {
            "symbol": "CHFJPY",
            "direction": "BUY",
            "streak": 3,
            "quorum_size": 3,
            "quorum_reached": True,
        },
        "htf_structure_context": {
            "daily_bias": "BEARISH",
            "h4_structure": "BEARISH_PULLBACK",
            "price_location": "H4_SUPPLY",
            "liquidity_context": "BUY_SIDE_LIQUIDITY_TEST",
            "allowed_playbook": "SELL_ON_REJECTION",
            "blocked_playbook": ["BUY_BREAKOUT_CHASE"],
        },
    }
    payload.update(overrides)
    return payload


def _railway_record(payload=None, *, timestamp="2026-07-17T13:05:00.100Z"):
    resolved = payload or _pressure_payload()
    return {
        "message": "2026-07-17 13:05:00 WARNING signal_json [SignalPressureStateJSON] "
        + json.dumps(resolved, separators=(",", ":")),
        "timestamp": timestamp,
    }


def _lifecycle(*, mode="REPLAY", source_clean_block_id=None):
    payload = _pressure_payload()
    if source_clean_block_id is not None:
        payload["source_clean_block_id"] = source_clean_block_id
    event = PressureEventNormalizer(input_mode=mode).normalize(_railway_record(payload))
    return PressureLifecycleAccumulator().ingest(event)[0]


def _evidence(
    *,
    target=189.908,
    stop=190.05,
    context_status="RESOLVED",
    h1_confirmed=True,
    m15_break=True,
    m15_acceptance=True,
    source_candle_close_times=("2026-07-17T13:00:00+00:00", "2026-07-17T13:15:00+00:00"),
):
    return Strategy5SCRMarketEvidence.model_validate(
        {
            "decision_at_utc": "2026-07-17T13:15:00+00:00",
            "context_resolution": {
                "status": context_status,
                "origin": "WAIT_FOR_CONFIRMATION",
                "price_location": "H4_SUPPLY",
                "liquidity_context": "BUY_SIDE_REJECTED",
                "daily_bias": "BEARISH",
                "h4_structure": "BEARISH_PULLBACK",
                "allowed_playbook": "SELL_ON_CONFIRMED_BREAK_RETEST",
                "selected_playbook": "SELL_ON_CONFIRMED_BREAK_RETEST",
                "blocked_playbook": ["BUY_BREAKOUT_CHASE"],
                "scenario_allowed": True,
            },
            "h4": {
                "target_mode": "FINAL_MARKET_STRUCTURE",
                "structural_tp1": target,
                "target_room_valid": True,
            },
            "h1": {
                "direction": "SELL",
                "structure_state": "BEARISH_CONFIRMED",
                "structure_confirmed": h1_confirmed,
                "candle_closed": True,
                "confirmed_at_utc": "2026-07-17T13:00:00+00:00",
            },
            "m15": {
                "direction": "SELL",
                "structural_break": m15_break,
                "candle_closed": True,
                "acceptance_confirmed": m15_acceptance,
                "failed_reclaim_or_retest_confirmed": False,
                "rejection_candle_only": not m15_acceptance,
                "confirmed_at_utc": "2026-07-17T13:15:00+00:00",
            },
            "m1": {
                "box_id": "CHFJPY:BOX-V1",
                "box_low": 189.999,
                "box_high": 190.001,
                "fill_price": 190.0,
                "return_to_box_invalidated": False,
            },
            "structural_sl": stop,
            "pip_size": 0.01,
            "spread_price": 0.01,
            "source_candle_close_times": source_candle_close_times,
        }
    )


def test_normalizer_parses_legacy_railway_record_and_preserves_pressure_invariants():
    event = PressureEventNormalizer(input_mode="REPLAY").normalize(_railway_record())

    assert event.symbol == "CHFJPY"
    assert event.event_time_source == "signal_valid_time_utc"
    assert event.campaign_anchor is None
    assert event.campaign_anchor_source == "UNRESOLVED"
    assert event.campaign_anchor_execution_grade is False
    assert event.reference_price_role == "REFERENCE_ONLY_NOT_EXECUTABLE"
    assert event.allowed_quorum_reached is True


def test_runtime_identity_does_not_change_semantic_event_id():
    first = _pressure_payload(deployment_id="deployment-a", generated_at_utc="2026-07-17T13:05:01+00:00")
    second = _pressure_payload(deployment_id="deployment-b", generated_at_utc="2026-07-17T13:05:02+00:00")
    normalizer = PressureEventNormalizer(input_mode="REPLAY")

    event_a = normalizer.normalize(first)
    event_b = normalizer.normalize(second)

    assert event_a.event_id == event_b.event_id
    assert event_a.source_hash != event_b.source_hash


@pytest.mark.parametrize("field", ["valid_for_execution", "execution_valid_now", "is_final_signal"])
def test_normalizer_rejects_executable_pressure_flags(field):
    with pytest.raises(PressureInputError, match="PRESSURE_EVENT_EXECUTION_FLAG_TRUE"):
        PressureEventNormalizer(input_mode="LIVE").normalize(_pressure_payload(**{field: True}))


def test_replay_deduplicates_identical_exports_and_groups_legacy_episode():
    first = _railway_record()
    second_payload = _pressure_payload(
        cluster_id="CHFJPY_20260717T131000Z_NO_TRADE",
        signal_valid_time_utc="2026-07-17T13:10:00+00:00",
        pressure_event_count=5,
    )
    lifecycles = replay_pressure_records([first, first, _railway_record(second_payload)])

    assert len(lifecycles) == 1
    lifecycle = lifecycles[0]
    assert lifecycle.campaign_anchor_source == "LEGACY_EPISODE"
    assert lifecycle.campaign_anchor_execution_grade is False
    assert len(lifecycle.event_ids) == 2
    assert lifecycle.max_reported_pressure_count == 5
    assert lifecycle.legacy_grouping_rule_version == "5scr.legacy-m15-gap.v1"


def test_live_event_uses_canonical_clean_block_anchor():
    lifecycle = _lifecycle(mode="LIVE", source_clean_block_id="CHFJPY_20260717T130000Z_20260717T130500Z")

    assert lifecycle.campaign_id == "CHFJPY_20260717T130000Z_20260717T130500Z"
    assert lifecycle.campaign_anchor_source == "SOURCE_CLEAN_BLOCK_ID"
    assert lifecycle.campaign_anchor_execution_grade is True


def test_live_event_without_canonical_anchor_defers_tradeplan():
    result = PressureToTradePlanBuilder().build(_lifecycle(mode="LIVE"), _evidence())

    assert result.decision == "DEFER"
    assert "STRATEGY_5SCR_CANONICAL_LIFECYCLE_REQUIRED" in result.reasons


def test_context_unresolved_and_rejection_only_remain_no_trade():
    result = PressureToTradePlanBuilder().build(
        _lifecycle(),
        _evidence(
            context_status="WAIT_FOR_CONFIRMATION",
            h1_confirmed=False,
            m15_break=False,
            m15_acceptance=False,
        ),
    )

    assert result.decision == "DEFER"
    assert "NO_TRADE_CONTEXT_UNRESOLVED" in result.reasons
    assert "STRATEGY_5SCR_H1_CLOSED_STRUCTURE_CONFIRMATION_REQUIRED" in result.reasons
    assert "NO_TRADE_REJECTION_CANDLE_ONLY" in result.reasons


def test_valid_9_2_pip_structural_target_builds_non_executable_tradeplan():
    result = PressureToTradePlanBuilder().build(_lifecycle(), _evidence())

    assert result.decision == "READY"
    assert result.tradeplan is not None
    assert result.tradeplan.rr == pytest.approx(1.84)
    assert result.tradeplan.target_distance_price == pytest.approx(0.092)
    assert result.tradeplan.execution_floor_price == pytest.approx(0.06)
    assert result.tradeplan.valid_for_execution is False
    assert result.candidate_payload is not None
    assert result.candidate_payload["event"] == "strategy_5scr_tradeplan_candidate"
    assert result.candidate_payload["final_direction"] == "WAIT"
    assert result.candidate_payload["valid_for_execution"] is False
    assert result.candidate_payload["next_required_stage"] == "RISK_RESERVATION"
    assert result.candidate_payload["strategy_5scr"]["h1"]["direction"] == "SELL"


def test_micro_target_is_blocked_by_broker_aware_execution_floor_not_fixed_ten_pips():
    result = PressureToTradePlanBuilder().build(
        _lifecycle(),
        _evidence(target=189.965, stop=190.02),
    )

    assert result.decision == "BLOCK"
    assert "STRATEGY_5SCR_TARGET_BELOW_EXECUTION_FLOOR" in result.reasons


def test_future_candle_leakage_fails_closed():
    evidence = _evidence(source_candle_close_times=("2026-07-17T13:30:00+00:00",))
    result = PressureToTradePlanBuilder().build(_lifecycle(), evidence)

    assert result.decision == "BLOCK"
    assert "STRATEGY_5SCR_FUTURE_CANDLE_LEAKAGE" in result.reasons


def test_raw_pressure_direction_does_not_override_h1_and_m15_authority():
    payload = _pressure_payload(raw_direction="BUY")
    event = PressureEventNormalizer(input_mode="REPLAY").normalize(payload)
    lifecycle = PressureLifecycleAccumulator().ingest(event)[0]
    result = PressureToTradePlanBuilder().build(lifecycle, _evidence())

    assert lifecycle.raw_direction == "BUY"
    assert result.decision == "READY"
    assert result.tradeplan is not None
    assert result.tradeplan.direction == "SELL"


def test_tradeplan_id_is_deterministic():
    lifecycle = _lifecycle()
    evidence = _evidence()
    first = PressureToTradePlanBuilder().build(lifecycle, evidence)
    second = PressureToTradePlanBuilder().build(lifecycle, deepcopy(evidence))

    assert first.tradeplan is not None and second.tradeplan is not None
    assert first.tradeplan.tradeplan_id == second.tradeplan.tradeplan_id
