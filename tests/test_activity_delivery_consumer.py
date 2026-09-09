"""Transactional model and authenticated ASGI tests, not PostgreSQL acceptance."""

import asyncio
import copy
import json
import time
from contextlib import asynccontextmanager
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from contracts.strategy_5scr_lifecycle_v2 import StrategyLifecycleV2
from services.pressure_outbox.activity_delivery_transport import ActivityTransportBinding, activity_consumer_router
from storage.strategy_5scr_activity_consumer import LifecycleOwnerFence
from storage.strategy_5scr_shadow_evidence_v2_repository import StrategyShadowEvidenceV2Repository
from tests.test_activity_delivery_contract import delivery, scope
from tests.test_activity_delivery_relay import Store
from tests.test_strategy_5scr_pair_activity import START


class ConsumerDB:
    def __init__(self):
        self.fence = LifecycleOwnerFence("EURUSD", scope().scope_hash, scope().lifecycle_owner_id, 1, uuid4())
        self.data = {
            name: {} for name in ("inbox", "conflicts", "mappings", "consumer_cursors", "emissions", "lifecycles")
        }
        self.now = START + timedelta(seconds=301)
        self.active = False
        self.fail_at = None

    @asynccontextmanager
    async def transaction(self):
        assert not self.active
        before = copy.deepcopy(self.data)
        self.active = True
        try:
            yield self
        except BaseException:
            self.data = before
            raise
        finally:
            self.active = False

    async def execute(self, sql, *args):
        if "INSERT INTO strategy_5scr_analysis_lifecycles_v2" in sql:
            self.data["lifecycles"][args[0]] = {"strategy_lifecycle_id": args[0]}
        elif sql.startswith("INSERT INTO public.strategy_5scr_activity_"):
            table = sql.split("strategy_5scr_activity_")[1].split("_v1")[0]
            if table == self.fail_at:
                raise RuntimeError("injected consumer write failure")
            key = args[:2] if table in {"mappings", "consumer_cursors", "conflicts"} else args[0]
            row = {"payload": json.loads(args[-1])}
            if table == "emissions":
                self.data[table].setdefault(key, row)
            else:
                self.data[table][key] = row
        return "INSERT 0 1"

    async def fetchrow(self, sql, *args):
        if "owner_fences" in sql:
            return vars(self.fence)
        table = sql.split("strategy_5scr_activity_")[1].split("_v1")[0]
        return self.data[table].get(args[0] if table in {"inbox", "emissions"} else args)

    async def fetchval(self, sql):
        return self.now

    async def fetch(self, sql, *args):
        return list(self.data["lifecycles"].values())


def lifecycle(event, rows, previous):
    return StrategyLifecycleV2(
        strategy_lifecycle_id="5scr-lifecycle:" + "4" * 32,
        symbol="EURUSD",
        opened_at_utc=START,
        last_event_at_utc=START + timedelta(seconds=300),
        last_continuity_event_at_utc=START + timedelta(seconds=300),
        last_material_event_at_utc=START + timedelta(seconds=300),
        material_state_hash="5" * 64,
    )


def consumer(db):
    return StrategyShadowEvidenceV2Repository(pg=db).activity_consumer(
        scope=scope(),
        fence=db.fence,
        policy_hash=scope().lifecycle_policy_hash,
        select_lifecycle=lifecycle,
        validate_source=lambda event: True,
    )


def test_commit_then_expired_relay_ack_then_duplicate_ack_recovers():
    db = ConsumerDB()
    owner = consumer(db)
    relay_store = Store()
    relay_store.ack_updated = False

    def send(wire):
        ack = asyncio.run(owner.consume(wire))
        assert not db.active
        return ack

    relay = relay_store.relay(send)
    assert relay.poll_once() == "STALE_LEASE_ACK_IGNORED"
    before = copy.deepcopy(db.data)
    db.now = START + timedelta(days=1)
    relay_store.ack_updated = True
    assert relay.poll_once() == "ACKNOWLEDGED"
    assert db.data == before
    assert len(db.data["lifecycles"]) == len(db.data["emissions"]) == len(db.data["inbox"]) == 1


@pytest.mark.parametrize("fail_at", ["mappings", "emissions", "inbox", "consumer_cursors"])
def test_every_consumer_write_failure_rolls_back(fail_at):
    db = ConsumerDB()
    db.fail_at = fail_at
    with pytest.raises(RuntimeError, match="injected"):
        asyncio.run(consumer(db).consume(delivery().model_dump_json().encode()))
    assert all(not rows for rows in db.data.values())


def test_payload_conflict_quarantined_without_rewriting_outcome():
    db = ConsumerDB()
    owner = consumer(db)
    asyncio.run(owner.consume(delivery().model_dump_json().encode()))
    original = copy.deepcopy(db.data["inbox"])
    conflict = delivery(source_snapshot_id="sha256:" + "7" * 64)
    assert asyncio.run(owner.consume(conflict.model_dump_json().encode()))[-1] == "QUARANTINE_PAYLOAD_CONFLICT"
    assert db.data["inbox"] == original and len(db.data["conflicts"]) == 1


def test_uncommitted_predecessor_cannot_be_skipped():
    db = ConsumerDB()
    event = delivery(activity_sequence=2, previous_delivery_id="5scr-activity-delivery:" + "8" * 32)
    assert asyncio.run(consumer(db).consume(event.model_dump_json().encode()))[-1] == "WAITING_PREDECESSOR"
    assert all(not rows for rows in db.data.values())


def test_old_owner_rejected_after_handover():
    db = ConsumerDB()
    old = consumer(db)
    db.fence = LifecycleOwnerFence("EURUSD", scope().scope_hash, scope().lifecycle_owner_id, 2, uuid4())
    with pytest.raises(ValueError, match="STALE_OR_UNBOUND"):
        asyncio.run(old.consume(delivery().model_dump_json().encode()))
    assert all(not rows for rows in db.data.values())


def test_authenticated_route_returns_ack_only_after_commit():
    db = ConsumerDB()
    binding = ActivityTransportBinding(
        destination="https://consumer.test/internal/s03/activity-deliveries",
        identity="fixture-producer",
        key=b"x" * 32,
        maximum_skew_seconds=30,
    )
    app = FastAPI()
    app.include_router(activity_consumer_router(binding=binding, consumer=consumer(db), maximum_payload_bytes=100000))
    wire = delivery().model_dump_json().encode()
    timestamp = str(int(time.time()))
    with TestClient(app) as client:
        assert client.post("/internal/s03/activity-deliveries", content=wire).status_code == 401
        assert not db.data["inbox"]
        response = client.post(
            "/internal/s03/activity-deliveries",
            content=wire,
            headers={
                "X-S03-Identity": binding.identity,
                "X-S03-Time": timestamp,
                "X-S03-Signature": binding.signature(timestamp, wire),
            },
        )
    assert response.status_code == 200 and response.json()["outcome"] == "COMMITTED"
    assert not db.active and len(db.data["inbox"]) == 1


@pytest.mark.parametrize("field", ["identity", "timestamp", "payload", "signature"])
def test_transport_tampering_rejected(field):
    binding = ActivityTransportBinding(
        destination="https://consumer.test/internal/s03/activity-deliveries",
        identity="fixture",
        key=b"x" * 32,
        maximum_skew_seconds=30,
    )
    args = dict(
        identity="fixture", timestamp="100", payload=b"body", signature=binding.signature("100", b"body"), now=100
    )
    args[field] = b"other" if field == "payload" else "wrong"
    with pytest.raises(ValueError, match="UNAUTHENTICATED"):
        binding.authenticate(**args)


def test_api_factory_mounts_only_explicit_bound_endpoint(monkeypatch):
    from api import app_factory
    from services.pressure_outbox.activity_delivery_transport import ActivityDeliveryEndpoint

    monkeypatch.setattr(app_factory, "_create_app_inner", lambda: FastAPI())
    assert not any(route.path == "/internal/s03/activity-deliveries" for route in app_factory.create_app().routes)
    db = ConsumerDB()
    binding = ActivityTransportBinding(
        destination="https://consumer.test/internal/s03/activity-deliveries",
        identity="fixture",
        key=b"x" * 32,
        maximum_skew_seconds=30,
    )
    endpoint = ActivityDeliveryEndpoint(binding, consumer(db), 100000)
    app = app_factory.create_app(activity_delivery_endpoint=endpoint)
    with TestClient(app) as client:
        assert client.post("/internal/s03/activity-deliveries", content=b"{}").status_code == 401
    with pytest.raises(ValueError, match="BINDING_REQUIRED"):
        app_factory.create_app(activity_delivery_endpoint=object())
    monkeypatch.setattr(app_factory, "_create_app_inner", lambda: app)
    with pytest.raises(ValueError, match="ALREADY_REGISTERED"):
        app_factory.create_app(activity_delivery_endpoint=endpoint)


def test_unseen_expiry_and_missing_policy_fail_closed():
    db = ConsumerDB()
    db.now = delivery().evaluation.valid_until_utc
    assert asyncio.run(consumer(db).consume(delivery().model_dump_json().encode()))[-1] == "EXPIRED_UNSEEN_DELIVERY"
    assert all(not rows for rows in db.data.values())
    with pytest.raises(ValueError, match="POLICY_OR_OWNER_UNBOUND"):
        StrategyShadowEvidenceV2Repository(pg=db).activity_consumer(
            scope=scope(),
            fence=db.fence,
            policy_hash=None,
            select_lifecycle=lifecycle,
            validate_source=lambda event: True,
        )


def test_changed_policy_cannot_remap_same_logical_activity():
    db = ConsumerDB()
    asyncio.run(consumer(db).consume(delivery().model_dump_json().encode()))
    original = copy.deepcopy(db.data)
    new_scope = scope(lifecycle_policy_hash="sha256:" + "9" * 64)
    db.fence = LifecycleOwnerFence("EURUSD", new_scope.scope_hash, new_scope.lifecycle_owner_id, 2, uuid4())
    owner = StrategyShadowEvidenceV2Repository(pg=db).activity_consumer(
        scope=new_scope,
        fence=db.fence,
        policy_hash=new_scope.lifecycle_policy_hash,
        select_lifecycle=lifecycle,
        validate_source=lambda event: True,
    )
    with pytest.raises(ValueError, match="EXPLICIT_MIGRATION"):
        asyncio.run(owner.consume(delivery(scope=new_scope).model_dump_json().encode()))
    assert db.data == original


def test_recovery_capacity_excess_is_not_silently_truncated():
    db = ConsumerDB()
    db.data["lifecycles"] = {str(n): {} for n in range(1001)}
    before = copy.deepcopy(db.data)
    with pytest.raises(ValueError, match="CAPACITY_EXCEEDED"):
        asyncio.run(consumer(db).consume(delivery().model_dump_json().encode()))
    assert db.data == before
