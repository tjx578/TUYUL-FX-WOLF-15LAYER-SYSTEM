"""Tests for ingest/dlq_consumer.py — DLQ re-processing background task."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from ingest.dlq_consumer import _NON_RETRYABLE, DLQConsumer


@pytest.fixture()
def fake_redis():
    """Minimal async Redis mock."""
    r = AsyncMock()
    r.xgroup_create = AsyncMock()
    r.xreadgroup = AsyncMock(return_value=[])
    r.xack = AsyncMock()
    return r


@pytest.fixture()
def consumer(fake_redis):
    return DLQConsumer(fake_redis, batch_size=10, max_retries=2)


class TestDLQConsumerInit:
    def test_stats_initial(self, consumer: DLQConsumer) -> None:
        assert consumer.stats == {"processed": 0, "skipped": 0, "failed": 0}

    @pytest.mark.asyncio()
    async def test_ensure_group_creates(self, consumer: DLQConsumer, fake_redis) -> None:
        await consumer._ensure_group()
        fake_redis.xgroup_create.assert_awaited_once()

    @pytest.mark.asyncio()
    async def test_ensure_group_ignores_busygroup(self, fake_redis) -> None:
        fake_redis.xgroup_create.side_effect = Exception("BUSYGROUP consumer group already exists")
        c = DLQConsumer(fake_redis)
        await c._ensure_group()  # should not raise


class TestDLQConsumerHandle:
    @pytest.mark.asyncio()
    async def test_duplicate_skipped(self, consumer: DLQConsumer, fake_redis) -> None:
        await consumer._handle("1-0", {"symbol": "EURUSD", "reason": "duplicate", "price": "1.1"})
        assert consumer.stats["skipped"] == 1
        fake_redis.xack.assert_awaited_once()

    @pytest.mark.asyncio()
    async def test_spike_rejected_reprocessed(self, fake_redis) -> None:
        handler = AsyncMock()
        c = DLQConsumer(fake_redis, tick_handler=handler)
        await c._handle(
            "2-0",
            {
                "symbol": "GBPJPY",
                "price": "185.50",
                "exchange_ts": "1700000000.0",
                "reason": "spike_rejected",
            },
        )
        handler.assert_awaited_once()
        tick = handler.call_args[0][0]
        assert tick["symbol"] == "GBPJPY"
        assert tick["source"] == "dlq_replay"
        assert c.stats["processed"] == 1

    @pytest.mark.asyncio()
    async def test_handler_failure_increments_failed(self, fake_redis) -> None:
        handler = AsyncMock(side_effect=RuntimeError("boom"))
        c = DLQConsumer(fake_redis, tick_handler=handler)
        await c._handle(
            "3-0",
            {
                "symbol": "AUDUSD",
                "price": "0.66",
                "exchange_ts": "1700000000.0",
                "reason": "out_of_order",
            },
        )
        assert c.stats["failed"] == 1
        # Message NOT acknowledged — stays in PEL
        fake_redis.xack.assert_not_awaited()

    @pytest.mark.asyncio()
    async def test_details_parsed_into_tick(self, fake_redis) -> None:
        handler = AsyncMock()
        c = DLQConsumer(fake_redis, tick_handler=handler)
        await c._handle(
            "4-0",
            {
                "symbol": "USDJPY",
                "price": "150.0",
                "exchange_ts": "1700000000.0",
                "reason": "spike_rejected",
                "details": '{"threshold_pct": 0.5}',
            },
        )
        tick = handler.call_args[0][0]
        assert tick["dlq_details"] == {"threshold_pct": 0.5}


class TestNonRetryable:
    def test_duplicate_is_non_retryable(self) -> None:
        assert "duplicate" in _NON_RETRYABLE

    def test_spike_rejected_is_retryable(self) -> None:
        assert "spike_rejected" not in _NON_RETRYABLE

    def test_out_of_order_is_retryable(self) -> None:
        assert "out_of_order" not in _NON_RETRYABLE


class TestDLQConsumerLoop:
    @pytest.mark.asyncio()
    async def test_start_stop(self, consumer: DLQConsumer) -> None:
        """Consumer can be stopped cleanly."""

        async def stop_after_tick():
            await asyncio.sleep(0.1)
            consumer.stop()

        asyncio.create_task(stop_after_tick())
        await consumer.start()
        assert consumer._running is False
