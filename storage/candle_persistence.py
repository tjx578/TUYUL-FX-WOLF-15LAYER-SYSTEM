"""Async OHLC candle persistence to PostgreSQL.

Buffers completed candles and batch-inserts them periodically to avoid
per-tick database pressure. Uses the shared PostgresClient singleton.

Zone: storage/ — no analysis or execution side-effects.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import deque
from typing import TYPE_CHECKING

from loguru import logger

from storage.postgres_client import pg_client

if TYPE_CHECKING:
    from ingest.candle_builder import Candle

# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

_UPSERT_SQL = """
INSERT INTO ohlc_candles (symbol, timeframe, open_time, close_time,
                          open, high, low, close, volume, tick_count)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
ON CONFLICT (symbol, timeframe, open_time) DO UPDATE SET
    close_time = EXCLUDED.close_time,
    high       = GREATEST(ohlc_candles.high, EXCLUDED.high),
    low        = LEAST(ohlc_candles.low, EXCLUDED.low),
    close      = EXCLUDED.close,
    volume     = EXCLUDED.volume,
    tick_count = EXCLUDED.tick_count
"""

# ---------------------------------------------------------------------------
# Buffer + flush loop
# ---------------------------------------------------------------------------

_buffer: deque[Candle] = deque(maxlen=5000)
_flush_task: asyncio.Task[None] | None = None
_running = False

FLUSH_INTERVAL_SEC = 5.0
BATCH_SIZE = 200


def enqueue_candle(candle: Candle) -> None:
    """Thread-safe enqueue of a completed candle for async persistence."""
    _buffer.append(candle)


async def _flush_batch() -> int:
    """Drain buffer and batch-upsert into PostgreSQL. Returns rows written."""
    if not pg_client.is_available or not _buffer:
        return 0

    batch: list[Candle] = []
    for _ in range(min(BATCH_SIZE, len(_buffer))):
        batch.append(_buffer.popleft())

    if not batch:
        return 0

    pool = pg_client._pool  # noqa: SLF001
    if pool is None:
        return 0

    try:
        async with pool.acquire() as conn:
            await conn.executemany(
                _UPSERT_SQL,
                [
                    (
                        c.symbol,
                        c.timeframe,
                        c.open_time,
                        c.close_time,
                        c.open,
                        c.high,
                        c.low,
                        c.close,
                        c.volume,
                        c.tick_count,
                    )
                    for c in batch
                ],
            )
        return len(batch)
    except Exception:
        # Re-enqueue failed candles at front so they retry next cycle
        for c in reversed(batch):
            _buffer.appendleft(c)
        logger.exception("ohlc_persist flush failed; %d candles re-queued", len(batch))
        return 0


async def _flush_loop() -> None:
    """Background loop that periodically flushes the candle buffer."""
    global _running
    _running = True
    while _running:
        try:
            written = await _flush_batch()
            if written:
                logger.debug("ohlc_persist flushed %d candles", written)
        except Exception:
            logger.exception("ohlc_persist loop error")
        await asyncio.sleep(FLUSH_INTERVAL_SEC)

    # Final drain on shutdown
    while _buffer:
        await _flush_batch()


async def start_candle_persistence() -> None:
    """Start the background flush loop. Idempotent."""
    global _flush_task
    if _flush_task is not None:
        return
    if not pg_client.is_available:
        logger.info("ohlc_persist: PostgreSQL not available, skipping")
        return
    _flush_task = asyncio.create_task(_flush_loop())
    logger.info("ohlc_persist: background flush started (interval=%ss)", FLUSH_INTERVAL_SEC)


async def stop_candle_persistence() -> None:
    """Stop the background flush loop gracefully."""
    global _running, _flush_task
    _running = False
    if _flush_task is not None:
        _flush_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _flush_task
        _flush_task = None
    logger.info("ohlc_persist: stopped")
