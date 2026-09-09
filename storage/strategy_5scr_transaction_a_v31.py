"""Own the TEST_ONLY multi-record transaction and acknowledge only after commit."""

import json
from uuid import UUID

from contracts.strategy_5scr_transaction_a_v31 import (
    TransactionABundleV31,
    TransactionAReceiptV31,
    TransactionARequestV31,
    transaction_content_hash_v31,
)
from storage import strategy_5scr_prepared_v31 as detached

PREFIX = "public.strategy_5scr_transaction_a_"


class TransactionARepositoryV31:
    def __init__(
        self, *, pg, capacity_repository, candidate_repository, verify_handoff, verify_universe, verify_risk_inputs
    ):
        self._pg = pg
        self.capacity = capacity_repository
        self.candidates = candidate_repository
        self.verify_handoff = verify_handoff
        self.verify_universe = verify_universe
        self.verify_risk_inputs = verify_risk_inputs

    async def _existing(self, connection, request, current):
        row = await connection.fetchrow(
            f"SELECT * FROM {PREFIX}campaigns_v31 WHERE reservation_id=$1", request.reservation_id
        )
        if row is None:
            return None
        if row["request_hash"] != transaction_content_hash_v31(request):
            raise ValueError("TRANSACTION_A_REPLAY_CONFLICT")
        payload = json.loads(row["payload"])
        bundle = TransactionABundleV31.model_validate(payload["bundle"])
        if bundle.request != request:
            raise ValueError("TRANSACTION_A_STORED_REQUEST_MISMATCH")
        expected = bundle.records()
        live = next((r for r in current.reservations if r.reservation_id == request.reservation_id), None)
        lifecycle_fields = {"state", "changed_at", "release_evidence_hash"}
        if live is None or live.model_dump(exclude=lifecycle_fields) != bundle.reservation.model_dump(
            exclude=lifecycle_fields
        ):
            raise ValueError("TRANSACTION_A_CAPACITY_BINDING_MISSING")
        for name, content in expected.items():
            stored = (
                row
                if name == "campaigns"
                else await connection.fetchrow(
                    f"SELECT * FROM {PREFIX}{name}_v31 WHERE reservation_id=$1", request.reservation_id
                )
            )
            ids = {
                "campaigns": request.campaign_id,
                "parent_legs": request.parent_leg_id,
                "signal_previews": request.signal_id,
                "outbox": request.outbox_id,
            }
            if (
                stored is None
                or stored["account_id"] != current.account_id
                or str(stored["record_id"]) != str(ids[name])
                or str(stored["reservation_id"]) != str(request.reservation_id)
                or str(stored["tradeplan_id"]) != request.sizing.tradeplan_id
                or stored["tradeplan_revision"] != request.sizing.tradeplan_revision
                or str(stored["campaign_id"]) != str(request.campaign_id)
                or str(stored["parent_leg_id"]) != str(request.parent_leg_id)
                or str(stored["signal_id"]) != str(request.signal_id)
                or stored["request_hash"] != transaction_content_hash_v31(request)
                or stored["payload_hash"] != transaction_content_hash_v31(content)
                or json.loads(stored["payload"]) != content
            ):
                raise ValueError("TRANSACTION_A_PARTIAL_OR_CORRUPT_BUNDLE")
        return bundle

    async def submit(self, request: TransactionARequestV31, *, now):
        request = TransactionARequestV31.model_validate(request.model_dump())
        request_digest = transaction_content_hash_v31(request)
        # Snapshot locks are released before any externally supplied verifier.
        # An exact historical bundle wins before freshness or a new proposal.
        async with self._pg.transaction() as connection:
            current = await self.capacity.lock_current(connection)
            if (request.sizing.expected_account_id, request.sizing.expected_executor_id) != (
                current.account_id,
                current.executor_id,
            ):
                raise ValueError("TRANSACTION_A_ACCOUNT_BINDING_MISMATCH")
            bundle = await self._existing(connection, request, current)
            latest = (
                await self.candidates.lock_latest(connection, UUID(request.sizing.tradeplan_id))
                if bundle is None
                else None
            )
        if bundle is not None:
            return TransactionAReceiptV31(status="DUPLICATE_TEST_ONLY", bundle=bundle)

        arguments = dict(
            request=request.sizing,
            expected_candidate_revision_hash=request.candidate_revision_hash,
            reservation_id=request.reservation_id,
            expires_at=request.expires_at,
            now=now,
            expected_capacity_version=request.expected_capacity_version,
        )
        prepared_token = self.candidates.prepare_parent_detached(
            latest,
            ledger=current,
            capacity_owner_epoch=self.capacity.fence.owner_epoch,
            **arguments,
            verify_handoff=self.verify_handoff,
            verify_universe=self.verify_universe,
            verify_risk_inputs=self.verify_risk_inputs,
        )
        if transaction_content_hash_v31(request) != request_digest:
            raise ValueError("TRANSACTION_A_REQUEST_CHANGED_DURING_VERIFICATION")

        # This is the only writing transaction. Reacquire both owners and state
        # bindings; never execute the verifier again while those locks are held.
        async with self._pg.transaction() as connection:
            current = await self.capacity.lock_current(connection)
            bundle = await self._existing(connection, request, current)
            duplicate = bundle is not None
            if bundle is None:
                prepared = await self.capacity.prepare_parent_in_transaction(
                    connection,
                    candidate_repository=self.candidates,
                    **arguments,
                    prepared=prepared_token,
                )
                if prepared.capacity.status != "APPLIED_TEST_ONLY":
                    raise ValueError("TRANSACTION_A_ORPHAN_CAPACITY_REQUIRES_RECONCILIATION")
                bundle = TransactionABundleV31(
                    profile="TEST_ONLY", request=request, reservation=prepared.capacity.reservation
                )
                ids = {
                    "campaigns": request.campaign_id,
                    "parent_legs": request.parent_leg_id,
                    "signal_previews": request.signal_id,
                    "outbox": request.outbox_id,
                }
                for name, payload in bundle.records().items():
                    await connection.execute(
                        f"INSERT INTO {PREFIX}{name}_v31(record_id,reservation_id,account_id,tradeplan_id,"
                        "tradeplan_revision,campaign_id,parent_leg_id,signal_id,request_hash,payload_hash,payload) "
                        "VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)",
                        ids[name],
                        request.reservation_id,
                        current.account_id,
                        UUID(request.sizing.tradeplan_id),
                        request.sizing.tradeplan_revision,
                        request.campaign_id,
                        request.parent_leg_id,
                        request.signal_id,
                        transaction_content_hash_v31(request),
                        transaction_content_hash_v31(payload),
                        json.dumps(payload),
                    )
                # Recheck after awaited writes. This is an application exit check,
                # not a guarantee about the server's eventual commit timestamp.
                detached.fresh_parent_v31(
                    request.sizing,
                    prepared.candidate_revision.request.handoff,
                    request.expires_at,
                    detached.commit_time_v31(),
                )
        # Even the duplicate path exits the transaction before its receipt leaves.
        return TransactionAReceiptV31(
            status="DUPLICATE_TEST_ONLY" if duplicate else "COMMITTED_TEST_ONLY", bundle=bundle
        )
