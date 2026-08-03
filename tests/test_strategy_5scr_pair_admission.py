from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from analysis.signal_throttle_log_analyzer import PressureBlock, SignalThrottleLogEvent
from analysis.strategy_5scr_pair_admission import (
    build_pair_admission_audit,
    build_pair_admission_grant,
)

START = datetime(2026, 8, 3, 11, 0, tzinfo=UTC)


def _event(
    seconds: int,
    *,
    deployment: str | None = "deploy-A",
    scanner_cycle_id: str | None = None,
    suppressed: int = 2,
) -> SignalThrottleLogEvent:
    return SignalThrottleLogEvent(
        timestamp=START + timedelta(seconds=seconds),
        severity="WARNING",
        message="raw",
        symbol="AUDJPY",
        event_type="THROTTLED",
        direction="SELL",
        suppressed=suppressed,
        deployment_id=deployment,
        scanner_cycle_id=scanner_cycle_id if scanner_cycle_id is not None else f"cycle-{seconds}",
    )


def _block(*, duration: float = 300.0) -> PressureBlock:
    return PressureBlock(
        symbol="AUDJPY",
        start=START,
        end=START + timedelta(seconds=duration),
        events=3,
        duration_seconds=duration,
        density_per_minute=0.6,
        max_gap_seconds=150.0,
        direction="SELL",
        effective_ticks=9,
        deployment_ids=("deploy-A",),
    )


def test_raw_global_ledger_produces_non_executable_analysis_grant() -> None:
    grant = build_pair_admission_grant(
        _block(),
        raw_events=[_event(0), _event(150), _event(300)],
        source_clean_block_id="AUDJPY_20260803T110000Z_20260803T110500Z",
    )

    assert grant is not None
    assert grant.status == "GRANTED"
    assert grant.ledger_scope == "GLOBAL_SIGNAL_THROTTLE_RAW_LEDGER"
    assert grant.pair_eligible_for_analysis is True
    assert grant.execution_authority is False
    assert grant.duration_seconds == 300
    assert grant.effective_ticks == 9
    assert grant.source_event_count == 3
    assert grant.max_observed_gap_seconds == 150
    assert grant.source_scanner_cycle_ids == ("cycle-0", "cycle-150", "cycle-300")
    assert grant.lineage_complete is True
    assert grant.source_clean_block_ids == ("AUDJPY_20260803T110000Z_20260803T110500Z",)


def test_lineage_without_minimum_duration_cannot_grant_admission() -> None:
    grant = build_pair_admission_grant(
        _block(duration=299.0),
        raw_events=[_event(0), _event(150), _event(299)],
        source_clean_block_id="AUDJPY_LINEAGE_ONLY",
    )

    assert grant is None


def test_mixed_deployments_fail_closed() -> None:
    grant = build_pair_admission_grant(
        _block(),
        raw_events=[_event(0), _event(150, deployment="deploy-B"), _event(300)],
    )

    assert grant is None


def test_shadow_audit_exposes_mixed_deployment_rejection_reason() -> None:
    audit = build_pair_admission_audit(
        [_block()],
        raw_events=[_event(0), _event(150, deployment="deploy-B"), _event(300)],
    )

    assert audit.grants == ()
    assert audit.to_payload()["rejection_counts"] == {"MIXED_DEPLOYMENTS": 1}


def test_block_summary_cannot_forge_raw_duration() -> None:
    forged = replace(_block(), start=START + timedelta(seconds=270))

    audit = build_pair_admission_audit(
        [forged],
        raw_events=[_event(270), _event(285), _event(300)],
    )

    assert audit.grants == ()
    assert audit.to_payload()["rejection_counts"] == {"BLOCK_DURATION_EVIDENCE_MISMATCH": 1}


def test_block_summary_cannot_forge_effective_ticks() -> None:
    forged = replace(_block(), effective_ticks=99)

    audit = build_pair_admission_audit(
        [forged],
        raw_events=[_event(0), _event(150), _event(300)],
    )

    assert audit.grants == ()
    assert audit.to_payload()["rejection_counts"] == {"BLOCK_TICK_EVIDENCE_MISMATCH": 1}


def test_one_missing_deployment_in_mixed_evidence_fails_closed() -> None:
    audit = build_pair_admission_audit(
        [_block()],
        raw_events=[_event(0), _event(150, deployment=None), _event(300)],
    )

    assert audit.grants == ()
    assert audit.to_payload()["rejection_counts"] == {"DEPLOYMENT_ID_MISSING": 1}


def test_missing_scanner_cycle_lineage_fails_closed() -> None:
    events = [_event(0), _event(150), _event(300)]
    events[1] = replace(events[1], scanner_cycle_id=None)

    audit = build_pair_admission_audit([_block()], raw_events=events)

    assert audit.grants == ()
    assert audit.to_payload()["rejection_counts"] == {"SCANNER_CYCLE_ID_MISSING": 1}


def test_raw_ledger_ids_are_deterministic_in_event_time_order() -> None:
    events = [_event(0), _event(150), _event(300)]

    forward = build_pair_admission_grant(_block(), raw_events=events)
    reversed_input = build_pair_admission_grant(_block(), raw_events=reversed(events))

    assert forward is not None
    assert reversed_input is not None
    assert forward.source_ledger_event_ids == reversed_input.source_ledger_event_ids
    assert forward.source_ledger_hash == reversed_input.source_ledger_hash


def test_expired_grant_is_not_active() -> None:
    grant = build_pair_admission_grant(
        _block(),
        raw_events=[_event(0), _event(150), _event(300)],
    )

    assert grant is not None
    assert grant.is_active_at(START + timedelta(minutes=10)) is True
    assert grant.is_active_at(grant.expires_at_utc) is False


def test_gap_beyond_uninterrupted_limit_fails_closed() -> None:
    block = _block(duration=601.0)
    block = replace(block, max_gap_seconds=301.0)
    audit = build_pair_admission_audit(
        [block],
        raw_events=[_event(0), _event(300), _event(601)],
    )

    assert audit.grants == ()
    assert audit.to_payload()["rejection_counts"] == {"RAW_LEDGER_GAP_EXCEEDED": 1}
