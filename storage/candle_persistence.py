"""Async OHLC candle persistence to PostgreSQL.

Buffers completed candles and batch-inserts them periodically to avoid
per-tick database pressure. Uses the shared PostgresClient singleton.

Zone: storage/ — no analysis or execution side-effects.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
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
                          open, high, low, close, volume, tick_count,
                          complete, provider, provider_timestamp_semantics)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
ON CONFLICT (symbol, timeframe, open_time) DO UPDATE SET
    close_time = EXCLUDED.close_time,
    high       = GREATEST(ohlc_candles.high, EXCLUDED.high),
    low        = LEAST(ohlc_candles.low, EXCLUDED.low),
    close      = EXCLUDED.close,
    volume     = EXCLUDED.volume,
    tick_count = EXCLUDED.tick_count,
    complete   = EXCLUDED.complete,
    provider   = EXCLUDED.provider,
    provider_timestamp_semantics = EXCLUDED.provider_timestamp_semantics
"""

_PROVIDER_AWARE_UPSERT_SQL = """
WITH raw AS (
    INSERT INTO raw_provider_candles (
        provider, feed, symbol, timeframe, provider_timestamp,
        provider_timestamp_semantics, open_time, close_time,
        open, high, low, close, volume, tick_count, complete,
        payload_hash, metadata, last_observed_at
    )
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12,
            $13, $14, $15, $16, '{}'::jsonb, NOW())
    ON CONFLICT (provider, feed, symbol, timeframe, provider_timestamp)
    DO UPDATE SET
        open_time = EXCLUDED.open_time,
        close_time = EXCLUDED.close_time,
        open = EXCLUDED.open,
        high = EXCLUDED.high,
        low = EXCLUDED.low,
        close = EXCLUDED.close,
        volume = EXCLUDED.volume,
        tick_count = EXCLUDED.tick_count,
        complete = EXCLUDED.complete,
        provider_timestamp_semantics = EXCLUDED.provider_timestamp_semantics,
        payload_hash = EXCLUDED.payload_hash,
        last_observed_at = NOW()
    RETURNING *
)
INSERT INTO canonical_candles (
    symbol, timeframe, open_time, close_time, open, high, low, close,
    volume, tick_count, complete, selected_provider, selected_feed,
    provider_timestamp_semantics, selected_raw_candle_id,
    selection_policy, selection_rank, content_hash, selected_at
)
SELECT symbol, timeframe, open_time, close_time, open, high, low, close,
       volume, tick_count, complete, provider, feed,
       provider_timestamp_semantics, id, '5scr.provider-priority.v1',
       $17, payload_hash, NOW()
FROM raw
WHERE provider_timestamp_semantics <> 'UNSPECIFIED'
ON CONFLICT (symbol, timeframe, open_time) DO UPDATE SET
    close_time = EXCLUDED.close_time,
    open = EXCLUDED.open,
    high = EXCLUDED.high,
    low = EXCLUDED.low,
    close = EXCLUDED.close,
    volume = EXCLUDED.volume,
    tick_count = EXCLUDED.tick_count,
    complete = EXCLUDED.complete,
    selected_provider = EXCLUDED.selected_provider,
    selected_feed = EXCLUDED.selected_feed,
    provider_timestamp_semantics = EXCLUDED.provider_timestamp_semantics,
    selected_raw_candle_id = EXCLUDED.selected_raw_candle_id,
    selection_policy = EXCLUDED.selection_policy,
    selection_rank = EXCLUDED.selection_rank,
    content_hash = EXCLUDED.content_hash,
    selected_at = NOW()
WHERE EXCLUDED.selection_rank > canonical_candles.selection_rank
   OR (
       EXCLUDED.selection_rank = canonical_candles.selection_rank
       AND (
           EXCLUDED.selected_raw_candle_id = canonical_candles.selected_raw_candle_id
           OR (EXCLUDED.selected_provider, EXCLUDED.selected_feed)
              < (canonical_candles.selected_provider, canonical_candles.selected_feed)
       )
   )
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
        parsed = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    if isinstance(value, str):
        with contextlib.suppress(ValueError):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            resolved = parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
            return resolved.astimezone(UTC)
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


from services.shared.type_coerce import to_float as _to_float  # noqa: E402
from services.shared.type_coerce import to_int as _to_int  # noqa: E402


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
        provider_timestamp = _parse_dt(candle_dict.get("timestamp"))
        semantics = str(candle_dict.get("provider_timestamp_semantics") or "").strip().upper()
        tf_delta = _timeframe_to_delta(timeframe)

        if open_time is None or close_time is None:
            if provider_timestamp is None or tf_delta is None:
                return
            if semantics == "PERIOD_END":
                open_time = provider_timestamp - tf_delta
                close_time = provider_timestamp
            else:
                # Preserve legacy diagnostics using the historical PERIOD_OPEN
                # interpretation, but do not grant closed-candle authority.
                open_time = provider_timestamp
                close_time = provider_timestamp + tf_delta
                if not semantics:
                    semantics = "UNSPECIFIED"

        if not semantics:
            semantics = "CANONICAL_WINDOW"
        complete = candle_dict.get("complete") is True and semantics != "UNSPECIFIED"
        provider = str(candle_dict.get("provider") or candle_dict.get("source") or "legacy_unknown").strip()
        if not provider:
            provider = "legacy_unknown"

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
            complete=complete,
            provider=provider,
            provider_timestamp_semantics=semantics,
            provider_timestamp=provider_timestamp,
            provider_feed=str(candle_dict.get("provider_feed") or candle_dict.get("source") or "default"),
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
                _PROVIDER_AWARE_UPSERT_SQL,
                [_provider_aware_args(c) for c in batch],
            )
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
                        c.complete,
                        c.provider,
                        c.provider_timestamp_semantics,
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


async def drain_candle_persistence() -> int:
    """Flush the current buffer completely for bounded backfill commands."""

    written_total = 0
    while _buffer:
        written = await _flush_batch()
        if written <= 0:
            break
        written_total += written
    return written_total


def _provider_priority(provider: str) -> int:
    value = provider.strip().lower()
    if value.startswith(("mt5", "broker")):
        return 300
    if value in {"wolf15_tick_builder", "tick_builder"}:
        return 200
    if value == "finnhub":
        return 100
    return 50


def _provider_aware_args(candle: Candle) -> tuple[object, ...]:
    semantics = candle.provider_timestamp_semantics
    provider_timestamp = candle.provider_timestamp
    if provider_timestamp is None:
        provider_timestamp = candle.close_time if semantics == "PERIOD_END" else candle.open_time
    material = json.dumps(
        {
            "provider": candle.provider,
            "feed": candle.provider_feed,
            "symbol": candle.symbol,
            "timeframe": candle.timeframe,
            "provider_timestamp": provider_timestamp.isoformat(),
            "open_time": candle.open_time.isoformat(),
            "close_time": candle.close_time.isoformat(),
            "open": candle.open,
            "high": candle.high,
            "low": candle.low,
            "close": candle.close,
            "volume": candle.volume,
            "tick_count": candle.tick_count,
            "complete": candle.complete,
            "semantics": semantics,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    rank = _provider_priority(candle.provider) + (1000 if candle.complete else 0)
    return (
        candle.provider,
        candle.provider_feed,
        candle.symbol,
        candle.timeframe,
        provider_timestamp,
        semantics,
        candle.open_time,
        candle.close_time,
        candle.open,
        candle.high,
        candle.low,
        candle.close,
        candle.volume,
        candle.tick_count,
        candle.complete,
        hashlib.sha256(material).hexdigest(),
        rank,
    )


async def _flush_loop() -> None:
    """Background loop that periodically flushes the candle buffer."""
    global _running
    _running = True
    while _running:
        try:
            written = await _flush_batch()
            if written:
                logger.debug("ohlc_persist flushed {} candles", written)
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
    logger.info("ohlc_persist: background flush started (interval={}s)", FLUSH_INTERVAL_SEC)


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
