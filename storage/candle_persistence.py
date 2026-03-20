"""Async OHLC candle persistence to PostgreSQL.

Buffers completed candles and batch-inserts them periodically to avoid
per-tick database pressure. Uses the shared PostgresClient singleton.

Zone: storage/ — no analysis or execution side-effects.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import deque
from datetime import UTC, datetime, timedelta
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


def _parse_dt(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        with contextlib.suppress(ValueError):
            parsed = datetime.fromisoformat(value)
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return None


def _timeframe_to_delta(timeframe: str) -> timedelta | None:
    mapping = {
        "M1": timedelta(minutes=1),
        "M5": timedelta(minutes=5),
        "M15": timedelta(minutes=15),
        "H1": timedelta(hours=1),
        "H4": timedelta(hours=4),
        "D1": timedelta(days=1),
        "W1": timedelta(days=7),
        # Approximate month duration for persistence fallback paths.
        "MN": timedelta(days=30),
    }
    return mapping.get(str(timeframe).upper())


def _to_float(value: object, default: float = 0.0) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        with contextlib.suppress(ValueError):
            return float(value)
    return default


def _to_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        with contextlib.suppress(ValueError):
            return int(float(value))
    return default


def enqueue_candle_dict(candle_dict: dict[str, object]) -> None:
    """Convert dict payload to Candle and enqueue it for PostgreSQL persistence.

    The ingest fallback schedulers emit candle dicts that may use either
    ``open_time``/``close_time`` or a single ``timestamp`` field.
    """
    try:
        from ingest.candle_builder import Candle  # noqa: PLC0415

        symbol = str(candle_dict.get("symbol", "")).strip().upper()
        timeframe = str(candle_dict.get("timeframe", "")).strip().upper()
        if not symbol or not timeframe:
            return

        open_time = _parse_dt(candle_dict.get("open_time"))
        close_time = _parse_dt(candle_dict.get("close_time"))

        if open_time is None:
            open_time = _parse_dt(candle_dict.get("timestamp"))
        if open_time is None:
            return

        if close_time is None:
            tf_delta = _timeframe_to_delta(timeframe)
            if tf_delta is None:
                return
            close_time = open_time + tf_delta

        candle = Candle(
            symbol=symbol,
            timeframe=timeframe,
            open_time=open_time,
            close_time=close_time,
            open=_to_float(candle_dict.get("open")),
            high=_to_float(candle_dict.get("high")),
            low=_to_float(candle_dict.get("low")),
            close=_to_float(candle_dict.get("close")),
            volume=_to_float(candle_dict.get("volume")),
            tick_count=_to_int(candle_dict.get("tick_count")),
            complete=True,
        )
        enqueue_candle(candle)
    except Exception:
        logger.debug("ohlc_persist enqueue_candle_dict failed")


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
