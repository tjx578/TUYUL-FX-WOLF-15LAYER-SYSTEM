"""S03 delivery transaction owned by the existing lifecycle repository.

No default policy, source trust, owner takeover or network destination is chosen.
The DB trigger applies the same fence to legacy lifecycle writes.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from uuid import UUID, uuid4

from contracts.strategy_5scr_activity_delivery import (
    ActivityConsumerScopeV1,
    ActivityDeliveryV1,
    ActivityLifecycleEmissionLinkV1,
    classify_delivery_order,
    classify_delivery_replay,
    validate_existing_activity_owner,
)
from contracts.strategy_5scr_lifecycle_v2 import StrategyLifecycleV2


def decoded(value):
    return json.loads(value) if isinstance(value, str) else value


@dataclass(frozen=True)
class LifecycleOwnerFence:
    symbol: str
    scope_hash: str
    owner_id: str
    generation: int
    token: UUID

    def __post_init__(self):
        if (
            not re.fullmatch(r"[A-Z0-9._-]{3,32}", self.symbol)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", self.scope_hash)
            or not self.owner_id.strip()
            or type(self.generation) is not int
            or self.generation < 1
            or not isinstance(self.token, UUID)
        ):
            raise ValueError("OWNER_FENCE_BINDING_INVALID")


async def lock_symbol(connection, symbol):
    # Both the advisory lock and owner-token GUC are transaction scoped. In
    # autocommit they expire before the subsequent owner read/write can use them.
    if connection.is_in_transaction() is not True:
        raise ValueError("LIFECYCLE_OWNER_TRANSACTION_REQUIRED")
    await connection.execute("SELECT pg_advisory_xact_lock(hashtextextended('5scr-owner:' || $1::text,0))", symbol)


async def transfer_owner(connection, *, symbol, scope: ActivityConsumerScopeV1, expected_generation: int):
    """Explicit CAS handover in a caller-owned transaction, never auto-acquire."""
    scope = ActivityConsumerScopeV1.model_validate(scope.model_dump(mode="json"))
    if not isinstance(symbol, str) or not re.fullmatch(r"[A-Z0-9._-]{3,32}", symbol):
        raise ValueError("OWNER_SYMBOL_REQUIRED")
    if type(expected_generation) is not int or expected_generation < 0:
        raise ValueError("OWNER_GENERATION_REQUIRED")
    await lock_symbol(connection, symbol)
    row = await connection.fetchrow(
        "SELECT * FROM public.strategy_5scr_owner_fences_v1 WHERE symbol=$1 FOR UPDATE", symbol
    )
    if (row["generation"] if row else 0) != expected_generation:
        raise ValueError("OWNER_HANDOVER_CONFLICT")
    token = uuid4()
    generation = expected_generation + 1
    await connection.execute(
        "INSERT INTO public.strategy_5scr_owner_fences_v1(symbol,scope_hash,owner_id,generation,token) "
        "VALUES($1,$2,$3,$4,$5) ON CONFLICT(symbol) DO UPDATE SET scope_hash=$2,owner_id=$3,generation=$4,token=$5",
        symbol,
        scope.scope_hash,
        scope.lifecycle_owner_id,
        generation,
        token,
    )
    return LifecycleOwnerFence(symbol, scope.scope_hash, scope.lifecycle_owner_id, generation, token)


async def bind_owner(connection, fence: LifecycleOwnerFence):
    if connection.is_in_transaction() is not True:
        raise ValueError("LIFECYCLE_OWNER_TRANSACTION_REQUIRED")
    row = await connection.fetchrow(
        "SELECT public.bind_5scr_lifecycle_owner_v1($1,$2,$3,$4,$5) AS bound",
        fence.symbol,
        fence.scope_hash,
        fence.owner_id,
        fence.generation,
        fence.token,
    )
    if row is None or row["bound"] is not True:
        raise ValueError("STALE_OR_UNBOUND_LIFECYCLE_OWNER")


class ActivityLifecycleConsumer:
    def __init__(self, *, owner, scope, fence, policy_hash, select_lifecycle, validate_source):
        self.owner = owner
        self.scope = ActivityConsumerScopeV1.model_validate(scope.model_dump(mode="json"))
        self.fence = fence
        if (
            fence.scope_hash != self.scope.scope_hash
            or fence.owner_id != self.scope.lifecycle_owner_id
            or policy_hash != self.scope.lifecycle_policy_hash
            or not callable(select_lifecycle)
            or not callable(validate_source)
        ):
            raise ValueError("CONSUMER_POLICY_OR_OWNER_UNBOUND")
        self.select_lifecycle = select_lifecycle
        self.validate_source = validate_source

    async def consume(self, payload: bytes):
        event = ActivityDeliveryV1.model_validate_json(payload)
        if event.scope != self.scope or event.evaluation.symbol != self.fence.symbol:
            raise ValueError("CONSUMER_SCOPE_MISMATCH")
        # Authenticity is checked by transport before this method; provenance
        # verification is independently supplied by the configured source reader.
        async with self.owner._pg.transaction() as c:
            await bind_owner(c, self.fence)
            prior = await c.fetchrow(
                "SELECT payload FROM public.strategy_5scr_activity_inbox_v1 WHERE delivery_id=$1", event.delivery_id
            )
            replay = classify_delivery_replay(
                event, ActivityDeliveryV1.model_validate(decoded(prior["payload"])) if prior else None
            )
            if replay == "QUARANTINE_PAYLOAD_CONFLICT":
                await c.execute(
                    "INSERT INTO public.strategy_5scr_activity_conflicts_v1(delivery_id,payload_hash,payload) "
                    "VALUES($1,$2,$3::jsonb) ON CONFLICT DO NOTHING",
                    event.delivery_id,
                    event.payload_hash,
                    event.model_dump_json(),
                )
                outcome = replay
            elif replay == "DUPLICATE_NO_EFFECT":
                outcome = replay
            else:
                if self.validate_source(event) is not True:
                    raise ValueError("CONSUMER_SOURCE_NOT_VERIFIED")
                outcome = await self._apply(c, event)
        # This return happens only after transaction.__aexit__ has committed.
        return event.delivery_id, event.payload_hash, outcome

    async def _apply(self, c, event):
        key = (self.scope.scope_hash, event.evaluation.activity_id)
        cursor = await c.fetchrow(
            "SELECT payload FROM public.strategy_5scr_activity_consumer_cursors_v1 WHERE scope_hash=$1 AND activity_id=$2",
            *key,
        )
        order = classify_delivery_order(
            event, ActivityDeliveryV1.model_validate(decoded(cursor["payload"])) if cursor else None
        )
        if order != "NEXT_REQUIRES_OWNER_VALIDATION":
            return order
        now = await c.fetchval("SELECT clock_timestamp()")
        evaluation = event.evaluation
        if evaluation.evaluated_at_utc > now:
            return "FUTURE_SOURCE_EVALUATION"
        if evaluation.decision == "GRANTED" and now >= evaluation.valid_until_utc:
            return "EXPIRED_UNSEEN_DELIVERY"
        mapping = await c.fetchrow(
            "SELECT payload FROM public.strategy_5scr_activity_mappings_v1 WHERE consumer_scope_id=$1 AND activity_id=$2",
            self.scope.consumer_scope_id,
            evaluation.activity_id,
        )
        previous = ActivityLifecycleEmissionLinkV1.model_validate(decoded(mapping["payload"])) if mapping else None
        if evaluation.decision in {"SUSPENDED", "RECONCILIATION_REQUIRED"} and previous is None:
            return "ACTIVITY_MAPPING_REQUIRED"
        if evaluation.decision != "PENDING":
            rows = await c.fetch(
                "SELECT * FROM public.strategy_5scr_analysis_lifecycles_v2 WHERE symbol=$1 ORDER BY opened_at LIMIT 1001 FOR UPDATE",
                self.fence.symbol,
            )
            if len(rows) > 1000:
                raise ValueError("OWNER_RECOVERY_CAPACITY_EXCEEDED")
            # A pure policy receives fresh database rows; no process reducer state
            # is advanced before commit or retained after rollback.
            lifecycle = self.select_lifecycle(event, tuple(dict(row) for row in rows), previous)
            lifecycle = StrategyLifecycleV2.model_validate(lifecycle.model_dump(mode="json"))
            if lifecycle.symbol != self.fence.symbol or lifecycle.last_event_at_utc > now:
                raise ValueError("OWNER_LIFECYCLE_SCOPE_MISMATCH")
            link = ActivityLifecycleEmissionLinkV1(
                delivery=event,
                strategy_lifecycle_id=lifecycle.strategy_lifecycle_id,
                material_state_hash=lifecycle.material_state_hash,
                emission_purpose={
                    "GRANTED": "ACTIVITY_ATTACHED",
                    "SUSPENDED": "ACTIVITY_SUSPENDED",
                    "RECONCILIATION_REQUIRED": "ACTIVITY_RECONCILIATION",
                }[evaluation.decision],
            )
            if previous:
                validate_existing_activity_owner(previous, link)
            await self.owner._lifecycles.upsert_lifecycle(lifecycle, _executor=c)
            await c.execute(
                "INSERT INTO public.strategy_5scr_activity_mappings_v1(consumer_scope_id,activity_id,scope_hash,lifecycle_id,payload) "
                "VALUES($1,$2,$3,$4,$5::jsonb) ON CONFLICT(consumer_scope_id,activity_id) DO UPDATE SET payload=$5::jsonb",
                self.scope.consumer_scope_id,
                evaluation.activity_id,
                self.scope.scope_hash,
                lifecycle.strategy_lifecycle_id,
                link.model_dump_json(),
            )
            # Emission identity excludes the delivery. Keep the first payload for
            # unchanged material state; a new delivery is not a new emission.
            await c.execute(
                "INSERT INTO public.strategy_5scr_activity_emissions_v1(emission_id,lifecycle_id,payload) "
                "VALUES($1,$2,$3::jsonb) ON CONFLICT DO NOTHING",
                link.analysis_emission_id,
                lifecycle.strategy_lifecycle_id,
                link.model_dump_json(),
            )
            stored_emission = await c.fetchrow(
                "SELECT payload FROM public.strategy_5scr_activity_emissions_v1 WHERE emission_id=$1",
                link.analysis_emission_id,
            )
            stored_link = ActivityLifecycleEmissionLinkV1.model_validate(decoded(stored_emission["payload"]))
            if (
                stored_link.analysis_emission_id != link.analysis_emission_id
                or stored_link.strategy_lifecycle_id != link.strategy_lifecycle_id
                or stored_link.material_state_hash != link.material_state_hash
                or stored_link.emission_purpose != link.emission_purpose
                or stored_link.delivery.scope.scope_hash != link.delivery.scope.scope_hash
            ):
                raise ValueError("ANALYSIS_EMISSION_IDENTITY_CONFLICT")
        await c.execute(
            "INSERT INTO public.strategy_5scr_activity_inbox_v1(delivery_id,payload_hash,payload) VALUES($1,$2,$3::jsonb)",
            event.delivery_id,
            event.payload_hash,
            event.model_dump_json(),
        )
        await c.execute(
            "INSERT INTO public.strategy_5scr_activity_consumer_cursors_v1(scope_hash,activity_id,payload) "
            "VALUES($1,$2,$3::jsonb) ON CONFLICT(scope_hash,activity_id) DO UPDATE SET payload=$3::jsonb",
            *key,
            event.model_dump_json(),
        )
        return "COMMITTED"
