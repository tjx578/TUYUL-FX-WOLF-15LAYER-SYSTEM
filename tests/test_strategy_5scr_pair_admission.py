from __future__ import annotations

from datetime import UTC, datetime, timedelta

from analysis.signal_throttle_log_analyzer import PressureBlock, SignalThrottleLogEvent
from analysis.strategy_5scr_pair_admission import (
    build_pair_admission_audit,
    build_pair_admission_grant,
)

START = datetime(2026, 8, 3, 11, 0, tzinfo=UTC)


def _event(seconds: int, *, deployment: str = "deploy-A") -> SignalThrottleLogEvent:
    return SignalThrottleLogEvent(
        timestamp=START + timedelta(seconds=seconds),
        severity="WARNING",
        message="raw",
        symbol="AUDJPY",
        event_type="THROTTLED",
        direction="SELL",
        suppressed=2,
        deployment_id=deployment,
        scanner_cycle_id=f"cycle-{seconds}",
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
