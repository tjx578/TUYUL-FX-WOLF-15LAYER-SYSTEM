import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from contracts.strategy_5scr_risk_reservation import validate_final_signal_reservation
from contracts.strategy_5scr_transaction_a_v31 import TransactionARequestV31
from storage.strategy_5scr_transaction_a_v31 import PREFIX, TransactionARepositoryV31
from tests.test_strategy_5scr_capacity_persistence_v31 import NOW, CapacityDB, parent_fixture


class TransactionDB(CapacityDB):
    def __init__(self):
        super().__init__()
        self.records = {name: {} for name in ("campaigns", "parent_legs", "signal_previews", "outbox")}
        self.fault_after = None

    @asynccontextmanager
    async def transaction(self):
        before = deepcopy(self.records)
        try:
            async with super().transaction():
                yield self
        except BaseException:
            self.records = before
            raise

    async def fetchrow(self, sql, *args):
        for name, rows in self.records.items():
            if f"FROM {PREFIX}{name}_v31" in sql:
                return rows.get(args[0])
        return await super().fetchrow(sql, *args)

    async def execute(self, sql, *args):
        for name, rows in self.records.items():
            if f"INSERT INTO {PREFIX}{name}_v31" in sql:
                if args[1] in rows or any(r["record_id"] == args[0] for r in rows.values()):
                    raise ValueError("unique record conflict")
                rows[args[1]] = dict(
                    zip(
                        (
                            "record_id",
                            "reservation_id",
                            "account_id",
                            "tradeplan_id",
                            "tradeplan_revision",
                            "campaign_id",
                            "parent_leg_id",
                            "signal_id",
                            "request_hash",
                            "payload_hash",
                            "payload",
                        ),
                        args,
                        strict=True,
                    )
                )
                if self.fault_after == name:
                    raise RuntimeError("fault after " + name)
                return
        return await super().execute(sql, *args)


async def fixture():
    old, capacity, initial, candidates, kwargs = await parent_fixture()
    db = TransactionDB()
    db.capacity = deepcopy(old.capacity)
    db.rows = deepcopy(old.rows)
    sizing = kwargs["request"].model_copy(update={"campaign_id": str(UUID(int=901))})
    request = TransactionARequestV31(
        profile="TEST_ONLY",
        reservation_id=kwargs["reservation_id"],
        campaign_id=UUID(int=901),
        parent_leg_id=UUID(int=902),
        signal_id=UUID(int=903),
        outbox_id=UUID(int=904),
        candidate_revision_hash=kwargs["expected_candidate_revision_hash"],
        expected_capacity_version=0,
        sizing=sizing,
        expires_at=kwargs["expires_at"],
    )
    repo = TransactionARepositoryV31(
        pg=db,
        capacity_repository=capacity,
        candidate_repository=candidates,
        verify_handoff=kwargs["verify_handoff"],
        verify_universe=lambda *_: True,
        verify_risk_inputs=lambda *_: True,
    )
    return db, repo, initial, request


def test_all_records_and_capacity_commit_together_as_non_deliverable_test_only():
    async def run():
        db, repo, _, request = await fixture()
        result = await repo.submit(request, now=NOW)
        assert result.status == "COMMITTED_TEST_ONLY" and db.commits == 1
        assert all(len(rows) == 1 for rows in db.records.values())
        async with db.transaction():
            stored = await repo.capacity.lock_current(db)
        assert stored.version == 1 and stored.reservations[0] == result.bundle.reservation
        assert result.capital_reservation_authority is result.execution_authority is False
        preview = result.bundle.records()["signal_previews"]
        with pytest.raises(ValueError):
            validate_final_signal_reservation(preview)
        assert result.bundle.records()["outbox"]["status"] == "NON_DELIVERABLE_TEST_ONLY"

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["campaigns", "parent_legs", "signal_previews", "outbox", "commit"])
def test_failure_after_each_write_or_commit_rolls_back_every_effect(failure):
    async def run():
        db, repo, initial, request = await fixture()
        db.fault_after = failure
        db.fail_commit = failure == "commit"
        with pytest.raises(RuntimeError):
            await repo.submit(request, now=NOW)
        assert all(not rows for rows in db.records.values()) and db.commits == 0
        db.fail_commit = False
        async with db.transaction():
            assert await repo.capacity.lock_current(db) == initial

    asyncio.run(run())


def test_lost_ack_retry_after_expiry_returns_same_complete_bundle_without_new_effect():
    async def run():
        db, repo, _, request = await fixture()
        first = await repo.submit(request, now=NOW)
        before = deepcopy(db.records)
        restarted = TransactionARepositoryV31(
            pg=db,
            capacity_repository=repo.capacity,
            candidate_repository=repo.candidates,
            verify_handoff=None,
            verify_universe=None,
            verify_risk_inputs=None,
        )
        retry = await restarted.submit(request, now=NOW + timedelta(days=1))
        assert retry.status == "DUPLICATE_TEST_ONLY" and retry.bundle == first.bundle and db.records == before
        assert retry.execution_authority is False

    asyncio.run(run())


@pytest.mark.parametrize("field", ["signal_id", "outbox_id", "candidate_revision_hash", "expected_capacity_version"])
def test_replay_cannot_substitute_any_bound_request(field):
    async def run():
        db, repo, _, request = await fixture()
        await repo.submit(request, now=NOW)
        value = (
            "sha256:" + "f" * 64
            if field == "candidate_revision_hash"
            else (8 if field == "expected_capacity_version" else UUID(int=999))
        )
        with pytest.raises(ValueError, match="REPLAY_CONFLICT"):
            await repo.submit(request.model_copy(update={field: value}), now=NOW)
        assert all(len(rows) == 1 for rows in db.records.values())

    asyncio.run(run())


@pytest.mark.parametrize("fault", ["missing_leg", "payload_hash", "record_id", "missing_capacity", "capacity_scope"])
def test_partial_or_corrupt_existing_bundle_is_not_automatically_rebuilt(fault):
    async def run():
        db, repo, _, request = await fixture()
        await repo.submit(request, now=NOW)
        if fault == "missing_leg":
            db.records["parent_legs"] = {}
        elif fault == "payload_hash":
            db.records["outbox"][request.reservation_id]["payload_hash"] = "sha256:" + "f" * 64
        elif fault == "record_id":
            db.records["signal_previews"][request.reservation_id]["record_id"] = UUID(int=999)
        else:
            async with db.transaction():
                current = await repo.capacity.lock_current(db)
            altered = current.model_copy(
                update={
                    "reservations": ()
                    if fault == "missing_capacity"
                    else (current.reservations[0].model_copy(update={"campaign_id": "corrupt-campaign"}),)
                }
            )
            from risk.strategy_5scr_capacity_v31 import capacity_ledger_hash_v31

            db.capacity[current.account_id].update(
                payload=altered.model_dump_json(), ledger_hash=capacity_ledger_hash_v31(altered)
            )
        with pytest.raises(ValueError, match="PARTIAL_OR_CORRUPT|CAPACITY_BINDING_MISSING"):
            await repo.submit(request, now=NOW)

    asyncio.run(run())


def test_orphan_capacity_is_rejected_without_creating_missing_transaction_records():
    async def run():
        db, repo, _, request = await fixture()
        async with db.transaction():
            await repo.capacity.prepare_parent_in_transaction(
                db,
                candidate_repository=repo.candidates,
                request=request.sizing,
                expected_candidate_revision_hash=request.candidate_revision_hash,
                reservation_id=request.reservation_id,
                expires_at=request.expires_at,
                now=NOW,
                expected_capacity_version=0,
                verify_handoff=lambda *_: True,
                verify_universe=lambda *_: True,
                verify_risk_inputs=lambda *_: True,
            )
        with pytest.raises(ValueError, match="ORPHAN_CAPACITY"):
            await repo.submit(request, now=NOW)
        assert all(not rows for rows in db.records.values())

    asyncio.run(run())


def test_request_rejects_legacy_plan_and_campaign_identity_relabeling():
    async def run():
        _, _, _, request = await fixture()
        for field, value in [("tradeplan_id", "5scr-plan:" + "a" * 32), ("campaign_id", "legacy-campaign")]:
            with pytest.raises(ValidationError):
                TransactionARequestV31.model_validate(
                    {**request.model_dump(), "sizing": {**request.sizing.model_dump(), field: value}}
                )

    asyncio.run(run())
