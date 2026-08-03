from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest

from contracts.strategy_5scr_pressure import Strategy5SCRMarketEvidence
from contracts.strategy_5scr_pressure_outbox import (
    PressureInboxOutcome,
    PressureOutboxEnvelope,
)
from services.pressure_outbox.evidence_worker import (
    EvidenceRuntimeConfig,
    PostgresEvidenceRepository,
    Strategy5SCREvidenceWorker,
)
from storage.pressure_outbox import prepare_pressure_event


def _envelope() -> PressureOutboxEnvelope:
    prepared = prepare_pressure_event(
        {
            "symbol": "EURGBP",
            "source_clean_block_id": "clean-eurgbp-1",
            "pair_admission_id": "5scr-admission:55555555555555555555555555555555",
            "pair_admission_status": "GRANTED",
            "pair_admission_source_ledger_hash": "sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
            "radar_manifest_id": "5scr-radar:ffffffffffffffffffffffffffffffff",
            "radar_status": "ANALYSIS_READY",
            "pressure_selection_confirmed": True,
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
    kwargs: dict[str, Any] = {}

    async def provide(self, **kwargs: Any) -> Any:
        self.calls += 1
        self.kwargs = kwargs
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


def test_stale_enabled_flag_cannot_activate_live_evidence_without_second_key() -> None:
    config = EvidenceRuntimeConfig.from_env(
        {
            "STRATEGY_5SCR_EVIDENCE_ENABLED": "true",
            "STRATEGY_5SCR_EVIDENCE_MODE": "SHADOW",
        }
    )

    assert config.activation_requested is True
    assert config.live_allowed is False
    assert config.enabled is False


def test_live_evidence_requires_explicit_two_key_activation() -> None:
    config = EvidenceRuntimeConfig.from_env(
        {
            "STRATEGY_5SCR_EVIDENCE_ENABLED": "true",
            "STRATEGY_5SCR_EVIDENCE_LIVE_ALLOWED": "true",
            "STRATEGY_5SCR_EVIDENCE_MODE": "SHADOW",
        }
    )

    assert config.enabled is True


def test_production_observe_requires_every_execution_plane_flag_off() -> None:
    config = EvidenceRuntimeConfig.from_env(
        {
            "STRATEGY_5SCR_EVIDENCE_ENABLED": "true",
            "STRATEGY_5SCR_EVIDENCE_LIVE_ALLOWED": "true",
            "STRATEGY_5SCR_EVIDENCE_MODE": "PRODUCTION_OBSERVE",
        }
    )

    assert config.enabled is True
    assert config.mode == "PRODUCTION_OBSERVE"
    assert config.execution_enabled is False
    assert config.risk_reservation_enabled is False
    assert config.trade_outbox_write_enabled is False
    assert config.ea_command_delivery_enabled is False
    assert config.mt5_order_send_enabled is False

    with pytest.raises(RuntimeError, match="REQUIRES_EXECUTION_OFF"):
        EvidenceRuntimeConfig.from_env(
            {
                "STRATEGY_5SCR_EVIDENCE_ENABLED": "true",
                "STRATEGY_5SCR_EVIDENCE_LIVE_ALLOWED": "true",
                "STRATEGY_5SCR_EVIDENCE_MODE": "PRODUCTION_OBSERVE",
                "EA_COMMAND_DELIVERY_ENABLED": "true",
            }
        )


class _SnapshotConnection:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.snapshot_hash: str | None = None

    async def execute(self, query: str, *args: Any) -> str:
        normalized = " ".join(query.split())
        self.calls.append(normalized)
        if "INSERT INTO strategy_5scr_evidence_snapshots" in normalized:
            self.snapshot_hash = str(args[5])
            return "INSERT 0 1"
        if "UPDATE strategy_5scr_inbox" in normalized:
            return "UPDATE 1"
        raise AssertionError(normalized)

    async def fetchrow(self, query: str, *_: Any) -> dict[str, str]:
        assert "strategy_5scr_evidence_snapshots" in query
        assert self.snapshot_hash is not None
        return {"payload_hash": self.snapshot_hash}


class _SnapshotPostgres:
    def __init__(self) -> None:
        self.conn = _SnapshotConnection()

    @asynccontextmanager
    async def transaction(self) -> Any:
        yield self.conn


class _RetryPostgres:
    def __init__(self) -> None:
        self.args: tuple[Any, ...] = ()
        self.query = ""

    async def execute(self, query: str, *args: Any) -> str:
        self.query = " ".join(query.split())
        self.args = args
        return "UPDATE 1"


@pytest.mark.asyncio
async def test_failure_schedules_bounded_retry_and_terminal_attempt() -> None:
    envelope = _envelope()
    pg = _RetryPostgres()
    repository = PostgresEvidenceRepository(pg=cast(Any, pg))

    assert await repository.record_failure(
        envelope,
        error="TRANSIENT_CANDLE_GAP",
        retry_delay_seconds=40,
        max_attempts=8,
    )
    assert "evidence_next_attempt_at" in pg.query
    assert "status = CASE" in pg.query
    assert pg.args[2:] == (40.0, 8)


@pytest.mark.asyncio
async def test_outcome_commits_immutable_snapshot_before_inbox_result() -> None:
    envelope = _envelope()
    pg = _SnapshotPostgres()
    repository = PostgresEvidenceRepository(pg=cast(Any, pg))
    evidence = Strategy5SCRMarketEvidence(
        decision_at_utc=envelope.signal_valid_at,
        lifecycle_anchor_utc=envelope.signal_valid_at,
        evidence_snapshot_id="5scr-evidence:" + "b" * 32,
    )
    outcome = PressureInboxOutcome(
        event_id=envelope.event_id,
        lifecycle_id=envelope.lifecycle_id,
        status="PROCESSED",
        decision="DEFER",
        result_id=f"5scr-defer:{envelope.event_id}",
    )

    assert await repository.record_outcome(
        envelope,
        outcome,
        evidence_snapshot=evidence,
    )
    assert "INSERT INTO strategy_5scr_evidence_snapshots" in pg.conn.calls[0]
    assert "UPDATE strategy_5scr_inbox" in pg.conn.calls[1]


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


class _DeferredProcessor:
    def process(self, envelope: PressureOutboxEnvelope, *, evidence: Any) -> PressureInboxOutcome:
        return PressureInboxOutcome(
            event_id=envelope.event_id,
            lifecycle_id=envelope.lifecycle_id,
            status="PROCESSED",
            decision="DEFER",
            result_id=f"5scr-defer:{envelope.event_id}",
            reasons=("STRATEGY_5SCR_M15_CLOSED_STRUCTURAL_BREAK_REQUIRED",),
        )


@pytest.mark.asyncio
async def test_live_evaluation_time_advances_beyond_anchor_and_defer_retries() -> None:
    envelope = _envelope()
    anchor = envelope.signal_valid_at
    evaluation_at = datetime(2026, 7, 20, 6, 30, tzinfo=UTC)
    repository = _CrashWindowRepository(envelope)
    provider = _Provider()
    worker = Strategy5SCREvidenceWorker(
        repository=cast(Any, repository),
        provider=provider,
        processor=cast(Any, _DeferredProcessor()),
        config=EvidenceRuntimeConfig(
            enabled=True,
            live_allowed=True,
            activation_requested=True,
            mode="PRODUCTION_OBSERVE",
            provider="finnhub",
            poll_seconds=5,
            batch_size=1,
        ),
        clock=lambda: evaluation_at,
    )

    assert await worker.process_once() == 1
    assert provider.kwargs["decision_at_utc"] == evaluation_at
    assert provider.kwargs["lifecycle_anchor_utc"] == anchor
    assert repository.failure_records == 1
    assert repository.outcome_attempts == 0
