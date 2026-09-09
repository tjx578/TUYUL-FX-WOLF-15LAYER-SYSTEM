"""Bounded at-least-once S03 relay; no lifecycle or execution writer.

The injected transport must authenticate the destination and return an ACK only
after its owner transaction commits. No default destination or policy is assumed.
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from contracts.strategy_5scr_activity_delivery import ActivityConsumerScopeV1, ActivityDeliveryV1


class ActivityDeliveryRelay:
    def __init__(
        self,
        *,
        connect: Callable,
        ledger_id: str,
        scope: ActivityConsumerScopeV1,
        send: Callable[[bytes], tuple[str, str, str]],
        lease_seconds: int,
    ) -> None:
        if type(lease_seconds) is not int or lease_seconds <= 0 or not ledger_id.strip():
            raise ValueError("RELAY_LEASE_AND_LEDGER_REQUIRED")
        self._connect = connect
        self._ledger_id = ledger_id
        self._scope = ActivityConsumerScopeV1.model_validate(scope.model_dump(mode="json"))
        self._send = send
        self._lease_seconds = lease_seconds

    def poll_once(self) -> str:
        token = uuid4()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT o.delivery_id,o.payload,o.payload_hash FROM public.pair_activity_delivery_outbox_v1 o "
                "WHERE o.ledger_id=%s AND o.scope_hash=%s AND NOT o.acknowledged "
                "AND (o.lease_until IS NULL OR o.lease_until<=clock_timestamp()) "
                "AND (o.previous_delivery_id IS NULL OR EXISTS "
                "(SELECT 1 FROM public.pair_activity_delivery_outbox_v1 p "
                "WHERE p.delivery_id=o.previous_delivery_id AND p.acknowledged)) "
                "ORDER BY o.activity_id,o.sequence LIMIT 1 FOR UPDATE OF o SKIP LOCKED",
                (self._ledger_id, self._scope.scope_hash),
            ).fetchone()
            if row is None:
                return "NO_READY_DELIVERY"
            delivery = ActivityDeliveryV1.model_validate_json(row["payload"])
            if (
                delivery.delivery_id != row["delivery_id"]
                or delivery.payload_hash != row["payload_hash"]
                or delivery.scope != self._scope
            ):
                raise ValueError("RELAY_IMMUTABLE_PAYLOAD_CONFLICT")
            connection.execute(
                "UPDATE public.pair_activity_delivery_outbox_v1 SET lease_token=%s,"
                "lease_until=clock_timestamp()+(%s * interval '1 second'),attempts=attempts+1 "
                "WHERE delivery_id=%s",
                (token, self._lease_seconds, delivery.delivery_id),
            )
        # Remote I/O deliberately happens after the local lease commit. An exception
        # leaves the same bytes retryable after the bound lease; no replacement ID.
        ack = self._send(row["payload"].encode("utf-8"))
        if ack not in (
            (delivery.delivery_id, delivery.payload_hash, "COMMITTED"),
            (delivery.delivery_id, delivery.payload_hash, "DUPLICATE_NO_EFFECT"),
        ):
            return "UNACKNOWLEDGED"
        with self._connect() as connection:
            updated = connection.execute(
                "UPDATE public.pair_activity_delivery_outbox_v1 SET acknowledged=true,lease_token=NULL,lease_until=NULL "
                "WHERE delivery_id=%s AND lease_token=%s AND NOT acknowledged "
                "AND lease_until>clock_timestamp() RETURNING delivery_id",
                (delivery.delivery_id, token),
            ).fetchone()
        return "ACKNOWLEDGED" if updated else "STALE_LEASE_ACK_IGNORED"
