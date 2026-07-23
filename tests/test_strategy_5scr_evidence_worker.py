from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest

from contracts.strategy_5scr_pressure_outbox import (
    PressureInboxOutcome,
    PressureOutboxEnvelope,
)
from services.pressure_outbox.evidence_worker import (
    EvidenceRuntimeConfig,
    Strategy5SCREvidenceWorker,
)
from storage.pressure_outbox import prepare_pressure_event


def _envelope() -> PressureOutboxEnvelope:
    prepared = prepare_pressure_event(
        {
            "symbol": "EURGBP",
            "source_clean_block_id": "clean-eurgbp-1",
            "cluster_id": "EURGBP:20260720T060000Z",
            "signal_valid_time_utc": "2026-07-20T06:00:00+00:00",
            "promotion_stage": "PRESSURE_ONLY",
            "final_direction": "WAIT",
            "valid_for_execution": False,
            "execution_valid_now": False,
            "is_final_signal": False,
            "pressure_seen": True,
            "pair_eligible_for_analysis": True,
            "pressure_event_count": 3,
        }
    )
    now = datetime(2026, 7, 20, 6, tzinfo=UTC)
    return PressureOutboxEnvelope(
        outbox_id=prepared.outbox_id,
        event_id=prepared.event_id,
        schema_version=prepared.schema_version,
        symbol=prepared.symbol,
        lifecycle_id=prepared.lifecycle_id,
        lifecycle_sequence=1,
        source_clean_block_id=prepared.source_clean_block_id,
        signal_valid_at=prepared.signal_valid_at,
        payload={**prepared.payload, "lifecycle_sequence": 1},
        payload_hash=prepared.payload_hash,
        status="PUBLISHED",
        attempt_count=1,
        published_at=now,
        created_at=now,
    )


class _Provider:
    calls = 0

    async def provide(self, **_: Any) -> Any:
        self.calls += 1
        return SimpleNamespace(evidence_snapshot_id="5scr-evidence:" + "a" * 32)


class _Processor:
    calls = 0

    def process(self, envelope: PressureOutboxEnvelope, *, evidence: Any) -> PressureInboxOutcome:
        self.calls += 1
        return PressureInboxOutcome(
            event_id=envelope.event_id,
            lifecycle_id=envelope.lifecycle_id,
            status="PROCESSED",
            decision="BLOCK",
            result_id=f"5scr-block:{envelope.event_id}",
            reasons=("TEST_SHADOW_BLOCK",),
        )


class _CrashWindowRepository:
    def __init__(self, envelope: PressureOutboxEnvelope) -> None:
        self.envelope = envelope
        self.outcome_committed = False
        self.outcome_attempts = 0
        self.failure_records = 0

    async def load_waiting(self, *, limit: int) -> tuple[PressureOutboxEnvelope, ...]:
        assert limit == 1
        return () if self.outcome_committed else (self.envelope,)

    async def record_outcome(self, *_: Any, **__: Any) -> bool:
        self.outcome_attempts += 1
        if self.outcome_attempts == 1:
            raise ConnectionError("crash before outcome commit")
        self.outcome_committed = True
        return True

    async def record_failure(self, *_: Any, **__: Any) -> bool:
        self.failure_records += 1
        return True


def test_evidence_flags_are_dark_shadow_and_execution_off_by_default() -> None:
    config = EvidenceRuntimeConfig.from_env({})

    assert config.enabled is False
    assert config.mode == "SHADOW"
    assert config.provider == "finnhub"
    assert config.execution_enabled is False


def test_enabled_shadow_refuses_execution_flag() -> None:
    with pytest.raises(RuntimeError, match="REQUIRES_EXECUTION_OFF"):
        EvidenceRuntimeConfig.from_env(
            {
                "STRATEGY_5SCR_EVIDENCE_ENABLED": "true",
                "STRATEGY_5SCR_EVIDENCE_MODE": "SHADOW",
                "STRATEGY_5SCR_EVIDENCE_PROVIDER": "finnhub",
                "STRATEGY_5SCR_EXECUTION_ENABLED": "true",
            }
        )


@pytest.mark.asyncio
async def test_crash_before_outcome_commit_replays_deterministically() -> None:
    envelope = _envelope()
    repository = _CrashWindowRepository(envelope)
    provider = _Provider()
    processor = _Processor()
    worker = Strategy5SCREvidenceWorker(
        repository=repository,
        provider=provider,
        processor=cast(Any, processor),
        config=EvidenceRuntimeConfig(
            enabled=True,
            mode="SHADOW",
            provider="finnhub",
            execution_enabled=False,
            poll_seconds=0.1,
            batch_size=1,
        ),
    )

    assert await worker.process_once() == 1
    assert repository.outcome_committed is False
    assert repository.failure_records == 1

    assert await worker.process_once() == 1
    assert repository.outcome_committed is True
    assert repository.outcome_attempts == 2
    assert provider.calls == 2
    assert processor.calls == 2
