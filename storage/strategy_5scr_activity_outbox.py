"""Producer-owned delivery allocation. Caller owns the transaction and ledger lock.

No connection, commit, transport, lifecycle writer or execution authority lives here.
"""

from __future__ import annotations

import json

from psycopg.types.json import Jsonb

from contracts.strategy_5scr_activity_delivery import ActivityConsumerScopeV1, ActivityDeliveryV1, activity_delivery
from contracts.strategy_5scr_pair_activity import PairActivityEvaluationV31


def enqueue_activity_evaluation(connection, *, binding, scope, snapshot_id, revision, evaluation) -> ActivityDeliveryV1:
    scope = ActivityConsumerScopeV1.model_validate(scope.model_dump(mode="json"))
    evaluation = PairActivityEvaluationV31.model_validate(evaluation.model_dump(mode="json"))
    if scope.producer_binding_hash != binding.binding_hash or scope.environment_class != binding.environment_class:
        raise ValueError("DELIVERY_PRODUCER_BINDING_MISMATCH")
    # These checks bind the envelope to the actual transaction's source rows.
    source = connection.execute(
        "SELECT report,revision FROM public.pair_activity_snapshots_v31 WHERE ledger_id=%s AND snapshot_id=%s",
        (binding.ledger_id, snapshot_id),
    ).fetchone()
    payload = evaluation.model_dump(mode="json")
    if (
        source is None
        or source["revision"] != revision
        or source["report"].get("provenance", {}).get("binding_hash") != binding.binding_hash
        or payload not in source["report"].get("audit", {}).get("evaluations", [])
    ):
        raise ValueError("DELIVERY_SOURCE_SNAPSHOT_MISMATCH")
    key = (binding.ledger_id, scope.scope_hash, evaluation.activity_id)
    connection.execute(
        "INSERT INTO public.pair_activity_delivery_cursors_v1(ledger_id,scope_hash,activity_id) "
        "VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
        key,
    )
    cursor = connection.execute(
        "SELECT sequence,last_delivery_id FROM public.pair_activity_delivery_cursors_v1 "
        "WHERE ledger_id=%s AND scope_hash=%s AND activity_id=%s FOR UPDATE",
        key,
    ).fetchone()
    existing = connection.execute(
        "SELECT payload FROM public.pair_activity_delivery_outbox_v1 "
        "WHERE ledger_id=%s AND scope_hash=%s AND evaluation_id=%s",
        (binding.ledger_id, scope.scope_hash, evaluation.evaluation_id),
    ).fetchone()
    if existing:
        committed = ActivityDeliveryV1.model_validate_json(existing["payload"])
        if committed.scope != scope or committed.evaluation != evaluation:
            raise ValueError("DELIVERY_IMMUTABLE_EVALUATION_CONFLICT")
        # A repeated evaluation in another snapshot keeps its first envelope.
        return committed
    delivery = activity_delivery(
        scope=scope,
        source_snapshot_id=snapshot_id,
        source_revision=revision,
        activity_sequence=cursor["sequence"] + 1,
        previous_delivery_id=cursor["last_delivery_id"],
        evaluation=evaluation,
    )
    wire = json.dumps(delivery.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    connection.execute(
        "INSERT INTO public.pair_activity_delivery_outbox_v1 "
        "(delivery_id,ledger_id,scope_hash,activity_id,evaluation_id,snapshot_id,sequence,previous_delivery_id,payload,payload_hash,envelope) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            delivery.delivery_id,
            *key,
            evaluation.evaluation_id,
            snapshot_id,
            delivery.activity_sequence,
            delivery.previous_delivery_id,
            wire,
            delivery.payload_hash,
            Jsonb(delivery.model_dump(mode="json")),
        ),
    )
    connection.execute(
        "UPDATE public.pair_activity_delivery_cursors_v1 SET sequence=%s,last_delivery_id=%s "
        "WHERE ledger_id=%s AND scope_hash=%s AND activity_id=%s",
        (delivery.activity_sequence, delivery.delivery_id, *key),
    )
    return delivery
