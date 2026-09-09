"""Separate candidate-history PostgreSQL acceptance; not part of S03's 63 IDs."""

import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
from uuid import uuid4

import asyncpg
import pytest

from contracts.strategy_5scr_activity_delivery import ActivityConsumerScopeV1
from storage.strategy_5scr_activity_consumer import transfer_owner
from storage.strategy_5scr_candidate_revision_v31 import TABLE, CandidateRevisionRepositoryV31
from tests.integration.test_pair_activity_runtime_postgres import pg_dsn
from tests.test_strategy_5scr_candidate_revision_v31 import NOW, revision

__all__ = ["pg_dsn"]


class DB:
    def __init__(self, dsn):
        self.dsn = dsn

    @asynccontextmanager
    async def transaction(self):
        c = await asyncpg.connect(self.dsn, timeout=3, command_timeout=10)
        try:
            async with c.transaction():
                yield c
        finally:
            await c.close()


@pytest.mark.parametrize(
    "scenario",
    [
        "restart_duplicate",
        "rollback",
        "concurrent_duplicate",
        "payload_conflict",
        "advisory_canonical",
        "stale_owner",
        "raw_mutation",
    ],
)
def test_candidate_revision_postgres_acceptance(pg_dsn, scenario):
    async def run():
        db = DB(pg_dsn)
        scope = ActivityConsumerScopeV1(
            consumer_scope_id="candidate-history-test",
            producer_binding_hash="sha256:" + "a" * 64,
            lifecycle_owner_id="candidate-history-owner",
            lifecycle_policy_hash="sha256:" + "b" * 64,
            environment_class="DISPOSABLE_TEST",
        )
        async with db.transaction() as c:
            assert await c.fetchval("SELECT to_regclass($1)", TABLE), "explicit migration 20260909_04 required"
            old = await c.fetchrow("SELECT generation FROM public.strategy_5scr_owner_fences_v1 WHERE symbol='EURUSD'")
            fence = await transfer_owner(
                c, symbol="EURUSD", scope=scope, expected_generation=old["generation"] if old else 0
            )
        repo = CandidateRevisionRepositoryV31(pg=db, fence=fence, verify_reevaluation=lambda *_: True)
        request = revision(advisory=scenario == "advisory_canonical")
        plan = uuid4()
        request = request.model_copy(
            update={
                "reevaluation_id": uuid4(),
                "handoff": request.handoff.model_copy(
                    update={"candidate": request.handoff.candidate.model_copy(update={"tradeplan_id": plan})}
                ),
            }
        )
        if scenario == "rollback":
            with pytest.raises(RuntimeError, match="rollback injected"):
                async with db.transaction() as c:
                    await repo.append_in_transaction(c, request, now=NOW)
                    raise RuntimeError("rollback injected")
            async with db.transaction() as c:
                assert await c.fetchval(f"SELECT count(*) FROM {TABLE} WHERE tradeplan_id=$1", plan) == 0
            return
        if scenario == "concurrent_duplicate":
            first, second = await asyncio.gather(repo.append(request, now=NOW), repo.append(request, now=NOW))
            assert first == second
        else:
            first = await repo.append(request, now=NOW)
            if scenario == "restart_duplicate":
                restarted = CandidateRevisionRepositoryV31(pg=DB(pg_dsn), fence=fence, verify_reevaluation=None)
                assert await restarted.append(request, now=NOW + timedelta(days=1)) == first
            elif scenario == "payload_conflict":
                with pytest.raises(ValueError, match="PAYLOAD_CONFLICT"):
                    await repo.append(
                        request.model_copy(update={"reevaluation_receipt_hash": "sha256:" + "f" * 64}), now=NOW
                    )
            elif scenario == "advisory_canonical":
                second = revision(2, first)
                second = second.model_copy(
                    update={
                        "reevaluation_id": uuid4(),
                        "handoff": second.handoff.model_copy(
                            update={"candidate": second.handoff.candidate.model_copy(update={"tradeplan_id": plan})}
                        ),
                    }
                )
                await repo.append(second, now=NOW + timedelta(seconds=1))
                async with db.transaction() as c:
                    latest = await repo.lock_latest(c, plan)
                    assert latest.request.handoff.candidate.tradeplan_revision == 2
                assert first.request.handoff.candidate.analysis_admission_class == "MATURE_ADVISORY"
            elif scenario == "stale_owner":
                async with db.transaction() as c:
                    await transfer_owner(c, symbol="EURUSD", scope=scope, expected_generation=fence.generation)
                with pytest.raises(ValueError, match="STALE_OR_UNBOUND"):
                    await repo.append(request, now=NOW)
            elif scenario == "raw_mutation":
                with pytest.raises(asyncpg.RaiseError, match="IMMUTABLE"):
                    async with db.transaction() as c:
                        await c.execute(
                            f"UPDATE {TABLE} SET request_hash=$1 WHERE tradeplan_id=$2", "sha256:" + "f" * 64, plan
                        )
                with pytest.raises(asyncpg.RaiseError, match="STALE_OR_UNBOUND"):
                    async with db.transaction() as c:
                        await c.execute(
                            f"INSERT INTO {TABLE} SELECT $1,revision,symbol,$2,predecessor_revision,predecessor_hash,request_hash,request_payload FROM {TABLE} WHERE tradeplan_id=$3",
                            uuid4(),
                            uuid4(),
                            plan,
                        )
        async with db.transaction() as c:
            assert await c.fetchval(f"SELECT count(*) FROM {TABLE} WHERE tradeplan_id=$1", plan) == (
                2 if scenario == "advisory_canonical" else 1
            )

    asyncio.run(run())
