"""Transactional, append-only observer telemetry export for Wolf15.

This repository intentionally has no claim, ACK, retry, processed, or delete
operation.  An observer reads immutable rows with SELECT and advances a cursor
in the observer-owned database.  Producers must call ``append_in_transaction``
with the same asyncpg connection that writes the canonical source fact.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from contracts.observer_telemetry_export_v1 import (
    ObserverTelemetryDraftV1,
    ObserverTelemetryEnvelopeV1,
    build_observer_envelope,
    observer_event_hash,
)
from storage.postgres_client import PostgresClient, pg_client

OBSERVER_EXPORT_SCHEMA = "observer_export"
OBSERVER_EXPORT_STREAM_HEAD_TABLE = f"{OBSERVER_EXPORT_SCHEMA}.stream_heads"
OBSERVER_EXPORT_OUTBOX_TABLE = f"{OBSERVER_EXPORT_SCHEMA}.outbox"

_REQUIRED_TABLES = frozenset({"stream_heads", "outbox"})
_REQUIRED_INDEXES = frozenset(
    {
        "ix_observer_export_outbox_stream_read",
        "ix_observer_export_outbox_published",
        "ix_observer_export_outbox_payload_type",
    }
)
_REQUIRED_TRIGGERS = frozenset(
    {
        "trg_observer_export_reject_row_mutation",
        "trg_observer_export_reject_truncate",
    }
)

_SELECT_COLUMNS = """
    event_id, logical_event_key, stream_id, stream_sequence,
    previous_stream_sequence, previous_event_hash, event_hash,
    authority_class, payload_type, payload_version, envelope_version,
    payload_hash, envelope, source_system, source_service,
    source_commit_sha, source_deployment_id, policy_version,
    occurred_at, published_at, created_at
"""


class ObserverExportOutboxError(RuntimeError):
    """Base error for the durable observer export."""


class ObserverExportIntegrityError(ObserverExportOutboxError):
    """Raised when stable identity, hash, ordering, or projection drifts."""


@dataclass(frozen=True)
class ObserverExportAppendResult:
    envelope: ObserverTelemetryEnvelopeV1
    event_hash: str
    duplicate: bool = False


@dataclass(frozen=True)
class ObserverExportSchemaStatus:
    present_tables: frozenset[str]
    present_indexes: frozenset[str]
    present_triggers: frozenset[str]
    missing_tables: tuple[str, ...]
    missing_indexes: tuple[str, ...]
    missing_triggers: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.missing_tables and not self.missing_indexes and not self.missing_triggers


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, TypeError):
        return default


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return parsed
    raise ObserverExportIntegrityError("OBSERVER_EXPORT_ENVELOPE_JSON_INVALID")


def observer_export_from_row(row: Any) -> ObserverExportAppendResult:
    envelope = ObserverTelemetryEnvelopeV1.model_validate(_json_object(_row_value(row, "envelope")))
    stored_event_hash = str(_row_value(row, "event_hash") or "")
    if observer_event_hash(envelope) != stored_event_hash:
        raise ObserverExportIntegrityError("OBSERVER_EXPORT_EVENT_HASH_MISMATCH")
    expected_projection = (
        str(envelope.event_id),
        envelope.stream.stream_id,
        envelope.stream.stream_sequence,
        envelope.stream.previous_stream_sequence,
        envelope.stream.previous_event_hash,
        envelope.authority.authority_class,
        envelope.payload.payload_type,
        envelope.payload.payload_version,
        envelope.source.schema_version,
        envelope.payload.payload_hash,
        envelope.source.system,
        envelope.source.service,
        envelope.source.commit_sha,
        envelope.source.deployment_id,
        envelope.source.policy_version,
        envelope.timing.occurred_at_utc,
        envelope.timing.published_at_utc,
    )
    actual_projection = (
        str(_row_value(row, "event_id")),
        str(_row_value(row, "stream_id")),
        int(_row_value(row, "stream_sequence")),
        _optional_int(_row_value(row, "previous_stream_sequence")),
        _row_value(row, "previous_event_hash"),
        str(_row_value(row, "authority_class")),
        str(_row_value(row, "payload_type")),
        str(_row_value(row, "payload_version")),
        str(_row_value(row, "envelope_version")),
        str(_row_value(row, "payload_hash")),
        str(_row_value(row, "source_system")),
        str(_row_value(row, "source_service")),
        str(_row_value(row, "source_commit_sha")),
        _row_value(row, "source_deployment_id"),
        _row_value(row, "policy_version"),
        _row_value(row, "occurred_at"),
        _row_value(row, "published_at"),
    )
    if actual_projection != expected_projection:
        raise ObserverExportIntegrityError("OBSERVER_EXPORT_ENVELOPE_PROJECTION_MISMATCH")
    return ObserverExportAppendResult(envelope=envelope, event_hash=stored_event_hash)


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)


class ObserverExportOutboxRepository:
    """Allocate a contiguous hash-chained stream inside a caller transaction."""

    def __init__(self, *, pg: PostgresClient | None = None) -> None:
        self._pg = pg or pg_client

    @property
    def is_available(self) -> bool:
        return self._pg.is_available

    async def schema_status(self) -> ObserverExportSchemaStatus:
        if not self._pg.is_available:
            return ObserverExportSchemaStatus(
                present_tables=frozenset(),
                present_indexes=frozenset(),
                present_triggers=frozenset(),
                missing_tables=tuple(sorted(_REQUIRED_TABLES)),
                missing_indexes=tuple(sorted(_REQUIRED_INDEXES)),
                missing_triggers=tuple(sorted(_REQUIRED_TRIGGERS)),
            )
        table_rows = await self._pg.fetch(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = $1 AND table_name = ANY($2::text[])
            """,
            OBSERVER_EXPORT_SCHEMA,
            sorted(_REQUIRED_TABLES),
        )
        index_rows = await self._pg.fetch(
            """
            SELECT indexname
            FROM pg_catalog.pg_indexes
            WHERE schemaname = $1 AND indexname = ANY($2::text[])
            """,
            OBSERVER_EXPORT_SCHEMA,
            sorted(_REQUIRED_INDEXES),
        )
        trigger_rows = await self._pg.fetch(
            """
            SELECT trigger.tgname AS trigger_name
            FROM pg_catalog.pg_trigger AS trigger
            JOIN pg_catalog.pg_class AS relation ON relation.oid = trigger.tgrelid
            JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = $1
              AND relation.relname = $2
              AND NOT trigger.tgisinternal
              AND trigger.tgenabled IN ('O', 'A')
              AND trigger.tgname = ANY($3::text[])
            """,
            OBSERVER_EXPORT_SCHEMA,
            "outbox",
            sorted(_REQUIRED_TRIGGERS),
        )
        present_tables = frozenset(str(_row_value(row, "table_name")) for row in table_rows)
        present_indexes = frozenset(str(_row_value(row, "indexname")) for row in index_rows)
        present_triggers = frozenset(str(_row_value(row, "trigger_name")) for row in trigger_rows)
        return ObserverExportSchemaStatus(
            present_tables=present_tables,
            present_indexes=present_indexes,
            present_triggers=present_triggers,
            missing_tables=tuple(sorted(_REQUIRED_TABLES - present_tables)),
            missing_indexes=tuple(sorted(_REQUIRED_INDEXES - present_indexes)),
            missing_triggers=tuple(sorted(_REQUIRED_TRIGGERS - present_triggers)),
        )

    async def append_in_transaction(
        self,
        connection: Any,
        draft: ObserverTelemetryDraftV1,
        *,
        published_at_utc: datetime | None = None,
    ) -> ObserverExportAppendResult:
        """Append exactly one event using a transaction owned by the caller."""

        await connection.execute(
            f"""
            INSERT INTO {OBSERVER_EXPORT_STREAM_HEAD_TABLE} (
                stream_id, last_sequence, last_event_hash, updated_at
            ) VALUES ($1, 0, NULL, NOW())
            ON CONFLICT (stream_id) DO NOTHING
            """,
            draft.stream_id,
        )
        head = await connection.fetchrow(
            f"""
            SELECT last_sequence, last_event_hash
            FROM {OBSERVER_EXPORT_STREAM_HEAD_TABLE}
            WHERE stream_id = $1
            FOR UPDATE
            """,
            draft.stream_id,
        )
        if head is None:
            raise ObserverExportIntegrityError("OBSERVER_EXPORT_STREAM_HEAD_MISSING")
        last_sequence = int(_row_value(head, "last_sequence", 0) or 0)
        last_event_hash = _row_value(head, "last_event_hash")
        if (last_sequence == 0) != (last_event_hash is None):
            raise ObserverExportIntegrityError("OBSERVER_EXPORT_STREAM_HEAD_INVALID")

        existing = await connection.fetchrow(
            f"SELECT {_SELECT_COLUMNS} FROM {OBSERVER_EXPORT_OUTBOX_TABLE} WHERE event_id = $1",
            draft.event_id,
        )
        if existing is not None:
            return self._validate_duplicate(draft, existing, last_sequence, last_event_hash)

        sequence = last_sequence + 1
        published_at = published_at_utc or datetime.now(UTC)
        if published_at < draft.occurred_at_utc:
            published_at = draft.occurred_at_utc
        envelope = build_observer_envelope(
            draft,
            stream_sequence=sequence,
            previous_event_hash=last_event_hash,
            published_at_utc=published_at,
        )
        event_hash = observer_event_hash(envelope)
        row = await connection.fetchrow(
            f"""
            INSERT INTO {OBSERVER_EXPORT_OUTBOX_TABLE} (
                event_id, logical_event_key, stream_id, stream_sequence,
                previous_stream_sequence, previous_event_hash, event_hash,
                authority_class, payload_type, payload_version, envelope_version,
                payload_hash, envelope, source_system, source_service,
                source_commit_sha, source_deployment_id, policy_version,
                occurred_at, published_at, created_at
            ) VALUES (
                $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13::jsonb,$14,$15,
                $16,$17,$18,$19,$20,NOW()
            )
            RETURNING {_SELECT_COLUMNS}
            """,
            envelope.event_id,
            draft.logical_event_key,
            envelope.stream.stream_id,
            envelope.stream.stream_sequence,
            envelope.stream.previous_stream_sequence,
            envelope.stream.previous_event_hash,
            event_hash,
            envelope.authority.authority_class,
            envelope.payload.payload_type,
            envelope.payload.payload_version,
            envelope.source.schema_version,
            envelope.payload.payload_hash,
            json.dumps(envelope.model_dump(mode="json"), sort_keys=True, separators=(",", ":")),
            envelope.source.system,
            envelope.source.service,
            envelope.source.commit_sha,
            envelope.source.deployment_id,
            envelope.source.policy_version,
            envelope.timing.occurred_at_utc,
            envelope.timing.published_at_utc,
        )
        if row is None:
            raise ObserverExportOutboxError("OBSERVER_EXPORT_INSERT_RETURNED_NO_ROW")
        updated = await connection.execute(
            f"""
            UPDATE {OBSERVER_EXPORT_STREAM_HEAD_TABLE}
            SET last_sequence = $2, last_event_hash = $3, updated_at = NOW()
            WHERE stream_id = $1 AND last_sequence = $4
              AND last_event_hash IS NOT DISTINCT FROM $5
            """,
            draft.stream_id,
            sequence,
            event_hash,
            last_sequence,
            last_event_hash,
        )
        if not str(updated).endswith(" 1"):
            raise ObserverExportIntegrityError("OBSERVER_EXPORT_STREAM_HEAD_ADVANCE_FAILED")
        stored = observer_export_from_row(row)
        return ObserverExportAppendResult(
            envelope=stored.envelope,
            event_hash=stored.event_hash,
        )

    async def append_many_in_transaction(
        self,
        connection: Any,
        drafts: Sequence[ObserverTelemetryDraftV1],
    ) -> tuple[ObserverExportAppendResult, ...]:
        """Append a batch while locking stream IDs in deterministic order."""

        indexed = sorted(enumerate(drafts), key=lambda item: (item[1].stream_id, item[0]))
        results: dict[int, ObserverExportAppendResult] = {}
        for index, draft in indexed:
            results[index] = await self.append_in_transaction(connection, draft)
        return tuple(results[index] for index in range(len(drafts)))

    def _validate_duplicate(
        self,
        draft: ObserverTelemetryDraftV1,
        row: Any,
        head_sequence: int,
        head_event_hash: str | None,
    ) -> ObserverExportAppendResult:
        stored = observer_export_from_row(row)
        envelope = stored.envelope
        stable_projection = (
            str(_row_value(row, "logical_event_key")),
            envelope.stream.stream_id,
            envelope.authority.authority_class,
            envelope.payload.payload_type,
            envelope.payload.payload_version,
            envelope.payload.payload_hash,
            envelope.timing.occurred_at_utc,
        )
        incoming_projection = (
            draft.logical_event_key,
            draft.stream_id,
            draft.authority_class,
            draft.payload.payload_type,
            draft.payload.payload_version,
            draft.payload.payload_hash,
            draft.occurred_at_utc,
        )
        if stable_projection != incoming_projection:
            raise ObserverExportIntegrityError("OBSERVER_EXPORT_EVENT_ID_CONTENT_MISMATCH")
        if head_sequence < envelope.stream.stream_sequence:
            raise ObserverExportIntegrityError("OBSERVER_EXPORT_STREAM_HEAD_BEHIND_EVENT")
        if head_sequence == envelope.stream.stream_sequence and head_event_hash != stored.event_hash:
            raise ObserverExportIntegrityError("OBSERVER_EXPORT_STREAM_HEAD_HASH_MISMATCH")
        return ObserverExportAppendResult(
            envelope=envelope,
            event_hash=stored.event_hash,
            duplicate=True,
        )

    async def load_event(self, event_id: UUID) -> ObserverExportAppendResult | None:
        row = await self._pg.fetchrow(
            f"SELECT {_SELECT_COLUMNS} FROM {OBSERVER_EXPORT_OUTBOX_TABLE} WHERE event_id = $1",
            event_id,
        )
        return None if row is None else observer_export_from_row(row)

    async def read_stream(
        self,
        stream_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 1000,
    ) -> tuple[ObserverExportAppendResult, ...]:
        """Read immutable stream rows without changing upstream cursor state."""

        rows = await self._pg.fetch(
            f"""
            SELECT {_SELECT_COLUMNS}
            FROM {OBSERVER_EXPORT_OUTBOX_TABLE}
            WHERE stream_id = $1 AND stream_sequence > $2
            ORDER BY stream_sequence
            LIMIT $3
            """,
            stream_id,
            max(0, int(after_sequence)),
            max(1, min(10_000, int(limit))),
        )
        return tuple(observer_export_from_row(row) for row in rows)


__all__ = [
    "OBSERVER_EXPORT_OUTBOX_TABLE",
    "OBSERVER_EXPORT_SCHEMA",
    "OBSERVER_EXPORT_STREAM_HEAD_TABLE",
    "ObserverExportAppendResult",
    "ObserverExportIntegrityError",
    "ObserverExportOutboxError",
    "ObserverExportOutboxRepository",
    "ObserverExportSchemaStatus",
    "observer_export_from_row",
]
