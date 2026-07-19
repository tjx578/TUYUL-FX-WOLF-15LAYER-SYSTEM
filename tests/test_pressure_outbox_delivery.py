from __future__ import annotations

import asyncio
import copy
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from contracts.strategy_5scr_pressure_outbox import PressureInboxOutcome, PressureOutboxEnvelope
from storage.pressure_outbox import prepare_pressure_event
from storage.pressure_outbox_worker import PressureOutboxWorker
from storage.strategy_5scr_pressure_inbox import (
    Strategy5SCRInboxConsumer,
    Strategy5SCRPressureProcessor,
    decide_inbox_delivery,
)


def _envelope(*, anchor: str = "clean-1", count: int = 3) -> PressureOutboxEnvelope:
    prepared = prepare_pressure_event(
        {
            "symbol": "USDJPY",
            "source_clean_block_id": anchor,
            "cluster_id": f"USDJPY:{anchor}:{count}",
            "signal_valid_time_utc": "2026-07-20T03:00:00+00:00",
            "promotion_stage": "PRESSURE_ONLY",
            "final_direction": "WAIT",
            "valid_for_execution": False,
            "execution_valid_now": False,
            "is_final_signal": False,
            "pressure_seen": True,
            "pair_eligible_for_analysis": True,
            "pressure_event_count": count,
            "raw_direction": "SELL",
        }
    )
    payload = {**prepared.payload, "lifecycle_sequence": 1}
    now = datetime(2026, 7, 20, 3, tzinfo=UTC)
    return PressureOutboxEnvelope(
        outbox_id=prepared.outbox_id,
        event_id=prepared.event_id,
        schema_version=prepared.schema_version,
        symbol=prepared.symbol,
        lifecycle_id=prepared.lifecycle_id,
        lifecycle_sequence=1,
        source_clean_block_id=prepared.source_clean_block_id,
        source_watch_id=prepared.source_watch_id,
        signal_valid_at=prepared.signal_valid_at,
        payload=payload,
        payload_hash=prepared.payload_hash,
        status="IN_FLIGHT",
        attempt_count=0,
        available_at=now,
        locked_at=now,
        lease_expires_at=now,
        created_at=now,
    )


class _InboxConnection:
    def __init__(self, rows: dict[Any, dict[str, Any]]) -> None:
        self.rows = rows

    async def execute(self, query: str, *args: Any) -> str:
        normalized = " ".join(query.split())
        event_id = args[0]
        if "INSERT INTO strategy_5scr_inbox" in normalized:
            self.rows.setdefault(
                event_id,
                {
                    "event_id": event_id,
                    "payload_hash": args[1],
                    "status": "RECEIVED",
                    "result_id": None,
                    "last_error": None,
                },
            )
        elif "INTEGRITY_VIOLATION" in normalized:
            self.rows[event_id]["status"] = "INTEGRITY_VIOLATION"
            self.rows[event_id]["last_error"] = "EVENT_ID_REUSED_WITH_DIFFERENT_PAYLOAD_HASH"
        elif "status = 'PROCESSING'" in normalized:
            self.rows[event_id]["status"] = "PROCESSING"
            self.rows[event_id]["last_error"] = None
        elif "SET status = $2" in normalized:
            self.rows[event_id]["status"] = args[1]
            self.rows[event_id]["result_id"] = args[2]
            self.rows[event_id]["last_error"] = args[3]
        else:
            raise AssertionError(f"Unexpected inbox execute: {normalized}")
        return "UPDATE 1"

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        assert "FOR UPDATE" in query
        return self.rows.get(args[0])


class _InboxPostgres:
    def __init__(self) -> None:
        self.is_available = True
        self.rows: dict[Any, dict[str, Any]] = {}
        self.conn = _InboxConnection(self.rows)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[_InboxConnection]:
        snapshot = copy.deepcopy(self.rows)
        try:
            yield self.conn
        except Exception:
            self.rows.clear()
            self.rows.update(snapshot)
            raise


class _CountingProcessor(Strategy5SCRPressureProcessor):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def process(self, envelope: PressureOutboxEnvelope) -> PressureInboxOutcome:
        self.calls += 1
        return super().process(envelope)


def test_inbox_delivery_decision_detects_duplicate_and_hash_conflict() -> None:
    assert decide_inbox_delivery(existing_hash="a", existing_status="PROCESSED", incoming_hash="a") == "DUPLICATE"
    assert (
        decide_inbox_delivery(existing_hash="a", existing_status="WAITING_EVIDENCE", incoming_hash="a") == "DUPLICATE"
    )
    assert (
        decide_inbox_delivery(existing_hash="a", existing_status="RECEIVED", incoming_hash="b") == "INTEGRITY_VIOLATION"
    )
    assert decide_inbox_delivery(existing_hash="a", existing_status="RECEIVED", incoming_hash="a") == "PROCESS"


@pytest.mark.asyncio
async def test_duplicate_delivery_produces_one_strategy_effect() -> None:
    pg = _InboxPostgres()
    processor = _CountingProcessor()
    consumer = Strategy5SCRInboxConsumer(pg=cast(Any, pg), processor=processor)
    event = _envelope()

    first = await consumer.consume(event)
    duplicate = await consumer.consume(event)

    assert first.status == "WAITING_EVIDENCE"
    assert first.decision == "DEFER"
    assert first.candidate_payload is None
    assert duplicate.duplicate is True
    assert duplicate.status == "WAITING_EVIDENCE"
    assert processor.calls == 1
    assert len(pg.rows) == 1


@pytest.mark.asyncio
async def test_same_event_id_with_different_hash_is_quarantined() -> None:
    pg = _InboxPostgres()
    consumer = Strategy5SCRInboxConsumer(pg=cast(Any, pg))
    event = _envelope()
    await consumer.consume(event)
    corrupt = event.model_copy(update={"payload_hash": "0" * 64})

    outcome = await consumer.consume(corrupt)

    assert outcome.status == "INTEGRITY_VIOLATION"
    assert pg.rows[event.event_id]["status"] == "INTEGRITY_VIOLATION"


class _AckCrashRepository:
    def __init__(self, event: PressureOutboxEnvelope) -> None:
        self.event = event
        self.published = False
        self.ack_calls = 0

    async def claim_batch(self, **_: Any) -> list[PressureOutboxEnvelope]:
        return [] if self.published else [self.event]

    async def mark_published(self, *_: Any, **__: Any) -> bool:
        self.ack_calls += 1
        if self.ack_calls == 1:
            raise ConnectionError("crash after delivery before acknowledgment")
        self.published = True
        return True

    async def mark_dead(self, *_: Any, **__: Any) -> bool:
        return True

    async def mark_retry(self, *_: Any, **__: Any) -> str:
        return "PENDING"

    async def metrics_snapshot(self) -> dict[str, float]:
        return {}


@pytest.mark.asyncio
async def test_crash_after_delivery_before_ack_redelivers_without_duplicate_effect() -> None:
    pg = _InboxPostgres()
    processor = _CountingProcessor()
    consumer = Strategy5SCRInboxConsumer(pg=cast(Any, pg), processor=processor)
    repository = _AckCrashRepository(_envelope())
    worker = PressureOutboxWorker(
        worker_id="worker-crash",
        repository=cast(Any, repository),
        consumer=consumer,
    )

    assert await worker.process_once() == 1
    assert repository.published is False
    assert await worker.process_once() == 1

    assert repository.published is True
    assert repository.ack_calls == 2
    assert processor.calls == 1


class _ConcurrentLeaseRepository:
    def __init__(self, events: list[PressureOutboxEnvelope]) -> None:
        self._events = list(events)
        self._lock = asyncio.Lock()
        self.published: set[Any] = set()

    async def claim_batch(self, **_: Any) -> list[PressureOutboxEnvelope]:
        async with self._lock:
            if not self._events:
                return []
            return [self._events.pop(0)]

    async def mark_published(self, event_id: Any, **_: Any) -> bool:
        self.published.add(event_id)
        return True

    async def mark_dead(self, *_: Any, **__: Any) -> bool:
        return True

    async def mark_retry(self, *_: Any, **__: Any) -> str:
        return "PENDING"

    async def metrics_snapshot(self) -> dict[str, float]:
        return {}


class _RecordingConsumer:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def consume(self, event: PressureOutboxEnvelope) -> PressureInboxOutcome:
        self.events.append(event.event_id)
        return PressureInboxOutcome(
            event_id=event.event_id,
            lifecycle_id=event.lifecycle_id,
            status="WAITING_EVIDENCE",
            decision="DEFER",
        )


@pytest.mark.asyncio
async def test_two_workers_claim_distinct_events() -> None:
    events = [_envelope(anchor="clean-a"), _envelope(anchor="clean-b")]
    repository = _ConcurrentLeaseRepository(events)
    consumer = _RecordingConsumer()
    workers = [
        PressureOutboxWorker(
            worker_id=f"worker-{index}",
            repository=cast(Any, repository),
            consumer=cast(Any, consumer),
            batch_size=1,
        )
        for index in range(2)
    ]

    processed = await asyncio.gather(*(worker.process_once() for worker in workers))

    assert processed == [1, 1]
    assert len(set(consumer.events)) == 2
    assert repository.published == {event.event_id for event in events}
