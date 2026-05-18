from __future__ import annotations

import time
from unittest.mock import AsyncMock

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
