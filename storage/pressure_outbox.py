"""PostgreSQL-backed durable transport for Wolf15 pressure events.

This module implements an at-least-once transactional outbox.  It never uses
Redis as durable storage and it never writes execution commands.  Until a
separate pressure-state table exists, the outbox row itself is the durable
pressure record written atomically with its per-lifecycle sequence.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast
from uuid import UUID, uuid5

from loguru import logger

from contracts.strategy_5scr_pressure_outbox import PressureOutboxEnvelope
from core.metrics import (
    PRESSURE_OUTBOX_BACKLOG,
    PRESSURE_OUTBOX_DEAD_TOTAL,
    PRESSURE_OUTBOX_OLDEST_AGE_SECONDS,
    PRESSURE_OUTBOX_PRODUCER_TOTAL,
    PRESSURE_OUTBOX_RETRY_TOTAL,
)
from storage.postgres_client import PostgresClient, pg_client

_PRESSURE_EVENT_NAMESPACE = UUID("a267327e-9b80-5be0-a169-5547a412471d")
_PRESSURE_OUTBOX_NAMESPACE = UUID("4d2f67b2-6d27-5a31-870a-7e17df64d826")
_RUNTIME_IDENTITY_FIELDS = frozenset({"deployment_id", "commit_sha", "replica_id", "generated_at_utc"})
_TRANSPORT_FIELDS = frozenset({"event_id", "lifecycle_id", "lifecycle_sequence", "pressure_outbox_id"})

_SELECT_COLUMNS = """
    id, event_id, event_type, schema_version, symbol, lifecycle_id,
    lifecycle_sequence, source_clean_block_id, source_watch_id,
    signal_valid_at, payload, payload_hash, status, attempt_count,
    available_at, locked_at, lease_expires_at, published_at, created_at
"""


class PressureOutboxError(RuntimeError):
    """Base error for durable pressure transport."""


class PressureOutboxContractError(PressureOutboxError):
    """Raised when a LIVE pressure event lacks canonical identity or safety."""


class PressureOutboxIntegrityError(PressureOutboxError):
    """Raised when an event ID is reused with a different semantic hash."""


@dataclass(frozen=True)
class _PreparedPressureEvent:
    outbox_id: UUID
    event_id: UUID
    schema_version: str
    symbol: str
    lifecycle_id: str
    source_clean_block_id: str | None
    source_watch_id: str | None
    signal_valid_at: datetime
    payload: dict[str, Any]
    payload_hash: str


PersistenceStatus = Literal["PERSISTED", "DUPLICATE", "DISABLED", "REJECTED", "FAILED"]


@dataclass(frozen=True)
class PressurePersistenceResult:
    status: PersistenceStatus
    envelope: PressureOutboxEnvelope | None = None
    error: str | None = None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    resolved = str(value).strip()
    return resolved or None


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000.0
        parsed = datetime.fromtimestamp(timestamp, tz=UTC)
    elif isinstance(value, str) and value.strip():
        raw = value.strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _signal_valid_at(payload: Mapping[str, Any]) -> datetime:
    for key in (
        "signal_valid_at",
        "signal_valid_time_utc",
        "observed_price_time",
        "price_snapshot_time_utc",
    ):
        parsed = _parse_datetime(payload.get(key))
        if parsed is not None:
            return parsed
    raise PressureOutboxContractError("PRESSURE_SIGNAL_VALID_AT_MISSING")


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def pressure_semantic_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Remove runtime and transport fields before hashing a pressure event."""

    excluded = _RUNTIME_IDENTITY_FIELDS | _TRANSPORT_FIELDS
    return {key: value for key, value in payload.items() if key not in excluded}


def pressure_payload_hash(payload: Mapping[str, Any]) -> str:
    semantic = pressure_semantic_payload(payload)
    return hashlib.sha256(_canonical_json(semantic).encode("utf-8")).hexdigest()


def pressure_retry_delay(
    attempt_count: int,
    *,
    base_backoff_seconds: float = 1.0,
    max_backoff_seconds: float = 300.0,
) -> float:
    """Return deterministic exponential retry delay for a 1-based attempt."""

    return min(
        max(0.0, float(max_backoff_seconds)),
        max(0.0, float(base_backoff_seconds)) * (2 ** max(0, int(attempt_count) - 1)),
    )


def prepare_pressure_event(payload: Mapping[str, Any]) -> _PreparedPressureEvent:
    """Freeze canonical LIVE identity without allocating a lifecycle sequence."""

    data = dict(payload)
    if any(data.get(field) is True for field in ("valid_for_execution", "execution_valid_now", "is_final_signal")):
        raise PressureOutboxContractError("PRESSURE_EXECUTION_FLAG_TRUE")
    if str(data.get("final_direction") or "WAIT").upper() != "WAIT":
        raise PressureOutboxContractError("PRESSURE_FINAL_DIRECTION_NOT_WAIT")
    if str(data.get("promotion_stage") or "PRESSURE_ONLY").upper() != "PRESSURE_ONLY":
        raise PressureOutboxContractError("PRESSURE_PROMOTION_STAGE_INVALID")

    symbol = str(data.get("symbol") or "").strip().upper()
    if not symbol:
        raise PressureOutboxContractError("PRESSURE_SYMBOL_MISSING")
    source_clean_block_id = _text(data.get("source_clean_block_id"))
    source_watch_id = _text(data.get("source_watch_id"))
    if not (source_clean_block_id or source_watch_id):
        raise PressureOutboxContractError("PRESSURE_CANONICAL_LINEAGE_MISSING")

    lineage_kind = "clean-block" if source_clean_block_id else "watch"
    lineage_value = cast(str, source_clean_block_id or source_watch_id)
    lifecycle_id = _text(data.get("lifecycle_id")) or f"pressure:{symbol}:{lineage_kind}:{lineage_value}"
    if len(lifecycle_id) > 500:
        raise PressureOutboxContractError("PRESSURE_LIFECYCLE_ID_TOO_LONG")

    data["event"] = "signal_pressure_state_json"
    data["schema_version"] = str(data.get("schema_version") or "2.0-pressure-state")
    data["symbol"] = symbol
    data["lifecycle_id"] = lifecycle_id
    data["promotion_stage"] = "PRESSURE_ONLY"
    data["final_direction"] = "WAIT"
    data["valid_for_execution"] = False
    data["execution_valid_now"] = False
    data["is_final_signal"] = False

    payload_hash = pressure_payload_hash(data)
    event_id = uuid5(_PRESSURE_EVENT_NAMESPACE, f"{lifecycle_id}|{payload_hash}")
    outbox_id = uuid5(_PRESSURE_OUTBOX_NAMESPACE, str(event_id))
    data["event_id"] = str(event_id)
    data["pressure_outbox_id"] = str(outbox_id)

    return _PreparedPressureEvent(
        outbox_id=outbox_id,
        event_id=event_id,
        schema_version=str(data["schema_version"]),
        symbol=symbol,
        lifecycle_id=lifecycle_id,
        source_clean_block_id=source_clean_block_id,
        source_watch_id=source_watch_id,
        signal_valid_at=_signal_valid_at(data),
        payload=data,
        payload_hash=payload_hash,
    )


def _payload_from_db(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return cast(dict[str, Any], parsed)
    raise PressureOutboxIntegrityError("PRESSURE_OUTBOX_PAYLOAD_INVALID")


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, TypeError):
        return default


def pressure_envelope_from_row(row: Any) -> PressureOutboxEnvelope:
    return PressureOutboxEnvelope(
        outbox_id=_row_value(row, "id"),
        event_id=_row_value(row, "event_id"),
        event_type=_row_value(row, "event_type"),
        schema_version=str(_row_value(row, "schema_version")),
        symbol=str(_row_value(row, "symbol")),
        lifecycle_id=str(_row_value(row, "lifecycle_id")),
        lifecycle_sequence=int(_row_value(row, "lifecycle_sequence")),
        source_clean_block_id=_row_value(row, "source_clean_block_id"),
        source_watch_id=_row_value(row, "source_watch_id"),
        signal_valid_at=_row_value(row, "signal_valid_at"),
        payload=_payload_from_db(_row_value(row, "payload")),
        payload_hash=str(_row_value(row, "payload_hash")),
        status=cast(Any, str(_row_value(row, "status", "PENDING"))),
        attempt_count=int(_row_value(row, "attempt_count", 0) or 0),
        available_at=_row_value(row, "available_at"),
        locked_at=_row_value(row, "locked_at"),
        lease_expires_at=_row_value(row, "lease_expires_at"),
        published_at=_row_value(row, "published_at"),
        created_at=_row_value(row, "created_at"),
    )


class PressureOutboxRepository:
    """Atomic producer, lease-based dispatcher repository, and replay reader."""

    def __init__(self, *, pg: PostgresClient | None = None) -> None:
        self._pg = pg or pg_client

    @property
    def is_available(self) -> bool:
        return self._pg.is_available

    async def enqueue(self, payload: Mapping[str, Any]) -> tuple[PressureOutboxEnvelope, bool]:
        """Persist one event and allocate its sequence in one DB transaction.

        Returns ``(envelope, duplicate)``.  The lifecycle counter row is locked
        before duplicate detection, preventing concurrent producer retries from
        consuming extra sequence numbers.
        """

        if not self._pg.is_available:
            raise PressureOutboxError("PRESSURE_OUTBOX_DATABASE_UNAVAILABLE")
        prepared = prepare_pressure_event(payload)
        async with self._pg.transaction() as conn:
            return await self.enqueue_in_transaction(conn, prepared)

    async def enqueue_in_transaction(
        self,
        conn: Any,
        prepared: _PreparedPressureEvent,
    ) -> tuple[PressureOutboxEnvelope, bool]:
        await conn.execute(
            """
            INSERT INTO pressure_lifecycle_sequences (lifecycle_id, last_sequence, updated_at)
            VALUES ($1, 0, NOW())
            ON CONFLICT (lifecycle_id) DO NOTHING
            """,
            prepared.lifecycle_id,
        )
        sequence_row = await conn.fetchrow(
            """
            SELECT last_sequence
            FROM pressure_lifecycle_sequences
            WHERE lifecycle_id = $1
            FOR UPDATE
            """,
            prepared.lifecycle_id,
        )
        if sequence_row is None:
            raise PressureOutboxError("PRESSURE_LIFECYCLE_SEQUENCE_ROW_MISSING")

        existing = await conn.fetchrow(
            f"SELECT {_SELECT_COLUMNS} FROM pressure_outbox WHERE event_id = $1",
            prepared.event_id,
        )
        if existing is not None:
            envelope = pressure_envelope_from_row(existing)
            if envelope.payload_hash != prepared.payload_hash:
                raise PressureOutboxIntegrityError("PRESSURE_EVENT_ID_HASH_MISMATCH")
            return envelope, True

        lifecycle_sequence = int(_row_value(sequence_row, "last_sequence", 0) or 0) + 1
        stored_payload = dict(prepared.payload)
        stored_payload["lifecycle_sequence"] = lifecycle_sequence
        row = await conn.fetchrow(
            f"""
            INSERT INTO pressure_outbox (
                id, event_id, event_type, schema_version, symbol, lifecycle_id,
                lifecycle_sequence, source_clean_block_id, source_watch_id,
                signal_valid_at, payload, payload_hash, status, attempt_count,
                available_at, created_at, updated_at
            ) VALUES (
                $1, $2, 'signal_pressure_state_json', $3, $4, $5,
                $6, $7, $8, $9, $10::jsonb, $11, 'PENDING', 0,
                NOW(), NOW(), NOW()
            )
            RETURNING {_SELECT_COLUMNS}
            """,
            prepared.outbox_id,
            prepared.event_id,
            prepared.schema_version,
            prepared.symbol,
            prepared.lifecycle_id,
            lifecycle_sequence,
            prepared.source_clean_block_id,
            prepared.source_watch_id,
            prepared.signal_valid_at,
            json.dumps(stored_payload, separators=(",", ":"), ensure_ascii=False, default=str),
            prepared.payload_hash,
        )
        if row is None:
            raise PressureOutboxError("PRESSURE_OUTBOX_INSERT_RETURNED_NO_ROW")
        await conn.execute(
            """
            UPDATE pressure_lifecycle_sequences
            SET last_sequence = $2, updated_at = NOW()
            WHERE lifecycle_id = $1
            """,
            prepared.lifecycle_id,
            lifecycle_sequence,
        )
        return pressure_envelope_from_row(row), False

    async def claim_batch(
        self,
        *,
        worker_id: str,
        batch_size: int = 100,
        lease_seconds: float = 30.0,
    ) -> list[PressureOutboxEnvelope]:
        if not self._pg.is_available:
            return []
        rows = await self._pg.fetch(
            f"""
            WITH candidates AS (
                SELECT candidate.id
                FROM pressure_outbox AS candidate
                WHERE ((
                    candidate.status = 'PENDING' AND candidate.available_at <= NOW()
                ) OR (
                    candidate.status = 'IN_FLIGHT' AND candidate.lease_expires_at <= NOW()
                ))
                  AND NOT EXISTS (
                    SELECT 1
                    FROM pressure_outbox AS predecessor
                    WHERE predecessor.lifecycle_id = candidate.lifecycle_id
                      AND predecessor.lifecycle_sequence < candidate.lifecycle_sequence
                      AND predecessor.status NOT IN ('PUBLISHED', 'DEAD')
                  )
                ORDER BY candidate.created_at, candidate.lifecycle_id, candidate.lifecycle_sequence
                FOR UPDATE SKIP LOCKED
                LIMIT $1
            )
            UPDATE pressure_outbox AS target
            SET status = 'IN_FLIGHT',
                locked_at = NOW(),
                locked_by = $2,
                lease_expires_at = NOW() + ($3 * INTERVAL '1 second'),
                updated_at = NOW()
            FROM candidates
            WHERE target.id = candidates.id
            RETURNING {_SELECT_COLUMNS}
            """,
            max(1, int(batch_size)),
            worker_id,
            max(1.0, float(lease_seconds)),
        )
        envelopes = [pressure_envelope_from_row(row) for row in rows]
        return sorted(envelopes, key=lambda item: (item.lifecycle_id, item.lifecycle_sequence))

    async def mark_published(self, event_id: UUID, *, worker_id: str) -> bool:
        result = await self._pg.execute(
            """
            UPDATE pressure_outbox
            SET status = 'PUBLISHED', published_at = NOW(), locked_at = NULL,
                locked_by = NULL, lease_expires_at = NULL, last_error = NULL,
                updated_at = NOW()
            WHERE event_id = $1 AND status = 'IN_FLIGHT' AND locked_by = $2
            """,
            event_id,
            worker_id,
        )
        return result.endswith(" 1")

    async def mark_retry(
        self,
        event_id: UUID,
        *,
        worker_id: str,
        error: str,
        max_attempts: int = 8,
        base_backoff_seconds: float = 1.0,
        max_backoff_seconds: float = 300.0,
    ) -> str:
        async with self._pg.transaction() as conn:
            row = await conn.fetchrow(
                """
                SELECT attempt_count
                FROM pressure_outbox
                WHERE event_id = $1 AND status = 'IN_FLIGHT' AND locked_by = $2
                FOR UPDATE
                """,
                event_id,
                worker_id,
            )
            if row is None:
                return "LEASE_LOST"
            attempt_count = int(_row_value(row, "attempt_count", 0) or 0) + 1
            is_dead = attempt_count >= max(1, int(max_attempts))
            status = "DEAD" if is_dead else "PENDING"
            delay = pressure_retry_delay(
                attempt_count,
                base_backoff_seconds=base_backoff_seconds,
                max_backoff_seconds=max_backoff_seconds,
            )
            available_at = datetime.now(UTC) + timedelta(seconds=delay)
            await conn.execute(
                """
                UPDATE pressure_outbox
                SET status = $3, attempt_count = $4, available_at = $5,
                    locked_at = NULL, locked_by = NULL, lease_expires_at = NULL,
                    last_error = $6, updated_at = NOW()
                WHERE event_id = $1 AND locked_by = $2
                """,
                event_id,
                worker_id,
                status,
                attempt_count,
                available_at,
                error[:2000],
            )
        if is_dead:
            PRESSURE_OUTBOX_DEAD_TOTAL.inc()
        else:
            PRESSURE_OUTBOX_RETRY_TOTAL.inc()
        return status

    async def mark_dead(self, event_id: UUID, *, worker_id: str, error: str) -> bool:
        result = await self._pg.execute(
            """
            UPDATE pressure_outbox
            SET status = 'DEAD', attempt_count = attempt_count + 1,
                locked_at = NULL, locked_by = NULL, lease_expires_at = NULL,
                last_error = $3, updated_at = NOW()
            WHERE event_id = $1 AND status = 'IN_FLIGHT' AND locked_by = $2
            """,
            event_id,
            worker_id,
            error[:2000],
        )
        changed = result.endswith(" 1")
        if changed:
            PRESSURE_OUTBOX_DEAD_TOTAL.inc()
        return changed

    async def metrics_snapshot(self) -> dict[str, float]:
        rows = await self._pg.fetch(
            """
            SELECT status, COUNT(*) AS count
            FROM pressure_outbox
            GROUP BY status
            """
        )
        snapshot = {str(_row_value(row, "status")): float(_row_value(row, "count", 0) or 0) for row in rows}
        age_row = await self._pg.fetchrow(
            """
            SELECT COALESCE(EXTRACT(EPOCH FROM (NOW() - MIN(created_at))), 0) AS oldest_age_seconds
            FROM pressure_outbox
            WHERE status IN ('PENDING', 'IN_FLIGHT')
            """
        )
        snapshot["oldest_age_seconds"] = float(_row_value(age_row, "oldest_age_seconds", 0.0) or 0.0)
        for status in ("PENDING", "IN_FLIGHT", "PUBLISHED", "DEAD"):
            PRESSURE_OUTBOX_BACKLOG.labels(status=status).set(snapshot.get(status, 0.0))
        PRESSURE_OUTBOX_OLDEST_AGE_SECONDS.set(snapshot["oldest_age_seconds"])
        return snapshot

    async def load_replay_events(
        self,
        *,
        lifecycle_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 10_000,
    ) -> list[PressureOutboxEnvelope]:
        """Read canonical replay input from PostgreSQL, never Railway logs."""

        rows = await self._pg.fetch(
            f"""
            SELECT {_SELECT_COLUMNS}
            FROM pressure_outbox
            WHERE ($1::text IS NULL OR lifecycle_id = $1)
              AND ($2::timestamptz IS NULL OR signal_valid_at >= $2)
              AND ($3::timestamptz IS NULL OR signal_valid_at <= $3)
            ORDER BY lifecycle_id, lifecycle_sequence
            LIMIT $4
            """,
            lifecycle_id,
            since,
            until,
            max(1, int(limit)),
        )
        return [pressure_envelope_from_row(row) for row in rows]


class PressureOutboxRuntime:
    """Thread-safe bridge from the synchronous pipeline to the asyncpg loop."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._repository: PressureOutboxRepository | None = None

    def configure(self, *, loop: asyncio.AbstractEventLoop, repository: PressureOutboxRepository) -> None:
        self._loop = loop
        self._repository = repository

    def clear(self) -> None:
        self._loop = None
        self._repository = None

    def persist_sync(self, payload: Mapping[str, Any], *, timeout_seconds: float = 5.0) -> PressurePersistenceResult:
        if os.getenv("SIGNAL_PRESSURE_OUTBOX_ENABLED", "false").strip().lower() != "true":
            return PressurePersistenceResult(status="DISABLED")
        loop = self._loop
        repository = self._repository
        if loop is None or repository is None or not loop.is_running() or not repository.is_available:
            PRESSURE_OUTBOX_PRODUCER_TOTAL.labels(outcome="failed").inc()
            return PressurePersistenceResult(status="FAILED", error="PRESSURE_OUTBOX_RUNTIME_UNAVAILABLE")
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None
        if current_loop is loop:
            PRESSURE_OUTBOX_PRODUCER_TOTAL.labels(outcome="failed").inc()
            return PressurePersistenceResult(
                status="FAILED",
                error="PRESSURE_OUTBOX_SYNC_BRIDGE_CALLED_ON_OWNER_LOOP",
            )

        future = asyncio.run_coroutine_threadsafe(repository.enqueue(payload), loop)
        try:
            envelope, duplicate = future.result(timeout=max(0.1, float(timeout_seconds)))
        except concurrent.futures.TimeoutError:
            future.cancel()
            PRESSURE_OUTBOX_PRODUCER_TOTAL.labels(outcome="failed").inc()
            return PressurePersistenceResult(status="FAILED", error="PRESSURE_OUTBOX_WRITE_TIMEOUT")
        except PressureOutboxContractError as exc:
            PRESSURE_OUTBOX_PRODUCER_TOTAL.labels(outcome="rejected").inc()
            return PressurePersistenceResult(status="REJECTED", error=str(exc))
        except Exception as exc:  # noqa: BLE001
            PRESSURE_OUTBOX_PRODUCER_TOTAL.labels(outcome="failed").inc()
            logger.warning("Durable pressure write failed: {}", exc)
            return PressurePersistenceResult(status="FAILED", error=str(exc))

        outcome = "duplicate" if duplicate else "persisted"
        PRESSURE_OUTBOX_PRODUCER_TOTAL.labels(outcome=outcome).inc()
        return PressurePersistenceResult(
            status="DUPLICATE" if duplicate else "PERSISTED",
            envelope=envelope,
        )


pressure_outbox_runtime = PressureOutboxRuntime()


def configure_pressure_outbox_runtime(
    *,
    loop: asyncio.AbstractEventLoop | None = None,
    repository: PressureOutboxRepository | None = None,
) -> None:
    pressure_outbox_runtime.configure(
        loop=loop or asyncio.get_running_loop(),
        repository=repository or PressureOutboxRepository(),
    )


def persist_pressure_payload_sync(payload: Mapping[str, Any]) -> PressurePersistenceResult:
    timeout = float(os.getenv("SIGNAL_PRESSURE_OUTBOX_WRITE_TIMEOUT_SECONDS", "5"))
    return pressure_outbox_runtime.persist_sync(payload, timeout_seconds=timeout)


__all__ = [
    "PressureOutboxContractError",
    "PressureOutboxError",
    "PressureOutboxIntegrityError",
    "PressureOutboxRepository",
    "PressureOutboxRuntime",
    "PressurePersistenceResult",
    "configure_pressure_outbox_runtime",
    "persist_pressure_payload_sync",
    "prepare_pressure_event",
    "pressure_envelope_from_row",
    "pressure_outbox_runtime",
    "pressure_payload_hash",
    "pressure_retry_delay",
    "pressure_semantic_payload",
]
