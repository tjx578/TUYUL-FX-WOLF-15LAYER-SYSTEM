"""Separate producer/relay database scope. Does not close consumer D01-D11.

Uses the existing disposable guard; migrations must be applied explicitly.
No production credentials, implicit DDL, or replacement of the original 45 tests.
"""

from datetime import timedelta

import psycopg
import pytest
from psycopg.rows import dict_row

from contracts.strategy_5scr_activity_delivery import ActivityConsumerScopeV1
from scripts.ci.pair_activity_run_evidence import record_runtime_fixture
from services.pressure_outbox.activity_delivery_relay import ActivityDeliveryRelay
from storage.strategy_5scr_activity_runtime import PostgresActivityRuntime
from tests.integration.test_pair_activity_runtime_postgres import (
    START,
    checkpoint,
    fixture_binding,
    pg_dsn,
    raw,
)

__all__ = ["pg_dsn"]


def setup_runtime(dsn):
    binding = fixture_binding()
    events = [raw(0), raw(150, "SELL"), raw(300)]
    cp = checkpoint(binding, events)
    record_runtime_fixture(binding, cp)
    scope = ActivityConsumerScopeV1(
        consumer_scope_id="fixture-owner-scope",
        producer_binding_hash=binding.binding_hash,
        lifecycle_owner_id="fixture-owner",
        lifecycle_policy_hash="sha256:" + "2" * 64,
        environment_class="DISPOSABLE_TEST",
    )
    worker = PostgresActivityRuntime(
        dsn=dsn,
        binding=binding,
        checkpoint_provider=lambda: cp,
        clock=lambda: START + timedelta(seconds=300),
        delivery_scope=scope,
    )
    worker.append(events)
    return worker, scope


def outbox(dsn, ledger):
    with psycopg.connect(dsn, row_factory=dict_row) as c:
        return c.execute(
            "SELECT * FROM public.pair_activity_delivery_outbox_v1 WHERE ledger_id=%s ORDER BY sequence", (ledger,)
        ).fetchall()


def test_producer_duplicate_restart_keeps_first_envelope(pg_dsn):
    worker, scope = setup_runtime(pg_dsn)
    report = worker.evaluate()
    assert report["audit"]["evaluations"][0]["duration_seconds"] == 300
    first = outbox(pg_dsn, worker.binding.ledger_id)
    assert len(first) == 1 and first[0]["sequence"] == 1
    restarted = PostgresActivityRuntime(
        dsn=pg_dsn,
        binding=worker.binding,
        checkpoint_provider=worker._checkpoint_provider,
        clock=worker._clock,
        delivery_scope=scope,
    )
    restarted.evaluate()
    assert outbox(pg_dsn, worker.binding.ledger_id) == first


def test_producer_outbox_failure_rolls_back_evaluation_snapshot_and_counter(pg_dsn, monkeypatch):
    from storage import strategy_5scr_activity_runtime as module

    worker, _ = setup_runtime(pg_dsn)
    actual = module.enqueue_activity_evaluation

    def crash(*args, **kwargs):
        actual(*args, **kwargs)
        raise RuntimeError("injected after outbox before commit")

    with monkeypatch.context() as patch:
        patch.setattr(module, "enqueue_activity_evaluation", crash)
        with pytest.raises(RuntimeError, match="injected"):
            worker.evaluate()
    assert outbox(pg_dsn, worker.binding.ledger_id) == []
    with psycopg.connect(pg_dsn) as c:
        for table in (
            "pair_activity_evaluations_v31",
            "pair_activity_snapshots_v31",
            "pair_activity_delivery_cursors_v1",
        ):
            assert (
                c.execute(
                    f"SELECT count(*) FROM public.{table} WHERE ledger_id=%s", (worker.binding.ledger_id,)
                ).fetchone()[0]
                == 0
            )
    worker.evaluate()
    assert outbox(pg_dsn, worker.binding.ledger_id)[0]["sequence"] == 1


def test_relay_ack_loss_keeps_payload_after_database_lease_expiry(pg_dsn):
    worker, scope = setup_runtime(pg_dsn)
    worker.evaluate()
    sent = []

    def send(wire):
        from contracts.strategy_5scr_activity_delivery import ActivityDeliveryV1

        sent.append(wire)
        if len(sent) == 1:
            raise TimeoutError("fake ACK loss; not a real consumer")
        delivery = ActivityDeliveryV1.model_validate_json(wire)
        return delivery.delivery_id, delivery.payload_hash, "DUPLICATE_NO_EFFECT"

    relay = ActivityDeliveryRelay(
        connect=worker._connect, ledger_id=worker.binding.ledger_id, scope=scope, send=send, lease_seconds=60
    )
    with pytest.raises(TimeoutError):
        relay.poll_once()
    assert relay.poll_once() == "NO_READY_DELIVERY"
    with worker._connect() as c:
        c.execute(
            "UPDATE public.pair_activity_delivery_outbox_v1 SET lease_until=clock_timestamp()-interval '1 second' "
            "WHERE ledger_id=%s",
            (worker.binding.ledger_id,),
        )
    assert relay.poll_once() == "ACKNOWLEDGED"
    assert sent[0] == sent[1]


def test_committed_envelope_is_database_immutable(pg_dsn):
    worker, _ = setup_runtime(pg_dsn)
    worker.evaluate()
    first = outbox(pg_dsn, worker.binding.ledger_id)
    with pytest.raises(psycopg.Error, match="ACTIVITY_DELIVERY_IMMUTABLE_PAYLOAD"), worker._connect() as c:
        c.execute(
            "UPDATE public.pair_activity_delivery_outbox_v1 SET payload_hash=%s WHERE ledger_id=%s",
            ("sha256:" + "0" * 64, worker.binding.ledger_id),
        )
    assert outbox(pg_dsn, worker.binding.ledger_id) == first


def test_new_evaluation_same_revision_has_committed_predecessor(pg_dsn):
    worker, _ = setup_runtime(pg_dsn)
    worker.evaluate()
    worker._clock = lambda: START + timedelta(seconds=301)
    worker.evaluate()
    stored = outbox(pg_dsn, worker.binding.ledger_id)
    assert len(stored) == 2
    assert [r["sequence"] for r in stored] == [1, 2]
    assert stored[1]["previous_delivery_id"] == stored[0]["delivery_id"]
    assert stored[0]["envelope"]["source_revision"] == stored[1]["envelope"]["source_revision"]


def test_concurrent_duplicate_evaluation_allocates_once(pg_dsn):
    from concurrent.futures import ThreadPoolExecutor

    worker, _ = setup_runtime(pg_dsn)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: worker.evaluate(), range(4)))
    assert len(results) == 4
    assert len(outbox(pg_dsn, worker.binding.ledger_id)) == 1


def test_relay_waits_for_predecessor_ack(pg_dsn):
    worker, scope = setup_runtime(pg_dsn)
    worker.evaluate()
    worker._clock = lambda: START + timedelta(seconds=301)
    worker.evaluate()
    sent = []
    relay = ActivityDeliveryRelay(
        connect=worker._connect,
        ledger_id=worker.binding.ledger_id,
        scope=scope,
        send=lambda wire: sent.append(wire),
        lease_seconds=60,
    )
    assert relay.poll_once() == "UNACKNOWLEDGED"
    assert relay.poll_once() == "NO_READY_DELIVERY"
    assert len(sent) == 1
