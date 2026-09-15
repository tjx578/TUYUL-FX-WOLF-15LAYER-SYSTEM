"""Append-only repository service for authoritative direct-broker receipts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from contracts.direct_broker_reconciliation import (
    DirectBrokerReconciliationReceipt,
    DirectBrokerReconciliationRequest,
    DirectBrokerSourceSnapshotV1,
    canonical_sha256,
)
from storage.postgres_client import PostgresClient, pg_client


class ReconciliationError(RuntimeError):
    pass


class StaleDirectSnapshotError(ReconciliationError):
    pass


class DirectSnapshotDigestMismatchError(ReconciliationError):
    pass


class ReconciliationConflictError(ReconciliationError):
    pass


class ReconciliationReceiptStore(Protocol):
    async def get(self, reconciliation_id: UUID) -> DirectBrokerReconciliationReceipt | None: ...

    async def append_or_get(
        self, receipt: DirectBrokerReconciliationReceipt
    ) -> tuple[DirectBrokerReconciliationReceipt, bool]: ...


def reconciliation_evidence(receipt: DirectBrokerReconciliationReceipt) -> dict[str, object]:
    """Return terminal evidence independent of caller-selected receipt identity."""

    return receipt.model_dump(
        mode="json",
        exclude={"reconciliation_id", "created_at_utc", "receipt_sha256"},
    )


class DirectBrokerReconciliationRepository:
    """Validate direct evidence, derive the verdict, and append one terminal receipt."""

    def __init__(self, store: ReconciliationReceiptStore, *, max_snapshot_age: timedelta = timedelta(seconds=30)):
        self._store = store
        self._max_snapshot_age = max_snapshot_age

    async def record(
        self,
        request: DirectBrokerReconciliationRequest,
        *,
        source_snapshot: Mapping[str, object],
        now: datetime | None = None,
    ) -> tuple[DirectBrokerReconciliationReceipt, bool]:
        clock = now or datetime.now(UTC)
        if clock.tzinfo is None:
            raise ReconciliationError("repository clock must be timezone-aware")
        age = clock.astimezone(UTC) - request.observed_at_utc
        if age < timedelta(0) or age > self._max_snapshot_age:
            raise StaleDirectSnapshotError("direct snapshot is stale or future-dated")
        try:
            snapshot = DirectBrokerSourceSnapshotV1.model_validate(dict(source_snapshot))
        except ValueError as exc:
            raise ReconciliationError("direct snapshot schema validation failed") from exc
        if canonical_sha256(snapshot) != request.source_snapshot_sha256:
            raise DirectSnapshotDigestMismatchError("direct snapshot digest mismatch")
        if (
            snapshot.snapshot_id != request.source_snapshot_id
            or snapshot.executor_id != request.executor_id
            or snapshot.account_reference != request.account_reference
            or snapshot.broker_server_sha256 != request.broker_server_sha256
            or snapshot.observed_at_utc != request.observed_at_utc
            or snapshot.counts != request.counts
        ):
            raise ReconciliationError("direct snapshot binding differs from reconciliation request")

        material: dict[str, Any] = {
            **request.model_dump(),
            "counts": request.counts,
            "broker_ledger_reconciled": request.counts.reconciled,
            "created_at_utc": clock.astimezone(UTC),
        }
        # Hash the receipt's validated representation.  Pydantic canonicalizes
        # UTC datetime strings (for example ``+00:00`` to ``Z``), so hashing the
        # pre-validation request dictionary would bind different bytes.
        draft = DirectBrokerReconciliationReceipt.model_construct(**material, receipt_sha256="sha256:" + "0" * 64)
        canonical_material = draft.model_dump(mode="json", exclude={"receipt_sha256"})
        receipt = DirectBrokerReconciliationReceipt.model_validate(
            {**material, "receipt_sha256": canonical_sha256(canonical_material)}
        )
        existing = await self._store.get(request.reconciliation_id)
        if existing is not None:
            if reconciliation_evidence(existing) != reconciliation_evidence(receipt):
                raise ReconciliationConflictError("terminal reconciliation identity already has different evidence")
            return existing, True
        return await self._store.append_or_get(receipt)


class PostgresDirectBrokerReconciliationStore:
    """Atomic append-or-get adapter for the immutable PostgreSQL ledger."""

    def __init__(self, pg: PostgresClient | None = None) -> None:
        self._pg = pg or pg_client

    async def get(self, reconciliation_id: UUID) -> DirectBrokerReconciliationReceipt | None:
        row = await self._pg.fetchrow(
            "SELECT payload FROM direct_broker_reconciliation_receipts WHERE reconciliation_id=$1::uuid",
            str(reconciliation_id),
        )
        if not row:
            return None
        payload = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        return DirectBrokerReconciliationReceipt.model_validate(payload)

    async def append_or_get(
        self, receipt: DirectBrokerReconciliationReceipt
    ) -> tuple[DirectBrokerReconciliationReceipt, bool]:
        async with self._pg.transaction() as connection:
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended('wolf15:direct-reconciliation:' || $1::text, 0))",
                str(receipt.reconciliation_id),
            )
            existing = await connection.fetchrow(
                """
                SELECT payload
                FROM direct_broker_reconciliation_receipts
                WHERE reconciliation_id=$1::uuid
                   OR (source_snapshot_sha256=$2 AND command_id IS NOT DISTINCT FROM $3::uuid)
                """,
                str(receipt.reconciliation_id),
                receipt.source_snapshot_sha256,
                str(receipt.command_id) if receipt.command_id else None,
            )
            if existing:
                existing_payload = existing["payload"]
                if isinstance(existing_payload, str):
                    existing_payload = json.loads(existing_payload)
                found = DirectBrokerReconciliationReceipt.model_validate(existing_payload)
                if reconciliation_evidence(found) != reconciliation_evidence(receipt):
                    raise ReconciliationConflictError("terminal reconciliation identity already has different evidence")
                return found, True
            await connection.execute(
                """
                INSERT INTO direct_broker_reconciliation_receipts (
                    reconciliation_id, executor_id, account_reference, broker_server_sha256,
                    source_snapshot_id, source_snapshot_sha256, command_id, observed_at,
                    counts, broker_ledger_reconciled, terminal_reason, receipt_sha256,
                    payload, created_at
                ) VALUES (
                    $1::uuid, $2::uuid, $3, $4, $5, $6, $7::uuid, $8,
                    $9::jsonb, $10, $11, $12, $13::jsonb, $14
                )
                """,
                str(receipt.reconciliation_id),
                str(receipt.executor_id),
                receipt.account_reference,
                receipt.broker_server_sha256,
                receipt.source_snapshot_id,
                receipt.source_snapshot_sha256,
                str(receipt.command_id) if receipt.command_id else None,
                receipt.observed_at_utc,
                receipt.counts.model_dump_json(),
                receipt.broker_ledger_reconciled,
                receipt.terminal_reason,
                receipt.receipt_sha256,
                receipt.model_dump_json(),
                receipt.created_at_utc,
            )
        return receipt, False
