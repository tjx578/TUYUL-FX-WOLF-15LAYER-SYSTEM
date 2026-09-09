from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from analysis.strategy_5scr_closed_candle_provider import Strategy5SCRClosedCandleEvidenceProvider
from analysis.strategy_5scr_replay import FrozenClosedCandleStore
from contracts.strategy_5scr_lifecycle_v2 import StrategyLifecycleEventLink
from contracts.strategy_5scr_shadow_evidence_v2 import (
    ShadowCandleReferenceV2,
    StrategyEvidenceComparisonV2,
    StrategyLifecycleAdmissionLinkV2,
)
from services.pressure_outbox.lifecycle_shadow_worker import LifecycleV2RuntimeConfig
from services.pressure_outbox.preflight import validate_lifecycle_evidence_owner_phase
from services.pressure_outbox.shadow_evidence_v2_worker import (
    ShadowEvidenceV2RuntimeConfig,
    admission_link_from_outbox_row,
    build_comparison_v2,
    build_shadow_snapshot_v2,
)
from storage.strategy_5scr_shadow_evidence_v2_repository import ShadowEvidenceWorkItemV2
from tests.test_strategy_5scr_closed_candle_evidence import DECISION_AT, _snapshot

LIFECYCLE_ID = "5scr-lifecycle:" + "a" * 32
ADMISSION_ID = "5scr-admission:" + "b" * 32
EVENT_ID = "7cd7bb57-1eb1-42c4-b998-ff250fabcc15"


def _item(*, decision_time: datetime | None = None) -> ShadowEvidenceWorkItemV2:
    return ShadowEvidenceWorkItemV2(
        evidence_job_id="5scr-evidence-job-v2:" + "c" * 32,
        strategy_lifecycle_id=LIFECYCLE_ID,
        admission_event_id=ADMISSION_ID,
        pressure_event_id=EVENT_ID,
        symbol="NZDUSD",
        lifecycle_state="ANALYSIS_OPEN",
        opened_at_utc=datetime(2026, 7, 20, 6, tzinfo=UTC),
        admitted_at_utc=datetime(2026, 7, 20, 6, tzinfo=UTC),
        decision_time_utc=decision_time,
        legacy_lifecycle_id=ADMISSION_ID,
        attempt_count=0,
    )


def _evidence():
    candles_by_timeframe = _snapshot()
    provider = Strategy5SCRClosedCandleEvidenceProvider(
        FrozenClosedCandleStore([candle for batch in candles_by_timeframe.values() for candle in batch])
    )
    return provider.build_from_snapshot(
        symbol="NZDUSD",
        decision_at_utc=DECISION_AT,
        lifecycle_anchor_utc=datetime(2026, 7, 20, 6, tzinfo=UTC),
        candles_by_timeframe=candles_by_timeframe,
    )


def test_shadow_evidence_v2_is_dark_and_execution_isolated_by_default() -> None:
    config = ShadowEvidenceV2RuntimeConfig.from_env({})

    assert config.enabled is False
    assert config.shadow_only is True
    assert not any(
        (
            config.execution_enabled,
            config.strategy_execution_enabled,
            config.signed_command_bridge_enabled,
            config.command_producer_enabled,
            config.risk_reservation_enabled,
            config.trade_outbox_write_enabled,
            config.ea_command_delivery_enabled,
            config.legacy_push_execution_enabled,
            config.mt5_order_send_enabled,
        )
    )


@pytest.mark.parametrize(
    "flag",
    [
        "EXECUTION_ENABLED",
        "STRATEGY_5SCR_EXECUTION_ENABLED",
        "SIGNED_COMMAND_BRIDGE_ENABLED",
        "EXECUTION_COMMAND_PRODUCER_ENABLED",
        "RISK_RESERVATION_ENABLED",
        "TRADE_OUTBOX_WRITE_ENABLED",
        "EA_COMMAND_DELIVERY_ENABLED",
        "LEGACY_PUSH_EXECUTION_ENABLED",
        "MT5_ORDER_SEND_ENABLED",
    ],
)
def test_shadow_evidence_v2_rejects_every_execution_flag(flag: str) -> None:
    with pytest.raises(RuntimeError, match="REQUIRES_EXECUTION_OFF"):
        ShadowEvidenceV2RuntimeConfig.from_env(
            {
                "STRATEGY_5SCR_SHADOW_EVIDENCE_V2_ENABLED": "true",
                flag: "true",
            }
        )


def test_owner_writer_requires_durable_lifecycle_dual_write() -> None:
    with pytest.raises(RuntimeError, match="REQUIRES_LIFECYCLE_DUAL_WRITE"):
        validate_lifecycle_evidence_owner_phase(
            lifecycle_config=LifecycleV2RuntimeConfig(evidence_owner_writer_enabled=True),
            evidence_config=ShadowEvidenceV2RuntimeConfig(),
        )


def test_owner_writer_rejects_an_active_execution_plane() -> None:
    with pytest.raises(RuntimeError, match="OWNER_WRITER_REQUIRES_EXECUTION_OFF"):
        validate_lifecycle_evidence_owner_phase(
            lifecycle_config=LifecycleV2RuntimeConfig(
                enabled=True,
                dual_write_enabled=True,
                evidence_owner_writer_enabled=True,
            ),
            evidence_config=ShadowEvidenceV2RuntimeConfig(execution_enabled=True),
        )


def test_evidence_worker_requires_owner_writer() -> None:
    with pytest.raises(RuntimeError, match="REQUIRES_OWNER_WRITER"):
        validate_lifecycle_evidence_owner_phase(
            lifecycle_config=LifecycleV2RuntimeConfig(enabled=True, dual_write_enabled=True),
            evidence_config=ShadowEvidenceV2RuntimeConfig(enabled=True, activation_requested=True),
        )


def test_pair_admission_lineage_is_required_and_preserved() -> None:
    linked_at = datetime(2026, 7, 20, 6, 1, tzinfo=UTC)
    event_link = StrategyLifecycleEventLink(
        strategy_lifecycle_id=LIFECYCLE_ID,
        pressure_event_id=EVENT_ID,
        transport_lifecycle_id=ADMISSION_ID,
        linked_at_utc=linked_at,
        link_reason="EPISODE_OPENED",
    )
    admission = admission_link_from_outbox_row(
        {
            "payload": {
                "pair_admission_id": ADMISSION_ID,
                "pair_admission_rule_version": "5scr.pair-admission.raw-ledger.v2",
                "pair_admission_source_ledger_hash": "sha256:" + "d" * 64,
                "pair_admission_granted_at_utc": "2026-07-20T06:00:00+00:00",
            }
        },
        event_link,
    )

    assert admission.admission_event_id == ADMISSION_ID
    assert admission.strategy_lifecycle_id == LIFECYCLE_ID
    assert admission.raw_lineage_hash == "sha256:" + "d" * 64
    assert admission.execution_authority is False


def test_missing_raw_admission_lineage_fails_closed() -> None:
    event_link = StrategyLifecycleEventLink(
        strategy_lifecycle_id=LIFECYCLE_ID,
        pressure_event_id=EVENT_ID,
        transport_lifecycle_id=ADMISSION_ID,
        linked_at_utc=datetime(2026, 7, 20, 6, 1, tzinfo=UTC),
        link_reason="EPISODE_OPENED",
    )
    with pytest.raises(ValidationError):
        admission_link_from_outbox_row(
            {"payload": {"pair_admission_granted_at_utc": "2026-07-20T06:00:00+00:00"}},
            event_link,
        )


def test_snapshot_is_restart_deterministic_and_non_executable() -> None:
    evidence = _evidence()
    assert evidence is not None

    first = build_shadow_snapshot_v2(_item(), evidence, decision_time=DECISION_AT)
    restarted = build_shadow_snapshot_v2(_item(decision_time=DECISION_AT), evidence, decision_time=DECISION_AT)

    assert restarted == first
    assert first.evidence_hash == restarted.evidence_hash
    assert max(item.period_close_utc for item in first.source_candles) <= first.decision_time_utc
    assert first.valid_for_execution is False
    assert first.execution_authority is False


def test_forming_or_future_candle_can_never_enter_snapshot() -> None:
    with pytest.raises(ValidationError, match="future candle leakage"):
        from contracts.strategy_5scr_shadow_evidence_v2 import StrategyShadowEvidenceSnapshotV2

        StrategyShadowEvidenceSnapshotV2(
            snapshot_id="5scr-evidence-v2:" + "1" * 32,
            evidence_job_id="5scr-evidence-job-v2:" + "2" * 32,
            strategy_lifecycle_id=LIFECYCLE_ID,
            admission_event_id=ADMISSION_ID,
            symbol="NZDUSD",
            decision_time_utc=DECISION_AT,
            provider_calendar_version="calendar-v1",
            source_candles=(
                ShadowCandleReferenceV2(
                    candle_id="sha256:" + "3" * 64,
                    timeframe="M1",
                    period_open_utc=DECISION_AT,
                    period_close_utc=DECISION_AT + timedelta(minutes=1),
                    provider="test",
                ),
            ),
            coverage_status="COMPLETE",
            context_hash="sha256:" + "4" * 64,
            evidence_hash="sha256:" + "5" * 64,
            result_state="WAIT",
            terminal_reason="FUTURE_TEST",
        )


def test_missing_legacy_result_is_a_durable_explained_comparison() -> None:
    evidence = _evidence()
    assert evidence is not None
    snapshot = build_shadow_snapshot_v2(_item(), evidence, decision_time=DECISION_AT)

    comparison = build_comparison_v2(
        _item(),
        snapshot,
        grouping={"events": 1, "transport_lifecycles": 1, "clean_blocks": 1},
        legacy=None,
    )

    assert comparison.same_lifecycle_grouping is True
    assert comparison.same_candle_set is None
    assert comparison.reason_codes == ("LEGACY_EVIDENCE_NOT_AVAILABLE",)
    assert comparison.execution_authority is False


def test_unexplained_comparison_difference_is_rejected() -> None:
    with pytest.raises(ValidationError, match="require reason_codes"):
        StrategyEvidenceComparisonV2(
            comparison_id="5scr-evidence-comparison-v2:" + "e" * 32,
            strategy_lifecycle_id=LIFECYCLE_ID,
            v2_snapshot_id="5scr-evidence-v2:" + "f" * 32,
            same_lifecycle_grouping=False,
        )


def test_admission_link_cannot_precede_authority_time() -> None:
    with pytest.raises(ValidationError, match="cannot precede"):
        StrategyLifecycleAdmissionLinkV2(
            admission_event_id=ADMISSION_ID,
            strategy_lifecycle_id=LIFECYCLE_ID,
            pressure_event_id=EVENT_ID,
            raw_lineage_hash="sha256:" + "a" * 64,
            admission_rule_version="rule-v2",
            admitted_at_utc=DECISION_AT,
            linked_at_utc=DECISION_AT - timedelta(seconds=1),
        )
