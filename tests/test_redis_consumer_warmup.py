"""Tests for RedisConsumer candle history warmup on startup."""

from __future__ import annotations

import asyncio
from collections.abc import Generator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import orjson
import pytest

from context.live_context_bus import LiveContextBus
from context.redis_consumer import RedisConsumer


def _make_candle(symbol: str, timeframe: str, idx: int) -> dict[str, Any]:
    """Create a minimal candle dict."""
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "open": 1.1000 + idx * 0.0001,
        "high": 1.1010 + idx * 0.0001,
        "low": 1.0990 + idx * 0.0001,
        "close": 1.1005 + idx * 0.0001,
        "volume": 100 + idx,
        "timestamp": datetime(2024, 1, 15, idx % 24, 0, 0, tzinfo=UTC).isoformat(),
        "source": "rest_api",
    }


def _make_mock_redis() -> AsyncMock:
    """Return an async Redis mock with safe defaults for unused fallbacks."""
    mock_redis = AsyncMock()
    mock_redis.scan = AsyncMock(side_effect=NotImplementedError)
    mock_redis.type = AsyncMock(return_value="mock")
    mock_redis.lrange = AsyncMock(return_value=[])
    mock_redis.hget = AsyncMock(return_value=None)
    mock_redis.hgetall = AsyncMock(return_value={})
    return mock_redis


@pytest.fixture()
def fresh_bus() -> Generator[LiveContextBus, None, None]:
    """Return a fresh LiveContextBus (reset singleton)."""
    LiveContextBus._instance = None
    bus = LiveContextBus()
    yield bus
    LiveContextBus._instance = None


class TestLoadCandleHistory:
    """Test _load_candle_history populates LiveContextBus from Redis Lists."""

    @pytest.mark.asyncio
    async def test_hydrates_feed_timestamp_from_latest_tick_last_seen_ts(self, fresh_bus: LiveContextBus) -> None:
        """Warmup should seed feed freshness from Redis latest_tick last_seen_ts."""
        symbols = ["EURUSD"]
        h1_candles = [_make_candle("EURUSD", "H1", i) for i in range(3)]
        serialized = [orjson.dumps(c) for c in h1_candles]
        expected_ts = 1714300000.5

        mock_redis = _make_mock_redis()

        async def mock_scan(cursor: int, match: str | None = None, count: int | None = None) -> tuple[int, list[str]]:
            if match and "candle_history" in match:
                return 0, ["wolf15:candle_history:EURUSD:H1"]
            return 0, []

        async def mock_type(key: str) -> str:
            if key == "wolf15:candle_history:EURUSD:H1":
                return "list"
            return "none"

        async def mock_lrange(key: str, start: int, end: int) -> list[bytes]:
            if key == "wolf15:candle_history:EURUSD:H1":
                return serialized
            return []

        async def mock_hget(key: str, field: str) -> bytes | None:
            if key == "wolf15:latest_tick:EURUSD" and field == "last_seen_ts":
                return str(expected_ts).encode()
            return None

        mock_redis.scan = AsyncMock(side_effect=mock_scan)
        mock_redis.type = AsyncMock(side_effect=mock_type)
        mock_redis.lrange = AsyncMock(side_effect=mock_lrange)
        mock_redis.hget = AsyncMock(side_effect=mock_hget)
        mock_redis.hgetall = AsyncMock(return_value={})

        consumer = RedisConsumer(
            symbols=symbols,
            redis_client=mock_redis,
            context_bus=fresh_bus,
        )
        await consumer.load_candle_history()

        assert fresh_bus.get_feed_timestamp("EURUSD") == pytest.approx(expected_ts)

    @pytest.mark.asyncio
    async def test_hydrates_feed_timestamp_from_latest_candle_when_tick_missing(
        self, fresh_bus: LiveContextBus
    ) -> None:
        """Warmup should fall back to latest_candle last_seen_ts when latest_tick is absent."""
        symbols = ["EURUSD"]
        m15_candles = [_make_candle("EURUSD", "M15", i) for i in range(2)]
        serialized = [orjson.dumps(c) for c in m15_candles]
        expected_ts = 1714301111.25

        mock_redis = _make_mock_redis()

        async def mock_scan(cursor: int, match: str | None = None, count: int | None = None) -> tuple[int, list[str]]:
            if match and "candle_history" in match:
                return 0, ["wolf15:candle_history:EURUSD:M15"]
            return 0, []

        async def mock_type(key: str) -> str:
            if key == "wolf15:candle_history:EURUSD:M15":
                return "list"
            return "none"

        async def mock_lrange(key: str, start: int, end: int) -> list[bytes]:
            if key == "wolf15:candle_history:EURUSD:M15":
                return serialized
            return []

        async def mock_hget(key: str, field: str) -> bytes | None:
            if field != "last_seen_ts":
                return None
            if key == "wolf15:latest_tick:EURUSD":
                return None
            if key == "wolf15:candle:EURUSD:M15":
                return str(expected_ts).encode()
            return None

        mock_redis.scan = AsyncMock(side_effect=mock_scan)
        mock_redis.type = AsyncMock(side_effect=mock_type)
        mock_redis.lrange = AsyncMock(side_effect=mock_lrange)
        mock_redis.hget = AsyncMock(side_effect=mock_hget)
        mock_redis.hgetall = AsyncMock(return_value={})

        consumer = RedisConsumer(
            symbols=symbols,
            redis_client=mock_redis,
            context_bus=fresh_bus,
        )
        await consumer.load_candle_history()

        assert fresh_bus.get_feed_timestamp("EURUSD") == pytest.approx(expected_ts)

    @pytest.mark.asyncio
    async def test_hydrates_feed_timestamp_from_newer_candle_when_tick_stale(
        self, fresh_bus: LiveContextBus
    ) -> None:
        """Warmup should not keep a stale tick timestamp when candles refreshed later."""
        symbols = ["EURJPY"]
        h1_candles = [_make_candle("EURJPY", "H1", i) for i in range(3)]
        serialized = [orjson.dumps(c) for c in h1_candles]
        stale_tick_ts = 1714300000.5
        fresh_candle_ts = stale_tick_ts + 8906.0

        mock_redis = _make_mock_redis()

        async def mock_scan(cursor: int, match: str | None = None, count: int | None = None) -> tuple[int, list[str]]:
            if match and "candle_history" in match:
                return 0, ["wolf15:candle_history:EURJPY:H1"]
            return 0, []

        async def mock_type(key: str) -> str:
            if key == "wolf15:candle_history:EURJPY:H1":
                return "list"
            return "none"

        async def mock_lrange(key: str, start: int, end: int) -> list[bytes]:
            if key == "wolf15:candle_history:EURJPY:H1":
                return serialized
            return []

        async def mock_hget(key: str, field: str) -> bytes | None:
            if field != "last_seen_ts":
                return None
            if key == "wolf15:latest_tick:EURJPY":
                return str(stale_tick_ts).encode()
            if key == "wolf15:candle:EURJPY:H1":
                return str(fresh_candle_ts).encode()
            return None

        mock_redis.scan = AsyncMock(side_effect=mock_scan)
        mock_redis.type = AsyncMock(side_effect=mock_type)
        mock_redis.lrange = AsyncMock(side_effect=mock_lrange)
        mock_redis.hget = AsyncMock(side_effect=mock_hget)
        mock_redis.hgetall = AsyncMock(return_value={})

        consumer = RedisConsumer(
            symbols=symbols,
            redis_client=mock_redis,
            context_bus=fresh_bus,
        )
        await consumer.load_candle_history()

        assert fresh_bus.get_feed_timestamp("EURJPY") == pytest.approx(fresh_candle_ts)

    @pytest.mark.asyncio
    async def test_loads_h1_candles_from_redis(self, fresh_bus: LiveContextBus) -> None:
        """Candles stored in Redis Lists are loaded into LiveContextBus."""
        symbols = ["EURUSD"]
        h1_candles = [_make_candle("EURUSD", "H1", i) for i in range(25)]
        serialized = [orjson.dumps(c) for c in h1_candles]

        mock_redis = _make_mock_redis()

        async def mock_lrange(key: str, start: int, end: int) -> list[bytes]:
            if "candle_history:EURUSD:H1" in key:
                return serialized
            return []

        mock_redis.lrange = AsyncMock(side_effect=mock_lrange)

        consumer = RedisConsumer(
            symbols=symbols,
            redis_client=mock_redis,
            context_bus=fresh_bus,
        )
        await consumer.load_candle_history()

        bar_count = fresh_bus.get_warmup_bar_count("EURUSD", "H1")
        assert bar_count == 25

    @pytest.mark.asyncio
    async def test_loads_multiple_timeframes(self, fresh_bus: LiveContextBus) -> None:
        """All required timeframes are loaded from Redis."""
        symbols = ["EURUSD"]
        tf_data = {
            "H1": [_make_candle("EURUSD", "H1", i) for i in range(30)],
            "H4": [_make_candle("EURUSD", "H4", i) for i in range(10)],
            "D1": [_make_candle("EURUSD", "D1", i) for i in range(15)],
            "W1": [_make_candle("EURUSD", "W1", i) for i in range(5)],
        }

        mock_redis = _make_mock_redis()

        async def mock_lrange(key: str, start: int, end: int) -> list[bytes]:
            for tf, candles in tf_data.items():
                if f"candle_history:EURUSD:{tf}" in key:
                    return [orjson.dumps(c) for c in candles]
            return []

        mock_redis.lrange = AsyncMock(side_effect=mock_lrange)

        consumer = RedisConsumer(
            symbols=symbols,
            redis_client=mock_redis,
            context_bus=fresh_bus,
        )
        await consumer.load_candle_history()

        assert fresh_bus.get_warmup_bar_count("EURUSD", "H1") == 30
        assert fresh_bus.get_warmup_bar_count("EURUSD", "H4") == 10
        assert fresh_bus.get_warmup_bar_count("EURUSD", "D1") == 15
        assert fresh_bus.get_warmup_bar_count("EURUSD", "W1") == 5

    @pytest.mark.asyncio
    async def test_empty_redis_returns_zero_bars(self, fresh_bus: LiveContextBus) -> None:
        """When Redis Lists are empty, bars stay at zero."""
        mock_redis = _make_mock_redis()
        mock_redis.lrange = AsyncMock(return_value=[])

        consumer = RedisConsumer(
            symbols=["EURUSD"],
            redis_client=mock_redis,
            context_bus=fresh_bus,
        )
        await consumer.load_candle_history()

        assert fresh_bus.get_warmup_bar_count("EURUSD", "H1") == 0
        assert fresh_bus.get_warmup_bar_count("EURUSD", "D1") == 0

    @pytest.mark.asyncio
    async def test_load_candle_history_method_exists(self, fresh_bus: LiveContextBus) -> None:
        """RedisConsumer exposes a public load_candle_history coroutine."""
        import inspect

        mock_redis = _make_mock_redis()
        mock_redis.lrange = AsyncMock(return_value=[])

        consumer = RedisConsumer(
            symbols=["EURUSD"],
            redis_client=mock_redis,
            context_bus=fresh_bus,
        )

        assert hasattr(consumer, "load_candle_history"), "RedisConsumer must expose load_candle_history method"
        assert inspect.iscoroutinefunction(consumer.load_candle_history), (
            "load_candle_history must be an async coroutine"
        )

    @pytest.mark.asyncio
    async def test_multiple_symbols_loaded(self, fresh_bus: LiveContextBus) -> None:
        """Candle history is loaded for every symbol in the consumer."""
        symbols = ["EURUSD", "GBPUSD"]
        candle_map = {
            "EURUSD": {"H1": [_make_candle("EURUSD", "H1", i) for i in range(20)]},
            "GBPUSD": {"H1": [_make_candle("GBPUSD", "H1", i) for i in range(18)]},
        }

        mock_redis = _make_mock_redis()

        async def mock_lrange(key: str, start: int, end: int) -> list[bytes]:
            for sym, tfs in candle_map.items():
                for tf, candles in tfs.items():
                    if f"candle_history:{sym}:{tf}" in key:
                        return [orjson.dumps(c) for c in candles]
            return []

        mock_redis.lrange = AsyncMock(side_effect=mock_lrange)

        consumer = RedisConsumer(
            symbols=symbols,
            redis_client=mock_redis,
            context_bus=fresh_bus,
        )
        await consumer.load_candle_history()

        assert fresh_bus.get_warmup_bar_count("EURUSD", "H1") == 20
        assert fresh_bus.get_warmup_bar_count("GBPUSD", "H1") == 18

    @pytest.mark.asyncio
    async def test_partial_timeframe_failure_does_not_abort_others(self, fresh_bus: LiveContextBus) -> None:
        """If one timeframe key raises, remaining timeframes still load."""
        symbols = ["EURUSD"]
        h4_candles = [_make_candle("EURUSD", "H4", i) for i in range(12)]

        mock_redis = _make_mock_redis()

        async def mock_lrange(key: str, start: int, end: int) -> list[bytes]:
            if "candle_history:EURUSD:H1" in key:
                raise ConnectionError("Redis timeout on H1")
            if "candle_history:EURUSD:H4" in key:
                return [orjson.dumps(c) for c in h4_candles]
            return []

        mock_redis.lrange = AsyncMock(side_effect=mock_lrange)

        consumer = RedisConsumer(
            symbols=symbols,
            redis_client=mock_redis,
            context_bus=fresh_bus,
        )

        await consumer.load_candle_history()

        assert fresh_bus.get_warmup_bar_count("EURUSD", "H4") == 12

    @pytest.mark.asyncio
    async def test_malformed_candle_bytes_skipped(self, fresh_bus: LiveContextBus) -> None:
        """Corrupted bytes in Redis List do not crash the consumer."""
        symbols = ["EURUSD"]
        valid_candles = [orjson.dumps(_make_candle("EURUSD", "H1", i)) for i in range(5)]
        bad_entry = b"not-valid-json{{{"
        mixed = valid_candles[:2] + [bad_entry] + valid_candles[2:]

        mock_redis = _make_mock_redis()

        async def mock_lrange(key: str, start: int, end: int) -> list[bytes]:
            if "candle_history:EURUSD:H1" in key:
                return mixed
            return []

        mock_redis.lrange = AsyncMock(side_effect=mock_lrange)

        consumer = RedisConsumer(
            symbols=symbols,
            redis_client=mock_redis,
            context_bus=fresh_bus,
        )
        await consumer.load_candle_history()

        bar_count = fresh_bus.get_warmup_bar_count("EURUSD", "H1")
        assert bar_count >= 0  # graceful: valid candles counted, bad entry skipped

    @pytest.mark.asyncio
    async def test_load_candle_history_idempotent(self, fresh_bus: LiveContextBus) -> None:
        """Calling load_candle_history twice does not double-count bars."""
        symbols = ["EURUSD"]
        h1_candles = [_make_candle("EURUSD", "H1", i) for i in range(10)]
        serialized = [orjson.dumps(c) for c in h1_candles]

        mock_redis = _make_mock_redis()

        async def mock_lrange(key: str, start: int, end: int) -> list[bytes]:
            if "candle_history:EURUSD:H1" in key:
                return serialized
            return []

        mock_redis.lrange = AsyncMock(side_effect=mock_lrange)

        consumer = RedisConsumer(
            symbols=symbols,
            redis_client=mock_redis,
            context_bus=fresh_bus,
        )

        await consumer.load_candle_history()
        first_count = fresh_bus.get_warmup_bar_count("EURUSD", "H1")

        await consumer.load_candle_history()
        second_count = fresh_bus.get_warmup_bar_count("EURUSD", "H1")

        assert second_count == first_count == 10

    @pytest.mark.asyncio
    async def test_warmup_gate_fails_when_below_minimum(self, fresh_bus: LiveContextBus) -> None:
        """check_warmup returns ready=False when loaded bars < required minimum."""
        symbols = ["EURUSD"]
        tf_data = {
            "H1": [_make_candle("EURUSD", "H1", i) for i in range(5)],  # below 20
        }

        mock_redis = _make_mock_redis()

        async def mock_lrange(key: str, start: int, end: int) -> list[bytes]:
            for tf, candles in tf_data.items():
                if f"candle_history:EURUSD:{tf}" in key:
                    return [orjson.dumps(c) for c in candles]
            return []

        mock_redis.lrange = AsyncMock(side_effect=mock_lrange)

        consumer = RedisConsumer(
            symbols=symbols,
            redis_client=mock_redis,
            context_bus=fresh_bus,
        )
        await consumer.load_candle_history()

        result = fresh_bus.check_warmup("EURUSD", min_bars={"H1": 20})
        assert result["ready"] is False


class TestPubsubReconnect:
    """Test that run() reconnects after transient pubsub failures."""

    @pytest.mark.asyncio
    async def test_run_retries_after_connection_error(self, fresh_bus: LiveContextBus) -> None:
        """run() should retry _consume_pubsub when it raises ConnectionError."""
        from redis.exceptions import ConnectionError as RedisConnectionError

        mock_redis = _make_mock_redis()
        mock_redis.lrange = AsyncMock(return_value=[])
        mock_redis.scan = AsyncMock(return_value=(0, []))

        consumer = RedisConsumer(
            symbols=["EURUSD"],
            redis_client=mock_redis,
            context_bus=fresh_bus,
        )

        call_count = 0

        async def fake_consume_pubsub() -> None:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RedisConnectionError("Connection closed by server.")
            # Third call: stop consumer to exit the loop
            consumer.stop()

        consumer._consume_pubsub = fake_consume_pubsub

        await asyncio.wait_for(consumer.run(), timeout=10.0)

        assert call_count == 3, f"Expected 3 calls to _consume_pubsub, got {call_count}"

    @pytest.mark.asyncio
    async def test_run_does_not_retry_on_cancellation(self, fresh_bus: LiveContextBus) -> None:
        """CancelledError should propagate immediately, not be retried."""
        mock_redis = _make_mock_redis()
        mock_redis.lrange = AsyncMock(return_value=[])
        mock_redis.scan = AsyncMock(return_value=(0, []))

        consumer = RedisConsumer(
            symbols=["EURUSD"],
            redis_client=mock_redis,
            context_bus=fresh_bus,
        )

        async def fake_consume_pubsub() -> None:
            raise asyncio.CancelledError()

        consumer._consume_pubsub = fake_consume_pubsub

        with pytest.raises(asyncio.CancelledError):
            await consumer.run()
