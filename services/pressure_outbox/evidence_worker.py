"""Post-inbox Strategy 5S-CR closed-candle evidence worker.

The dispatcher transaction stops at ``WAITING_EVIDENCE``.  This worker reads
those durable rows, builds an as-of candle snapshot outside any inbox lock,
and commits only the deterministic non-executable outcome.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from loguru import logger

from analysis.strategy_5scr_closed_candle_provider import (
    ClosedCandleEvidenceError,
    Strategy5SCRClosedCandleEvidenceProvider,
)
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


@dataclass(frozen=True)
class EvidenceRuntimeConfig:
    enabled: bool = False
    live_allowed: bool = False
    activation_requested: bool = False
    mode: str = "SHADOW"
    provider: str = "finnhub"
    execution_enabled: bool = False
    poll_seconds: float = 5.0
    batch_size: int = 25

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
            poll_seconds=max(
                0.1,
                float(source.get("STRATEGY_5SCR_EVIDENCE_POLL_SECONDS") or "5"),
            ),
            batch_size=max(
                1,
                int(source.get("STRATEGY_5SCR_EVIDENCE_BATCH_SIZE") or "25"),
            ),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.mode not in {"SHADOW", "REPLAY"}:
            raise RuntimeError(f"STRATEGY_5SCR_EVIDENCE_MODE_INVALID:{self.mode}")
        if self.provider != "finnhub":
            raise RuntimeError(f"STRATEGY_5SCR_EVIDENCE_PROVIDER_UNSUPPORTED:{self.provider}")
        if self.enabled and self.mode != "SHADOW":
            raise RuntimeError("LIVE_EVIDENCE_WORKER_REQUIRES_SHADOW_MODE")
        if self.activation_requested and self.execution_enabled:
            raise RuntimeError("STRATEGY_5SCR_EVIDENCE_REQUIRES_EXECUTION_OFF")


class EvidenceRepository(Protocol):
    async def load_waiting(self, *, limit: int) -> Sequence[PressureOutboxEnvelope]: ...

    async def record_outcome(
        self,
        envelope: PressureOutboxEnvelope,
        outcome: PressureInboxOutcome,
        *,
        evidence_snapshot_id: str | None,
    ) -> bool: ...

    async def record_failure(
        self,
        envelope: PressureOutboxEnvelope,
        *,
        error: str,
    ) -> bool: ...


class PostgresEvidenceRepository:
    """Crash-safe waiting-row reader and compare-and-set outcome writer."""

    def __init__(self, *, pg: PostgresClient | None = None) -> None:
        self._pg = pg or pg_client

    async def load_waiting(self, *, limit: int) -> Sequence[PressureOutboxEnvelope]:
        if not self._pg.is_available:
            return ()
        rows = await self._pg.fetch(
            f"""
            SELECT {_SELECT_COLUMNS}
            FROM pressure_outbox AS outbox
            JOIN strategy_5scr_inbox AS inbox
              ON inbox.event_id = outbox.event_id
            WHERE outbox.status = 'PUBLISHED'
              AND inbox.status = 'WAITING_EVIDENCE'
            ORDER BY outbox.signal_valid_at, outbox.lifecycle_id, outbox.lifecycle_sequence
            LIMIT $1
            """,
            max(1, int(limit)),
        )
        return tuple(pressure_envelope_from_row(row) for row in rows)

    async def record_outcome(
        self,
        envelope: PressureOutboxEnvelope,
        outcome: PressureInboxOutcome,
        *,
        evidence_snapshot_id: str | None,
    ) -> bool:
        result = await self._pg.execute(
            """
            UPDATE strategy_5scr_inbox
            SET status = $2,
                processed_at = CASE WHEN $2 = 'PROCESSED' THEN NOW() ELSE NULL END,
                result_id = $3,
                result_payload = $4::jsonb,
                evidence_snapshot_id = $5,
                evidence_attempt_count = evidence_attempt_count + 1,
                evidence_last_attempt_at = NOW(),
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
            evidence_snapshot_id,
            "|".join(outcome.reasons)[:2000] or None,
        )
        return result.endswith(" 1")

    async def record_failure(
        self,
        envelope: PressureOutboxEnvelope,
        *,
        error: str,
    ) -> bool:
        result = await self._pg.execute(
            """
            UPDATE strategy_5scr_inbox
            SET evidence_attempt_count = evidence_attempt_count + 1,
                evidence_last_attempt_at = NOW(),
                last_error = $2
            WHERE event_id = $1
              AND status = 'WAITING_EVIDENCE'
            """,
            envelope.event_id,
            error[:2000],
        )
        return result.endswith(" 1")


class EvidenceProvider(Protocol):
    async def provide(
        self,
        *,
        symbol: str,
        decision_at_utc: datetime,
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
    ) -> None:
        self._repository = repository
        self._provider = provider
        self._processor = processor or Strategy5SCRPressureProcessor()
        self._config = config or EvidenceRuntimeConfig.from_env()
        self._running = False

    async def process_once(self) -> int:
        if not self._config.enabled:
            return 0
        envelopes = await self._repository.load_waiting(limit=self._config.batch_size)
        processed = 0
        for envelope in envelopes:
            try:
                evidence = await self._provider.provide(
                    symbol=envelope.symbol,
                    decision_at_utc=envelope.signal_valid_at,
                )
                if evidence is None:
                    await self._repository.record_failure(
                        envelope,
                        error="STRATEGY_5SCR_CLOSED_CANDLE_EVIDENCE_INCOMPLETE",
                    )
                    processed += 1
                    continue
                outcome = self._processor.process(envelope, evidence=evidence)
                await self._repository.record_outcome(
                    envelope,
                    outcome,
                    evidence_snapshot_id=evidence.evidence_snapshot_id,
                )
                processed += 1
            except ClosedCandleEvidenceError as exc:
                await self._repository.record_failure(envelope, error=str(exc))
                processed += 1
            except Exception as exc:
                # The durable row remains WAITING_EVIDENCE.  A crash or
                # transient store failure therefore retries without losing the
                # event or publishing a partial candidate.
                await self._repository.record_failure(
                    envelope,
                    error=f"STRATEGY_5SCR_EVIDENCE_WORKER_ERROR:{type(exc).__name__}",
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
    provider = Strategy5SCRClosedCandleEvidenceProvider(store, mode="SHADOW")
    repository = PostgresEvidenceRepository(pg=resolved_pg)
    return Strategy5SCREvidenceWorker(
        repository=repository,
        provider=provider,
        config=resolved_config,
    )


__all__ = [
    "EvidenceRuntimeConfig",
    "PostgresEvidenceRepository",
    "Strategy5SCREvidenceWorker",
    "build_evidence_worker",
]
