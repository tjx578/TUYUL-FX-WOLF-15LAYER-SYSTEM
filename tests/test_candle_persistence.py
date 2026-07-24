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
    _provider_aware_args,
    enqueue_candle,
    enqueue_candle_dict,
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

    def test_enqueue_candle_dict_with_open_close_time(self) -> None:
        _buffer.clear()
        payload = {
            "symbol": "EURUSD",
            "timeframe": "M15",
            "open_time": "2026-03-15T12:00:00+00:00",
            "close_time": "2026-03-15T12:15:00+00:00",
            "open": 1.1,
            "high": 1.2,
            "low": 1.0,
            "close": 1.15,
            "volume": 10.0,
            "tick_count": 5,
        }

        enqueue_candle_dict(payload)

        assert len(_buffer) == 1
        assert _buffer[0].symbol == "EURUSD"
        assert _buffer[0].timeframe == "M15"
        assert _buffer[0].complete is False
        _buffer.clear()

    def test_enqueue_candle_dict_with_timestamp_fallback(self) -> None:
        _buffer.clear()
        payload = {
            "symbol": "EURUSD",
            "timeframe": "H1",
            "timestamp": "2026-03-15T12:00:00+00:00",
            "open": 1.1,
            "high": 1.2,
            "low": 1.0,
            "close": 1.15,
        }

        enqueue_candle_dict(payload)

        assert len(_buffer) == 1
        assert _buffer[0].close_time == datetime(2026, 3, 15, 13, 0, tzinfo=UTC)
        assert _buffer[0].complete is False
        assert _buffer[0].provider_timestamp_semantics == "UNSPECIFIED"
        _buffer.clear()


def test_provider_aware_identity_and_rank_do_not_mix_feeds() -> None:
    finnhub = _make_candle()
    finnhub.provider = "finnhub"
    finnhub.provider_feed = "oanda_rest"
    finnhub.provider_timestamp_semantics = "PERIOD_OPEN"
    finnhub.provider_timestamp = finnhub.open_time

    broker = _make_candle()
    broker.provider = "mt5"
    broker.provider_feed = "demo_account_1"
    broker.provider_timestamp_semantics = "PERIOD_OPEN"
    broker.provider_timestamp = broker.open_time

    finnhub_args = _provider_aware_args(finnhub)
    broker_args = _provider_aware_args(broker)

    assert finnhub_args[:2] == ("finnhub", "oanda_rest")
    assert broker_args[:2] == ("mt5", "demo_account_1")
    assert finnhub_args[4] == finnhub.open_time
    assert len(str(finnhub_args[15])) == 64
    assert int(broker_args[16]) > int(finnhub_args[16])


def test_forming_to_closed_revision_increases_canonical_selection_rank() -> None:
    forming = _make_candle(timeframe="H1")
    forming.complete = False
    forming.provider = "finnhub"
    forming.provider_feed = "oanda_rest"
    forming.provider_timestamp_semantics = "PERIOD_OPEN"
    forming.provider_timestamp = forming.open_time

    closed = _make_candle(timeframe="H1")
    closed.provider = forming.provider
    closed.provider_feed = forming.provider_feed
    closed.provider_timestamp_semantics = forming.provider_timestamp_semantics
    closed.provider_timestamp = forming.provider_timestamp

    forming_args = _provider_aware_args(forming)
    closed_args = _provider_aware_args(closed)

    assert forming_args[:6] == closed_args[:6]
    assert forming_args[15] != closed_args[15]
    assert int(closed_args[16]) > int(forming_args[16])


def test_enqueue_canonical_closed_candle_preserves_authority() -> None:
    _buffer.clear()
    payload = {
        "symbol": "EURUSD",
        "timeframe": "H1",
        "open_time": "2026-03-15T12:00:00+00:00",
        "close_time": "2026-03-15T13:00:00+00:00",
        "open": 1.1,
        "high": 1.2,
        "low": 1.0,
        "close": 1.15,
        "complete": True,
        "provider": "finnhub",
        "provider_timestamp_semantics": "PERIOD_END",
    }

    enqueue_candle_dict(payload)

    assert len(_buffer) == 1
    assert _buffer[0].complete is True
    assert _buffer[0].provider == "finnhub"
    assert _buffer[0].provider_timestamp_semantics == "PERIOD_END"
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
        assert mock_conn.executemany.await_count == 2
        args = mock_conn.executemany.call_args_list[1]
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
