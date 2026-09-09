import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from contracts.strategy_5scr_capacity_owner_v31 import CapacityOwnerFenceV31
from risk.strategy_5scr_capacity_v31 import capacity_ledger_hash_v31
from storage import strategy_5scr_prepared_v31 as detached
from storage.strategy_5scr_capacity_v31 import CapacityRepositoryV31, _ledger
from tests.test_strategy_5scr_candidate_revision_v31 import FakeDB
from tests.test_strategy_5scr_capacity_baseline_v31 import evidence_for
from tests.test_strategy_5scr_capacity_v31 import NOW, seed
from tests.test_strategy_5scr_latest_candidate_capacity_v31 import fixture as candidate_fixture


@pytest.fixture(autouse=True)
def trusted_clock(monkeypatch):
    monkeypatch.setattr(detached, "commit_time_v31", lambda: NOW + timedelta(microseconds=500000))


class CapacityDB(FakeDB):
    """Protocol fake, explicitly not a PostgreSQL durability/concurrency test."""

    def __init__(self):
        super().__init__()
        self.capacity = {}
        self.calls = []
        self.force_cas_miss = False

    @asynccontextmanager
    async def transaction(self):
        before = deepcopy(self.capacity)
        try:
            async with super().transaction():
                yield self
        except BaseException:
            self.capacity = before
            raise

    async def execute(self, sql, *args):
        self.calls.append(sql)
        if "INSERT INTO public.strategy_5scr_capacity_ledgers" in sql:
            row = dict(
                zip(
                    (
                        "account_id",
                        "executor_id",
                        "owner_id",
                        "owner_epoch",
                        "token",
                        "version",
                        "initial_hash",
                        "ledger_hash",
                        "payload",
                    ),
                    args,
                    strict=True,
                )
            )
            self.capacity[row["account_id"]] = row
            return
        return await super().execute(sql, *args)

    async def fetchrow(self, sql, *args):
        self.calls.append(sql)
        if "UPDATE public.strategy_5scr_capacity_ledgers" in sql:
            row = self.capacity.get(args[6])
            if (
                self.force_cas_miss
                or row is None
                or tuple(
                    row[k]
                    for k in ("account_id", "executor_id", "owner_id", "owner_epoch", "token", "version", "ledger_hash")
                )
                != args[6:]
            ):
                return None
            row.update(
                dict(
                    zip(
                        ("owner_id", "owner_epoch", "token", "version", "ledger_hash", "payload"), args[:6], strict=True
                    )
                )
            )
            return {"account_id": row["account_id"]}
        if "FROM public.strategy_5scr_capacity_ledgers" in sql:
            return self.capacity.get(args[0])
        return await super().fetchrow(sql, *args)


def owner(ledger=None):
    ledger = ledger or seed()
    return CapacityOwnerFenceV31(
        profile="TEST_ONLY",
        account_id=ledger.account_id,
        executor_id=ledger.executor_id,
        owner_id="fixture-capacity-owner",
        owner_epoch=1,
        token=UUID(int=800),
    )


async def initialized():
    db = CapacityDB()
    ledger = seed()
    repo = CapacityRepositoryV31(fence=owner(ledger))
    await repo.initialize(db, ledger, verify_initial=lambda _, digest: digest == capacity_ledger_hash_v31(ledger))
    return db, repo, ledger


async def parent_fixture():
    db, repo, ledger = await initialized()
    candidate_db, candidate, _, kwargs = await candidate_fixture()
    db.rows = deepcopy(candidate_db.rows)
    del kwargs["ledger"]
    del kwargs["capacity_owner_epoch"]
    async with db.transaction():
        latest = await candidate.lock_latest(db, UUID(kwargs["request"].tradeplan_id))
    prepared = candidate.prepare_parent_detached(
        latest, ledger=ledger, capacity_owner_epoch=repo.fence.owner_epoch, **kwargs
    )
    kwargs = {k: v for k, v in kwargs.items() if not k.startswith("verify_")}
    kwargs["prepared"] = prepared
    return db, repo, ledger, candidate, kwargs


def test_initialization_is_explicit_verified_and_never_resets_progress(monkeypatch):
    monkeypatch.setattr(detached, "commit_time_v31", lambda: NOW + timedelta(seconds=2))

    async def run():
        db, repo, initial = await initialized()
        changed = await repo.refresh(
            db,
            evidence_for(initial),
            expected_version=0,
            now=NOW + timedelta(seconds=2),
            verify_refresh=lambda *_: True,
        )
        async with db.transaction():
            replay = await repo.initialize_in_transaction(db, initial)
            assert replay == changed.ledger and replay.version == 1
        conflict = initial.model_copy(update={"closed_balance_usd": Decimal("999")})
        with pytest.raises(ValueError, match="INITIALIZATION_CONFLICT"):
            async with db.transaction():
                await repo.initialize_in_transaction(db, conflict)

    asyncio.run(run())


@pytest.mark.parametrize(
    "fault,reason",
    [
        ("uninitialized", "UNINITIALIZED"),
        ("transaction", "CALLER_TRANSACTION_REQUIRED"),
        ("owner", "OWNER_FENCED"),
        ("hash", "PERSISTED_STATE_MISMATCH"),
        ("row_version", "PERSISTED_STATE_MISMATCH"),
    ],
)
def test_locked_state_requires_bound_owner_transaction_and_content(fault, reason):
    async def run():
        db, repo, initial = await initialized()
        if fault == "uninitialized":
            db.capacity = {}
        elif fault == "owner":
            db.capacity[initial.account_id]["token"] = UUID(int=900)
        elif fault == "hash":
            db.capacity[initial.account_id]["ledger_hash"] = "sha256:" + "f" * 64
        elif fault == "row_version":
            db.capacity[initial.account_id]["version"] = 42
        with pytest.raises(ValueError, match=reason):
            if fault == "transaction":
                await repo.lock_current(db)
            else:
                async with db.transaction():
                    await repo.lock_current(db)

    asyncio.run(run())


@pytest.mark.parametrize("fault", ["verifier", "mutation", "nonzero_version", "epoch"])
def test_initialization_rejects_unverified_or_noninitial_state(fault):
    async def run():
        db = CapacityDB()
        initial = seed()
        repo = CapacityRepositoryV31(fence=owner(initial))

        def verifier(*_):
            return True

        if fault == "verifier":
            verifier = None
        elif fault == "mutation":

            def verifier(value, digest):
                object.__setattr__(value, "version", 8)
                return True
        elif fault == "nonzero_version":
            initial = initial.model_copy(update={"version": 8})
        else:
            initial = initial.model_copy(update={"owner_epoch": 2})
        with pytest.raises(ValueError):
            await repo.initialize(db, initial, verify_initial=verifier)
        assert not db.capacity

    asyncio.run(run())


def test_account_then_candidate_preparation_persists_one_capacity_state_and_replays():
    async def run():
        db, repo, _, candidate, kwargs = await parent_fixture()
        db.calls = []
        async with db.transaction():
            result = await repo.prepare_parent_in_transaction(db, candidate_repository=candidate, **kwargs)
        assert "5scr-capacity-v31:" in db.calls[0]
        # The binder now owns the symbol lock inside PostgreSQL; account
        # locking must still precede that capability-validation boundary.
        assert next(i for i, s in enumerate(db.calls) if "bind_5scr_lifecycle_owner_v1" in s) > 0
        assert result.durable_commit is False and result.capacity.execution_authority is False
        restarted = CapacityRepositoryV31(fence=repo.fence)
        async with db.transaction():
            persisted = await restarted.lock_current(db)
            duplicate = await restarted.prepare_parent_in_transaction(db, candidate_repository=candidate, **kwargs)
        assert persisted == result.capacity.ledger
        assert duplicate.capacity.status == "DUPLICATE_TEST_ONLY"
        assert _ledger(db.capacity[repo.fence.account_id]).version == 1

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["after_write", "commit", "cas"])
def test_failed_parent_transaction_leaves_no_capacity_effect(failure):
    async def run():
        db, repo, initial, candidate, kwargs = await parent_fixture()
        db.fail_commit = failure == "commit"
        db.force_cas_miss = failure == "cas"
        with pytest.raises((RuntimeError, ValueError)):
            async with db.transaction():
                await repo.prepare_parent_in_transaction(db, candidate_repository=candidate, **kwargs)
                if failure == "after_write":
                    raise RuntimeError("fault after capacity write")
        assert _ledger(db.capacity[initial.account_id]) == initial

    asyncio.run(run())


def test_owner_handover_preserves_risk_state_and_fences_old_writer():
    async def run():
        db, repo, _, candidate, kwargs = await parent_fixture()
        async with db.transaction():
            result = await repo.prepare_parent_in_transaction(db, candidate_repository=candidate, **kwargs)
        before = result.capacity.ledger
        async with db.transaction():
            new_fence = await repo.transfer_owner_in_transaction(db, next_owner_id="successor", expected_version=1)
        with pytest.raises(ValueError, match="OWNER_FENCED"):
            async with db.transaction():
                await repo.lock_current(db)
        new_repo = CapacityRepositoryV31(fence=new_fence)
        async with db.transaction():
            recovered = await new_repo.lock_current(db)
        assert recovered.model_dump(exclude={"owner_epoch", "version"}) == before.model_dump(
            exclude={"owner_epoch", "version"}
        )
        assert recovered.owner_epoch == 2 and recovered.version == 2

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["stale_version", "rollback"])
def test_failed_owner_handover_preserves_old_owner_and_state(failure):
    async def run():
        db, repo, initial = await initialized()
        with pytest.raises((ValueError, RuntimeError)):
            async with db.transaction():
                await repo.transfer_owner_in_transaction(
                    db, next_owner_id="successor", expected_version=5 if failure == "stale_version" else 0
                )
                raise RuntimeError("rollback after handover")
        async with db.transaction():
            assert await repo.lock_current(db) == initial

    asyncio.run(run())


def test_expiry_transition_persists_without_freeing_pending_broker_risk():
    async def run():
        db, repo, _, candidate, kwargs = await parent_fixture()
        async with db.transaction():
            await repo.prepare_parent_in_transaction(db, candidate_repository=candidate, **kwargs)
        async with db.transaction():
            pending = await repo.transition_in_transaction(
                db, expected_version=1, reservation_id=kwargs["reservation_id"], action="MARK_DISPATCHED", now=NOW
            )
        with pytest.raises(ValueError):
            async with db.transaction():
                await repo.transition_in_transaction(
                    db,
                    expected_version=2,
                    reservation_id=kwargs["reservation_id"],
                    action="EXPIRE_UNISSUED",
                    now=NOW + timedelta(seconds=2),
                )
        assert _ledger(db.capacity[repo.fence.account_id]) == pending.ledger

    asyncio.run(run())


@pytest.mark.parametrize("operation", ["initial", "refresh", "release"])
def test_external_verifier_never_runs_inside_capacity_transaction(operation, monkeypatch):
    async def run():
        db = CapacityDB()
        initial = seed()
        repo = CapacityRepositoryV31(fence=owner(initial))
        seen = []

        def verified(*_):
            assert not db.is_in_transaction()
            seen.append(operation)
            return True

        if operation == "initial":
            await repo.initialize(db, initial, verify_initial=verified)
        else:
            await repo.initialize(db, initial, verify_initial=lambda *_: True)
            monkeypatch.setattr(detached, "commit_time_v31", lambda: NOW + timedelta(seconds=2))
            if operation == "refresh":
                await repo.refresh(
                    db,
                    evidence_for(initial),
                    expected_version=0,
                    now=NOW + timedelta(seconds=2),
                    verify_refresh=verified,
                )
            else:
                from tests.test_strategy_5scr_capacity_v31 import release_proof, reserve

                held = reserve(initial).ledger
                async with db.transaction():
                    await repo.lock_current(db)
                    await repo._save(db, initial, held)
                record = held.reservations[0]
                evidence = release_proof(held, NOW).model_copy(
                    update={"outcome": "NO_BROKER_EFFECT_CONFIRMED", "delivery_disposition": "NEVER_ISSUED"}
                )
                await repo.transition(
                    db,
                    expected_version=1,
                    now=NOW,
                    reservation_id=record.reservation_id,
                    action="RELEASE_RECONCILED",
                    release_evidence=evidence,
                    verify_release=verified,
                )
        assert seen == [operation]

    asyncio.run(run())


@pytest.mark.parametrize("operation", ["initial", "refresh", "release", "parent"])
def test_in_transaction_entrypoints_reject_raw_verifiers(operation):
    async def run():
        db, repo, initial = await initialized()
        called = []
        with pytest.raises(ValueError, match="EXTERNAL_VERIFIER_REQUIRES_DETACHED"):
            async with db.transaction():
                if operation == "initial":
                    await repo.initialize_in_transaction(db, initial, verify_initial=lambda *_: called.append(1))
                elif operation == "refresh":
                    await repo.refresh_in_transaction(
                        db,
                        evidence_for(initial),
                        expected_version=0,
                        now=NOW,
                        verify_refresh=lambda *_: called.append(1),
                    )
                elif operation == "release":
                    await repo.transition_in_transaction(
                        db, expected_version=0, verify_release=lambda *_: called.append(1)
                    )
                else:
                    await repo.prepare_parent_in_transaction(
                        db, candidate_repository=None, verify_risk_inputs=lambda *_: called.append(1)
                    )
        assert called == []

    asyncio.run(run())


@pytest.mark.parametrize("fault", ["expired", "changed_ledger", "changed_fence", "changed_request", "tampered_token"])
def test_refresh_rechecks_detached_evidence_after_lock(fault, monkeypatch):
    async def run():
        from dataclasses import replace

        db, repo, initial = await initialized()
        request = evidence_for(initial)
        now = NOW + timedelta(seconds=2)
        prepared = repo.prepare_refresh_detached(
            initial, request, expected_version=0, now=now, verify_refresh=lambda *_: True
        )
        monkeypatch.setattr(detached, "commit_time_v31", lambda: now)
        if fault == "expired":
            monkeypatch.setattr(detached, "commit_time_v31", lambda: now + timedelta(days=1))
        elif fault == "changed_ledger":
            async with db.transaction():
                await repo.refresh_in_transaction(db, request, expected_version=0, now=now, prepared=prepared)
            # A different new operation may not consume the old snapshot's token.
            request = evidence_for(initial, n=2)
        elif fault == "changed_fence":
            async with db.transaction():
                await repo.transfer_owner_in_transaction(db, next_owner_id="next", expected_version=0)
        elif fault == "changed_request":
            request = request.model_copy(update={"source_receipt_hash": "sha256:" + "e" * 64})
        else:
            prepared = replace(prepared, payload=prepared.payload.replace("1100", "1200"))
        snapshot = deepcopy(db.capacity)
        with pytest.raises(ValueError):
            async with db.transaction():
                await repo.refresh_in_transaction(db, request, expected_version=0, now=now, prepared=prepared)
        assert db.capacity == snapshot

    asyncio.run(run())


def test_refresh_historical_duplicate_needs_neither_freshness_nor_verifier(monkeypatch):
    async def run():
        db, repo, initial = await initialized()
        now = NOW + timedelta(seconds=2)
        monkeypatch.setattr(detached, "commit_time_v31", lambda: now)
        evidence = evidence_for(initial)
        first = await repo.refresh(db, evidence, expected_version=0, now=now, verify_refresh=lambda *_: True)
        monkeypatch.setattr(detached, "commit_time_v31", lambda: now + timedelta(days=1))
        replay = await repo.refresh(db, evidence, expected_version=0, now=now + timedelta(days=1), verify_refresh=None)
        assert replay.status == "DUPLICATE_TEST_ONLY" and replay.ledger == first.ledger

    asyncio.run(run())


def test_release_expiry_during_verification_does_not_free_capacity(monkeypatch):
    async def run():
        from tests.test_strategy_5scr_capacity_v31 import release_proof, reserve

        db, repo, initial = await initialized()
        held = reserve(initial).ledger
        async with db.transaction():
            await repo.lock_current(db)
            await repo._save(db, initial, held)
        evidence = release_proof(held, NOW).model_copy(
            update={"outcome": "NO_BROKER_EFFECT_CONFIRMED", "delivery_disposition": "NEVER_ISSUED"}
        )
        kwargs = dict(
            expected_version=1,
            now=NOW,
            reservation_id=held.reservations[0].reservation_id,
            action="RELEASE_RECONCILED",
            release_evidence=evidence,
        )
        prepared = repo.prepare_transition_detached(held, **kwargs, verify_release=lambda *_: True)
        monkeypatch.setattr(detached, "commit_time_v31", lambda: NOW + timedelta(days=1))
        with pytest.raises(ValueError, match="COMMIT_RELEASE_STALE"):
            async with db.transaction():
                await repo.transition_in_transaction(db, prepared=prepared, **kwargs)
        assert _ledger(db.capacity[initial.account_id]) == held

    asyncio.run(run())


@pytest.mark.parametrize("operation", ["parent", "refresh", "dispatch", "release"])
def test_delayed_capacity_write_crossing_deadline_rolls_back(operation, monkeypatch):
    async def run():
        from tests.test_strategy_5scr_capacity_v31 import release_proof, reserve

        if operation == "parent":
            db, repo, before, candidate, kwargs = await parent_fixture()
        else:
            db, repo, before = await initialized()
        if operation in {"dispatch", "release"}:
            held = reserve(before).ledger
            async with db.transaction():
                await repo.lock_current(db)
                await repo._save(db, before, held)
            before = held
        now = NOW + timedelta(seconds=2) if operation == "refresh" else NOW
        monkeypatch.setattr(detached, "commit_time_v31", lambda: now)
        original_save = repo._save
        wrote = []

        async def delayed_save(*args, **options):
            value = await original_save(*args, **options)
            wrote.append(True)
            monkeypatch.setattr(detached, "commit_time_v31", lambda: now + timedelta(days=1))
            return value

        monkeypatch.setattr(repo, "_save", delayed_save)
        if operation == "refresh":
            evidence = evidence_for(before)
            prepared = repo.prepare_refresh_detached(
                before, evidence, expected_version=before.version, now=now, verify_refresh=lambda *_: True
            )
        elif operation == "release":
            evidence = release_proof(before, now).model_copy(
                update={"outcome": "NO_BROKER_EFFECT_CONFIRMED", "delivery_disposition": "NEVER_ISSUED"}
            )
            arguments = dict(
                expected_version=before.version,
                now=now,
                reservation_id=before.reservations[0].reservation_id,
                action="RELEASE_RECONCILED",
                release_evidence=evidence,
            )
            prepared = repo.prepare_transition_detached(before, **arguments, verify_release=lambda *_: True)
        with pytest.raises(ValueError, match="CAPACITY_COMMIT"):
            async with db.transaction():
                if operation == "parent":
                    await repo.prepare_parent_in_transaction(db, candidate_repository=candidate, **kwargs)
                elif operation == "refresh":
                    await repo.refresh_in_transaction(
                        db, evidence, expected_version=before.version, now=now, prepared=prepared
                    )
                elif operation == "dispatch":
                    await repo.transition_in_transaction(
                        db,
                        expected_version=before.version,
                        now=now,
                        reservation_id=before.reservations[0].reservation_id,
                        action="MARK_DISPATCHED",
                    )
                else:
                    await repo.transition_in_transaction(db, prepared=prepared, **arguments)
        assert wrote == [True], "fault must happen after the tentative database update"
        assert _ledger(db.capacity[before.account_id]) == before

    asyncio.run(run())


def test_delayed_expire_unissued_has_no_invented_upper_deadline(monkeypatch):
    async def run():
        from tests.test_strategy_5scr_capacity_v31 import reserve

        db, repo, initial = await initialized()
        held = reserve(initial).ledger
        async with db.transaction():
            await repo.lock_current(db)
            await repo._save(db, initial, held)
        now = held.reservations[0].expires_at
        monkeypatch.setattr(detached, "commit_time_v31", lambda: now)
        original_save = repo._save

        async def delayed_save(*args, **options):
            value = await original_save(*args, **options)
            monkeypatch.setattr(detached, "commit_time_v31", lambda: now + timedelta(days=1))
            return value

        monkeypatch.setattr(repo, "_save", delayed_save)
        async with db.transaction():
            result = await repo.transition_in_transaction(
                db,
                expected_version=held.version,
                now=now,
                reservation_id=held.reservations[0].reservation_id,
                action="EXPIRE_UNISSUED",
            )
        assert result.reservation.state == "EXPIRED_UNISSUED"
        assert result.reservation.expires_at == now
        assert _ledger(db.capacity[held.account_id]) == result.ledger

    asyncio.run(run())
