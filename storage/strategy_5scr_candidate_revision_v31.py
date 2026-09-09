"""Explicitly injected PostgreSQL candidate history; no runtime activation.

Append acknowledgement leaves the owned transaction only after commit. The
in-transaction variant returns a tentative record for composition, not an ACK.
No default connection, owner acquisition, migration or risk effect is supplied.
"""

from uuid import UUID

from contracts.strategy_5scr_candidate_revision_v31 import (
    CandidateCapacityPreparationV31,
    CandidateRevisionAppendV31,
    StoredCandidateRevisionV31,
    candidate_revision_hash_v31,
    prepare_candidate_revision_v31,
)
from contracts.strategy_5scr_risk_adapter_v31 import ParentSizingRequestV31
from contracts.strategy_5scr_transaction_a_v31 import transaction_content_hash_v31
from risk.strategy_5scr_candidate_handoff_v31 import propose_canonical_parent_v31
from storage import strategy_5scr_prepared_v31 as detached
from storage.strategy_5scr_activity_consumer import bind_owner

TABLE = "public.strategy_5scr_candidate_revisions_v31"


def _stored(row):
    if row is None:
        return None
    request = CandidateRevisionAppendV31.model_validate_json(row["request_payload"])
    candidate = request.handoff.candidate
    if (
        str(row["tradeplan_id"]) != str(candidate.tradeplan_id)
        or row["revision"] != candidate.tradeplan_revision
        or row["symbol"] != candidate.symbol
        or str(row["reevaluation_id"]) != str(request.reevaluation_id)
        or row["predecessor_hash"] != request.predecessor_hash
    ):
        raise ValueError("CANDIDATE_ROW_IDENTITY_MISMATCH")
    return StoredCandidateRevisionV31(request=request, request_hash=row["request_hash"])


class CandidateRevisionRepositoryV31:
    def __init__(self, *, pg, fence, verify_reevaluation):
        self._pg = pg
        self.fence = fence
        self._verify = verify_reevaluation
        self._issuer = object()

    async def _bind(self, connection):
        if not connection.is_in_transaction():
            raise ValueError("CANDIDATE_CALLER_TRANSACTION_REQUIRED")
        await bind_owner(connection, self.fence)

    async def lock_latest(self, connection, tradeplan_id):
        """Locked history fact only: caller must validate current risk authority."""
        await self._bind(connection)
        row = await connection.fetchrow(
            f"SELECT * FROM {TABLE} WHERE tradeplan_id=$1 ORDER BY revision DESC LIMIT 1 FOR UPDATE", tradeplan_id
        )
        stored = _stored(row)
        if stored and stored.request.handoff.candidate.symbol != self.fence.symbol:
            raise ValueError("CANDIDATE_OWNER_SYMBOL_MISMATCH")
        return stored

    async def append_in_transaction(
        self, connection, request: CandidateRevisionAppendV31, *, now, prepared=None, **callbacks
    ):
        detached.reject_callbacks_v31(callbacks)
        if callbacks:
            raise ValueError("CANDIDATE_UNEXPECTED_ARGUMENT")
        request = CandidateRevisionAppendV31.model_validate(request.model_dump())
        candidate = request.handoff.candidate
        if candidate.symbol != self.fence.symbol:
            raise ValueError("CANDIDATE_OWNER_SYMBOL_MISMATCH")
        latest = await self.lock_latest(connection, candidate.tradeplan_id)
        existing = _stored(
            await connection.fetchrow(
                f"SELECT * FROM {TABLE} WHERE tradeplan_id=$1 AND revision=$2",
                candidate.tradeplan_id,
                candidate.tradeplan_revision,
            )
        )
        if existing:
            if existing.request_hash != candidate_revision_hash_v31(request):
                raise ValueError("CANDIDATE_REVISION_PAYLOAD_CONFLICT")
            # Historical acknowledgement does not move latest backwards or renew expiry.
            return existing
        prepared = detached.unseal_v31(
            prepared, self._issuer, "append", self._append_binding(request, latest), StoredCandidateRevisionV31
        )
        checked_at = detached.commit_time_v31()
        if not request.handoff.candidate.decision_at <= checked_at < request.handoff.handoff_receipt_valid_until:
            raise ValueError("CANDIDATE_REVISION_RECEIPT_EXPIRED")
        await connection.execute(
            f"INSERT INTO {TABLE}(tradeplan_id,revision,symbol,reevaluation_id,predecessor_revision,"
            "predecessor_hash,request_hash,request_payload) VALUES($1,$2,$3,$4,$5,$6,$7,$8)",
            candidate.tradeplan_id,
            candidate.tradeplan_revision,
            candidate.symbol,
            request.reevaluation_id,
            candidate.tradeplan_revision - 1 if candidate.tradeplan_revision > 1 else None,
            request.predecessor_hash,
            prepared.request_hash,
            request.model_dump_json(),
        )
        if (
            not request.handoff.candidate.decision_at
            <= detached.commit_time_v31()
            < request.handoff.handoff_receipt_valid_until
        ):
            raise ValueError("CANDIDATE_REVISION_RECEIPT_EXPIRED")
        return prepared

    def _append_binding(self, request, latest):
        return {
            "request": request.model_dump(mode="json"),
            "previous": latest.model_dump(mode="json") if latest else None,
            "fence": str(self.fence),
        }

    def prepare_append_detached(self, request, latest, *, now):
        original_hash = candidate_revision_hash_v31(request)
        original = request
        request = CandidateRevisionAppendV31.model_validate(request.model_dump())
        binding = self._append_binding(request, latest)
        before = transaction_content_hash_v31(binding)
        result = prepare_candidate_revision_v31(
            request, latest, now=now, verify_reevaluation=detached.guard_callback_v31(self._verify)
        )
        if (
            transaction_content_hash_v31(self._append_binding(request, latest)) != before
            or candidate_revision_hash_v31(original) != original_hash
        ):
            raise ValueError("DETACHED_VERIFIER_INPUT_CHANGED")
        return detached.seal_v31(self._issuer, "append", binding, result)

    async def append(self, request: CandidateRevisionAppendV31, *, now):
        original = request
        original_hash = candidate_revision_hash_v31(original)
        request = CandidateRevisionAppendV31.model_validate(request.model_dump())
        async with self._pg.transaction() as connection:
            latest = await self.lock_latest(connection, request.handoff.candidate.tradeplan_id)
            existing = _stored(
                await connection.fetchrow(
                    f"SELECT * FROM {TABLE} WHERE tradeplan_id=$1 AND revision=$2",
                    request.handoff.candidate.tradeplan_id,
                    request.handoff.candidate.tradeplan_revision,
                )
            )
            if existing and existing.request_hash != candidate_revision_hash_v31(request):
                raise ValueError("CANDIDATE_REVISION_PAYLOAD_CONFLICT")
        if existing:
            return existing
        prepared = self.prepare_append_detached(request, latest, now=now)
        if candidate_revision_hash_v31(original) != original_hash:
            raise ValueError("DETACHED_VERIFIER_INPUT_CHANGED")
        async with self._pg.transaction() as connection:
            result = await self.append_in_transaction(connection, request, now=now, prepared=prepared)
        return result

    def _parent_binding(self, latest, ledger, kwargs):
        return {
            "candidate": latest.model_dump(mode="json"),
            "ledger": ledger.model_dump(mode="json"),
            "fence": str(self.fence),
            "arguments": {
                k: (v.model_dump(mode="json") if hasattr(v, "model_dump") else str(v))
                for k, v in kwargs.items()
                if not k.startswith("verify_")
            },
        }

    def prepare_parent_detached(self, latest, *, ledger, **kwargs):
        request = ParentSizingRequestV31.model_validate(kwargs["request"].model_dump())
        if latest is None:
            raise ValueError("CANDIDATE_LATEST_REVISION_UNAVAILABLE")
        if (
            latest.request_hash != kwargs["expected_candidate_revision_hash"]
            or latest.request.handoff.candidate.tradeplan_revision != request.tradeplan_revision
        ):
            raise ValueError("CANDIDATE_LATEST_REVISION_MISMATCH")
        binding = self._parent_binding(latest, ledger, kwargs)
        before = transaction_content_hash_v31(binding)
        callback_kwargs = {
            k: detached.guard_callback_v31(v) if k.startswith("verify_") else v
            for k, v in kwargs.items()
            if k
            not in {"request", "expected_candidate_revision_hash", "capacity_owner_epoch", "expected_capacity_version"}
        }
        result = propose_canonical_parent_v31(
            ledger,
            latest.request.handoff,
            request,
            **callback_kwargs,
            owner_epoch=kwargs["capacity_owner_epoch"],
            expected_version=kwargs["expected_capacity_version"],
        )
        if transaction_content_hash_v31(self._parent_binding(latest, ledger, kwargs)) != before:
            raise ValueError("DETACHED_VERIFIER_INPUT_CHANGED")
        result = CandidateCapacityPreparationV31(profile="TEST_ONLY", candidate_revision=latest, capacity=result)
        return detached.seal_v31(self._issuer, "parent", binding, result)

    async def prepare_parent_in_transaction(
        self,
        connection,
        *,
        expected_candidate_revision_hash,
        ledger,
        request: ParentSizingRequestV31,
        reservation_id,
        expires_at,
        now,
        capacity_owner_epoch,
        expected_capacity_version,
        prepared=None,
        **callbacks,
    ) -> CandidateCapacityPreparationV31:
        """Prepare capacity from locked latest history in the caller transaction.

        The caller must lock/authenticate the account ledger and persist the
        complete Transaction A effects before commit. This method writes none
        of those effects and cannot be used as a durable reservation receipt.
        Historical append ACKs are separate from admission of the latest plan.
        """
        detached.reject_callbacks_v31(callbacks)
        if callbacks:
            raise ValueError("CANDIDATE_UNEXPECTED_ARGUMENT")
        request = ParentSizingRequestV31.model_validate(request.model_dump())
        latest = await self.lock_latest(connection, UUID(request.tradeplan_id))
        if latest is None:
            raise ValueError("CANDIDATE_LATEST_REVISION_UNAVAILABLE")
        if (
            latest.request_hash != expected_candidate_revision_hash
            or latest.request.handoff.candidate.tradeplan_revision != request.tradeplan_revision
        ):
            raise ValueError("CANDIDATE_LATEST_REVISION_MISMATCH")
        arguments = dict(
            expected_candidate_revision_hash=expected_candidate_revision_hash,
            request=request,
            reservation_id=reservation_id,
            expires_at=expires_at,
            now=now,
            capacity_owner_epoch=capacity_owner_epoch,
            expected_capacity_version=expected_capacity_version,
        )
        if any(item.reservation_id == reservation_id for item in ledger.reservations):
            # Pure historical identity validation precedes prepared-state checks.
            # A concurrent winner may have committed after our detached snapshot.
            proposal = propose_canonical_parent_v31(
                ledger,
                latest.request.handoff,
                request,
                reservation_id=reservation_id,
                expires_at=expires_at,
                now=now,
                owner_epoch=capacity_owner_epoch,
                expected_version=expected_capacity_version,
                verify_handoff=None,
                verify_universe=None,
                verify_risk_inputs=None,
            )
            return CandidateCapacityPreparationV31(profile="TEST_ONLY", candidate_revision=latest, capacity=proposal)
        result = detached.unseal_v31(
            prepared,
            self._issuer,
            "parent",
            self._parent_binding(latest, ledger, arguments),
            CandidateCapacityPreparationV31,
        )
        if result.capacity.status != "DUPLICATE_TEST_ONLY":
            detached.fresh_parent_v31(request, latest.request.handoff, expires_at, detached.commit_time_v31())
        return result
