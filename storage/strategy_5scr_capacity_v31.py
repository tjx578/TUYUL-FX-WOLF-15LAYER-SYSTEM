"""Caller-owned TEST_ONLY capacity persistence; no automatic bootstrap or DSN.

Acquire this account lock before candidate/symbol locks. Transaction A must add
campaign/leg/signal/outbox records on this same connection before commit. The
methods here return tentative state and do not authorize a command or broker.
"""

from uuid import uuid4

from contracts.strategy_5scr_capacity_owner_v31 import CapacityOwnerFenceV31
from contracts.strategy_5scr_capacity_v31 import CapacityBaselineProposalV31, CapacityLedgerV31, CapacityProposalV31
from contracts.strategy_5scr_transaction_a_v31 import transaction_content_hash_v31
from risk.strategy_5scr_capacity_v31 import (
    capacity_ledger_hash_v31,
    refresh_capacity_baseline_v31,
    transition_capacity_v31,
)
from storage import strategy_5scr_prepared_v31 as detached

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
        self._issuer = object()

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

    def _binding(self, before, arguments):
        return {
            "ledger": before.model_dump(mode="json"),
            "fence": self.fence.model_dump(mode="json"),
            "arguments": {
                k: v.model_dump(mode="json") if hasattr(v, "model_dump") else str(v)
                for k, v in arguments.items()
                if not k.startswith("verify_")
            },
        }

    def prepare_initial_detached(self, ledger, *, verify_initial):
        ledger = CapacityLedgerV31.model_validate(ledger.model_dump())
        self._validate_initial(ledger)
        binding = self._binding(ledger, {})
        digest = capacity_ledger_hash_v31(ledger)
        verifier = detached.guard_callback_v31(verify_initial)
        if verifier is None or verifier(ledger, digest) is not True:
            raise ValueError("CAPACITY_INITIAL_VERIFICATION_REJECTED")
        if self._binding(ledger, {}) != binding:
            raise ValueError("CAPACITY_INITIAL_EVIDENCE_CHANGED")
        return detached.seal_v31(self._issuer, "initial", binding, ledger)

    def _validate_initial(self, ledger):
        if (
            (ledger.account_id, ledger.executor_id, ledger.owner_epoch)
            != (self.fence.account_id, self.fence.executor_id, self.fence.owner_epoch)
            or self.fence.owner_epoch != 1
            or ledger.version != 0
            or ledger.reservations
            or ledger.baseline_refreshes
        ):
            raise ValueError("CAPACITY_INITIAL_STATE_INVALID")

    async def initialize_in_transaction(self, connection, ledger, *, prepared=None, **callbacks):
        """Consume detached verification; historical initialization never resets."""
        detached.reject_callbacks_v31(callbacks)
        if callbacks:
            raise ValueError("CAPACITY_UNEXPECTED_ARGUMENT")
        ledger = CapacityLedgerV31.model_validate(ledger.model_dump())
        self._validate_initial(ledger)
        digest = capacity_ledger_hash_v31(ledger)
        await self._account_lock(connection)
        row = await connection.fetchrow(f"SELECT * FROM {TABLE} WHERE account_id=$1 FOR UPDATE", self.fence.account_id)
        if row is not None:
            current = await self.lock_current(connection)
            if row["initial_hash"] != digest:
                raise ValueError("CAPACITY_INITIALIZATION_CONFLICT")
            return current
        ledger = detached.unseal_v31(prepared, self._issuer, "initial", self._binding(ledger, {}), CapacityLedgerV31)
        if ledger.as_of > detached.commit_time_v31():
            raise ValueError("CAPACITY_INITIAL_COMMIT_CLOCK_FUTURE")
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
        detached.reject_callbacks_v31(kwargs)
        before = await self.lock_current(connection)
        prepared = await candidate_repository.prepare_parent_in_transaction(
            connection,
            ledger=before,
            capacity_owner_epoch=self.fence.owner_epoch,
            **kwargs,
        )
        await self._save(connection, before, prepared.capacity.ledger)
        if prepared.capacity.status != "DUPLICATE_TEST_ONLY":
            # Recheck after awaited storage work. This is an application
            # pre-exit guard, not a PostgreSQL commit timestamp guarantee.
            detached.fresh_parent_v31(
                kwargs["request"],
                prepared.candidate_revision.request.handoff,
                kwargs["expires_at"],
                detached.commit_time_v31(),
            )
        return prepared

    def prepare_transition_detached(self, before, *, expected_version, **kwargs):
        binding = self._binding(before, dict(expected_version=expected_version, **kwargs))
        proposal = transition_capacity_v31(
            before,
            owner_epoch=self.fence.owner_epoch,
            expected_version=expected_version,
            **{k: detached.guard_callback_v31(v) if k.startswith("verify_") else v for k, v in kwargs.items()},
        )
        if self._binding(before, dict(expected_version=expected_version, **kwargs)) != binding:
            raise ValueError("DETACHED_VERIFIER_INPUT_CHANGED")
        return detached.seal_v31(self._issuer, "transition", binding, proposal)

    def prepare_refresh_detached(self, before, request, *, expected_version, now, verify_refresh):
        arguments = dict(request=request, expected_version=expected_version, now=now)
        binding = self._binding(before, arguments)
        proposal = refresh_capacity_baseline_v31(
            before,
            request,
            owner_epoch=self.fence.owner_epoch,
            expected_version=expected_version,
            now=now,
            verify_refresh=detached.guard_callback_v31(verify_refresh),
        )
        if self._binding(before, arguments) != binding:
            raise ValueError("DETACHED_VERIFIER_INPUT_CHANGED")
        return detached.seal_v31(self._issuer, "refresh", binding, proposal)

    def _check_transition_freshness(self, before, proposal, arguments):
        if proposal.status == "DUPLICATE_TEST_ONLY":
            return
        checked_at = detached.commit_time_v31()
        if arguments["now"] > checked_at:
            raise ValueError("CAPACITY_COMMIT_CLOCK_FUTURE")
        if arguments["action"] == "MARK_DISPATCHED" and checked_at >= proposal.reservation.expires_at:
            raise ValueError("CAPACITY_COMMIT_RESERVATION_EXPIRED")
        if arguments["action"] == "RELEASE_RECONCILED":
            evidence = arguments["release_evidence"]
            if not 0 <= (checked_at - evidence.observed_at).total_seconds() <= before.release_evidence_max_age_seconds:
                raise ValueError("CAPACITY_COMMIT_RELEASE_STALE_OR_FUTURE")

    def _check_refresh_freshness(self, proposal, request, now):
        if proposal.status == "DUPLICATE_TEST_ONLY":
            return
        checked_at = detached.commit_time_v31()
        if now > checked_at or not 0 <= (checked_at - request.snapshot.captured_at_utc).total_seconds() <= min(
            request.policy.snapshot_max_age_seconds, request.policy.risk_state_max_age_seconds
        ):
            raise ValueError("CAPACITY_COMMIT_BASELINE_STALE_OR_FUTURE")

    async def transition_in_transaction(self, connection, *, expected_version, prepared=None, **kwargs):
        detached.reject_callbacks_v31(kwargs)
        before = await self.lock_current(connection)
        action = kwargs.get("action")
        if action != "RELEASE_RECONCILED":
            # No external verifier exists for these deterministic transitions.
            proposal = transition_capacity_v31(
                before, owner_epoch=self.fence.owner_epoch, expected_version=expected_version, **kwargs
            )
        else:
            record = next((r for r in before.reservations if r.reservation_id == kwargs.get("reservation_id")), None)
            if record is not None and record.state == "RELEASED":
                # Pure duplicate/conflict validation never invokes a verifier.
                proposal = transition_capacity_v31(
                    before, owner_epoch=self.fence.owner_epoch, expected_version=expected_version, **kwargs
                )
            else:
                proposal = detached.unseal_v31(
                    prepared,
                    self._issuer,
                    "transition",
                    self._binding(before, dict(expected_version=expected_version, **kwargs)),
                    CapacityProposalV31,
                )
        self._check_transition_freshness(before, proposal, kwargs)
        await self._save(connection, before, proposal.ledger)
        # Catch expiration while the awaited update was in flight. The caller
        # must still finish its transaction; no server commit-time claim.
        self._check_transition_freshness(before, proposal, kwargs)
        return proposal

    async def refresh_in_transaction(self, connection, request, *, expected_version, now, prepared=None, **callbacks):
        detached.reject_callbacks_v31(callbacks)
        if callbacks:
            raise ValueError("CAPACITY_UNEXPECTED_ARGUMENT")
        before = await self.lock_current(connection)
        if any(r.operation_id == request.operation_id for r in before.baseline_refreshes):
            proposal = refresh_capacity_baseline_v31(
                before,
                request,
                owner_epoch=self.fence.owner_epoch,
                expected_version=expected_version,
                now=now,
                verify_refresh=None,
            )
        else:
            proposal = detached.unseal_v31(
                prepared,
                self._issuer,
                "refresh",
                self._binding(before, dict(request=request, expected_version=expected_version, now=now)),
                CapacityBaselineProposalV31,
            )
        self._check_refresh_freshness(proposal, request, now)
        await self._save(connection, before, proposal.ledger)
        self._check_refresh_freshness(proposal, request, now)
        return proposal

    async def initialize(self, pg, ledger, *, verify_initial):
        # First transaction is a short read only; verification runs after exit.
        original = capacity_ledger_hash_v31(ledger)
        async with pg.transaction() as connection:
            await self._account_lock(connection)
            row = await connection.fetchrow(
                f"SELECT * FROM {TABLE} WHERE account_id=$1 FOR UPDATE", self.fence.account_id
            )
            if row is not None:
                return await self.initialize_in_transaction(connection, ledger)
        prepared = self.prepare_initial_detached(ledger, verify_initial=verify_initial)
        if capacity_ledger_hash_v31(ledger) != original:
            raise ValueError("DETACHED_VERIFIER_INPUT_CHANGED")
        async with pg.transaction() as connection:
            result = await self.initialize_in_transaction(connection, ledger, prepared=prepared)
        return result

    async def refresh(self, pg, request, *, expected_version, now, verify_refresh):
        original = transaction_content_hash_v31(request)
        async with pg.transaction() as connection:
            before = await self.lock_current(connection)
            if any(r.operation_id == request.operation_id for r in before.baseline_refreshes):
                return await self.refresh_in_transaction(
                    connection, request, expected_version=expected_version, now=now
                )
        prepared = self.prepare_refresh_detached(
            before, request, expected_version=expected_version, now=now, verify_refresh=verify_refresh
        )
        if transaction_content_hash_v31(request) != original:
            raise ValueError("DETACHED_VERIFIER_INPUT_CHANGED")
        async with pg.transaction() as connection:
            result = await self.refresh_in_transaction(
                connection, request, expected_version=expected_version, now=now, prepared=prepared
            )
        return result

    async def transition(self, pg, *, expected_version, **kwargs):
        arguments = {k: v for k, v in kwargs.items() if not k.startswith("verify_")}
        async with pg.transaction() as connection:
            before = await self.lock_current(connection)
            record = next((r for r in before.reservations if r.reservation_id == kwargs.get("reservation_id")), None)
            if kwargs.get("action") != "RELEASE_RECONCILED" or (record is not None and record.state == "RELEASED"):
                return await self.transition_in_transaction(connection, expected_version=expected_version, **arguments)
        binding = self._binding(before, arguments)
        prepared = self.prepare_transition_detached(before, expected_version=expected_version, **kwargs)
        if self._binding(before, arguments) != binding:
            raise ValueError("DETACHED_VERIFIER_INPUT_CHANGED")
        async with pg.transaction() as connection:
            result = await self.transition_in_transaction(
                connection, expected_version=expected_version, prepared=prepared, **arguments
            )
        return result
