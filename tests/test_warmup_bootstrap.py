from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import orjson
import pytest


def _serialized_candle(age: timedelta) -> str:
    timestamp = (datetime.now(UTC) - age).isoformat()
    return orjson.dumps(
        {
            "symbol": "XAGUSD",
            "timeframe": "H1",
            "open": 30.0,
            "high": 31.0,
            "low": 29.5,
            "close": 30.5,
            "volume": 100.0,
            "timestamp": timestamp,
        }
    ).decode("utf-8")


@pytest.mark.asyncio
async def test_supplemental_htf_fetch_refreshes_stale_cache_even_with_enough_bars(monkeypatch: pytest.MonkeyPatch):
    from ingest import warmup_bootstrap

    fake_redis = AsyncMock()
    fake_redis.llen = AsyncMock(return_value=50)
    fake_redis.lrange = AsyncMock(return_value=[_serialized_candle(timedelta(hours=20))])

    fake_fetcher = MagicMock()
    fake_fetcher.fetch = AsyncMock(
        return_value=[
            {
                "symbol": "XAGUSD",
                "timeframe": "H1",
                "open": 30.0,
                "high": 31.0,
                "low": 29.5,
                "close": 30.5,
                "volume": 100.0,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        ]
    )
    fake_fetcher.context_bus = MagicMock()
    monkeypatch.setattr(warmup_bootstrap, "FinnhubCandleFetcher", MagicMock(return_value=fake_fetcher))

    result = await warmup_bootstrap.supplemental_htf_fetch(fake_redis, ["XAGUSD"])

    assert "XAGUSD" in result
    assert set(result["XAGUSD"]) == {"H1", "H4"}


@pytest.mark.asyncio
async def test_supplemental_htf_fetch_repairs_h1_below_l3_floor(monkeypatch: pytest.MonkeyPatch):
    from ingest import warmup_bootstrap

    fake_redis = AsyncMock()

    async def _llen(key: str) -> int:
        if "XAGUSD:H1" in key:
            return 25
        if "XAGUSD:H4" in key:
            return 10
        return 50

    fake_redis.llen = AsyncMock(side_effect=_llen)
    fake_redis.lrange = AsyncMock(return_value=[_serialized_candle(timedelta(minutes=30))])

    fake_fetcher = MagicMock()
    fake_fetcher.fetch = AsyncMock(
        return_value=[
            {
                "symbol": "XAGUSD",
                "timeframe": "H1",
                "open": 30.0,
                "high": 31.0,
                "low": 29.5,
                "close": 30.5,
                "volume": 100.0,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        ]
    )
    fake_fetcher.context_bus = MagicMock()
    monkeypatch.setattr(warmup_bootstrap, "FinnhubCandleFetcher", MagicMock(return_value=fake_fetcher))

    result = await warmup_bootstrap.supplemental_htf_fetch(fake_redis, ["XAGUSD"])

    assert set(result["XAGUSD"]) == {"H1"}
    fake_fetcher.fetch.assert_awaited_once_with("XAGUSD", "H1", 50)


@pytest.mark.asyncio
async def test_seed_redis_candle_history_updates_latest_candle_hash():
    from ingest import warmup_bootstrap

    fake_redis = AsyncMock()
    fake_redis.llen = AsyncMock(return_value=1)
    fake_redis.delete = AsyncMock()
    fake_redis.rpush = AsyncMock()
    fake_redis.rename = AsyncMock()
    fake_redis.hset = AsyncMock()

    await warmup_bootstrap.seed_redis_candle_history(
        fake_redis,
        {
            "XAGUSD": {
                "H1": [
                    {
                        "symbol": "XAGUSD",
                        "timeframe": "H1",
                        "open": 30.0,
                        "high": 31.0,
                        "low": 29.5,
                        "close": 30.5,
                        "volume": 100.0,
                        "timestamp": datetime.now(UTC),
                    }
                ]
            }
        },
    )

    fake_redis.hset.assert_awaited_once()
    assert fake_redis.hset.await_args.args[0] == "wolf15:candle:XAGUSD:H1"
    mapping: dict[str, Any] = fake_redis.hset.await_args.kwargs["mapping"]
    assert "data" in mapping
    assert "last_seen_ts" in mapping
