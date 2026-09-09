"""Actual TEST_ONLY transaction composition acceptance on guarded PostgreSQL."""

import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
from uuid import uuid4

import psycopg
import pytest

from contracts.strategy_5scr_activity_delivery import ActivityConsumerScopeV1
from contracts.strategy_5scr_candidate_revision_v31 import CandidateRevisionAppendV31
from contracts.strategy_5scr_capacity_owner_v31 import CapacityOwnerFenceV31
from risk.strategy_5scr_candidate_handoff_v31 import candidate_handoff_hash_v31
from risk.strategy_5scr_capacity_v31 import capacity_content_hash_v31, capacity_ledger_hash_v31
from storage.strategy_5scr_activity_consumer import transfer_owner
from storage.strategy_5scr_candidate_revision_v31 import CandidateRevisionRepositoryV31
from storage.strategy_5scr_capacity_v31 import CapacityRepositoryV31
from storage.strategy_5scr_transaction_a_v31 import PREFIX, TransactionARepositoryV31
from tests.integration.test_candidate_revision_v31_postgres import DB
from tests.integration.test_pair_activity_runtime_postgres import pg_dsn
from tests.test_strategy_5scr_transaction_a_v31 import NOW, fixture

__all__ = ["pg_dsn"]


class FaultConnection:
    def __init__(self, c, fault, after_write=None):
        self.c, self.fault = c, fault
        self.after_write = after_write

    def __getattr__(self, name):
        return getattr(self.c, name)

    async def execute(self, sql, *args):
        result = await self.c.execute(sql, *args)
        if self.after_write:
            self.after_write(sql)
        if self.fault and f"INSERT INTO {PREFIX}{self.fault}_v31" in sql:
            raise RuntimeError("injected write failure")
        return result

    async def fetchrow(self, sql, *args):
        result = await self.c.fetchrow(sql, *args)
        if self.fault == "capacity" and sql.startswith("UPDATE public.strategy_5scr_capacity_ledgers_v31"):
            raise RuntimeError("injected write failure")
        return result


class FaultDB(DB):
    def __init__(self, dsn):
        super().__init__(dsn)
        self.fault = None
        self.after_write = None

    @asynccontextmanager
    async def transaction(self):
        async with super().transaction() as c:
            yield FaultConnection(c, self.fault, self.after_write)


@pytest.mark.parametrize(
    "scenario",
    [
        "commit",
        "restart_duplicate",
        "concurrent_duplicate",
        "conflicting_replay",
        "rollback_capacity",
        "rollback_campaigns",
        "rollback_parent_legs",
        "rollback_signal_previews",
        "rollback_outbox",
        "verifier_account_lock_available",
        "expiry_after_verification",
        "expiry_during_last_write",
    ],
)
def test_transaction_a_postgres_acceptance(pg_dsn, scenario, monkeypatch):
    from storage import strategy_5scr_prepared_v31 as detached

    monkeypatch.setattr(detached, "commit_time_v31", lambda: NOW + timedelta(milliseconds=500))

    async def run():
        db = FaultDB(pg_dsn)
        constructed, _, ledger, request = await fixture()
        account = "transaction-fixture-" + str(uuid4())
        snapshot = request.sizing.snapshot.model_copy(update={"account_id": account})
        ledger = ledger.model_copy(
            update={"account_id": account, "account_snapshot_hash": capacity_content_hash_v31(snapshot)}
        )
        owner = CapacityOwnerFenceV31(
            profile="TEST_ONLY",
            account_id=account,
            executor_id=ledger.executor_id,
            owner_id="fixture-transaction-owner",
            owner_epoch=1,
            token=uuid4(),
        )
        capacity = CapacityRepositoryV31(fence=owner)
        prepared_initial = capacity.prepare_initial_detached(ledger, verify_initial=lambda *_: True)
        async with db.transaction() as c:
            assert await c.fetchval("SELECT to_regclass($1)", PREFIX + "outbox_v31"), (
                "explicit migration 20260909_06 required"
            )
            await capacity.initialize_in_transaction(c, ledger, prepared=prepared_initial)
        scope = ActivityConsumerScopeV1(
            consumer_scope_id="transaction-a-fixture",
            producer_binding_hash="sha256:" + "a" * 64,
            lifecycle_owner_id="fixture-strategy-owner",
            lifecycle_policy_hash="sha256:" + "b" * 64,
            environment_class="DISPOSABLE_TEST",
        )
        async with db.transaction() as c:
            old = await c.fetchrow("SELECT generation FROM public.strategy_5scr_owner_fences_v1 WHERE symbol='EURUSD'")
            fence = await transfer_owner(
                c, symbol="EURUSD", scope=scope, expected_generation=old["generation"] if old else 0
            )
        candidates = CandidateRevisionRepositoryV31(pg=db, fence=fence, verify_reevaluation=lambda *_: True)
        append = CandidateRevisionAppendV31.model_validate_json(constructed.rows[0]["request_payload"])
        plan = uuid4()
        campaign = uuid4()
        append = append.model_copy(
            update={
                "reevaluation_id": uuid4(),
                "handoff": append.handoff.model_copy(
                    update={"candidate": append.handoff.candidate.model_copy(update={"tradeplan_id": plan})}
                ),
            }
        )
        candidate = await candidates.append(append, now=NOW)
        sizing = request.sizing.model_copy(
            update={
                "expected_account_id": account,
                "snapshot": snapshot,
                "tradeplan_id": str(plan),
                "campaign_id": str(campaign),
                "risk_state_evidence_hash": capacity_ledger_hash_v31(ledger),
                "strategy_candidate_receipt_hash": candidate_handoff_hash_v31(candidate.request.handoff),
            }
        )
        request = request.model_copy(
            update={
                "reservation_id": uuid4(),
                "campaign_id": campaign,
                "parent_leg_id": uuid4(),
                "signal_id": uuid4(),
                "outbox_id": uuid4(),
                "candidate_revision_hash": candidate.request_hash,
                "sizing": sizing,
            }
        )
        repo = TransactionARepositoryV31(
            pg=db,
            capacity_repository=capacity,
            candidate_repository=candidates,
            verify_handoff=lambda *_: True,
            verify_universe=lambda *_: True,
            verify_risk_inputs=lambda *_: True,
        )
        failed = scenario.startswith("rollback_")
        if scenario == "verifier_account_lock_available":
            calls = []

            def verify(*_):
                with psycopg.connect(pg_dsn) as other:
                    acquired = other.execute(
                        "SELECT pg_try_advisory_xact_lock(hashtextextended('5scr-capacity-v31:' || %s::text,0))",
                        (account,),
                    ).fetchone()[0]
                    assert acquired is True
                calls.append(True)
                return True

            repo.verify_handoff = repo.verify_universe = repo.verify_risk_inputs = verify
            await repo.submit(request, now=NOW)
            assert len(calls) >= 3
        elif scenario == "expiry_during_last_write":

            def after_write(sql):
                if f"INSERT INTO {PREFIX}outbox_v31" in sql:
                    monkeypatch.setattr(detached, "commit_time_v31", lambda: request.expires_at)

            db.after_write = after_write
            with pytest.raises(ValueError, match="EXPIRED"):
                await repo.submit(request, now=NOW)
            db.after_write = None
            failed = True
        elif scenario == "expiry_after_verification":

            def verify(*_):
                monkeypatch.setattr(detached, "commit_time_v31", lambda: request.expires_at)
                return True

            repo.verify_handoff = verify
            with pytest.raises(ValueError, match="EXPIRED"):
                await repo.submit(request, now=NOW)
            failed = True
        elif failed:
            db.fault = scenario.removeprefix("rollback_")
            with pytest.raises(RuntimeError, match="injected write failure"):
                await repo.submit(request, now=NOW)
            db.fault = None
        elif scenario == "concurrent_duplicate":
            receipts = await asyncio.gather(repo.submit(request, now=NOW), repo.submit(request, now=NOW))
            assert {r.status for r in receipts} == {"COMMITTED_TEST_ONLY", "DUPLICATE_TEST_ONLY"}
        else:
            first = await repo.submit(request, now=NOW)
            if scenario == "restart_duplicate":
                restarted = TransactionARepositoryV31(
                    pg=DB(pg_dsn),
                    capacity_repository=capacity,
                    candidate_repository=candidates,
                    verify_handoff=None,
                    verify_universe=None,
                    verify_risk_inputs=None,
                )
                duplicate = await restarted.submit(request, now=NOW + timedelta(days=1))
                assert duplicate.bundle == first.bundle and duplicate.status == "DUPLICATE_TEST_ONLY"
            elif scenario == "conflicting_replay":
                with pytest.raises(ValueError, match="REPLAY_CONFLICT"):
                    await repo.submit(request.model_copy(update={"outbox_id": uuid4()}), now=NOW)
        async with DB(pg_dsn).transaction() as c:
            current = await capacity.lock_current(c)
            assert current.version == (0 if failed else 1)
            assert len(current.reservations) == (0 if failed else 1)
            for name in ("campaigns", "parent_legs", "signal_previews", "outbox"):
                count = await c.fetchval(
                    f"SELECT count(*) FROM {PREFIX}{name}_v31 WHERE reservation_id=$1", request.reservation_id
                )
                assert count == (0 if failed else 1)

    asyncio.run(run())
