"""Producer allocation unit model; SQL transactions still require PostgreSQL acceptance."""

from types import SimpleNamespace

import pytest

from storage.strategy_5scr_activity_outbox import enqueue_activity_evaluation
from tests.test_activity_delivery_contract import delivery


class ProducerStore:
    def __init__(self, event):
        self.source = {
            "revision": event.source_revision,
            "report": {
                "provenance": {"binding_hash": event.scope.producer_binding_hash},
                "audit": {"evaluations": [event.evaluation.model_dump(mode="json")]},
            },
        }
        self.cursor = {"sequence": 0, "last_delivery_id": None}
        self.existing = None
        self.result = None
        self.writes = []

    def execute(self, sql, args):
        if sql.startswith("SELECT report"):
            self.result = self.source
        elif sql.startswith("SELECT sequence"):
            self.result = self.cursor
        elif sql.startswith("SELECT payload"):
            self.result = self.existing
        else:
            self.writes.append((sql, args))
            if sql.startswith("INSERT INTO public.pair_activity_delivery_outbox"):
                self.existing = {"payload": args[8]}
            if sql.startswith("UPDATE"):
                self.cursor = {"sequence": args[0], "last_delivery_id": args[1]}
            self.result = None
        return self

    def fetchone(self):
        return self.result


def enqueue(store, event):
    binding = SimpleNamespace(
        binding_hash=event.scope.producer_binding_hash,
        environment_class=event.scope.environment_class,
        ledger_id="fixture-ledger",
    )
    return enqueue_activity_evaluation(
        store,
        binding=binding,
        scope=event.scope,
        snapshot_id=event.source_snapshot_id,
        revision=event.source_revision,
        evaluation=event.evaluation,
    )


def test_first_allocation_and_duplicate_snapshot_preserve_original_envelope():
    event = delivery()
    store = ProducerStore(event)
    first = enqueue(store, event)
    assert first.activity_sequence == 1 and first.previous_delivery_id is None
    other_snapshot = delivery(source_snapshot_id="sha256:" + "7" * 64)
    assert enqueue(store, other_snapshot) == first
    assert len([sql for sql, _ in store.writes if sql.startswith("UPDATE")]) == 1


@pytest.mark.parametrize("corruption", ["missing", "revision", "provenance", "evaluation"])
def test_unbound_source_never_allocates(corruption):
    event = delivery()
    store = ProducerStore(event)
    if corruption == "missing":
        store.source = None
    elif corruption == "revision":
        store.source["revision"] = 999
    elif corruption == "provenance":
        store.source["report"]["provenance"] = {}
    else:
        store.source["report"]["audit"]["evaluations"] = []
    with pytest.raises(ValueError, match="DELIVERY_SOURCE_SNAPSHOT_MISMATCH"):
        enqueue(store, event)
    assert store.writes == []
