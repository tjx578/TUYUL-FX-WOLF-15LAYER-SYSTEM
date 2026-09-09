from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from analysis.signal_throttle_log_analyzer import SignalThrottleLogEvent
from analysis.strategy_5scr_pair_admission import build_pair_admission_audit
from analysis.strategy_5scr_raw_admission_blocks import (
    build_raw_admission_population,
    raw_signal_throttle_event_id,
)

START = datetime(2026, 8, 10, 0, 0, tzinfo=UTC)


def _raw(seconds: float, symbol: str = "EURUSD") -> SignalThrottleLogEvent:
    return SignalThrottleLogEvent(
        timestamp=START + timedelta(seconds=seconds),
        severity="warning",
        message="raw",
        symbol=symbol,
        event_type="ALLOWED",
        verdict="EXECUTE_BUY",
        direction="BUY",
        pressure_source="SignalThrottle",
        source_stream="ALLOWED",
        deployment_id="deployment-A",
        scanner_cycle_id=f"cycle-{seconds}",
        eligible_for_pressure_block=True,
        eligible_for_execution=False,
    )


def _canary(seconds: float, symbol: str = "EURUSD") -> SignalThrottleLogEvent:
    return replace(
        _raw(seconds, symbol),
        event_type="PRESSURE_CANARY",
        pressure_source="signal_throttle_check",
        source_stream="CANARY",
    )


def _runtime_throttle_pair(seconds: float) -> tuple[SignalThrottleLogEvent, SignalThrottleLogEvent]:
    throttled = replace(
        _raw(seconds),
        event_type="THROTTLED",
        source_stream="RAW_THROTTLED",
        verdict=None,
        direction=None,
        throttled_inferred_direction="BUY",
    )
    downgraded = replace(
        _raw(seconds),
        event_type="DOWNGRADED_TO_HOLD",
        source_stream="DOWNGRADED",
    )
    return throttled, downgraded


def test_canary_only_builds_no_raw_admission_block() -> None:
    population = build_raw_admission_population([_canary(0), _canary(300)])

    assert population.events == ()
    assert population.blocks == ()
    assert population.to_payload()["skipped_non_authority_event_count"] == 2
    assert population.to_payload()["population_status"] == "NO_RAW_AUTHORITY_CANDIDATE"


def test_mixed_canary_does_not_change_raw_interval_or_counts() -> None:
    population = build_raw_admission_population(
        [_canary(-60), _raw(0), _canary(75), _raw(150), _canary(225), _raw(300), _canary(360)]
    )

    assert len(population.blocks) == 1
    block = population.blocks[0]
    assert block.start == START
    assert block.end == START + timedelta(seconds=300)
    assert block.events == 3
    assert block.duration_seconds == 300
    assert block.max_gap_seconds == 150


def test_raw_only_300_seconds_grants_exactly_once() -> None:
    population = build_raw_admission_population([_raw(0), _raw(150), _raw(300)])
    audit = build_pair_admission_audit(population.blocks, raw_events=population.events)

    assert len(audit.grants) == 1
    assert audit.evaluated_blocks == 1
    assert audit.rejection_counts == {}
    assert audit.evaluations[0]["candidate_block_id"].startswith("5scr-raw-block:")


def test_duplicate_replay_does_not_increase_raw_count_or_duplicate_grant() -> None:
    middle = _raw(150)
    population = build_raw_admission_population([_raw(0), middle, middle, _raw(300)])
    audit = build_pair_admission_audit(population.blocks, raw_events=population.events)

    assert population.duplicate_event_count == 1
    assert population.blocks[0].events == 3
    assert len(audit.grants) == 1


def test_cross_symbol_event_finalizes_the_active_raw_block() -> None:
    population = build_raw_admission_population([_raw(0), _raw(100), _raw(150, "GBPUSD"), _raw(300)])

    assert [(block.symbol, block.events) for block in population.blocks] == [
        ("EURUSD", 2),
        ("GBPUSD", 1),
        ("EURUSD", 1),
    ]
    assert population.blocks[0].cross_symbol_interruption_count == 1
    assert population.blocks[0].evaluation_state == "FINALIZED"
    assert population.blocks[0].finalization_reason == "CROSS_SYMBOL_EVENT"
    assert population.blocks[0].finalization_event_id == raw_signal_throttle_event_id(_raw(150, "GBPUSD"))
    assert population.blocks[-1].evaluation_state == "ACTIVE"
    assert population.blocks[-1].finalization_event_id is None


def test_gap_boundary_is_inclusive_at_exactly_300_seconds() -> None:
    exact = build_raw_admission_population([_raw(0), _raw(300)])
    over = build_raw_admission_population([_raw(0), _raw(300.001)])

    assert len(exact.blocks) == 1
    assert exact.blocks[0].events == 2
    assert len(over.blocks) == 2
    assert [block.events for block in over.blocks] == [1, 1]


def test_replay_produces_stable_raw_block_and_lineage_hashes() -> None:
    events = [_raw(0), _raw(150), _raw(300)]
    first = build_raw_admission_population(events)
    replay = build_raw_admission_population(reversed(events))
    first_audit = build_pair_admission_audit(first.blocks, raw_events=first.events)
    replay_audit = build_pair_admission_audit(replay.blocks, raw_events=replay.events)

    assert first.blocks[0].raw_block_id == replay.blocks[0].raw_block_id
    assert first_audit.grants[0].source_ledger_hash == replay_audit.grants[0].source_ledger_hash
    assert first_audit.grants[0].pair_admission_id == replay_audit.grants[0].pair_admission_id


def test_grant_identity_and_evidence_freeze_at_first_threshold_crossing() -> None:
    first = build_raw_admission_population([_raw(0), _raw(150), _raw(300)])
    growing = build_raw_admission_population([_raw(0), _raw(150), _raw(300), _raw(350), _raw(500), _raw(650)])
    first_grant = build_pair_admission_audit(first.blocks, raw_events=first.events).grants[0]
    growing_grant = build_pair_admission_audit(growing.blocks, raw_events=growing.events).grants[0]

    assert first.blocks[0].raw_block_id == growing.blocks[0].raw_block_id
    assert first_grant.pair_admission_id == growing_grant.pair_admission_id
    assert first_grant.episode_observed_through_utc == growing_grant.episode_observed_through_utc
    assert first_grant.duration_seconds == growing_grant.duration_seconds == 300
    assert first_grant.source_event_count == growing_grant.source_event_count == 3
    assert first_grant.source_ledger_hash == growing_grant.source_ledger_hash


def test_runtime_throttle_pair_can_grant_without_promoting_execution_authority() -> None:
    events = [event for seconds in (0, 150, 300) for event in _runtime_throttle_pair(seconds)]

    population = build_raw_admission_population(events)
    audit = build_pair_admission_audit(population.blocks, raw_events=population.events)

    assert len(population.blocks) == 1
    assert population.blocks[0].direction == "BUY"
    assert population.blocks[0].events == 6
    assert len(audit.grants) == 1
    assert audit.grants[0].execution_authority is False


def test_true_unresolved_raw_event_still_fails_closed() -> None:
    unresolved, _ = _runtime_throttle_pair(150)
    unresolved = replace(unresolved, throttled_inferred_direction=None)
    events = [_raw(0), unresolved, _raw(300)]

    population = build_raw_admission_population(events)
    audit = build_pair_admission_audit(population.blocks, raw_events=population.events)

    assert audit.grants == ()
    assert audit.rejection_counts == {"RAW_LEDGER_DIRECTION_UNRESOLVED": 1}


def test_non_throttled_event_cannot_launder_inferred_direction() -> None:
    spoofed = replace(
        _raw(150),
        verdict=None,
        direction=None,
        throttled_inferred_direction="BUY",
    )
    events = [_raw(0), spoofed, _raw(300)]

    population = build_raw_admission_population(events)
    audit = build_pair_admission_audit(population.blocks, raw_events=population.events)

    assert audit.grants == ()
    assert audit.rejection_counts == {"RAW_LEDGER_DIRECTION_UNRESOLVED": 1}


def test_inferred_direction_is_part_of_stable_raw_identity() -> None:
    throttled, _ = _runtime_throttle_pair(0)

    buy_id = raw_signal_throttle_event_id(throttled)
    sell_id = raw_signal_throttle_event_id(replace(throttled, throttled_inferred_direction="SELL"))

    assert buy_id != sell_id


def test_identical_active_snapshot_replays_the_same_evaluation_identity() -> None:
    events = [_raw(0), _raw(150)]

    first = build_raw_admission_population(events)
    replay = build_raw_admission_population(reversed(events))
    first_evaluation = build_pair_admission_audit(first.blocks, raw_events=first.events).evaluations[0]
    replay_evaluation = build_pair_admission_audit(replay.blocks, raw_events=replay.events).evaluations[0]

    assert first_evaluation == replay_evaluation
    assert first_evaluation["evaluation_state"] == "ACTIVE"


def test_growing_active_block_versions_the_evaluation_watermark() -> None:
    first = build_raw_admission_population([_raw(0), _raw(150)])
    growing = build_raw_admission_population([_raw(0), _raw(150), _raw(250)])
    first_evaluation = build_pair_admission_audit(first.blocks, raw_events=first.events).evaluations[0]
    growing_evaluation = build_pair_admission_audit(growing.blocks, raw_events=growing.events).evaluations[0]

    assert first_evaluation["candidate_block_id"] == growing_evaluation["candidate_block_id"]
    assert first_evaluation["evaluation_id"] != growing_evaluation["evaluation_id"]
    assert first_evaluation["evaluation_state"] == growing_evaluation["evaluation_state"] == "ACTIVE"
    assert first_evaluation["evaluation_watermark"] != growing_evaluation["evaluation_watermark"]


def test_active_to_finalized_versions_evaluation_without_changing_raw_block_identity() -> None:
    active = build_raw_admission_population([_raw(0)])
    finalized = build_raw_admission_population([_raw(0), _raw(1, "GBPUSD")])
    active_evaluation = build_pair_admission_audit(active.blocks, raw_events=active.events).evaluations[0]
    finalized_evaluation = build_pair_admission_audit(finalized.blocks, raw_events=finalized.events).evaluations[0]

    assert active_evaluation["candidate_block_id"] == finalized_evaluation["candidate_block_id"]
    assert active_evaluation["evaluation_id"] != finalized_evaluation["evaluation_id"]
    assert active_evaluation["evaluation_state"] == "ACTIVE"
    assert finalized_evaluation["evaluation_state"] == "FINALIZED"
    assert finalized_evaluation["finalization_reason"] == "CROSS_SYMBOL_EVENT"
    assert finalized_evaluation["finalization_event_id"] is not None


def test_active_grant_survives_normal_cross_symbol_finalization() -> None:
    active = build_raw_admission_population([_raw(0), _raw(150), _raw(300)])
    finalized = build_raw_admission_population([_raw(0), _raw(150), _raw(300), _raw(301, "GBPUSD")])
    active_audit = build_pair_admission_audit(active.blocks, raw_events=active.events)
    finalized_audit = build_pair_admission_audit(finalized.blocks, raw_events=finalized.events)

    assert len(active_audit.grants) == len(finalized_audit.grants) == 1
    assert active_audit.grants[0].pair_admission_id == finalized_audit.grants[0].pair_admission_id
    assert active_audit.evaluations[0]["evaluation_id"] != finalized_audit.evaluations[0]["evaluation_id"]
    assert active_audit.evaluations[0]["evaluation_state"] == "ACTIVE"
    assert finalized_audit.evaluations[0]["evaluation_state"] == "FINALIZED"


def test_multi_symbol_finalizer_ordering_is_deterministic() -> None:
    events = [_raw(0), _raw(150), _raw(300), _raw(301, "GBPUSD")]

    population = build_raw_admission_population(reversed(events))

    assert [(block.symbol, block.evaluation_state) for block in population.blocks] == [
        ("EURUSD", "FINALIZED"),
        ("GBPUSD", "ACTIVE"),
    ]
    assert population.blocks[0].events == 3
    assert population.blocks[1].events == 1
    assert population.blocks[0].finalization_event_id == raw_signal_throttle_event_id(_raw(301, "GBPUSD"))
