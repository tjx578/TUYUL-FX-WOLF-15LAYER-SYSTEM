"""Account capacity PostgreSQL acceptance, separate from earlier inventories."""

import asyncio
from datetime import timedelta
from uuid import uuid4

import asyncpg
import pytest

from contracts.strategy_5scr_activity_delivery import ActivityConsumerScopeV1
from contracts.strategy_5scr_capacity_owner_v31 import CapacityOwnerFenceV31
from risk.strategy_5scr_candidate_handoff_v31 import candidate_handoff_hash_v31
from risk.strategy_5scr_capacity_v31 import capacity_content_hash_v31, capacity_ledger_hash_v31
from storage import strategy_5scr_prepared_v31 as detached
from storage.strategy_5scr_activity_consumer import transfer_owner
from storage.strategy_5scr_candidate_revision_v31 import CandidateRevisionRepositoryV31
from storage.strategy_5scr_capacity_v31 import TABLE, CapacityRepositoryV31
from tests.integration.test_candidate_revision_v31_postgres import DB
from tests.integration.test_pair_activity_runtime_postgres import pg_dsn
from tests.test_strategy_5scr_candidate_handoff_v31 import bundle
from tests.test_strategy_5scr_candidate_revision_v31 import NOW, revision

__all__ = ["pg_dsn"]


@pytest.mark.parametrize(
    "scenario",
    [
        "initialize_restart",
        "initialize_concurrent",
        "initialization_rollback",
        "owner_handover",
        "raw_write_fenced",
        "parent_restart_duplicate",
        "parent_concurrent_duplicate",
        "parent_rollback",
    ],
)
def test_capacity_persistence_postgres_acceptance(pg_dsn, scenario, monkeypatch):
    monkeypatch.setattr(detached, "commit_time_v31", lambda: NOW + timedelta(microseconds=500000))

    async def run():
        db = DB(pg_dsn)
        ledger, _, request = bundle()
        account = "capacity-fixture-" + str(uuid4())
        snapshot = request.snapshot.model_copy(update={"account_id": account})
        ledger = ledger.model_copy(
            update={"account_id": account, "account_snapshot_hash": capacity_content_hash_v31(snapshot)}
        )
        fence = CapacityOwnerFenceV31(
            profile="TEST_ONLY",
            account_id=account,
            executor_id=ledger.executor_id,
            owner_id="fixture-account-owner",
            owner_epoch=1,
            token=uuid4(),
        )
        repo = CapacityRepositoryV31(fence=fence)
        async with db.transaction() as c:
            assert await c.fetchval("SELECT to_regclass($1)", TABLE), "explicit migration 20260909_05 required"

        async def initialize():
            prepared = repo.prepare_initial_detached(ledger, verify_initial=lambda *_: True)
            async with db.transaction() as c:
                result = await repo.initialize_in_transaction(c, ledger, prepared=prepared)
                if scenario == "initialization_rollback":
                    raise RuntimeError("injected initialization rollback")
                return result

        if scenario == "initialization_rollback":
            with pytest.raises(RuntimeError, match="initialization rollback"):
                await initialize()
            async with db.transaction() as c:
                assert await c.fetchval(f"SELECT count(*) FROM {TABLE} WHERE account_id=$1", account) == 0
            return
        if scenario == "initialize_concurrent":
            assert await asyncio.gather(initialize(), initialize()) == [ledger, ledger]
        else:
            await initialize()
        if scenario == "owner_handover":
            async with db.transaction() as c:
                next_fence = await repo.transfer_owner_in_transaction(c, next_owner_id="successor", expected_version=0)
            with pytest.raises(ValueError, match="OWNER_FENCED"):
                async with db.transaction() as c:
                    await repo.lock_current(c)
            async with db.transaction() as c:
                recovered = await CapacityRepositoryV31(fence=next_fence).lock_current(c)
                assert recovered.model_dump(exclude={"version", "owner_epoch"}) == ledger.model_dump(
                    exclude={"version", "owner_epoch"}
                )
            return
        if scenario == "raw_write_fenced":
            with pytest.raises(asyncpg.RaiseError, match="OWNER_FENCED"):
                async with db.transaction() as c:
                    await c.execute(
                        f"UPDATE {TABLE} SET version=version+1,payload=jsonb_set(payload::jsonb,'{{version}}',to_jsonb(version+1))::text WHERE account_id=$1",
                        account,
                    )
            with pytest.raises(asyncpg.RaiseError, match="DELETE_PROHIBITED"):
                async with db.transaction() as c:
                    await c.execute(f"DELETE FROM {TABLE} WHERE account_id=$1", account)
        if scenario.startswith("parent_"):
            scope = ActivityConsumerScopeV1(
                consumer_scope_id="capacity-test-candidate",
                producer_binding_hash="sha256:" + "a" * 64,
                lifecycle_owner_id="fixture-strategy-owner",
                lifecycle_policy_hash="sha256:" + "b" * 64,
                environment_class="DISPOSABLE_TEST",
            )
            async with db.transaction() as c:
                old = await c.fetchrow(
                    "SELECT generation FROM public.strategy_5scr_owner_fences_v1 WHERE symbol='EURUSD'"
                )
                strategy_fence = await transfer_owner(
                    c, symbol="EURUSD", scope=scope, expected_generation=old["generation"] if old else 0
                )
            candidates = CandidateRevisionRepositoryV31(
                pg=db, fence=strategy_fence, verify_reevaluation=lambda *_: True
            )
            append = revision()
            plan = uuid4()
            append = append.model_copy(
                update={
                    "reevaluation_id": uuid4(),
                    "handoff": append.handoff.model_copy(
                        update={"candidate": append.handoff.candidate.model_copy(update={"tradeplan_id": plan})}
                    ),
                }
            )
            stored = await candidates.append(append, now=NOW)
            request = request.model_copy(
                update={
                    "tradeplan_id": str(plan),
                    "expected_account_id": account,
                    "snapshot": snapshot,
                    "risk_state_evidence_hash": capacity_ledger_hash_v31(ledger),
                    "strategy_candidate_receipt_hash": candidate_handoff_hash_v31(stored.request.handoff),
                }
            )
            reservation = uuid4()

            async def parent():
                kwargs = dict(
                    expected_candidate_revision_hash=stored.request_hash,
                    request=request,
                    reservation_id=reservation,
                    expires_at=NOW + timedelta(seconds=1),
                    now=NOW,
                    expected_capacity_version=0,
                )
                async with db.transaction() as c:
                    current = await repo.lock_current(c)
                    latest = await candidates.lock_latest(c, plan)
                prepared = candidates.prepare_parent_detached(
                    latest,
                    ledger=current,
                    capacity_owner_epoch=repo.fence.owner_epoch,
                    **kwargs,
                    verify_handoff=lambda *_: True,
                    verify_universe=lambda *_: True,
                    verify_risk_inputs=lambda *_: True,
                )
                async with db.transaction() as c:
                    result = await repo.prepare_parent_in_transaction(
                        c, candidate_repository=candidates, prepared=prepared, **kwargs
                    )
                    if scenario == "parent_rollback":
                        raise RuntimeError("injected parent rollback")
                    return result

            if scenario == "parent_rollback":
                with pytest.raises(RuntimeError, match="parent rollback"):
                    await parent()
            elif scenario == "parent_concurrent_duplicate":
                results = await asyncio.gather(parent(), parent())
                assert {x.capacity.status for x in results} == {"APPLIED_TEST_ONLY", "DUPLICATE_TEST_ONLY"}
            else:
                await parent()
                assert (await parent()).capacity.status == "DUPLICATE_TEST_ONLY"
        async with DB(pg_dsn).transaction() as c:
            recovered = await CapacityRepositoryV31(fence=fence).lock_current(c)
        expected = 1 if scenario in {"parent_restart_duplicate", "parent_concurrent_duplicate"} else 0
        assert recovered.version == expected and len(recovered.reservations) == expected

    asyncio.run(run())
