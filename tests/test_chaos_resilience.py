"""Chaos resilience tests: redis down, delayed feed, duplicate event, out-of-order tick."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from analysis.tick_filter import SpikeFilter, TickFilterConfig
from infrastructure.stream_consumer import StreamBinding, StreamConsumer
from ingest.dependencies import (
    _dedup_cache,
    _is_duplicate_tick,
    _is_out_of_order_tick,
    _last_exchange_ts_ms,
)


class TestChaosRedisDown:
    @pytest.mark.asyncio
    async def test_stream_consumer_redis_down_raises_and_keeps_unacked(self) -> None:
        callback = AsyncMock(return_value=None)
        redis_client = AsyncMock()
        redis_client.xack = AsyncMock(side_effect=RedisConnectionError("redis down"))

        binding = StreamBinding(stream="signals:l12", group="grp", callback=callback)
        consumer = StreamConsumer(bindings=[binding], redis_client=redis_client)

        with pytest.raises(RedisConnectionError):
            await consumer._process_and_ack(
                binding,
                "1-0",
                {"symbol": "EURUSD"},
            )

        assert consumer.stats["messages_acked"] == 0


class TestChaosDelayedFeed:
    def test_delayed_feed_stale_override_accepts_price_jump(self) -> None:
        filt = SpikeFilter(
            TickFilterConfig(spike_threshold_pct=0.5, staleness_seconds=60.0),
        )

        first = filt.check("EURUSD", 1.1000, timestamp=1000.0)
        delayed = filt.check("EURUSD", 1.1300, timestamp=1061.0)

        assert first.accepted is True
        assert delayed.accepted is True
        assert delayed.stale_override is True


class TestChaosDuplicateWebhook:
    def setup_method(self) -> None:
        _dedup_cache.clear()

    def test_duplicate_event_payload_detected(self) -> None:
        assert _is_duplicate_tick("EURUSD", 1.1001, 1_700_000_000_000.0) is False
        assert _is_duplicate_tick("EURUSD", 1.1001, 1_700_000_000_000.0) is True


class TestChaosOutOfOrderTick:
    def setup_method(self) -> None:
        _last_exchange_ts_ms.clear()

    def test_out_of_order_tick_rejected(self) -> None:
        assert _is_out_of_order_tick("EURUSD", 1_700_000_000_100.0) is False
        assert _is_out_of_order_tick("EURUSD", 1_700_000_000_050.0) is True
        assert _is_out_of_order_tick("EURUSD", 1_700_000_000_150.0) is False
