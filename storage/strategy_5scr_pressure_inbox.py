"""Idempotent Strategy 5S-CR inbox for durable pressure delivery."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Literal, cast

from analysis.strategy_5scr_pressure_to_tradeplan import (
    PressureEventNormalizer,
    PressureLifecycleAccumulator,
    PressureToTradePlanBuilder,
)
from contracts.strategy_5scr_pressure import Strategy5SCRMarketEvidence
from contracts.strategy_5scr_pressure_outbox import PressureInboxOutcome, PressureOutboxEnvelope
from core.metrics import PRESSURE_INBOX_DELIVERY_TOTAL
from storage.postgres_client import PostgresClient, pg_client
from storage.pressure_outbox import PressureOutboxIntegrityError, pressure_payload_hash

InboxDeliveryAction = Literal["PROCESS", "DUPLICATE", "INTEGRITY_VIOLATION"]
EvidenceProvider = Callable[[PressureOutboxEnvelope], Strategy5SCRMarketEvidence | None]


def decide_inbox_delivery(
    *,
    existing_hash: str,
    existing_status: str,
    incoming_hash: str,
) -> InboxDeliveryAction:
    """Resolve one at-least-once delivery without producing duplicate effects."""

    if existing_hash != incoming_hash:
        return "INTEGRITY_VIOLATION"
    if existing_status in {"WAITING_EVIDENCE", "PROCESSED", "INTEGRITY_VIOLATION"}:
        return "DUPLICATE"
    return "PROCESS"


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, TypeError):
        return default


class Strategy5SCRPressureProcessor:
    """Pure integration boundary from a durable envelope to tradeplan logic.

    Closed-candle evidence is deliberately optional in this milestone.  When
    it is unavailable, the inbox records ``WAITING_EVIDENCE`` and the outbox
    delivery is still safely acknowledged.  No execution signal is emitted.
    """

    def __init__(self, *, evidence_provider: EvidenceProvider | None = None) -> None:
        self._normalizer = PressureEventNormalizer(input_mode="LIVE")
        self._accumulator = PressureLifecycleAccumulator()
        self._builder = PressureToTradePlanBuilder()
        self._evidence_provider = evidence_provider

    def process(self, envelope: PressureOutboxEnvelope) -> PressureInboxOutcome:
        if pressure_payload_hash(envelope.payload) != envelope.payload_hash:
            raise PressureOutboxIntegrityError("PRESSURE_DELIVERY_PAYLOAD_HASH_MISMATCH")

        event = self._normalizer.normalize(envelope.payload)
        lifecycle, _duplicate = self._accumulator.ingest(event)
        if lifecycle.campaign_id != envelope.lifecycle_id:
            raise PressureOutboxIntegrityError("PRESSURE_DELIVERY_LIFECYCLE_MISMATCH")

        evidence = self._evidence_provider(envelope) if self._evidence_provider is not None else None
        if evidence is None:
            evidence = Strategy5SCRMarketEvidence(decision_at_utc=envelope.signal_valid_at)
        result = self._builder.build(lifecycle, evidence)
        if result.decision == "READY":
            assert result.tradeplan is not None
            return PressureInboxOutcome(
                event_id=envelope.event_id,
                lifecycle_id=envelope.lifecycle_id,
                status="PROCESSED",
                decision="READY",
                result_id=result.tradeplan.tradeplan_id,
                candidate_payload=result.candidate_payload,
            )
        if result.decision == "BLOCK":
            return PressureInboxOutcome(
                event_id=envelope.event_id,
                lifecycle_id=envelope.lifecycle_id,
                status="PROCESSED",
                decision="BLOCK",
                result_id=f"5scr-block:{envelope.event_id}",
                reasons=result.reasons,
            )
        return PressureInboxOutcome(
            event_id=envelope.event_id,
            lifecycle_id=envelope.lifecycle_id,
            status="WAITING_EVIDENCE",
            decision="DEFER",
            reasons=result.reasons,
        )


class Strategy5SCRInboxConsumer:
    """Atomically deduplicate and process pressure events in PostgreSQL."""

    def __init__(
        self,
        *,
        pg: PostgresClient | None = None,
        processor: Strategy5SCRPressureProcessor | None = None,
    ) -> None:
        self._pg = pg or pg_client
        self._processor = processor or Strategy5SCRPressureProcessor()

    async def consume(
        self,
        envelope: PressureOutboxEnvelope,
        *,
        process: bool = True,
    ) -> PressureInboxOutcome:
        async with self._pg.transaction() as conn:
            insert_result = await conn.execute(
                """
                INSERT INTO strategy_5scr_inbox (event_id, payload_hash, received_at, status)
                VALUES ($1, $2, NOW(), 'RECEIVED')
                ON CONFLICT (event_id) DO NOTHING
                """,
                envelope.event_id,
                envelope.payload_hash,
            )
            row = await conn.fetchrow(
                """
                SELECT event_id, payload_hash, status, result_id, last_error
                FROM strategy_5scr_inbox
                WHERE event_id = $1
                FOR UPDATE
                """,
                envelope.event_id,
            )
            if row is None:
                raise RuntimeError("STRATEGY_5SCR_INBOX_ROW_MISSING")

            existing_hash = str(_row_value(row, "payload_hash") or "")
            existing_status = str(_row_value(row, "status") or "RECEIVED")
            action = decide_inbox_delivery(
                existing_hash=existing_hash,
                existing_status=existing_status,
                incoming_hash=envelope.payload_hash,
            )
            if action == "INTEGRITY_VIOLATION":
                await conn.execute(
                    """
                    UPDATE strategy_5scr_inbox
                    SET status = 'INTEGRITY_VIOLATION',
                        last_error = 'EVENT_ID_REUSED_WITH_DIFFERENT_PAYLOAD_HASH'
                    WHERE event_id = $1
                    """,
                    envelope.event_id,
                )
                PRESSURE_INBOX_DELIVERY_TOTAL.labels(outcome="integrity_violation").inc()
                return PressureInboxOutcome(
                    event_id=envelope.event_id,
                    lifecycle_id=envelope.lifecycle_id,
                    status="INTEGRITY_VIOLATION",
                    reasons=("EVENT_ID_REUSED_WITH_DIFFERENT_PAYLOAD_HASH",),
                )
            if action == "DUPLICATE":
                PRESSURE_INBOX_DELIVERY_TOTAL.labels(outcome="duplicate").inc()
                reasons_raw = str(_row_value(row, "last_error") or "")
                reasons = tuple(item for item in reasons_raw.split("|") if item)
                status = cast(Any, existing_status)
                return PressureInboxOutcome(
                    event_id=envelope.event_id,
                    lifecycle_id=envelope.lifecycle_id,
                    status=status,
                    duplicate=True,
                    result_id=_row_value(row, "result_id"),
                    reasons=reasons,
                )

            if not process:
                PRESSURE_INBOX_DELIVERY_TOTAL.labels(outcome="received").inc()
                return PressureInboxOutcome(
                    event_id=envelope.event_id,
                    lifecycle_id=envelope.lifecycle_id,
                    status="RECEIVED",
                    duplicate=insert_result.endswith(" 0"),
                    decision="DEFER",
                    reasons=("STRATEGY_5SCR_PRESSURE_CONSUMER_DISABLED",),
                )

            await conn.execute(
                "UPDATE strategy_5scr_inbox SET status = 'PROCESSING', last_error = NULL WHERE event_id = $1",
                envelope.event_id,
            )
            outcome = self._processor.process(envelope)
            processed_at_sql = "NOW()" if outcome.status == "PROCESSED" else "NULL"
            await conn.execute(
                f"""
                UPDATE strategy_5scr_inbox
                SET status = $2, processed_at = {processed_at_sql}, result_id = $3,
                    last_error = $4
                WHERE event_id = $1
                """,
                envelope.event_id,
                outcome.status,
                outcome.result_id,
                "|".join(outcome.reasons)[:2000] or None,
            )
            metric_outcome = "processed" if outcome.status == "PROCESSED" else "waiting_evidence"
            PRESSURE_INBOX_DELIVERY_TOTAL.labels(outcome=metric_outcome).inc()
            return outcome


__all__ = [
    "EvidenceProvider",
    "Strategy5SCRInboxConsumer",
    "Strategy5SCRPressureProcessor",
    "decide_inbox_delivery",
]
