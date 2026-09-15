"""Disposable-PostgreSQL proof for D0 canary control capability ledgers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from importlib import import_module
from uuid import UUID, uuid4

import pytest

from contracts.direct_broker_reconciliation import (
    DirectBrokerReconciliationRequest,
    DirectBrokerSourceSnapshotV1,
    ReconciliationCounts,
    canonical_sha256,
)
from contracts.mt5_execution_protocol import ExecutorMode
from contracts.mt5_mode_transition_authority import (
    ModeTransitionAuthorityPacket,
    canonical_mode_transition_authority_sha256,
)
from execution.direct_broker_reconciliation_repository import (
    DirectBrokerReconciliationRepository,
    PostgresDirectBrokerReconciliationStore,
)
from execution.mt5_executor_governance import (
    GovernanceConflictError,
    ModeTransitionError,
    MT5ExecutorGovernanceRepository,
)
from tests.integration import test_mt5_bridge_postgres_e2e as bridge_e2e

pytestmark = [pytest.mark.integration]

postgres = bridge_e2e.postgres
executor_id = bridge_e2e.executor_id
client = bridge_e2e.client
registered = bridge_e2e.registered


def _counts() -> ReconciliationCounts:
    return ReconciliationCounts(
        positions=0,
        pending_orders=0,
        orders=0,
        deals=0,
        matched_wolf15=0,
        manual_external=0,
        preexisting=0,
        orphan_wolf15=0,
        unattributed=0,
        ambiguous=0,
        ledger_mismatch=0,
    )


@pytest.mark.asyncio
async def test_direct_snapshot_is_append_only_and_idempotent_by_snapshot_command(
    postgres: object,
    registered: UUID,
) -> None:
    now = datetime.now(UTC)
    snapshot = DirectBrokerSourceSnapshotV1(
        snapshot_id=f"direct-{uuid4().hex}",
        executor_id=registered,
        account_reference="sha256:" + "a" * 64,
        broker_server_sha256="sha256:" + "b" * 64,
        observed_at_utc=now,
        counts=_counts(),
    )
    request = DirectBrokerReconciliationRequest(
        reconciliation_id=uuid4(),
        executor_id=registered,
        account_reference=snapshot.account_reference,
        broker_server_sha256=snapshot.broker_server_sha256,
        observed_at_utc=now,
        source_snapshot_id=snapshot.snapshot_id,
        source_snapshot_sha256=canonical_sha256(snapshot),
        counts=snapshot.counts,
        terminal_reason="EMPTY_ACCOUNT_MATCHED",
    )
    repository = DirectBrokerReconciliationRepository(PostgresDirectBrokerReconciliationStore(postgres))  # type: ignore[arg-type]
    first, duplicate = await repository.record(request, source_snapshot=snapshot.model_dump(mode="json"), now=now)
    assert duplicate is False and first.broker_ledger_reconciled is True

    second, duplicate = await repository.record(
        request.model_copy(update={"reconciliation_id": uuid4()}),
        source_snapshot=snapshot.model_dump(mode="json"),
        now=now + timedelta(milliseconds=1),
    )
    assert duplicate is True and second.reconciliation_id == first.reconciliation_id
    postgres_error = import_module("asyncpg").PostgresError
    with pytest.raises(postgres_error, match="immutable D0 canary control evidence"):
        await postgres.execute(  # type: ignore[attr-defined]
            "UPDATE direct_broker_reconciliation_receipts SET terminal_reason='MUTATED' "
            "WHERE reconciliation_id=$1::uuid",
            str(first.reconciliation_id),
        )


def _transition_packet(executor_id: UUID, *, now: datetime) -> ModeTransitionAuthorityPacket:
    values: dict[str, object] = {
        "authority_packet_id": uuid4(),
        "approval_id": f"d0-mode-{uuid4().hex}",
        "approved_by": "integration-operator",
        "approved_at_utc": now - timedelta(seconds=1),
        "expires_at_utc": now + timedelta(minutes=2),
        "executor_id": executor_id,
        "account_reference": bridge_e2e.ACCOUNT_ID,
        "broker_server": bridge_e2e.BROKER_SERVER,
        "configuration_sha256": "sha256:" + "c" * 64,
        "final_shadow_receipt_sha256": "sha256:" + "d" * 64,
        "previous_mode": ExecutorMode.SHADOW,
        "new_mode": ExecutorMode.DEMO,
        "consumption_limit": 1,
    }
    values["authority_packet_sha256"] = canonical_mode_transition_authority_sha256(values)
    return ModeTransitionAuthorityPacket.model_validate(values)


@pytest.mark.asyncio
async def test_shadow_to_demo_consumes_exact_authority_once(postgres: object, registered: UUID) -> None:
    repository = MT5ExecutorGovernanceRepository(pg=postgres)  # type: ignore[arg-type]
    packet = _transition_packet(registered, now=datetime.now(UTC))
    snapshot = await repository.transition_mode(
        registered,
        target_mode=ExecutorMode.DEMO,
        expected_mode=ExecutorMode.SHADOW,
        actor="integration-operator",
        reason="D0 governed promotion fixture",
        authority_packet=packet,
        observed_configuration_sha256=packet.configuration_sha256,
        observed_final_shadow_receipt_sha256=packet.final_shadow_receipt_sha256,
    )
    assert snapshot.execution_mode == ExecutorMode.DEMO.value
    await repository.transition_mode(
        registered,
        target_mode=ExecutorMode.SHADOW,
        expected_mode=ExecutorMode.DEMO,
        actor="integration-operator",
        reason="return to containment before reuse control",
    )
    with pytest.raises(GovernanceConflictError, match="already used|conflicts"):
        await repository.transition_mode(
            registered,
            target_mode=ExecutorMode.DEMO,
            expected_mode=ExecutorMode.SHADOW,
            actor="integration-operator",
            reason="reused authority must fail",
            authority_packet=packet,
            observed_configuration_sha256=packet.configuration_sha256,
            observed_final_shadow_receipt_sha256=packet.final_shadow_receipt_sha256,
        )


@pytest.mark.asyncio
async def test_shadow_to_demo_without_authority_fails_closed(postgres: object, registered: UUID) -> None:
    repository = MT5ExecutorGovernanceRepository(pg=postgres)  # type: ignore[arg-type]
    with pytest.raises(ModeTransitionError, match="exact one-use authority packet"):
        await repository.transition_mode(
            registered,
            target_mode=ExecutorMode.DEMO,
            expected_mode=ExecutorMode.SHADOW,
            actor="integration-operator",
            reason="missing authority must fail",
        )
