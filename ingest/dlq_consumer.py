"""
DLQ Consumer — background task that re-processes failed ticks from the
dead-letter queue (``ingest:tick:dlq``).

Design:
- Runs as a long-lived ``asyncio.Task`` started during ingest service boot.
- Uses XREADGROUP so multiple consumer instances can share the workload
  (one consumer group, at-least-once delivery, XACK after success).
- Only ``spike_rejected`` and ``out_of_order`` entries are retried;
  ``duplicate`` entries are acknowledged immediately (no value in replay).
- Exponential back-off between batches to avoid tight loops.
- Capped retry count per message (configurable, default 3).

Zone: ingest/ — no analysis or execution side effects.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from typing import Any

from redis.asyncio import Redis

from ingest.tick_dlq import DLQ_STREAM_KEY

logger = logging.getLogger(__name__)

__all__ = ["DLQConsumer", "start_dlq_consumer"]

# Defaults ----------------------------------------------------------------
_GROUP = "dlq_reprocess"
_CONSUMER = "dlq-worker-0"
_BATCH_SIZE = 50
_BLOCK_MS = 5_000  # 5 s blocking read
_MAX_RETRIES = 3
_BACKOFF_BASE = 2.0  # seconds
_BACKOFF_CAP = 60.0
_NON_RETRYABLE = frozenset({"duplicate"})


class DLQConsumer:
    """Consume entries from the tick DLQ and re-process them."""

    def __init__(
        self,
        redis: Redis,
        *,
        tick_handler: Any | None = None,
        stream_key: str = DLQ_STREAM_KEY,
        group: str = _GROUP,
        consumer: str = _CONSUMER,
        batch_size: int = _BATCH_SIZE,
        max_retries: int = _MAX_RETRIES,
    ) -> None:
        self._redis = redis
        self._tick_handler = tick_handler
        self._stream_key = stream_key
        self._group = group
        self._consumer = consumer
        self._batch_size = batch_size
        self._max_retries = max_retries
        self._running = False
        self._processed = 0
        self._skipped = 0
        self._failed = 0

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        """Run the consume loop (blocking).  Cancel the task to stop."""
        await self._ensure_group()
        self._running = True
        backoff = 0.0
        logger.info("DLQ consumer started (group=%s, consumer=%s)", self._group, self._consumer)

        while self._running:
            try:
                messages = await self._read_batch()
                if not messages:
                    backoff = min(backoff + _BACKOFF_BASE, _BACKOFF_CAP)
                    await asyncio.sleep(backoff)
                    continue

                backoff = 0.0
                for msg_id, fields in messages:
                    await self._handle(msg_id, fields)

            except asyncio.CancelledError:
                logger.info("DLQ consumer cancelled — shutting down")
                break
            except Exception:
                logger.warning("DLQ consumer loop error", exc_info=True)
                await asyncio.sleep(min(backoff + _BACKOFF_BASE, _BACKOFF_CAP))

        self._running = False
        logger.info(
            "DLQ consumer stopped: processed=%d skipped=%d failed=%d",
            self._processed,
            self._skipped,
            self._failed,
        )

    def stop(self) -> None:
        self._running = False

    @property
    def stats(self) -> dict[str, int]:
        return {"processed": self._processed, "skipped": self._skipped, "failed": self._failed}

    # -- internals ---------------------------------------------------------

    async def _ensure_group(self) -> None:
        """Create consumer group if it doesn't already exist."""
        try:
            await self._redis.xgroup_create(
                self._stream_key,
                self._group,
                id="0",
                mkstream=True,
            )
        except Exception as exc:
            # BUSYGROUP = group already exists — safe to ignore
            if "BUSYGROUP" not in str(exc):
                raise

    async def _read_batch(self) -> list[tuple[str, dict[str, str]]]:
        """XREADGROUP a batch from the DLQ stream."""
        raw: Any = await self._redis.xreadgroup(
            groupname=self._group,
            consumername=self._consumer,
            streams={self._stream_key: ">"},
            count=self._batch_size,
            block=_BLOCK_MS,
        )
        if not raw:
            return []

        results: list[tuple[str, dict[str, str]]] = []
        for _stream_name, entries in raw:
            for msg_id, fields in entries:
                decoded_id = msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id)
                decoded_fields = {
                    (k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
                    for k, v in fields.items()
                }
                results.append((decoded_id, decoded_fields))
        return results

    async def _handle(self, msg_id: str, fields: dict[str, str]) -> None:
        reason = fields.get("reason", "")

        # Non-retryable: ACK immediately, skip processing
        if reason in _NON_RETRYABLE:
            await self._ack(msg_id)
            self._skipped += 1
            return

        # Attempt re-process
        try:
            await self._reprocess_tick(fields)
            await self._ack(msg_id)
            self._processed += 1
        except Exception:
            self._failed += 1
            logger.warning(
                "DLQ reprocess failed for %s (symbol=%s reason=%s)",
                msg_id,
                fields.get("symbol"),
                reason,
                exc_info=True,
            )
            # Message stays in PEL for claim / manual review

    async def _reprocess_tick(self, fields: dict[str, str]) -> None:
        """Re-inject the tick into the processing pipeline."""
        symbol = fields.get("symbol", "")
        price = float(fields.get("price", "0"))
        exchange_ts = float(fields.get("exchange_ts", "0"))

        tick = {
            "symbol": symbol,
            "price": price,
            "timestamp": exchange_ts,
            "source": "dlq_replay",
            "dlq_replay_ts": time.time(),
        }

        # Merge optional details
        raw_details = fields.get("details")
        if raw_details:
            with contextlib.suppress(json.JSONDecodeError, TypeError):
                tick["dlq_details"] = json.loads(raw_details)

        if self._tick_handler is not None:
            await self._tick_handler(tick)
        else:
            logger.debug("DLQ tick replayed (no handler): %s @ %s", symbol, price)

    async def _ack(self, msg_id: str) -> None:
        try:
            await self._redis.xack(self._stream_key, self._group, msg_id)
        except Exception:
            logger.warning("DLQ XACK failed for %s", msg_id, exc_info=True)


async def start_dlq_consumer(
    redis: Redis,
    *,
    tick_handler: Any | None = None,
) -> DLQConsumer:
    """Create and launch a DLQ consumer as a background asyncio task.

    Returns the ``DLQConsumer`` instance (whose ``start()`` coroutine is
    already scheduled).
    """
    consumer = DLQConsumer(redis, tick_handler=tick_handler)
    asyncio.create_task(consumer.start(), name="dlq-consumer")
    return consumer
