from __future__ import annotations

import copy
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from storage.pressure_outbox import PressureOutboxRepository, pressure_retry_delay


def _payload(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "symbol": "GBPUSD",
        "source_watch_id": "GBPUSD:watch:canonical-1",
        "cluster_id": "GBPUSD_CLUSTER",
        "signal_valid_time_utc": "2026-07-20T02:00:00+00:00",
        "promotion_stage": "PRESSURE_ONLY",
        "final_direction": "WAIT",
        "valid_for_execution": False,
        "execution_valid_now": False,
        "is_final_signal": False,
        "pressure_seen": True,
        "pair_eligible_for_analysis": True,
        "pressure_event_count": 3,
    }
    payload.update(updates)
    return payload


class _FakeConnection:
    def __init__(self, state: dict[str, Any]) -> None:
        self.state = state
        self.queries: list[str] = []
        self.fail_insert = False

    async def execute(self, query: str, *args: Any) -> str:
        self.queries.append(query)
        normalized = " ".join(query.split())
        if "INSERT INTO pressure_lifecycle_sequences" in normalized:
            self.state["sequences"].setdefault(args[0], 0)
        elif "UPDATE pressure_lifecycle_sequences" in normalized:
            self.state["sequences"][args[0]] = int(args[1])
        return "UPDATE 1"

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        self.queries.append(query)
        normalized = " ".join(query.split())
        if "SELECT last_sequence" in normalized:
            return {"last_sequence": self.state["sequences"].get(args[0], 0)}
        if "FROM pressure_outbox WHERE event_id" in normalized:
            return self.state["events"].get(args[0])
        if "INSERT INTO pressure_outbox" in normalized:
            if self.fail_insert:
                raise ConnectionError("crash before commit")
            now = datetime(2026, 7, 20, 2, tzinfo=UTC)
            row = {
                "id": args[0],
                "event_id": args[1],
                "event_type": "signal_pressure_state_json",
                "schema_version": args[2],
                "symbol": args[3],
                "lifecycle_id": args[4],
                "lifecycle_sequence": args[5],
                "source_clean_block_id": args[6],
                "source_watch_id": args[7],
                "signal_valid_at": args[8],
                "payload": json.loads(args[9]),
                "payload_hash": args[10],
                "status": "PENDING",
                "attempt_count": 0,
                "available_at": now,
                "locked_at": None,
                "lease_expires_at": None,
                "published_at": None,
                "created_at": now,
            }
            self.state["events"][args[1]] = row
            return row
        raise AssertionError(f"Unexpected fetchrow query: {normalized}")


class _FakePostgres:
    def __init__(self) -> None:
        self.is_available = True
        self.state: dict[str, Any] = {"sequences": {}, "events": {}}
        self.conn = _FakeConnection(self.state)
        self.fetch_queries: list[str] = []

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[_FakeConnection]:
        snapshot = copy.deepcopy(self.state)
        try:
            yield self.conn
        except Exception:
            self.state.clear()
            self.state.update(snapshot)
            raise

    async def fetch(self, query: str, *args: Any) -> list[Any]:
        self.fetch_queries.append(query)
        return []


@pytest.mark.asyncio
async def test_producer_allocates_sequence_and_deduplicates_inside_one_transaction() -> None:
    pg = _FakePostgres()
    repository = PressureOutboxRepository(pg=cast(Any, pg))

    first, first_duplicate = await repository.enqueue(_payload())
    retry, retry_duplicate = await repository.enqueue(_payload())
    second, second_duplicate = await repository.enqueue(_payload(pressure_event_count=4))

    assert first_duplicate is False
    assert retry_duplicate is True
    assert second_duplicate is False
    assert retry.event_id == first.event_id
    assert first.lifecycle_sequence == 1
    assert second.lifecycle_sequence == 2
    assert pg.state["sequences"][first.lifecycle_id] == 2
    assert len(pg.state["events"]) == 2
    assert any("FOR UPDATE" in query for query in pg.conn.queries)


@pytest.mark.asyncio
async def test_failure_before_commit_rolls_back_pressure_and_sequence() -> None:
    pg = _FakePostgres()
    pg.conn.fail_insert = True
    repository = PressureOutboxRepository(pg=cast(Any, pg))

    with pytest.raises(ConnectionError, match="crash before commit"):
        await repository.enqueue(_payload())

    assert pg.state == {"sequences": {}, "events": {}}


@pytest.mark.asyncio
async def test_dispatch_claim_uses_atomic_skip_locked_lease() -> None:
    pg = _FakePostgres()
    repository = PressureOutboxRepository(pg=cast(Any, pg))

    assert await repository.claim_batch(worker_id="worker-a", batch_size=10, lease_seconds=30) == []

    sql = " ".join(pg.fetch_queries[0].split())
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "status = 'IN_FLIGHT'" in sql
    assert "lease_expires_at <= NOW()" in sql
    assert "predecessor.lifecycle_sequence < candidate.lifecycle_sequence" in sql
    assert "predecessor.status NOT IN ('PUBLISHED', 'DEAD')" in sql
    assert "UPDATE pressure_outbox AS target" in sql


@pytest.mark.asyncio
async def test_consumer_backlog_reads_only_published_received_rows() -> None:
    pg = _FakePostgres()
    repository = PressureOutboxRepository(pg=cast(Any, pg))

    assert await repository.load_consumer_pending(limit=25) == []

    sql = " ".join(pg.fetch_queries[0].split())
    assert "status = 'PUBLISHED'" in sql
    assert "inbox.status IN ('RECEIVED', 'FAILED')" in sql
    assert "inbox.event_id = pressure_outbox.event_id" in sql
    assert "LIMIT $1" in sql


def test_retry_delay_is_exponential_and_capped() -> None:
    assert [pressure_retry_delay(attempt) for attempt in range(1, 6)] == [1.0, 2.0, 4.0, 8.0, 16.0]
    assert pressure_retry_delay(20, max_backoff_seconds=300) == 300.0


class _RetryConnection:
    def __init__(self, attempt_count: int) -> None:
        self.attempt_count = attempt_count
        self.update_args: tuple[Any, ...] | None = None

    async def fetchrow(self, query: str, *args: Any) -> dict[str, int]:
        assert "FOR UPDATE" in query
        return {"attempt_count": self.attempt_count}

    async def execute(self, query: str, *args: Any) -> str:
        assert "UPDATE pressure_outbox" in query
        self.update_args = args
        return "UPDATE 1"


class _RetryPostgres:
    def __init__(self, attempt_count: int) -> None:
        self.is_available = True
        self.conn = _RetryConnection(attempt_count)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[_RetryConnection]:
        yield self.conn


@pytest.mark.asyncio
async def test_retry_threshold_moves_event_to_dead_letter() -> None:
    from uuid import UUID

    pg = _RetryPostgres(attempt_count=7)
    repository = PressureOutboxRepository(pg=cast(Any, pg))

    status = await repository.mark_retry(
        UUID("b0a3aaf0-0f69-4e91-8b46-68b93618f320"),
        worker_id="worker-dead",
        error="delivery failed",
        max_attempts=8,
    )

    assert status == "DEAD"
    assert pg.conn.update_args is not None
    assert pg.conn.update_args[2] == "DEAD"
    assert pg.conn.update_args[3] == 8
