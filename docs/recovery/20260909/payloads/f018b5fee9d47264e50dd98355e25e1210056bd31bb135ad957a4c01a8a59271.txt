from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from contracts.direct_broker_reconciliation import (
    DirectBrokerReconciliationReceipt,
    DirectBrokerReconciliationRequest,
    ReconciliationCounts,
    canonical_sha256,
)
from execution.direct_broker_reconciliation_repository import (
    DirectBrokerReconciliationRepository,
    DirectSnapshotDigestMismatchError,
    ReconciliationConflictError,
    StaleDirectSnapshotError,
    reconciliation_evidence,
)

NOW = datetime(2026, 9, 5, 1, 0, tzinfo=UTC)
RID = UUID("00000000-0000-4000-8000-000000000001")
EID = UUID("00000000-0000-4000-8000-000000000002")


class MemoryStore:
    def __init__(self) -> None:
        self.rows: dict[UUID, DirectBrokerReconciliationReceipt] = {}

    async def get(self, reconciliation_id: UUID) -> DirectBrokerReconciliationReceipt | None:
        return self.rows.get(reconciliation_id)

    async def append_or_get(
        self, receipt: DirectBrokerReconciliationReceipt
    ) -> tuple[DirectBrokerReconciliationReceipt, bool]:
        existing = self.rows.get(receipt.reconciliation_id)
        if existing is None:
            existing = next(
                (
                    row
                    for row in self.rows.values()
                    if row.source_snapshot_sha256 == receipt.source_snapshot_sha256
                    and row.command_id == receipt.command_id
                ),
                None,
            )
        if existing is not None:
            if reconciliation_evidence(existing) != reconciliation_evidence(receipt):
                raise ReconciliationConflictError("terminal reconciliation identity already has different evidence")
            return existing, True
        self.rows[receipt.reconciliation_id] = receipt
        return receipt, False


def _snapshot(*, counts: ReconciliationCounts | None = None, snapshot_id: str = "direct-1") -> dict[str, object]:
    return {
        "schema_version": "wolf15.mt5.direct-broker-snapshot.v1",
        "source_type": "DIRECT_MT5_BROKER",
        "snapshot_id": snapshot_id,
        "executor_id": EID,
        "account_reference": "sha256:" + "a" * 64,
        "broker_server_sha256": "sha256:" + "b" * 64,
        "observed_at_utc": NOW,
        "counts": (counts or _counts()).model_dump(mode="json"),
    }


def _counts(**changes: int) -> ReconciliationCounts:
    values = {
        "positions": 0,
        "pending_orders": 0,
        "orders": 0,
        "deals": 0,
        "matched_wolf15": 0,
        "manual_external": 0,
        "preexisting": 0,
        "orphan_wolf15": 0,
        "unattributed": 0,
        "ambiguous": 0,
        "ledger_mismatch": 0,
    }
    values.update(changes)
    return ReconciliationCounts(**values)


def _request(**changes: object) -> DirectBrokerReconciliationRequest:
    counts = changes.get("counts")
    resolved_counts = counts if isinstance(counts, ReconciliationCounts) else _counts()
    snapshot = _snapshot(counts=resolved_counts)
    values: dict[str, object] = {
        "reconciliation_id": RID,
        "executor_id": EID,
        "account_reference": "sha256:" + "a" * 64,
        "broker_server_sha256": "sha256:" + "b" * 64,
        "observed_at_utc": NOW,
        "source_snapshot_id": "direct-1",
        "source_snapshot_sha256": canonical_sha256(snapshot),
        "counts": resolved_counts,
        "terminal_reason": "MATCHED",
    }
    values.update(changes)
    return DirectBrokerReconciliationRequest(**values)


@pytest.mark.asyncio
async def test_empty_direct_snapshot_is_reconciled_and_raw_values_are_not_persisted() -> None:
    store = MemoryStore()
    receipt, duplicate = await DirectBrokerReconciliationRepository(store).record(
        _request(), source_snapshot=_snapshot(), now=NOW
    )
    assert receipt.broker_ledger_reconciled is True
    assert duplicate is False
    assert len(store.rows) == 1
    serialized = receipt.model_dump_json()
    assert "login" not in serialized and "broker_ticket" not in serialized


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ("orphan_wolf15", "unattributed", "ambiguous", "ledger_mismatch"))
async def test_each_blocking_count_derives_false_and_cannot_be_overridden(field: str) -> None:
    counts = _counts(**{field: 1})
    receipt, _ = await DirectBrokerReconciliationRepository(MemoryStore()).record(
        _request(counts=counts), source_snapshot=_snapshot(counts=counts), now=NOW
    )
    assert receipt.broker_ledger_reconciled is False
    with pytest.raises(ValidationError):
        receipt.model_copy(update={"broker_ledger_reconciled": True}).model_validate(
            {**receipt.model_dump(), "broker_ledger_reconciled": True}
        )


@pytest.mark.asyncio
async def test_matched_order_deal_and_position_snapshot_is_reconciled() -> None:
    counts = _counts(positions=1, orders=1, deals=1, matched_wolf15=3)
    receipt, duplicate = await DirectBrokerReconciliationRepository(MemoryStore()).record(
        _request(counts=counts),
        source_snapshot=_snapshot(counts=counts),
        now=NOW,
    )
    assert duplicate is False
    assert receipt.broker_ledger_reconciled is True


@pytest.mark.asyncio
async def test_identical_duplicate_is_idempotent_but_conflict_is_rejected() -> None:
    store = MemoryStore()
    repository = DirectBrokerReconciliationRepository(store)
    first, _ = await repository.record(_request(), source_snapshot=_snapshot(), now=NOW)
    second, duplicate = await repository.record(_request(), source_snapshot=_snapshot(), now=NOW)
    assert duplicate is True and second == first and len(store.rows) == 1
    different_id = UUID("00000000-0000-4000-8000-000000000099")
    third, duplicate = await repository.record(
        _request(reconciliation_id=different_id), source_snapshot=_snapshot(), now=NOW
    )
    assert duplicate is True and third == first and len(store.rows) == 1
    with pytest.raises(ReconciliationConflictError):
        counts = _counts(ambiguous=1)
        await repository.record(
            _request(
                counts=counts,
                terminal_reason="AMBIGUOUS",
                source_snapshot_sha256=canonical_sha256(_snapshot(counts=counts)),
            ),
            source_snapshot=_snapshot(counts=counts),
            now=NOW,
        )


@pytest.mark.asyncio
async def test_stale_future_and_digest_mismatch_fail_closed() -> None:
    repository = DirectBrokerReconciliationRepository(MemoryStore())
    with pytest.raises(StaleDirectSnapshotError):
        await repository.record(_request(), source_snapshot=_snapshot(), now=NOW + timedelta(seconds=31))
    with pytest.raises(StaleDirectSnapshotError):
        await repository.record(_request(), source_snapshot=_snapshot(), now=NOW - timedelta(seconds=1))
    with pytest.raises(DirectSnapshotDigestMismatchError):
        await repository.record(_request(), source_snapshot=_snapshot(snapshot_id="tampered"), now=NOW)


def test_non_direct_source_and_raw_ticket_are_rejected_by_contract() -> None:
    with pytest.raises(ValidationError):
        _request(source_type="HEARTBEAT_DATABASE")
    with pytest.raises(ValidationError):
        _request(order_ticket_sha256="123456")
