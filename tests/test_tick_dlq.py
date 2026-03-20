"""Tests for ingest/tick_dlq.py — Dead Letter Queue for rejected ticks."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast
from unittest.mock import AsyncMock

import pytest

from ingest.tick_dlq import (
    DLQ_MAX_LEN,
    DLQ_STREAM_KEY,
    TickDeadLetterQueue,
    get_dlq,
    init_dlq,
)

_reset_dlq: Callable[[], None]
try:
    from ingest.tick_dlq import reset_dlq as _reset_dlq_import  # type: ignore[attr-defined]
    _reset_dlq = cast(Callable[[], None], _reset_dlq_import)
except ImportError:
    def _reset_dlq_fallback() -> None:
        """Fallback no-op if reset_dlq is not yet exported by tick_dlq."""

    _reset_dlq = _reset_dlq_fallback

reset_dlq: Callable[[], None] = _reset_dlq


@pytest.fixture
def mock_redis() -> AsyncMock:
    """Create a mock async Redis client."""
    redis = AsyncMock()
    redis.xadd = AsyncMock(return_value=b"1234567890-0")
    redis.xlen = AsyncMock(return_value=5)
    redis.xrange = AsyncMock(return_value=[])
    redis.xtrim = AsyncMock()
    return redis


@pytest.fixture
def dlq(mock_redis: AsyncMock) -> TickDeadLetterQueue:
    return TickDeadLetterQueue(mock_redis)


class TestTickDeadLetterQueue:
    @pytest.mark.asyncio
    async def test_push_returns_message_id(self, dlq: TickDeadLetterQueue, mock_redis: AsyncMock) -> None:
        msg_id = await dlq.push(
            symbol="EURUSD",
            price=1.085,
            exchange_ts=1000000.0,
            reason="spike_rejected",
        )
        assert msg_id == "1234567890-0"
        mock_redis.xadd.assert_awaited_once()
        call_args = mock_redis.xadd.call_args
        assert call_args[0][0] == DLQ_STREAM_KEY
        payload = call_args[0][1]
        assert payload["symbol"] == "EURUSD"
        assert payload["price"] == "1.085"
        assert payload["reason"] == "spike_rejected"

    @pytest.mark.asyncio
    async def test_push_includes_details(self, dlq: TickDeadLetterQueue, mock_redis: AsyncMock) -> None:
        await dlq.push(
            symbol="GBPJPY",
            price=150.0,
            exchange_ts=2000000.0,
            reason="spike_rejected",
            details={"threshold_pct": 1.0},
        )
        payload = mock_redis.xadd.call_args[0][1]
        assert "details" in payload
        assert "1.0" in payload["details"]

    @pytest.mark.asyncio
    async def test_push_uses_maxlen(self, dlq: TickDeadLetterQueue, mock_redis: AsyncMock) -> None:
        await dlq.push(symbol="EURUSD", price=1.0, exchange_ts=1.0, reason="test")
        call_kwargs = mock_redis.xadd.call_args[1]
        assert call_kwargs["maxlen"] == DLQ_MAX_LEN
        assert call_kwargs["approximate"] is True

    @pytest.mark.asyncio
    async def test_push_returns_none_on_redis_error(self, dlq: TickDeadLetterQueue, mock_redis: AsyncMock) -> None:
        mock_redis.xadd.side_effect = ConnectionError("Redis down")
        result = await dlq.push(symbol="EURUSD", price=1.0, exchange_ts=1.0, reason="test")
        assert result is None

    @pytest.mark.asyncio
    async def test_length(self, dlq: TickDeadLetterQueue, mock_redis: AsyncMock) -> None:
        mock_redis.xlen.return_value = 42
        assert await dlq.length() == 42

    @pytest.mark.asyncio
    async def test_length_returns_zero_on_error(self, dlq: TickDeadLetterQueue, mock_redis: AsyncMock) -> None:
        mock_redis.xlen.side_effect = ConnectionError("fail")
        assert await dlq.length() == 0

    @pytest.mark.asyncio
    async def test_peek_returns_entries(self, dlq: TickDeadLetterQueue, mock_redis: AsyncMock) -> None:
        mock_redis.xrange.return_value = [
            (b"100-0", {b"symbol": b"EURUSD", b"reason": b"duplicate"}),
        ]
        result = await dlq.peek(count=1)
        assert len(result) == 1
        assert result[0]["symbol"] == "EURUSD"
        assert result[0]["id"] == "100-0"

    @pytest.mark.asyncio
    async def test_peek_returns_empty_on_error(self, dlq: TickDeadLetterQueue, mock_redis: AsyncMock) -> None:
        mock_redis.xrange.side_effect = ConnectionError("fail")
        assert await dlq.peek() == []

    @pytest.mark.asyncio
    async def test_trim(self, dlq: TickDeadLetterQueue, mock_redis: AsyncMock) -> None:
        await dlq.trim(maxlen=100)
        mock_redis.xtrim.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_push_payload_hash_is_deterministic(self, dlq: TickDeadLetterQueue, mock_redis: AsyncMock) -> None:
        """Same tick should produce the same payload_hash."""
        await dlq.push(symbol="EURUSD", price=1.085, exchange_ts=1000.0, reason="dup")
        hash1 = mock_redis.xadd.call_args[0][1]["payload_hash"]
        mock_redis.xadd.reset_mock()
        await dlq.push(symbol="EURUSD", price=1.085, exchange_ts=1000.0, reason="dup")
        hash2 = mock_redis.xadd.call_args[0][1]["payload_hash"]
        assert hash1 == hash2


class TestDLQSingleton:
    def test_get_dlq_returns_none_before_init(self) -> None:
        """Before init, get_dlq should return None."""
        old = get_dlq()
        reset_dlq()
        try:
            assert get_dlq() is None
        finally:
            if old is not None:
                # Restore by re-initializing with a fresh mock;
                # the old singleton is gone after _reset_dlq().
                init_dlq(AsyncMock())

    def test_init_dlq_sets_singleton(self) -> None:
        redis_mock = AsyncMock()
        dlq = init_dlq(redis_mock)
        assert get_dlq() is dlq
        assert isinstance(dlq, TickDeadLetterQueue)
