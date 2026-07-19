"""Lease-based dispatcher for the durable Strategy 5S-CR pressure outbox."""

from __future__ import annotations

import asyncio
import contextlib
import os
from datetime import UTC, datetime

from loguru import logger

from core.metrics import PRESSURE_OUTBOX_PROCESSING_LATENCY
from storage.pressure_outbox import (
    PressureOutboxIntegrityError,
    PressureOutboxRepository,
)
from storage.strategy_5scr_pressure_inbox import Strategy5SCRInboxConsumer


class PressureOutboxWorker:
    """Deliver PostgreSQL outbox rows to an idempotent PostgreSQL inbox."""

    def __init__(
        self,
        *,
        worker_id: str | None = None,
        repository: PressureOutboxRepository | None = None,
        consumer: Strategy5SCRInboxConsumer | None = None,
        poll_interval_seconds: float = 1.0,
        batch_size: int = 100,
        lease_seconds: float = 30.0,
        max_attempts: int = 8,
    ) -> None:
        self.worker_id = worker_id or os.getenv("PRESSURE_OUTBOX_WORKER_ID") or "pressure-worker-1"
        self.repository = repository or PressureOutboxRepository()
        self.consumer = consumer or Strategy5SCRInboxConsumer()
        self.poll_interval_seconds = max(0.01, float(poll_interval_seconds))
        self.batch_size = max(1, int(batch_size))
        self.lease_seconds = max(1.0, float(lease_seconds))
        self.max_attempts = max(1, int(max_attempts))
        self._stopped = asyncio.Event()
        self._consecutive_poll_failures = 0

    async def stop(self) -> None:
        self._stopped.set()

    async def _wait_or_stop(self, timeout: float) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._stopped.wait(), timeout=timeout)

    async def run(self) -> None:
        logger.info(
            "Pressure outbox worker starting worker_id={} batch={} lease={}s",
            self.worker_id,
            self.batch_size,
            self.lease_seconds,
        )
        while not self._stopped.is_set():
            try:
                processed = await self.process_once()
                self._consecutive_poll_failures = 0
                if processed == 0:
                    await self._wait_or_stop(self.poll_interval_seconds)
            except Exception as exc:  # noqa: BLE001
                self._consecutive_poll_failures += 1
                delay = min(60.0, self.poll_interval_seconds * (2 ** min(self._consecutive_poll_failures, 10)))
                logger.warning("Pressure outbox poll failed; retrying in {:.1f}s: {}", delay, exc)
                await self._wait_or_stop(delay)

    async def process_once(self) -> int:
        events = await self.repository.claim_batch(
            worker_id=self.worker_id,
            batch_size=self.batch_size,
            lease_seconds=self.lease_seconds,
        )
        for event in events:
            try:
                outcome = await self.consumer.consume(event)
                if outcome.status == "INTEGRITY_VIOLATION":
                    await self.repository.mark_dead(
                        event.event_id,
                        worker_id=self.worker_id,
                        error="STRATEGY_5SCR_INBOX_INTEGRITY_VIOLATION",
                    )
                    continue
            except PressureOutboxIntegrityError as exc:
                await self.repository.mark_dead(
                    event.event_id,
                    worker_id=self.worker_id,
                    error=str(exc),
                )
                continue
            except Exception as exc:  # noqa: BLE001
                await self.repository.mark_retry(
                    event.event_id,
                    worker_id=self.worker_id,
                    error=f"{type(exc).__name__}: {exc}",
                    max_attempts=self.max_attempts,
                )
                continue

            # The inbox transaction has committed at this point.  If this ACK
            # write fails, the lease expires and at-least-once redelivery hits
            # the inbox dedup key without producing another business effect.
            try:
                published = await self.repository.mark_published(event.event_id, worker_id=self.worker_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Pressure outbox ACK failed event_id={}: {}", event.event_id, exc)
                continue
            if published:
                latency = max(0.0, (datetime.now(UTC) - event.signal_valid_at).total_seconds())
                PRESSURE_OUTBOX_PROCESSING_LATENCY.observe(latency)

        if events:
            with contextlib.suppress(Exception):
                await self.repository.metrics_snapshot()
        return len(events)


__all__ = ["PressureOutboxWorker"]
