"""Atomicity, idempotency, and ordering gates for observer export storage."""

from __future__ import annotations

import asyncio
import copy
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest

from contracts.observer_telemetry_export_v1 import (
    CanonicalDecisionReasonV1,
    observer_draft,
    observer_source_from_env,
)
from storage.observer_export_outbox import (
    ObserverExportIntegrityError,
    ObserverExportOutboxRepository,
)

NOW = datetime(2026, 8, 22, 2, 0, tzinfo=UTC)


def _draft(index: int, *, stream_id: str = "analysis-lifecycle:test"):
    body = CanonicalDecisionReasonV1(
        decision_id=f"decision-{index}",
        strategy_lifecycle_id="5scr-lifecycle:" + "a" * 32,
        authority_scope_id="5scr-lifecycle:" + "a" * 32,
        stage="TRADEPLAN_CANDIDATE",
        decision="WAIT",
        reason_code=f"WAIT_REASON_{index}",
        next_required_stage="CLOSED_CANDLE_EVIDENCE",
        evidence_refs=(f"evidence-{index}",),
        decided_at_utc=NOW + timedelta(seconds=index),
    )
    return observer_draft(
        logical_event_key=f"tradeplan-evaluation:{index}",
        stream_id=stream_id,
        occurred_at_utc=body.decided_at_utc,
        source=observer_source_from_env(
            service="strategy-5scr-tradeplan-candidate-v2",
            policy_version="5scr.tradeplan-candidate.v2",
            environ={"GIT_COMMIT_SHA": "b" * 40},
        ),
        body=body,
    )


class _FakeConnection:
    def __init__(self, postgres: _FakePostgres) -> None:
        self._postgres = postgres
        self.fail_insert = False

    async def execute(self, query: str, *args: Any) -> str:
        self._postgres.queries.append(query)
        normalized = " ".join(query.split())
        if "INSERT INTO observer_export.stream_heads" in normalized:
            self._postgres.heads.setdefault(args[0], {"last_sequence": 0, "last_event_hash": None})
            return "INSERT 0 1"
        if "UPDATE observer_export.stream_heads" in normalized:
            head = self._postgres.heads[args[0]]
            if head != {"last_sequence": args[3], "last_event_hash": args[4]}:
                return "UPDATE 0"
            head.update(last_sequence=args[1], last_event_hash=args[2])
            return "UPDATE 1"
        raise AssertionError(f"unexpected execute: {normalized}")

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        self._postgres.queries.append(query)
        normalized = " ".join(query.split())
        if "FROM observer_export.stream_heads" in normalized:
            return copy.deepcopy(self._postgres.heads.get(args[0]))
        if "FROM observer_export.outbox WHERE event_id" in normalized:
            return copy.deepcopy(self._postgres.outbox.get(args[0]))
        if "INSERT INTO observer_export.outbox" in normalized:
            if self.fail_insert:
                raise ConnectionError("injected observer export insert failure")
            row = {
                "event_id": args[0],
                "logical_event_key": args[1],
                "stream_id": args[2],
                "stream_sequence": args[3],
                "previous_stream_sequence": args[4],
                "previous_event_hash": args[5],
                "event_hash": args[6],
                "authority_class": args[7],
                "payload_type": args[8],
                "payload_version": args[9],
                "envelope_version": args[10],
                "payload_hash": args[11],
                "envelope": json.loads(args[12]),
                "source_system": args[13],
                "source_service": args[14],
                "source_commit_sha": args[15],
                "source_deployment_id": args[16],
                "policy_version": args[17],
                "occurred_at": args[18],
                "published_at": args[19],
                "created_at": args[19],
            }
            self._postgres.outbox[args[0]] = row
            return copy.deepcopy(row)
        raise AssertionError(f"unexpected fetchrow: {normalized}")


class _FakePostgres:
    def __init__(self) -> None:
        self.is_available = True
        self.heads: dict[str, dict[str, Any]] = {}
        self.outbox: dict[Any, dict[str, Any]] = {}
        self.queries: list[str] = []
        self.connection = _FakeConnection(self)
        self._transaction_lock = asyncio.Lock()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[_FakeConnection]:
        async with self._transaction_lock:
            heads = copy.deepcopy(self.heads)
            outbox = copy.deepcopy(self.outbox)
            try:
                yield self.connection
            except Exception:
                self.heads = heads
                self.outbox = outbox
                raise

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        return await self.connection.fetchrow(query, *args)

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        self.queries.append(query)
        normalized = " ".join(query.split())
        if "information_schema.tables" in normalized:
            return [{"table_name": "stream_heads"}, {"table_name": "outbox"}]
        if "pg_catalog.pg_indexes" in normalized:
            return [
                {"indexname": "ix_observer_export_outbox_stream_read"},
                {"indexname": "ix_observer_export_outbox_published"},
                {"indexname": "ix_observer_export_outbox_payload_type"},
            ]
        if "FROM pg_catalog.pg_trigger" in normalized:
            return [
                {"trigger_name": "trg_observer_export_reject_row_mutation"},
                {"trigger_name": "trg_observer_export_reject_truncate"},
            ]
        if "FROM observer_export.outbox" in normalized:
            stream_id, after_sequence, limit = args
            rows = [
                copy.deepcopy(row)
                for row in self.outbox.values()
                if row["stream_id"] == stream_id and row["stream_sequence"] > after_sequence
            ]
            return sorted(rows, key=lambda row: row["stream_sequence"])[:limit]
        raise AssertionError(f"unexpected fetch: {normalized}")


def _repository(pg: _FakePostgres) -> ObserverExportOutboxRepository:
    return ObserverExportOutboxRepository(pg=cast(Any, pg))


@pytest.mark.asyncio
async def test_append_allocates_contiguous_hash_chain_and_survives_restart() -> None:
    pg = _FakePostgres()
    repository = _repository(pg)
    async with pg.transaction() as connection:
        first = await repository.append_in_transaction(connection, _draft(1))
        second = await repository.append_in_transaction(connection, _draft(2))

    restarted = _repository(pg)
    async with pg.transaction() as connection:
        third = await restarted.append_in_transaction(connection, _draft(3))

    assert [first.envelope.stream.stream_sequence, second.envelope.stream.stream_sequence] == [1, 2]
    assert second.envelope.stream.previous_event_hash == first.event_hash
    assert third.envelope.stream.stream_sequence == 3
    assert third.envelope.stream.previous_event_hash == second.event_hash
    assert pg.heads["analysis-lifecycle:test"] == {
        "last_sequence": 3,
        "last_event_hash": third.event_hash,
    }


@pytest.mark.asyncio
async def test_exact_retry_is_idempotent_and_consumes_no_sequence() -> None:
    pg = _FakePostgres()
    repository = _repository(pg)
    draft = _draft(1)
    async with pg.transaction() as connection:
        first = await repository.append_in_transaction(connection, draft)
    async with pg.transaction() as connection:
        replay = await repository.append_in_transaction(connection, draft)

    assert replay.duplicate is True
    assert replay.envelope == first.envelope
    assert len(pg.outbox) == 1
    assert pg.heads[draft.stream_id]["last_sequence"] == 1


@pytest.mark.asyncio
async def test_same_event_id_with_different_payload_fails_closed() -> None:
    pg = _FakePostgres()
    repository = _repository(pg)
    original = _draft(1)
    changed_body = original.payload.body | {"reason_code": "MUTATED_CANONICAL_REASON"}
    changed = copy.copy(original)
    object.__setattr__(
        changed,
        "payload",
        original.payload.model_copy(
            update={
                "body": changed_body,
                "payload_hash": "sha256:" + "f" * 64,
            }
        ),
    )
    async with pg.transaction() as connection:
        await repository.append_in_transaction(connection, original)
    before = copy.deepcopy((pg.heads, pg.outbox))

    with pytest.raises(ObserverExportIntegrityError, match="CONTENT_MISMATCH"):
        async with pg.transaction() as connection:
            await repository.append_in_transaction(connection, changed)

    assert (pg.heads, pg.outbox) == before


@pytest.mark.asyncio
async def test_export_insert_failure_rolls_back_stream_head_and_event() -> None:
    pg = _FakePostgres()
    repository = _repository(pg)
    pg.connection.fail_insert = True

    with pytest.raises(ConnectionError, match="injected"):
        async with pg.transaction() as connection:
            await repository.append_in_transaction(connection, _draft(1))

    assert pg.heads == {}
    assert pg.outbox == {}


@pytest.mark.asyncio
async def test_concurrent_same_stream_publishers_commit_one_to_n_without_gaps() -> None:
    pg = _FakePostgres()
    repository = _repository(pg)

    async def publish(index: int) -> None:
        async with pg.transaction() as connection:
            await repository.append_in_transaction(connection, _draft(index))

    await asyncio.wait_for(asyncio.gather(*(publish(index) for index in range(1, 51))), timeout=10)

    rows = sorted(pg.outbox.values(), key=lambda row: row["stream_sequence"])
    assert [row["stream_sequence"] for row in rows] == list(range(1, 51))
    assert rows[0]["previous_event_hash"] is None
    assert all(
        current["previous_event_hash"] == previous["event_hash"]
        for previous, current in zip(rows, rows[1:], strict=False)
    )


@pytest.mark.asyncio
async def test_multi_stream_batch_uses_independent_heads_and_preserves_input_results() -> None:
    pg = _FakePostgres()
    repository = _repository(pg)
    drafts = (
        _draft(1, stream_id="stream-b"),
        _draft(2, stream_id="stream-a"),
        _draft(3, stream_id="stream-b"),
    )
    async with pg.transaction() as connection:
        results = await repository.append_many_in_transaction(connection, drafts)

    assert [item.envelope.event_id for item in results] == [item.event_id for item in drafts]
    assert [item.envelope.stream.stream_sequence for item in results] == [1, 1, 2]
    assert set(pg.heads) == {"stream-a", "stream-b"}


@pytest.mark.asyncio
async def test_read_stream_is_select_only_and_does_not_own_cursor() -> None:
    pg = _FakePostgres()
    repository = _repository(pg)
    async with pg.transaction() as connection:
        await repository.append_many_in_transaction(connection, (_draft(1), _draft(2), _draft(3)))
    before = copy.deepcopy((pg.heads, pg.outbox))

    rows = await repository.read_stream("analysis-lifecycle:test", after_sequence=1)

    assert [row.envelope.stream.stream_sequence for row in rows] == [2, 3]
    assert (pg.heads, pg.outbox) == before
    read_query = pg.queries[-1].upper()
    assert "SELECT" in read_query
    assert all(keyword not in read_query for keyword in ("UPDATE", "INSERT", "DELETE", "FOR UPDATE"))


@pytest.mark.asyncio
async def test_schema_status_requires_tables_indexes_and_immutability_triggers() -> None:
    status = await _repository(_FakePostgres()).schema_status()

    assert status.ready is True
    assert status.missing_tables == ()
    assert status.missing_indexes == ()
    assert status.missing_triggers == ()


def test_migration_has_append_only_pull_shape_and_select_only_conditional_grant() -> None:
    migration = (
        Path(__file__).parents[1] / "storage" / "migrations" / "versions" / "20260822_01_observer_export_outbox.py"
    ).read_text(encoding="utf-8")

    assert 'down_revision = "20260813_02"' in migration
    assert 'sa.Column("processed"' not in migration
    assert 'sa.Column("status"' not in migration
    assert 'sa.Column("consumer_cursor"' not in migration
    assert "BEFORE UPDATE OR DELETE" in migration
    assert "BEFORE TRUNCATE" in migration
    assert "GRANT SELECT ON ALL TABLES IN SCHEMA" in migration
    assert "GRANT INSERT" not in migration
    assert "GRANT UPDATE" not in migration
    assert "GRANT DELETE" not in migration


def test_runtime_has_no_callback_dispatch_or_upstream_ack_surface() -> None:
    runtime = (Path(__file__).parents[1] / "storage" / "observer_export_outbox.py").read_text(encoding="utf-8")
    forbidden_methods = (
        "mark_processed",
        "mark_published",
        "claim_batch",
        "acknowledge",
        "httpx",
        "requests",
        "redis",
        "socket",
    )

    assert all(term not in runtime for term in forbidden_methods)
