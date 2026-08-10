from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from analysis.signal_throttle_log_analyzer import SignalThrottleLogEvent
from analysis.strategy_5scr_pair_admission import build_pair_admission_audit
from analysis.strategy_5scr_raw_admission_blocks import build_raw_admission_population

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
