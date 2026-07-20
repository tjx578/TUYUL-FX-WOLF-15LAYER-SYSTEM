"""Durable pressure-radar manifests with atomic pressure-outbox promotion.

Every input event is deduplicated within its deployment.  Manifest transitions
are serialized per deployment/symbol with a PostgreSQL advisory transaction
lock.  An outbox row is created only when deferred canonical lineage promotes a
manifest to ``ANALYSIS_READY``; that enqueue and the manifest update share the
same database transaction.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast
from uuid import UUID

from loguru import logger

from analysis.strategy_5scr_pressure_radar import (
    PressureRadarAssembler,
    PressureRadarError,
    canonical_radar_payload,
    evaluate_pressure_radar,
)
from contracts.strategy_5scr_pressure_outbox import PressureOutboxEnvelope
from contracts.strategy_5scr_pressure_radar import PressureRadarManifest
from storage.postgres_client import PostgresClient, pg_client
from storage.pressure_outbox import (
    PressureOutboxContractError,
    PressureOutboxIntegrityError,
    PressureOutboxRepository,
    prepare_pressure_event,
)

_REQUIRED_RADAR_TABLES = frozenset({"pressure_radar_manifests", "pressure_radar_events"})
_REQUIRED_RADAR_INDEXES = frozenset(
    {
        "ix_pressure_radar_manifest_active",
        "ix_pressure_radar_manifest_expiry",
        "ix_pressure_radar_event_manifest",
    }
)
_ACTIVE_STATUSES = ("WAITING_CANONICAL_LINEAGE", "ANALYSIS_READY")


class PressureRadarPersistenceError(RuntimeError):
    """Base error for durable radar persistence."""


class PressureRadarPersistenceContractError(PressureRadarPersistenceError):
    """Raised when a LIVE radar event cannot be safely deployment-scoped."""


class PressureRadarPersistenceIntegrityError(PressureRadarPersistenceError):
    """Raised when a deployment/event identity is reused with new content."""


@dataclass(frozen=True)
class PressureRadarSchemaStatus:
    present_tables: frozenset[str]
    present_indexes: frozenset[str]
    missing_tables: tuple[str, ...]
    missing_indexes: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.missing_tables and not self.missing_indexes


@dataclass(frozen=True)
class DurablePressureRadarResult:
    transition: str
    manifest: PressureRadarManifest | None = None
    envelope: PressureOutboxEnvelope | None = None
    duplicate: bool = False


RadarPersistenceStatus = Literal["PERSISTED", "DUPLICATE", "DISABLED", "REJECTED", "FAILED"]


@dataclass(frozen=True)
class PressureRadarPersistenceResult:
    status: RadarPersistenceStatus
    transition: str | None = None
    manifest: PressureRadarManifest | None = None
    envelope: PressureOutboxEnvelope | None = None
    error: str | None = None


@dataclass(frozen=True)
class _StoredManifest:
    manifest: PressureRadarManifest
    qualifying_payload: dict[str, Any]
    outbox_event_id: UUID | None = None
    outbox_id: UUID | None = None


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, TypeError):
        return default


def _json_object(value: Any, *, error: str) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return cast(dict[str, Any], parsed)
    raise PressureRadarPersistenceIntegrityError(error)


def _uuid(value: Any) -> UUID | None:
    if value is None:
        return None
    return value if isinstance(value, UUID) else UUID(str(value))


def pressure_radar_payload_hash(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        dict(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _stored_manifest_from_row(row: Any) -> _StoredManifest:
    manifest_payload = _json_object(
        _row_value(row, "manifest"),
        error="PRESSURE_RADAR_MANIFEST_JSON_INVALID",
    )
    qualifying_payload = _json_object(
        _row_value(row, "qualifying_payload"),
        error="PRESSURE_RADAR_QUALIFYING_PAYLOAD_INVALID",
    )
    return _StoredManifest(
        manifest=PressureRadarManifest.model_validate(manifest_payload),
        qualifying_payload=qualifying_payload,
        outbox_event_id=_uuid(_row_value(row, "outbox_event_id")),
        outbox_id=_uuid(_row_value(row, "outbox_id")),
    )


class PressureRadarManifestRepository:
    """Deployment-scoped radar state machine backed by PostgreSQL."""

    def __init__(
        self,
        *,
        pg: PostgresClient | None = None,
        outbox_repository: PressureOutboxRepository | None = None,
    ) -> None:
        self._pg = pg or pg_client
        self._outbox = outbox_repository or PressureOutboxRepository(pg=self._pg)

    @property
    def is_available(self) -> bool:
        return self._pg.is_available

    async def schema_status(self) -> PressureRadarSchemaStatus:
        if not self._pg.is_available:
            return PressureRadarSchemaStatus(
                present_tables=frozenset(),
                present_indexes=frozenset(),
                missing_tables=tuple(sorted(_REQUIRED_RADAR_TABLES)),
                missing_indexes=tuple(sorted(_REQUIRED_RADAR_INDEXES)),
            )
        table_rows = await self._pg.fetch(
            """
            SELECT tablename
            FROM pg_catalog.pg_tables
            WHERE schemaname = current_schema()
              AND tablename = ANY($1::text[])
            """,
            sorted(_REQUIRED_RADAR_TABLES),
        )
        index_rows = await self._pg.fetch(
            """
            SELECT indexname
            FROM pg_catalog.pg_indexes
            WHERE schemaname = current_schema()
              AND indexname = ANY($1::text[])
            """,
            sorted(_REQUIRED_RADAR_INDEXES),
        )
        present_tables = frozenset(str(_row_value(row, "tablename") or "") for row in table_rows)
        present_indexes = frozenset(str(_row_value(row, "indexname") or "") for row in index_rows)
        return PressureRadarSchemaStatus(
            present_tables=present_tables,
            present_indexes=present_indexes,
            missing_tables=tuple(sorted(_REQUIRED_RADAR_TABLES - present_tables)),
            missing_indexes=tuple(sorted(_REQUIRED_RADAR_INDEXES - present_indexes)),
        )

    async def ingest(self, payload: Mapping[str, Any]) -> DurablePressureRadarResult:
        if not self._pg.is_available:
            raise PressureRadarPersistenceError("PRESSURE_RADAR_DATABASE_UNAVAILABLE")
        data = dict(payload)
        evaluation = evaluate_pressure_radar(data)
        if evaluation.deployment_id == "unknown":
            raise PressureRadarPersistenceContractError("PRESSURE_RADAR_DEPLOYMENT_ID_MISSING")
        payload_hash = pressure_radar_payload_hash(data)

        async with self._pg.transaction() as conn:
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                f"pressure-radar|{evaluation.deployment_id}|{evaluation.symbol}",
            )
            existing_event = await conn.fetchrow(
                """
                SELECT payload_hash, transition, manifest_id, outbox_event_id
                FROM pressure_radar_events
                WHERE deployment_id = $1 AND event_id = $2
                FOR UPDATE
                """,
                evaluation.deployment_id,
                evaluation.event_id,
            )
            if existing_event is not None:
                return await self._duplicate_result(conn, existing_event, payload_hash)

            stored = await self._load_active_manifests(
                conn,
                deployment_id=evaluation.deployment_id,
                symbol=evaluation.symbol,
            )
            prior = {item.manifest.manifest_id: item for item in stored}
            assembler = PressureRadarAssembler(item.manifest for item in stored)
            ingest_result = assembler.ingest(data)
            snapshots = assembler.snapshots(deployment_id=evaluation.deployment_id)

            envelope: PressureOutboxEnvelope | None = None
            ready_manifest = (
                ingest_result.manifest
                if ingest_result.transition == "ANALYSIS_READY" and ingest_result.manifest is not None
                else None
            )
            if ready_manifest is not None:
                qualifying_payload = self._qualifying_payload(
                    ready_manifest,
                    prior=prior,
                    current_payload=data,
                )
                canonical = canonical_radar_payload(ready_manifest, qualifying_payload)
                prepared = prepare_pressure_event(canonical)
                envelope, _ = await self._outbox.enqueue_in_transaction(conn, prepared)

            for manifest in snapshots:
                previous = prior.get(manifest.manifest_id)
                if previous is not None and previous.manifest == manifest:
                    continue
                qualifying_payload = self._qualifying_payload(
                    manifest,
                    prior=prior,
                    current_payload=data,
                )
                outbox_event_id = previous.outbox_event_id if previous else None
                outbox_id = previous.outbox_id if previous else None
                if ready_manifest is not None and manifest.manifest_id == ready_manifest.manifest_id:
                    assert envelope is not None
                    outbox_event_id = envelope.event_id
                    outbox_id = envelope.outbox_id
                await self._upsert_manifest(
                    conn,
                    manifest=manifest,
                    qualifying_payload=qualifying_payload,
                    outbox_event_id=outbox_event_id,
                    outbox_id=outbox_id,
                )

            event_manifest_id = ingest_result.manifest.manifest_id if ingest_result.manifest else None
            await conn.execute(
                """
                INSERT INTO pressure_radar_events (
                    deployment_id, event_id, symbol, observed_at_utc,
                    payload_hash, payload, transition, manifest_id,
                    outbox_event_id, created_at
                ) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9, NOW())
                """,
                evaluation.deployment_id,
                evaluation.event_id,
                evaluation.symbol,
                evaluation.observed_at_utc,
                payload_hash,
                json.dumps(data, separators=(",", ":"), ensure_ascii=False, default=str),
                ingest_result.transition,
                event_manifest_id,
                envelope.event_id if envelope else None,
            )
            return DurablePressureRadarResult(
                transition=ingest_result.transition,
                manifest=ingest_result.manifest,
                envelope=envelope,
            )

    async def _duplicate_result(
        self,
        conn: Any,
        event_row: Any,
        payload_hash: str,
    ) -> DurablePressureRadarResult:
        if str(_row_value(event_row, "payload_hash")) != payload_hash:
            raise PressureRadarPersistenceIntegrityError("PRESSURE_RADAR_EVENT_ID_HASH_MISMATCH")
        manifest_id = _row_value(event_row, "manifest_id")
        manifest: PressureRadarManifest | None = None
        if manifest_id:
            stored = await self._load_manifest(conn, str(manifest_id))
            manifest = stored.manifest if stored else None
        outbox_event_id = _uuid(_row_value(event_row, "outbox_event_id"))
        envelope = (
            await self._outbox.load_event_in_transaction(conn, outbox_event_id) if outbox_event_id is not None else None
        )
        if outbox_event_id is not None and envelope is None:
            raise PressureRadarPersistenceIntegrityError("PRESSURE_RADAR_OUTBOX_REFERENCE_MISSING")
        return DurablePressureRadarResult(
            transition=str(_row_value(event_row, "transition") or "RADAR_OBSERVED"),
            manifest=manifest,
            envelope=envelope,
            duplicate=True,
        )

    async def _load_active_manifests(
        self,
        conn: Any,
        *,
        deployment_id: str,
        symbol: str,
    ) -> list[_StoredManifest]:
        rows = await conn.fetch(
            """
            SELECT manifest, qualifying_payload, outbox_event_id, outbox_id
            FROM pressure_radar_manifests
            WHERE deployment_id = $1 AND symbol = $2
              AND status = ANY($3::text[])
            ORDER BY qualifying_time_utc, manifest_id
            FOR UPDATE
            """,
            deployment_id,
            symbol,
            list(_ACTIVE_STATUSES),
        )
        return [_stored_manifest_from_row(row) for row in rows]

    async def _load_manifest(self, conn: Any, manifest_id: str) -> _StoredManifest | None:
        row = await conn.fetchrow(
            """
            SELECT manifest, qualifying_payload, outbox_event_id, outbox_id
            FROM pressure_radar_manifests
            WHERE manifest_id = $1
            FOR UPDATE
            """,
            manifest_id,
        )
        return None if row is None else _stored_manifest_from_row(row)

    @staticmethod
    def _qualifying_payload(
        manifest: PressureRadarManifest,
        *,
        prior: Mapping[str, _StoredManifest],
        current_payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        previous = prior.get(manifest.manifest_id)
        if previous is not None:
            return dict(previous.qualifying_payload)
        return dict(current_payload)

    async def _upsert_manifest(
        self,
        conn: Any,
        *,
        manifest: PressureRadarManifest,
        qualifying_payload: Mapping[str, Any],
        outbox_event_id: UUID | None,
        outbox_id: UUID | None,
    ) -> None:
        if (outbox_event_id is None) != (outbox_id is None):
            raise PressureRadarPersistenceIntegrityError("PRESSURE_RADAR_PARTIAL_OUTBOX_REFERENCE")
        if manifest.status == "ANALYSIS_READY" and outbox_event_id is None:
            raise PressureRadarPersistenceIntegrityError("PRESSURE_RADAR_READY_OUTBOX_MISSING")
        await conn.execute(
            """
            INSERT INTO pressure_radar_manifests (
                manifest_id, deployment_id, gate_rule_version, symbol,
                raw_direction, context_signature, qualifying_time_utc,
                raw_direction_expires_at_utc, status, manifest,
                qualifying_payload, outbox_event_id, outbox_id,
                revision, created_at, updated_at
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9,
                $10::jsonb, $11::jsonb, $12, $13, 1, NOW(), NOW()
            )
            ON CONFLICT (manifest_id) DO UPDATE
            SET status = EXCLUDED.status,
                manifest = EXCLUDED.manifest,
                outbox_event_id = COALESCE(EXCLUDED.outbox_event_id, pressure_radar_manifests.outbox_event_id),
                outbox_id = COALESCE(EXCLUDED.outbox_id, pressure_radar_manifests.outbox_id),
                revision = pressure_radar_manifests.revision + 1,
                updated_at = NOW()
            """,
            manifest.manifest_id,
            manifest.deployment_id,
            manifest.gate_rule_version,
            manifest.symbol,
            manifest.raw_direction,
            manifest.context_signature,
            manifest.qualifying_time_utc,
            manifest.raw_direction_expires_at_utc,
            manifest.status,
            json.dumps(manifest.model_dump(mode="json"), separators=(",", ":"), ensure_ascii=False),
            json.dumps(dict(qualifying_payload), separators=(",", ":"), ensure_ascii=False, default=str),
            outbox_event_id,
            outbox_id,
        )


class PressureRadarRuntime:
    """Thread-safe bridge from the synchronous pipeline to radar persistence."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._repository: PressureRadarManifestRepository | None = None

    def configure(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        repository: PressureRadarManifestRepository,
    ) -> None:
        self._loop = loop
        self._repository = repository

    def clear(self) -> None:
        self._loop = None
        self._repository = None

    def persist_sync(
        self,
        payload: Mapping[str, Any],
        *,
        timeout_seconds: float = 5.0,
    ) -> PressureRadarPersistenceResult:
        flags_enabled = all(
            os.getenv(name, "false").strip().lower() == "true"
            for name in (
                "SIGNAL_PRESSURE_OUTBOX_ENABLED",
                "SIGNAL_PRESSURE_OUTBOX_WRITE_ENABLED",
                "SIGNAL_PRESSURE_RADAR_WRITE_ENABLED",
            )
        )
        if not flags_enabled:
            return PressureRadarPersistenceResult(status="DISABLED")
        loop = self._loop
        repository = self._repository
        if loop is None or repository is None or not loop.is_running() or not repository.is_available:
            return PressureRadarPersistenceResult(status="FAILED", error="PRESSURE_RADAR_RUNTIME_UNAVAILABLE")
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None
        if current_loop is loop:
            return PressureRadarPersistenceResult(
                status="FAILED",
                error="PRESSURE_RADAR_SYNC_BRIDGE_CALLED_ON_OWNER_LOOP",
            )

        future = asyncio.run_coroutine_threadsafe(repository.ingest(payload), loop)
        try:
            result = future.result(timeout=max(0.1, float(timeout_seconds)))
        except concurrent.futures.TimeoutError:
            future.cancel()
            return PressureRadarPersistenceResult(status="FAILED", error="PRESSURE_RADAR_WRITE_TIMEOUT")
        except (
            PressureRadarError,
            PressureRadarPersistenceContractError,
            PressureOutboxContractError,
        ) as exc:
            return PressureRadarPersistenceResult(status="REJECTED", error=str(exc))
        except (
            PressureRadarPersistenceIntegrityError,
            PressureOutboxIntegrityError,
        ) as exc:
            logger.error("Durable pressure radar integrity failure: {}", exc)
            return PressureRadarPersistenceResult(status="FAILED", error=str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Durable pressure radar write failed: {}", exc)
            return PressureRadarPersistenceResult(status="FAILED", error=str(exc))

        return PressureRadarPersistenceResult(
            status="DUPLICATE" if result.duplicate else "PERSISTED",
            transition=result.transition,
            manifest=result.manifest,
            envelope=result.envelope,
        )


pressure_radar_runtime = PressureRadarRuntime()


def configure_pressure_radar_runtime(
    *,
    loop: asyncio.AbstractEventLoop | None = None,
    repository: PressureRadarManifestRepository | None = None,
) -> None:
    pressure_radar_runtime.configure(
        loop=loop or asyncio.get_running_loop(),
        repository=repository or PressureRadarManifestRepository(),
    )


def persist_pressure_radar_payload_sync(payload: Mapping[str, Any]) -> PressureRadarPersistenceResult:
    timeout = float(
        os.getenv(
            "SIGNAL_PRESSURE_RADAR_WRITE_TIMEOUT_SECONDS",
            os.getenv("SIGNAL_PRESSURE_OUTBOX_WRITE_TIMEOUT_SECONDS", "5"),
        )
    )
    return pressure_radar_runtime.persist_sync(payload, timeout_seconds=timeout)


__all__ = [
    "DurablePressureRadarResult",
    "PressureRadarManifestRepository",
    "PressureRadarPersistenceContractError",
    "PressureRadarPersistenceError",
    "PressureRadarPersistenceIntegrityError",
    "PressureRadarPersistenceResult",
    "PressureRadarRuntime",
    "PressureRadarSchemaStatus",
    "configure_pressure_radar_runtime",
    "persist_pressure_radar_payload_sync",
    "pressure_radar_payload_hash",
    "pressure_radar_runtime",
]
