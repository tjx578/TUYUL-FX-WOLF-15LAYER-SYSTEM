"""Post-inbox Strategy 5S-CR closed-candle evidence worker.

The dispatcher transaction stops at ``WAITING_EVIDENCE``.  This worker reads
those durable rows, builds an as-of candle snapshot outside any inbox lock,
and commits only the deterministic non-executable outcome.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, cast

from loguru import logger

from analysis.strategy_5scr_closed_candle_provider import (
    ClosedCandleEvidenceError,
    EvidenceMode,
    Strategy5SCRClosedCandleEvidenceProvider,
)
from analysis.strategy_5scr_m1_outcome import tradeplan_from_candidate_payload
from contracts.canonical_candle import as_utc
from contracts.strategy_5scr_pressure import Strategy5SCRMarketEvidence
from contracts.strategy_5scr_pressure_outbox import (
    PressureInboxOutcome,
    PressureOutboxEnvelope,
)
from storage.postgres_client import PostgresClient, pg_client
from storage.pressure_outbox import pressure_envelope_from_row
from storage.strategy_5scr_candle_store import PostgresClosedCandleStore
from storage.strategy_5scr_pressure_inbox import Strategy5SCRPressureProcessor

_SELECT_COLUMNS = """
    outbox.id, outbox.event_id, outbox.event_type, outbox.schema_version,
    outbox.symbol, outbox.lifecycle_id, outbox.lifecycle_sequence,
    outbox.source_clean_block_id, outbox.source_watch_id,
    outbox.signal_valid_at, outbox.payload, outbox.payload_hash,
    outbox.status, outbox.attempt_count, outbox.available_at,
    outbox.locked_at, outbox.lease_expires_at, outbox.published_at,
    outbox.created_at
"""


def _enabled(value: str | None) -> bool:
    return str(value or "false").strip().lower() == "true"


def _row_value(row: Any, key: str) -> Any:
    if isinstance(row, Mapping):
        return row.get(key)
    try:
        return row[key]
    except (KeyError, TypeError):
        return None


def _row_datetime(row: object, key: str) -> datetime:
    value = _row_value(row, key)
    if not isinstance(value, datetime):
        raise RuntimeError(f"STRATEGY_5SCR_EVIDENCE_ROW_{key.upper()}_INVALID")
    return value


@dataclass(frozen=True)
class EvidenceRuntimeConfig:
    enabled: bool = False
    live_allowed: bool = False
    activation_requested: bool = False
    mode: str = "SHADOW"
    provider: str = "finnhub"
    execution_enabled: bool = False
    risk_reservation_enabled: bool = False
    trade_outbox_write_enabled: bool = False
    ea_command_delivery_enabled: bool = False
    mt5_order_send_enabled: bool = False
    poll_seconds: float = 5.0
    batch_size: int = 25
    max_attempts: int = 8

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> EvidenceRuntimeConfig:
        source = os.environ if environ is None else environ
        requested_enabled = _enabled(source.get("STRATEGY_5SCR_EVIDENCE_ENABLED"))
        live_allowed = _enabled(source.get("STRATEGY_5SCR_EVIDENCE_LIVE_ALLOWED"))
        config = cls(
            # Two-key activation prevents a stale Railway flag from reviving
            # live evidence while canonical storage/lifecycle work is pending.
            enabled=requested_enabled and live_allowed,
            live_allowed=live_allowed,
            activation_requested=requested_enabled,
            mode=str(source.get("STRATEGY_5SCR_EVIDENCE_MODE") or "SHADOW").strip().upper(),
            provider=str(source.get("STRATEGY_5SCR_EVIDENCE_PROVIDER") or "finnhub").strip().lower(),
            execution_enabled=_enabled(source.get("STRATEGY_5SCR_EXECUTION_ENABLED")),
            risk_reservation_enabled=_enabled(source.get("RISK_RESERVATION_ENABLED")),
            trade_outbox_write_enabled=_enabled(source.get("TRADE_OUTBOX_WRITE_ENABLED")),
            ea_command_delivery_enabled=_enabled(source.get("EA_COMMAND_DELIVERY_ENABLED")),
            mt5_order_send_enabled=_enabled(source.get("MT5_ORDER_SEND_ENABLED")),
            poll_seconds=max(
                0.1,
                float(source.get("STRATEGY_5SCR_EVIDENCE_POLL_SECONDS") or "5"),
            ),
            batch_size=max(
                1,
                int(source.get("STRATEGY_5SCR_EVIDENCE_BATCH_SIZE") or "25"),
            ),
            max_attempts=max(
                1,
                int(source.get("STRATEGY_5SCR_EVIDENCE_MAX_ATTEMPTS") or "8"),
            ),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.mode not in {"SHADOW", "REPLAY", "PRODUCTION_OBSERVE"}:
            raise RuntimeError(f"STRATEGY_5SCR_EVIDENCE_MODE_INVALID:{self.mode}")
        if self.provider != "finnhub":
            raise RuntimeError(f"STRATEGY_5SCR_EVIDENCE_PROVIDER_UNSUPPORTED:{self.provider}")
        if self.enabled and self.mode not in {"SHADOW", "PRODUCTION_OBSERVE"}:
            raise RuntimeError("LIVE_EVIDENCE_WORKER_REQUIRES_OBSERVE_MODE")
        execution_flags = (
            self.execution_enabled,
            self.risk_reservation_enabled,
            self.trade_outbox_write_enabled,
            self.ea_command_delivery_enabled,
            self.mt5_order_send_enabled,
        )
        if self.activation_requested and any(execution_flags):
            raise RuntimeError("STRATEGY_5SCR_EVIDENCE_REQUIRES_EXECUTION_OFF")


@dataclass(frozen=True)
class EvidenceWorkItem:
    envelope: PressureOutboxEnvelope
    lifecycle_anchor_at: datetime
    evidence_attempt_count: int = 0


class EvidenceRepository(Protocol):
    async def load_waiting(self, *, limit: int) -> Sequence[EvidenceWorkItem]: ...

    async def record_outcome(
        self,
        envelope: PressureOutboxEnvelope,
        outcome: PressureInboxOutcome,
        *,
        evidence_snapshot: Strategy5SCRMarketEvidence,
    ) -> bool: ...

    async def record_failure(
        self,
        envelope: PressureOutboxEnvelope,
        *,
        error: str,
        retry_delay_seconds: float,
        max_attempts: int,
    ) -> bool: ...


class PostgresEvidenceRepository:
    """Crash-safe waiting-row reader and compare-and-set outcome writer."""

    def __init__(self, *, pg: PostgresClient | None = None) -> None:
        self._pg = pg or pg_client

    async def load_waiting(self, *, limit: int) -> Sequence[EvidenceWorkItem]:
        if not self._pg.is_available:
            return ()
        rows = await self._pg.fetch(
            f"""
            SELECT {_SELECT_COLUMNS},
                   lifecycle.anchor_at AS lifecycle_anchor_at,
                   inbox.evidence_attempt_count AS evidence_attempt_count
            FROM pressure_outbox AS outbox
            JOIN strategy_5scr_inbox AS inbox
              ON inbox.event_id = outbox.event_id
            JOIN strategy_5scr_lifecycles AS lifecycle
              ON lifecycle.lifecycle_id = outbox.lifecycle_id
            WHERE outbox.status = 'PUBLISHED'
              AND inbox.status = 'WAITING_EVIDENCE'
              AND inbox.evidence_next_attempt_at <= NOW()
            ORDER BY outbox.signal_valid_at, outbox.lifecycle_id, outbox.lifecycle_sequence
            LIMIT $1
            """,
            max(1, int(limit)),
        )
        return tuple(
            EvidenceWorkItem(
                envelope=pressure_envelope_from_row(row),
                lifecycle_anchor_at=_row_datetime(row, "lifecycle_anchor_at"),
                evidence_attempt_count=int(_row_value(row, "evidence_attempt_count") or 0),
            )
            for row in rows
        )

    async def record_outcome(
        self,
        envelope: PressureOutboxEnvelope,
        outcome: PressureInboxOutcome,
        *,
        evidence_snapshot: Strategy5SCRMarketEvidence,
    ) -> bool:
        if evidence_snapshot.evidence_snapshot_id is None:
            raise RuntimeError("STRATEGY_5SCR_EVIDENCE_SNAPSHOT_ID_REQUIRED")
        snapshot_payload = evidence_snapshot.model_dump(mode="json")
        encoded = json.dumps(
            snapshot_payload,
            sort_keys=True,
            separators=(",", ":"),
        )
        snapshot_hash = hashlib.sha256(encoded.encode()).hexdigest()
        candidate_payload = outcome.candidate_payload
        candidate_encoded: str | None = None
        candidate_hash: str | None = None
        tradeplan = None
        if candidate_payload is not None:
            tradeplan = tradeplan_from_candidate_payload(candidate_payload)
            if candidate_payload.get("evidence_snapshot_id") != evidence_snapshot.evidence_snapshot_id:
                raise RuntimeError("STRATEGY_5SCR_CANDIDATE_EVIDENCE_MISMATCH")
            candidate_encoded = json.dumps(
                candidate_payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                default=str,
            )
            candidate_hash = hashlib.sha256(candidate_encoded.encode()).hexdigest()
        async with self._pg.transaction() as conn:
            await conn.execute(
                """
                INSERT INTO strategy_5scr_evidence_snapshots (
                    snapshot_id, lifecycle_id, event_id, decision_at,
                    lifecycle_anchor_at, payload, payload_hash
                )
                SELECT $1, $2, $3, $4, lifecycle.anchor_at, $5::jsonb, $6
                FROM strategy_5scr_lifecycles AS lifecycle
                WHERE lifecycle.lifecycle_id = $2
                ON CONFLICT (snapshot_id) DO NOTHING
                """,
                evidence_snapshot.evidence_snapshot_id,
                envelope.lifecycle_id,
                envelope.event_id,
                evidence_snapshot.decision_at_utc,
                encoded,
                snapshot_hash,
            )
            stored = await conn.fetchrow(
                """
                SELECT payload_hash
                FROM strategy_5scr_evidence_snapshots
                WHERE snapshot_id = $1
                """,
                evidence_snapshot.evidence_snapshot_id,
            )
            if stored is None or str(_row_value(stored, "payload_hash") or "") != snapshot_hash:
                raise RuntimeError("STRATEGY_5SCR_EVIDENCE_SNAPSHOT_IMMUTABILITY_VIOLATION")
            if tradeplan is not None and candidate_encoded is not None and candidate_hash is not None:
                await conn.execute(
                    """
                    INSERT INTO strategy_5scr_tradeplan_candidates (
                        tradeplan_id, lifecycle_id, event_id, evidence_snapshot_id,
                        symbol, direction, decision_at, payload, payload_hash
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9)
                    ON CONFLICT (tradeplan_id) DO NOTHING
                    """,
                    tradeplan.tradeplan_id,
                    envelope.lifecycle_id,
                    envelope.event_id,
                    evidence_snapshot.evidence_snapshot_id,
                    tradeplan.symbol,
                    tradeplan.direction,
                    tradeplan.decision_at_utc,
                    candidate_encoded,
                    candidate_hash,
                )
                stored_candidate = await conn.fetchrow(
                    """
                    SELECT payload_hash
                    FROM strategy_5scr_tradeplan_candidates
                    WHERE tradeplan_id = $1
                    """,
                    tradeplan.tradeplan_id,
                )
                if (
                    stored_candidate is None
                    or str(_row_value(stored_candidate, "payload_hash") or "") != candidate_hash
                ):
                    raise RuntimeError("STRATEGY_5SCR_CANDIDATE_IMMUTABILITY_VIOLATION")
            result = await conn.execute(
                """
            UPDATE strategy_5scr_inbox
            SET status = $2,
                processed_at = CASE WHEN $2 = 'PROCESSED' THEN NOW() ELSE NULL END,
                result_id = $3,
                result_payload = $4::jsonb,
                evidence_snapshot_id = $5,
                evidence_attempt_count = evidence_attempt_count + 1,
                evidence_last_attempt_at = NOW(),
                evidence_next_attempt_at = NOW(),
                last_error = $6
            WHERE event_id = $1
              AND status = 'WAITING_EVIDENCE'
            """,
                envelope.event_id,
                outcome.status,
                outcome.result_id,
                (
                    json.dumps(
                        outcome.candidate_payload,
                        separators=(",", ":"),
                        ensure_ascii=False,
                        default=str,
                    )
                    if outcome.candidate_payload is not None
                    else None
                ),
                evidence_snapshot.evidence_snapshot_id,
                "|".join(outcome.reasons)[:2000] or None,
            )
        return bool(result.endswith(" 1"))

    async def record_failure(
        self,
        envelope: PressureOutboxEnvelope,
        *,
        error: str,
        retry_delay_seconds: float,
        max_attempts: int,
    ) -> bool:
        result = await self._pg.execute(
            """
            UPDATE strategy_5scr_inbox
            SET evidence_attempt_count = evidence_attempt_count + 1,
                evidence_last_attempt_at = NOW(),
                evidence_next_attempt_at = NOW() + ($3 * INTERVAL '1 second'),
                status = CASE
                    WHEN evidence_attempt_count + 1 >= $4 THEN 'FAILED'
                    ELSE status
                END,
                last_error = $2
            WHERE event_id = $1
              AND status = 'WAITING_EVIDENCE'
            """,
            envelope.event_id,
            error[:2000],
            max(0.1, float(retry_delay_seconds)),
            max(1, int(max_attempts)),
        )
        return bool(result.endswith(" 1"))


class EvidenceProvider(Protocol):
    async def provide(
        self,
        *,
        symbol: str,
        decision_at_utc: datetime,
        lifecycle_anchor_utc: datetime,
    ) -> Strategy5SCRMarketEvidence | None: ...


class Strategy5SCREvidenceWorker:
    """Poll and resolve durable ``WAITING_EVIDENCE`` rows."""

    def __init__(
        self,
        *,
        repository: EvidenceRepository,
        provider: EvidenceProvider,
        processor: Strategy5SCRPressureProcessor | None = None,
        config: EvidenceRuntimeConfig | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._provider = provider
        self._processor = processor or Strategy5SCRPressureProcessor()
        self._config = config or EvidenceRuntimeConfig.from_env()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._running = False

    def _retry_delay(
        self,
        *,
        now: datetime,
        attempt: int,
        reasons: Sequence[str] = (),
    ) -> float:
        interval_seconds = 0
        if any("H1_" in reason for reason in reasons):
            interval_seconds = 3600
        elif any("M15_" in reason or "REJECTION_CANDLE" in reason for reason in reasons):
            interval_seconds = 900
        elif any("M1_" in reason for reason in reasons):
            interval_seconds = 180
        if interval_seconds:
            epoch = int(now.timestamp())
            return float(interval_seconds - (epoch % interval_seconds) + 2)
        return float(
            min(
                3600.0,
                self._config.poll_seconds * (2**attempt),
            )
        )

    async def process_once(self) -> int:
        if not self._config.enabled:
            return 0
        work_items = await self._repository.load_waiting(limit=self._config.batch_size)
        processed = 0
        for loaded_item in work_items:
            work_item = (
                loaded_item
                if isinstance(loaded_item, EvidenceWorkItem)
                else EvidenceWorkItem(
                    envelope=loaded_item,
                    lifecycle_anchor_at=loaded_item.signal_valid_at,
                )
            )
            envelope = work_item.envelope
            evaluation_at = as_utc(self._clock(), "evidence evaluation clock")
            retry_delay = self._retry_delay(
                now=evaluation_at,
                attempt=work_item.evidence_attempt_count,
            )
            try:
                expiry_raw = envelope.payload.get("raw_direction_expires_at_utc")
                if isinstance(expiry_raw, str):
                    expiry = as_utc(
                        datetime.fromisoformat(expiry_raw.replace("Z", "+00:00")),
                        "raw_direction_expires_at_utc",
                    )
                    if evaluation_at > expiry:
                        await self._repository.record_failure(
                            envelope,
                            error="STRATEGY_5SCR_PRESSURE_EXPIRED_BEFORE_EVIDENCE",
                            retry_delay_seconds=retry_delay,
                            max_attempts=1,
                        )
                        processed += 1
                        continue
                evidence = await self._provider.provide(
                    symbol=envelope.symbol,
                    decision_at_utc=evaluation_at,
                    lifecycle_anchor_utc=work_item.lifecycle_anchor_at,
                )
                if evidence is None:
                    await self._repository.record_failure(
                        envelope,
                        error="STRATEGY_5SCR_CLOSED_CANDLE_EVIDENCE_INCOMPLETE",
                        retry_delay_seconds=retry_delay,
                        max_attempts=self._config.max_attempts,
                    )
                    processed += 1
                    continue
                outcome = self._processor.process(envelope, evidence=evidence)
                if outcome.decision == "DEFER":
                    await self._repository.record_failure(
                        envelope,
                        error="|".join(outcome.reasons) or "STRATEGY_5SCR_CLOSED_CANDLE_EVIDENCE_INCOMPLETE",
                        retry_delay_seconds=self._retry_delay(
                            now=evaluation_at,
                            attempt=work_item.evidence_attempt_count,
                            reasons=outcome.reasons,
                        ),
                        max_attempts=self._config.max_attempts,
                    )
                    processed += 1
                    continue
                await self._repository.record_outcome(
                    envelope,
                    outcome,
                    evidence_snapshot=evidence,
                )
                processed += 1
            except ClosedCandleEvidenceError as exc:
                await self._repository.record_failure(
                    envelope,
                    error=str(exc),
                    retry_delay_seconds=retry_delay,
                    max_attempts=self._config.max_attempts,
                )
                processed += 1
            except Exception as exc:
                # The durable row remains WAITING_EVIDENCE.  A crash or
                # transient store failure therefore retries without losing the
                # event or publishing a partial candidate.
                await self._repository.record_failure(
                    envelope,
                    error=f"STRATEGY_5SCR_EVIDENCE_WORKER_ERROR:{type(exc).__name__}",
                    retry_delay_seconds=retry_delay,
                    max_attempts=self._config.max_attempts,
                )
                logger.exception(
                    "5S-CR evidence worker failed event={} symbol={}",
                    envelope.event_id,
                    envelope.symbol,
                )
                processed += 1
        return processed

    async def run(self) -> None:
        self._running = True
        while self._running:
            await self.process_once()
            # A frozen decision can remain incomplete until its source candles
            # are persisted.  Always pace retries to avoid a hot loop over the
            # same WAITING_EVIDENCE rows.
            await asyncio.sleep(self._config.poll_seconds)

    async def stop(self) -> None:
        self._running = False


def build_evidence_worker(
    *,
    pg: PostgresClient | None = None,
    config: EvidenceRuntimeConfig | None = None,
) -> Strategy5SCREvidenceWorker:
    resolved_pg = pg or pg_client
    resolved_config = config or EvidenceRuntimeConfig.from_env()
    store = PostgresClosedCandleStore(pg=resolved_pg)
    provider = Strategy5SCRClosedCandleEvidenceProvider(
        store,
        mode=cast(EvidenceMode, resolved_config.mode),
    )
    repository = PostgresEvidenceRepository(pg=resolved_pg)
    return Strategy5SCREvidenceWorker(
        repository=repository,
        provider=provider,
        config=resolved_config,
    )


__all__ = [
    "EvidenceWorkItem",
    "EvidenceRuntimeConfig",
    "PostgresEvidenceRepository",
    "Strategy5SCREvidenceWorker",
    "build_evidence_worker",
]
