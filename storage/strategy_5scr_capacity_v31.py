"""Caller-owned TEST_ONLY capacity persistence; no automatic bootstrap or DSN.

Acquire this account lock before candidate/symbol locks. Transaction A must add
campaign/leg/signal/outbox records on this same connection before commit. The
methods here return tentative state and do not authorize a command or broker.
"""

from uuid import uuid4

from contracts.strategy_5scr_capacity_owner_v31 import CapacityOwnerFenceV31
from contracts.strategy_5scr_capacity_v31 import CapacityLedgerV31
from risk.strategy_5scr_capacity_v31 import (
    capacity_ledger_hash_v31,
    refresh_capacity_baseline_v31,
    transition_capacity_v31,
)

TABLE = "public.strategy_5scr_capacity_ledgers_v31"


def _ledger(row):
    value = CapacityLedgerV31.model_validate_json(row["payload"])
    if (value.account_id, str(value.executor_id), value.version, value.owner_epoch) != (
        row["account_id"],
        str(row["executor_id"]),
        row["version"],
        row["owner_epoch"],
    ) or capacity_ledger_hash_v31(value) != row["ledger_hash"]:
        raise ValueError("CAPACITY_PERSISTED_STATE_MISMATCH")
    return value


class CapacityRepositoryV31:
    def __init__(self, *, fence: CapacityOwnerFenceV31):
        self.fence = CapacityOwnerFenceV31.model_validate(fence.model_dump())

    async def _account_lock(self, connection):
        if not connection.is_in_transaction():
            raise ValueError("CAPACITY_CALLER_TRANSACTION_REQUIRED")
        await connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended('5scr-capacity-v31:' || $1::text,0))",
            self.fence.account_id,
        )

    async def lock_current(self, connection):
        await self._account_lock(connection)
        row = await connection.fetchrow(f"SELECT * FROM {TABLE} WHERE account_id=$1 FOR UPDATE", self.fence.account_id)
        if row is None:
            raise ValueError("CAPACITY_PERSISTENCE_UNINITIALIZED")
        if any(
            str(row[key]) != str(getattr(self.fence, key))
            for key in ("executor_id", "owner_id", "owner_epoch", "token")
        ):
            raise ValueError("CAPACITY_PERSISTENCE_OWNER_FENCED")
        await connection.execute("SELECT set_config('wolf15.capacity_owner_token',$1,true)", str(self.fence.token))
        return _ledger(row)

    async def initialize_in_transaction(self, connection, ledger, *, verify_initial):
        """Explicit initialization with a verified initial baseline; never reset."""
        ledger = CapacityLedgerV31.model_validate(ledger.model_dump())
        if (
            (ledger.account_id, ledger.executor_id, ledger.owner_epoch)
            != (self.fence.account_id, self.fence.executor_id, self.fence.owner_epoch)
            or self.fence.owner_epoch != 1
            or ledger.version != 0
            or ledger.reservations
            or ledger.baseline_refreshes
        ):
            raise ValueError("CAPACITY_INITIAL_STATE_INVALID")
        digest = capacity_ledger_hash_v31(ledger)
        if verify_initial is None or verify_initial(ledger, digest) is not True:
            raise ValueError("CAPACITY_INITIAL_VERIFICATION_REJECTED")
        if capacity_ledger_hash_v31(ledger) != digest:
            raise ValueError("CAPACITY_INITIAL_EVIDENCE_CHANGED")
        await self._account_lock(connection)
        row = await connection.fetchrow(f"SELECT * FROM {TABLE} WHERE account_id=$1 FOR UPDATE", self.fence.account_id)
        if row is not None:
            current = await self.lock_current(connection)
            if row["initial_hash"] != digest:
                raise ValueError("CAPACITY_INITIALIZATION_CONFLICT")
            return current
        await connection.execute("SELECT set_config('wolf15.capacity_owner_token',$1,true)", str(self.fence.token))
        await connection.execute(
            f"INSERT INTO {TABLE}(account_id,executor_id,owner_id,owner_epoch,token,version,initial_hash,ledger_hash,payload) "
            "VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)",
            ledger.account_id,
            ledger.executor_id,
            self.fence.owner_id,
            ledger.owner_epoch,
            self.fence.token,
            ledger.version,
            digest,
            digest,
            ledger.model_dump_json(),
        )
        return ledger

    async def _save(self, connection, before, after, *, next_fence=None):
        after = CapacityLedgerV31.model_validate(after.model_dump())
        if after == before:
            return after
        target = next_fence or self.fence
        if (after.account_id, after.executor_id, after.version, after.owner_epoch) != (
            before.account_id,
            before.executor_id,
            before.version + 1,
            target.owner_epoch,
        ):
            raise ValueError("CAPACITY_PERSISTENCE_TRANSITION_INVALID")
        row = await connection.fetchrow(
            f"UPDATE {TABLE} SET owner_id=$1,owner_epoch=$2,token=$3,version=$4,ledger_hash=$5,payload=$6 "
            "WHERE account_id=$7 AND executor_id=$8 AND owner_id=$9 AND owner_epoch=$10 AND token=$11 "
            "AND version=$12 AND ledger_hash=$13 RETURNING account_id",
            target.owner_id,
            target.owner_epoch,
            target.token,
            after.version,
            capacity_ledger_hash_v31(after),
            after.model_dump_json(),
            self.fence.account_id,
            self.fence.executor_id,
            self.fence.owner_id,
            self.fence.owner_epoch,
            self.fence.token,
            before.version,
            capacity_ledger_hash_v31(before),
        )
        if row is None:
            raise ValueError("CAPACITY_PERSISTENCE_CAS_CONFLICT")
        return after

    async def transfer_owner_in_transaction(self, connection, *, next_owner_id, expected_version):
        before = await self.lock_current(connection)
        if type(expected_version) is not int or before.version != expected_version:
            raise ValueError("CAPACITY_PERSISTENCE_VERSION_CONFLICT")
        next_fence = CapacityOwnerFenceV31.model_validate(
            {
                **self.fence.model_dump(),
                "owner_id": next_owner_id,
                "owner_epoch": before.owner_epoch + 1,
                "token": uuid4(),
            }
        )
        after = before.model_copy(update={"owner_epoch": next_fence.owner_epoch, "version": before.version + 1})
        await self._save(connection, before, after, next_fence=next_fence)
        return next_fence

    async def prepare_parent_in_transaction(self, connection, *, candidate_repository, **kwargs):
        """Persist tentative capacity only; complete Transaction A remains caller-owned."""
        before = await self.lock_current(connection)
        prepared = await candidate_repository.prepare_parent_in_transaction(
            connection,
            ledger=before,
            capacity_owner_epoch=self.fence.owner_epoch,
            **kwargs,
        )
        await self._save(connection, before, prepared.capacity.ledger)
        return prepared

    async def transition_in_transaction(self, connection, *, expected_version, **kwargs):
        before = await self.lock_current(connection)
        proposal = transition_capacity_v31(
            before, owner_epoch=self.fence.owner_epoch, expected_version=expected_version, **kwargs
        )
        await self._save(connection, before, proposal.ledger)
        return proposal

    async def refresh_in_transaction(self, connection, request, *, expected_version, **kwargs):
        before = await self.lock_current(connection)
        proposal = refresh_capacity_baseline_v31(
            before, request, owner_epoch=self.fence.owner_epoch, expected_version=expected_version, **kwargs
        )
        await self._save(connection, before, proposal.ledger)
        return proposal
