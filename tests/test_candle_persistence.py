"""Tests for storage.candle_persistence — OHLC candle buffering + PostgreSQL upsert."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ingest.candle_builder import Candle
from storage.candle_persistence import (
    BATCH_SIZE,
    _buffer,
    _flush_batch,
    enqueue_candle,
)


def _make_candle(
    symbol: str = "EURUSD",
    timeframe: str = "M15",
    offset_min: int = 0,
) -> Candle:
    base = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
    from datetime import timedelta

    open_t = base + timedelta(minutes=offset_min)
    close_t = open_t + timedelta(minutes=15)
    return Candle(
        symbol=symbol,
        timeframe=timeframe,
        open_time=open_t,
        close_time=close_t,
        open=1.08500 + offset_min * 0.0001,
        high=1.08600 + offset_min * 0.0001,
        low=1.08400 + offset_min * 0.0001,
        close=1.08550 + offset_min * 0.0001,
        volume=120.0,
        tick_count=47,
        complete=True,
    )


class TestEnqueueCandle:
    def test_enqueue_appends_to_buffer(self) -> None:
        _buffer.clear()
        c = _make_candle()
        enqueue_candle(c)
        assert len(_buffer) == 1
        assert _buffer[0] is c
        _buffer.clear()

    def test_enqueue_multiple(self) -> None:
        _buffer.clear()
        for i in range(10):
            enqueue_candle(_make_candle(offset_min=i))
        assert len(_buffer) == 10
        _buffer.clear()


class TestFlushBatch:
    @pytest.mark.asyncio
    async def test_skip_when_pg_unavailable(self) -> None:
        _buffer.clear()
        enqueue_candle(_make_candle())
        with patch("storage.candle_persistence.pg_client") as mock_pg:
            mock_pg.is_available = False
            written = await _flush_batch()
        assert written == 0
        _buffer.clear()

    @pytest.mark.asyncio
    async def test_skip_when_buffer_empty(self) -> None:
        _buffer.clear()
        with patch("storage.candle_persistence.pg_client") as mock_pg:
            mock_pg.is_available = True
            written = await _flush_batch()
        assert written == 0

    @pytest.mark.asyncio
    async def test_flush_calls_executemany(self) -> None:
        _buffer.clear()
        for i in range(3):
            enqueue_candle(_make_candle(offset_min=i))

        mock_conn = AsyncMock()
        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("storage.candle_persistence.pg_client") as mock_pg:
            mock_pg.is_available = True
            mock_pg._pool = mock_pool
            written = await _flush_batch()

        assert written == 3
        assert mock_conn.executemany.await_count == 1
        args = mock_conn.executemany.call_args
        assert len(args[0][1]) == 3  # 3 rows
        assert len(_buffer) == 0
        _buffer.clear()

    @pytest.mark.asyncio
    async def test_requeue_on_failure(self) -> None:
        _buffer.clear()
        enqueue_candle(_make_candle(offset_min=0))
        enqueue_candle(_make_candle(offset_min=15))

        mock_conn = AsyncMock()
        mock_conn.executemany.side_effect = RuntimeError("pg down")
        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("storage.candle_persistence.pg_client") as mock_pg:
            mock_pg.is_available = True
            mock_pg._pool = mock_pool
            written = await _flush_batch()

        assert written == 0
        assert len(_buffer) == 2  # re-queued
        _buffer.clear()


class TestBatchSizeLimit:
    @pytest.mark.asyncio
    async def test_respects_batch_size(self) -> None:
        _buffer.clear()
        for i in range(BATCH_SIZE + 50):
            enqueue_candle(_make_candle(offset_min=i % 60))

        mock_conn = AsyncMock()
        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("storage.candle_persistence.pg_client") as mock_pg:
            mock_pg.is_available = True
            mock_pg._pool = mock_pool
            written = await _flush_batch()

        assert written == BATCH_SIZE
        assert len(_buffer) == 50  # remainder
        _buffer.clear()
