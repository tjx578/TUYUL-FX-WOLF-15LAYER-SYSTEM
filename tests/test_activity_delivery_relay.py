"""Relay control-flow tests with an explicit fake store/transport, not PostgreSQL acceptance."""

from contextlib import contextmanager

import pytest

from services.pressure_outbox.activity_delivery_relay import ActivityDeliveryRelay
from tests.test_activity_delivery_contract import delivery, scope


class Store:
    def __init__(self):
        self.event = delivery()
        self.row = dict(
            delivery_id=self.event.delivery_id,
            payload=self.event.model_dump_json(),
            payload_hash=self.event.payload_hash,
        )
        self.active = False
        self.queries = []
        self.ack_updated = True
        self.result = None

    @contextmanager
    def connect(self):
        assert not self.active
        self.active = True
        try:
            yield self
        finally:
            self.active = False

    def execute(self, sql, args):
        assert self.active
        self.queries.append((sql, args))
        self.result = (
            self.row
            if sql.startswith("SELECT")
            else ({"delivery_id": self.event.delivery_id} if "RETURNING" in sql and self.ack_updated else None)
        )
        return self

    def fetchone(self):
        return self.result

    def relay(self, send):
        return ActivityDeliveryRelay(
            connect=self.connect, ledger_id="fixture-ledger", scope=scope(), send=send, lease_seconds=10
        )


def test_network_is_outside_transaction_and_exact_bytes_are_sent():
    store = Store()

    def send(wire):
        assert not store.active
        assert wire == store.row["payload"].encode("utf-8")
        return store.event.delivery_id, store.event.payload_hash, "COMMITTED"

    assert store.relay(send).poll_once() == "ACKNOWLEDGED"


def test_ack_loss_retries_same_payload_and_delivery_with_new_lease():
    store = Store()
    wires = []

    def send(wire):
        wires.append(wire)
        if len(wires) == 1:
            raise TimeoutError("fake lost ACK")
        return store.event.delivery_id, store.event.payload_hash, "DUPLICATE_NO_EFFECT"

    relay = store.relay(send)
    with pytest.raises(TimeoutError):
        relay.poll_once()
    assert relay.poll_once() == "ACKNOWLEDGED"
    assert wires[0] == wires[1]
    leases = [args[0] for sql, args in store.queries if "attempts=attempts+1" in sql]
    assert len(leases) == 2 and leases[0] != leases[1]


@pytest.mark.parametrize(
    "ack",
    [None, ("wrong", "wrong", "COMMITTED"), (delivery().delivery_id, delivery().payload_hash, "WAITING_PREDECESSOR")],
)
def test_noncommitted_or_unbound_ack_does_not_acknowledge(ack):
    store = Store()
    assert store.relay(lambda _: ack).poll_once() == "UNACKNOWLEDGED"
    assert not any("acknowledged=true" in sql for sql, _ in store.queries)


def test_replaced_or_expired_lease_cannot_acknowledge():
    store = Store()
    store.ack_updated = False
    assert store.relay(lambda _: (store.event.delivery_id, store.event.payload_hash, "COMMITTED")).poll_once() == (
        "STALE_LEASE_ACK_IGNORED"
    )


def test_corrupt_payload_never_reaches_transport():
    store = Store()
    store.row["payload_hash"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="RELAY_IMMUTABLE_PAYLOAD_CONFLICT"):
        store.relay(lambda _: pytest.fail("transport must not run")).poll_once()


def test_no_ready_delivery_never_calls_transport():
    store = Store()
    store.row = None
    assert store.relay(lambda _: pytest.fail("transport must not run")).poll_once() == "NO_READY_DELIVERY"
