from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import orjson
import pytest

from core.candle_bridge_fix import _push_candle_to_redis_safe


@pytest.mark.asyncio
async def test_push_candle_updates_latest_hash_with_payload_and_receipt_time() -> None:
    redis = AsyncMock()
    redis.lrange = AsyncMock(return_value=[])
    redis.rpush = AsyncMock()
    redis.ltrim = AsyncMock()
    redis.hset = AsyncMock()
    redis.publish = AsyncMock()

    candle = {
        "symbol": "AUDJPY",
        "timeframe": "H1",
        "open": 100.1,
        "high": 100.4,
        "low": 100.0,
        "close": 100.2,
        "volume": 12,
        "timestamp": 1.0,
    }

    before = time.time()
    await _push_candle_to_redis_safe(redis, candle)
    after = time.time()

    redis.hset.assert_awaited_once()
    assert redis.hset.await_args.args[0] == "wolf15:candle:AUDJPY:H1"
    mapping = redis.hset.await_args.kwargs["mapping"]
    assert orjson.loads(mapping["data"]) == candle
    assert before <= float(mapping["last_seen_ts"]) <= after


@pytest.mark.asyncio
async def test_closed_refresh_replaces_forming_history_and_always_reaches_persistence() -> None:
    forming = {
        "symbol": "NZDUSD",
        "timeframe": "H1",
        "open_time": "2026-07-20T06:00:00+00:00",
        "close_time": "2026-07-20T07:00:00+00:00",
        "open": 0.6100,
        "high": 0.6110,
        "low": 0.6090,
        "close": 0.6105,
        "complete": False,
        "provider": "finnhub",
        "provider_timestamp_semantics": "PERIOD_OPEN",
    }
    closed = {**forming, "high": 0.6120, "close": 0.6115, "complete": True}
    redis = AsyncMock()
    redis.lrange = AsyncMock(return_value=[orjson.dumps(forming)])
    redis.lset = AsyncMock()
    redis.rpush = AsyncMock()
    redis.ltrim = AsyncMock()
    redis.hset = AsyncMock()
    redis.publish = AsyncMock()

    with patch("storage.candle_persistence.enqueue_candle_dict") as enqueue:
        await _push_candle_to_redis_safe(redis, closed)

    enqueue.assert_called_once_with(closed)
    redis.lset.assert_awaited_once()
    assert orjson.loads(redis.lset.await_args.args[2]) == closed
    redis.rpush.assert_not_awaited()
    redis.hset.assert_awaited_once()
    redis.publish.assert_awaited_once()
