"""Actual producer/relay/owner DB acceptance. Guarded disposable target only."""

import asyncio
import json
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest

from analysis.strategy_5scr_pair_activity import normalize_pair_activity_observations
from analysis.strategy_5scr_v3.episode_hash import build_strategy_lifecycle_id
from contracts.strategy_5scr_activity_delivery import ActivityConsumerScopeV1, ActivityDeliveryV1
from contracts.strategy_5scr_activity_runtime import ActivityCoverageCheckpointV1
from contracts.strategy_5scr_lifecycle_v2 import StrategyLifecycleV2
from scripts.ci.pair_activity_run_evidence import record_runtime_fixture
from services.pressure_outbox.activity_delivery_relay import ActivityDeliveryRelay
from storage.strategy_5scr_activity_consumer import bind_owner, transfer_owner
from storage.strategy_5scr_activity_runtime import PostgresActivityRuntime
from storage.strategy_5scr_shadow_evidence_v2_repository import StrategyShadowEvidenceV2Repository
from tests.integration.test_pair_activity_runtime_postgres import fixture_binding, pg_dsn, raw

__all__ = ["pg_dsn"]


class DB:
    def __init__(self, dsn):
        self.dsn = dsn
        self.fault = None

    @asynccontextmanager
    async def transaction(self):
        c = await asyncpg.connect(self.dsn, timeout=3, command_timeout=10)
        try:
            async with c.transaction():
                yield FaultConnection(c, self.fault)
        finally:
            await c.close()


class FaultConnection:
    def __init__(self, c, fault):
        self.c, self.fault = c, fault

    def __getattr__(self, name):
        return getattr(self.c, name)

    async def execute(self, sql, *args):
        result = await self.c.execute(sql, *args)
        if self.fault and self.fault in sql:
            raise RuntimeError("injected after consumer write")
        return result


def setup(dsn):
    start = datetime.now(UTC) - timedelta(seconds=300)
    binding = fixture_binding().model_copy(update={"window_start_utc": start})
    events = [
        replace(raw(second, direction, symbol="S03TEST"), timestamp=start + timedelta(seconds=second))
        for second, direction in ((0, "BUY"), (150, "SELL"), (300, "BUY"))
    ]
    normalized = normalize_pair_activity_observations(events)
    cp = ActivityCoverageCheckpointV1(
        binding_hash=binding.binding_hash,
        attestor_id=binding.coverage_attestor_id,
        window_start_utc=start,
        window_end_utc=start + timedelta(seconds=300),
        expected_raw_count=normalized.raw_event_count,
        expected_raw_hash=normalized.raw_population_hash,
        status="COMPLETE",
    )
    record_runtime_fixture(binding, cp)
    scope = ActivityConsumerScopeV1(
        consumer_scope_id=binding.ledger_id,
        producer_binding_hash=binding.binding_hash,
        lifecycle_owner_id="fixture-shared-owner",
        lifecycle_policy_hash="sha256:" + "2" * 64,
        environment_class="DISPOSABLE_TEST",
    )
    producer = PostgresActivityRuntime(
        dsn=dsn,
        binding=binding,
        checkpoint_provider=lambda: cp,
        clock=lambda: start + timedelta(seconds=300),
        delivery_scope=scope,
    )
    producer.append(events)
    producer.evaluate()
    db = DB(dsn)
    owner = StrategyShadowEvidenceV2Repository(pg=db)

    async def claim():
        async with db.transaction() as c:
            row = await c.fetchrow("SELECT generation FROM public.strategy_5scr_owner_fences_v1 WHERE symbol='S03TEST'")
            return await transfer_owner(
                c, symbol="S03TEST", scope=scope, expected_generation=row["generation"] if row else 0
            )

    fence = asyncio.run(claim())
    lifecycle = StrategyLifecycleV2(
        strategy_lifecycle_id=build_strategy_lifecycle_id(
            symbol="S03TEST", opened_at_utc=start, opening_direction_state="INCOMPLETE"
        ),
        symbol="S03TEST",
        opened_at_utc=start,
        last_event_at_utc=start + timedelta(seconds=300),
        last_continuity_event_at_utc=start + timedelta(seconds=300),
        last_material_event_at_utc=start + timedelta(seconds=300),
        material_state_hash="5" * 64,
    )

    def verify(event):
        with producer._connect() as c:
            stored = c.execute(
                "SELECT payload FROM public.pair_activity_delivery_outbox_v1 WHERE delivery_id=%s", (event.delivery_id,)
            ).fetchone()
        return stored is not None and ActivityDeliveryV1.model_validate_json(stored["payload"]) == event

    consumer = owner.activity_consumer(
        scope=scope,
        fence=fence,
        policy_hash=scope.lifecycle_policy_hash,
        select_lifecycle=lambda event, rows, previous: lifecycle,
        validate_source=verify,
    )

    def wire():
        with producer._connect() as c:
            return c.execute(
                "SELECT payload FROM public.pair_activity_delivery_outbox_v1 WHERE ledger_id=%s ORDER BY sequence",
                (binding.ledger_id,),
            ).fetchall()

    return producer, consumer, db, owner, lifecycle, wire


def test_commit_expired_lease_replay_then_successor(pg_dsn):
    import time

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from services.pressure_outbox.activity_delivery_transport import ActivityTransportBinding, activity_consumer_router

    producer, consumer, db, owner, lifecycle, wire = setup(pg_dsn)
    producer._clock = lambda: datetime.now(UTC)
    producer.evaluate()
    assert len(wire()) == 2
    calls = []
    binding = ActivityTransportBinding(
        destination="https://fixture.test/internal/s03/activity-deliveries",
        identity="fixture-producer",
        key=b"x" * 32,
        maximum_skew_seconds=30,
    )
    application = FastAPI()
    application.include_router(
        activity_consumer_router(binding=binding, consumer=consumer, maximum_payload_bytes=100000)
    )

    def send(payload):
        timestamp = str(int(time.time()))
        with TestClient(application) as client:
            response = client.post(
                "/internal/s03/activity-deliveries",
                content=payload,
                headers={
                    "X-S03-Identity": binding.identity,
                    "X-S03-Time": timestamp,
                    "X-S03-Signature": binding.signature(timestamp, payload),
                },
            )
            assert response.status_code == 200
            body = response.json()
        ack = body["delivery_id"], body["payload_hash"], body["outcome"]
        calls.append(ack[-1])
        if len(calls) == 1:
            with producer._connect() as c:
                c.execute(
                    "UPDATE public.pair_activity_delivery_outbox_v1 SET lease_until=clock_timestamp()-interval '1 second' "
                    "WHERE delivery_id=%s",
                    (ack[0],),
                )
        return ack

    relay = ActivityDeliveryRelay(
        connect=producer._connect,
        ledger_id=producer.binding.ledger_id,
        scope=consumer.scope,
        send=send,
        lease_seconds=60,
    )
    assert relay.poll_once() == "STALE_LEASE_ACK_IGNORED"
    assert relay.poll_once() == "ACKNOWLEDGED"
    assert relay.poll_once() == "ACKNOWLEDGED"
    assert calls == ["COMMITTED", "DUPLICATE_NO_EFFECT", "COMMITTED"]
    with producer._connect() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM public.strategy_5scr_activity_emissions_v1 WHERE lifecycle_id=%s",
                (lifecycle.strategy_lifecycle_id,),
            ).fetchone()["n"]
            == 1
        )
        assert (
            c.execute(
                "SELECT count(*) AS n FROM public.strategy_5scr_activity_mappings_v1 WHERE lifecycle_id=%s",
                (lifecycle.strategy_lifecycle_id,),
            ).fetchone()["n"]
            == 1
        )


@pytest.mark.parametrize("table", ["mappings", "emissions", "inbox", "consumer_cursors"])
def test_consumer_rollback_all_writes(pg_dsn, table):
    producer, consumer, db, owner, lifecycle, wire = setup(pg_dsn)
    db.fault = "INSERT INTO public.strategy_5scr_activity_" + table
    with pytest.raises(RuntimeError, match="injected"):
        asyncio.run(consumer.consume(wire()[0]["payload"].encode()))
    with producer._connect() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM public.strategy_5scr_analysis_lifecycles_v2 WHERE strategy_lifecycle_id=%s",
                (lifecycle.strategy_lifecycle_id,),
            ).fetchone()["n"]
            == 0
        )
        assert (
            c.execute(
                "SELECT count(*) AS n FROM public.strategy_5scr_activity_inbox_v1 WHERE delivery_id=%s",
                (ActivityDeliveryV1.model_validate_json(wire()[0]["payload"]).delivery_id,),
            ).fetchone()["n"]
            == 0
        )
    db.fault = None
    assert asyncio.run(consumer.consume(wire()[0]["payload"].encode()))[-1] == "COMMITTED"


def test_legacy_writer_and_old_owner_cannot_bypass_handover(pg_dsn):
    producer, consumer, db, owner, lifecycle, wire = setup(pg_dsn)

    async def run():
        async with db.transaction() as c:
            await transfer_owner(
                c, symbol="S03TEST", scope=consumer.scope, expected_generation=consumer.fence.generation
            )
        with pytest.raises(ValueError, match="STALE_OR_UNBOUND"):
            await consumer.consume(wire()[0]["payload"].encode())
        with pytest.raises(asyncpg.RaiseError, match="STALE_OR_UNBOUND"):
            async with db.transaction() as c:
                await owner._lifecycles.upsert_lifecycle(lifecycle, _executor=c)
        with pytest.raises(ValueError, match="STALE_OR_UNBOUND"):
            async with db.transaction() as c:
                await bind_owner(c, consumer.fence)

    asyncio.run(run())


def test_payload_conflict_quarantined_in_database(pg_dsn):
    producer, consumer, db, owner, lifecycle, wire = setup(pg_dsn)
    payload = wire()[0]["payload"]
    asyncio.run(consumer.consume(payload.encode()))
    changed = json.loads(payload)
    changed["source_snapshot_id"] = "sha256:" + "9" * 64
    assert asyncio.run(consumer.consume(json.dumps(changed).encode()))[-1] == "QUARANTINE_PAYLOAD_CONFLICT"
    with producer._connect() as c:
        assert (
            c.execute(
                "SELECT count(*) AS n FROM public.strategy_5scr_activity_conflicts_v1 WHERE delivery_id=%s",
                (changed["delivery_id"],),
            ).fetchone()["n"]
            == 1
        )


def test_successor_waits_for_consumer_predecessor(pg_dsn):
    producer, consumer, db, owner, lifecycle, wire = setup(pg_dsn)
    producer._clock = lambda: datetime.now(UTC)
    producer.evaluate()
    assert asyncio.run(consumer.consume(wire()[1]["payload"].encode()))[-1] == "WAITING_PREDECESSOR"
    assert asyncio.run(consumer.consume(wire()[0]["payload"].encode()))[-1] == "COMMITTED"
    assert asyncio.run(consumer.consume(wire()[1]["payload"].encode()))[-1] == "COMMITTED"


def test_existing_advisory_lifecycle_is_attached_without_remint(pg_dsn):
    producer, consumer, db, owner, lifecycle, wire = setup(pg_dsn)

    async def run():
        async with db.transaction() as c:
            await bind_owner(c, consumer.fence)
            await owner._lifecycles.upsert_lifecycle(lifecycle, _executor=c)
        assert (await consumer.consume(wire()[0]["payload"].encode()))[-1] == "COMMITTED"

    asyncio.run(run())
    with producer._connect() as c:
        assert (
            c.execute(
                "SELECT lifecycle_id FROM public.strategy_5scr_activity_mappings_v1 WHERE scope_hash=%s",
                (consumer.scope.scope_hash,),
            ).fetchone()["lifecycle_id"]
            == lifecycle.strategy_lifecycle_id
        )


def test_concurrent_consumer_duplicate_has_one_effect(pg_dsn):
    producer, consumer, db, owner, lifecycle, wire = setup(pg_dsn)
    payload = wire()[0]["payload"].encode()

    async def run():
        return await asyncio.gather(consumer.consume(payload), consumer.consume(payload))

    outcomes = asyncio.run(run())
    assert sorted(row[-1] for row in outcomes) == ["COMMITTED", "DUPLICATE_NO_EFFECT"]


def test_fresh_consumer_after_restart_recovers_committed_inbox(pg_dsn):
    producer, consumer, db, owner, lifecycle, wire = setup(pg_dsn)
    payload = wire()[0]["payload"].encode()
    assert asyncio.run(consumer.consume(payload))[-1] == "COMMITTED"
    restarted = StrategyShadowEvidenceV2Repository(pg=DB(pg_dsn)).activity_consumer(
        scope=consumer.scope,
        fence=consumer.fence,
        policy_hash=consumer.scope.lifecycle_policy_hash,
        select_lifecycle=lambda *args: pytest.fail("duplicate must not reduce again"),
        validate_source=lambda event: pytest.fail("committed duplicate must not reacquire source"),
    )
    assert asyncio.run(restarted.consume(payload))[-1] == "DUPLICATE_NO_EFFECT"


def test_unprivileged_application_role_enforces_owner_fence(pg_dsn):
    """Exercise the real trigger as a non-owner role in the guarded disposable DB.

    Positive current owner, unbound legacy write and stale post-handover writer
    use the same application privileges. This is not deployed-role attestation.
    """
    from uuid import uuid4

    _, consumer, db, owner, lifecycle, _ = setup(pg_dsn)
    role = "wolf15_acceptance_" + uuid4().hex

    async def run():
        admin = await asyncpg.connect(pg_dsn, timeout=3, command_timeout=10)
        try:
            await admin.execute(
                f'CREATE ROLE "{role}" NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS'
            )
            await admin.execute(f'GRANT USAGE ON SCHEMA public TO "{role}"')
            await admin.execute(
                f'GRANT SELECT, INSERT, UPDATE ON public.strategy_5scr_analysis_lifecycles_v2 TO "{role}"'
            )
            # SELECT FOR UPDATE in bind_owner needs UPDATE, not owner-table ownership.
            await admin.execute(f'GRANT SELECT, UPDATE ON public.strategy_5scr_owner_fences_v1 TO "{role}"')

            @asynccontextmanager
            async def app_transaction():
                async with db.transaction() as c:
                    await c.execute(f'SET LOCAL ROLE "{role}"')
                    assert await c.fetchval("SELECT current_user") == role
                    flags = await c.fetchrow(
                        "SELECT rolsuper,rolcreatedb,rolcreaterole,rolbypassrls FROM pg_roles WHERE rolname=current_user"
                    )
                    assert not any(flags.values())
                    yield c

            with pytest.raises(asyncpg.RaiseError, match="STALE_OR_UNBOUND"):
                async with app_transaction() as c:
                    await owner._lifecycles.upsert_lifecycle(lifecycle, _executor=c)
            async with app_transaction() as c:
                await bind_owner(c, consumer.fence)
                await owner._lifecycles.upsert_lifecycle(lifecycle, _executor=c)
                assert (
                    await c.fetchval(
                        "SELECT execution_authority FROM public.strategy_5scr_analysis_lifecycles_v2 "
                        "WHERE strategy_lifecycle_id=$1",
                        lifecycle.strategy_lifecycle_id,
                    )
                    is False
                )
            async with db.transaction() as c:
                await transfer_owner(
                    c, symbol="S03TEST", scope=consumer.scope, expected_generation=consumer.fence.generation
                )
            with pytest.raises(ValueError, match="STALE_OR_UNBOUND"):
                async with app_transaction() as c:
                    await bind_owner(c, consumer.fence)
                    await owner._lifecycles.upsert_lifecycle(lifecycle, _executor=c)
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                async with app_transaction() as c:
                    await c.execute("ALTER TABLE public.strategy_5scr_analysis_lifecycles_v2 DISABLE TRIGGER ALL")
        finally:
            await admin.execute(f'DROP OWNED BY "{role}"')
            await admin.execute(f'DROP ROLE "{role}"')
            await admin.close()

    asyncio.run(run())
