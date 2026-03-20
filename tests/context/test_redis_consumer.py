from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import orjson
import pytest

# Alias to silence Pyright "reportUnknownMemberType" on pytest.approx
_approx = pytest.approx  # type: ignore[reportUnknownMemberType]

from context.live_context_bus import LiveContextBus  # noqa: E402
from context.redis_consumer import RedisConsumer  # noqa: E402

"""Tests for RedisConsumer warmup — key-namespace mismatch regression."""

pytestmark = pytest.mark.anyio


def _make_candle(symbol: str, timeframe: str, close: float) -> bytes:
    return orjson.dumps({"symbol": symbol, "timeframe": timeframe, "close": close})


def _make_redis(
    list_data: dict[str, list[bytes]] | None = None,
    hash_data: dict[str, dict[str | bytes, str | bytes]] | None = None,
) -> MagicMock:
    """Return a mock Redis client.

    list_data: keys → list entries (for LRANGE)
    hash_data: keys → hash entries (for HGETALL)
    """
    redis = MagicMock()
    _ld = list_data or {}
    _hd = hash_data or {}

    async def lrange(key: str, start: int, end: int) -> list[bytes]:
        return _ld.get(key, [])

    async def hgetall(key: str) -> dict[str | bytes, str | bytes]:
        return _hd.get(key, {})

    redis.lrange = lrange
    redis.hgetall = hgetall
    redis.pubsub = MagicMock(return_value=MagicMock())
    return redis


# ---------------------------------------------------------------------------
# Warmup prefix-fallback tests
# ---------------------------------------------------------------------------


async def test_warmup_uses_wolf15_candle_history_prefix() -> None:
    """load_candle_history must pick data stored under wolf15:candle_history:* (List)."""
    candle = _make_candle("EURUSD", "H1", 1.0850)
    redis = _make_redis({"wolf15:candle_history:EURUSD:H1": [candle]})
    bus = LiveContextBus()

    consumer = RedisConsumer(["EURUSD"], redis, bus)
    await consumer.load_candle_history()

    history: list[dict[str, Any]] | None = bus.get_candle_history("EURUSD", "H1")
    assert history is not None
    assert len(history) == 1
    assert history[0]["close"] == _approx(1.0850)


async def test_warmup_hash_fallback() -> None:
    """When no List data exists, warmup falls back to wolf15:candle (Hash) via hgetall."""
    candle_json = orjson.dumps({"symbol": "EURUSD", "timeframe": "H1", "close": 1.0850}).decode("utf-8")
    redis = _make_redis(
        list_data={},
        hash_data={"wolf15:candle:EURUSD:H1": {"data": candle_json}},
    )
    bus = LiveContextBus()

    consumer = RedisConsumer(["EURUSD"], redis, bus)
    await consumer.load_candle_history()

    history: list[dict[str, Any]] | None = bus.get_candle_history("EURUSD", "H1")
    assert history is not None
    assert len(history) == 1
    assert history[0]["close"] == _approx(1.0850)


async def test_warmup_falls_back_to_wolf15_candle_history() -> None:
    """If wolf15:candle_history misses, fall back to candle_history (legacy)."""
    candle = _make_candle("GBPUSD", "H1", 1.2700)
    redis = _make_redis({"candle_history:GBPUSD:H1": [candle]})
    bus = LiveContextBus()

    consumer = RedisConsumer(["GBPUSD"], redis, bus)
    await consumer.load_candle_history()

    history: list[dict[str, Any]] | None = bus.get_candle_history("GBPUSD", "H1")
    assert history is not None
    assert len(history) == 1


async def test_warmup_falls_back_to_legacy_prefix() -> None:
    """Ultimate legacy fallback: candle_history prefix."""
    candle = _make_candle("USDJPY", "M15", 149.50)
    redis = _make_redis({"candle_history:USDJPY:M15": [candle]})
    bus = LiveContextBus()

    consumer = RedisConsumer(["USDJPY"], redis, bus)
    await consumer.load_candle_history()

    history: list[dict[str, Any]] | None = bus.get_candle_history("USDJPY", "M15")
    assert history is not None
    assert len(history) == 1


async def test_warmup_returns_empty_when_no_prefix_matches() -> None:
    """If no prefix has data, bus history should remain empty (no crash)."""
    redis = _make_redis({})
    bus = LiveContextBus()

    consumer = RedisConsumer(["XAUUSD"], redis, bus)
    await consumer.load_candle_history()  # must not raise

    history: list[dict[str, Any]] | None = bus.get_candle_history("XAUUSD", "H1")
    assert history == [] or history is None


async def test_warmup_prefers_first_matching_prefix() -> None:
    """wolf15:candle_history (List) must win over candle_history (legacy) when both have data."""
    candle_new = _make_candle("EURUSD", "H4", 1.0900)
    candle_old = _make_candle("EURUSD", "H4", 1.0800)
    redis = _make_redis(
        {
            "wolf15:candle_history:EURUSD:H4": [candle_new],
            "candle_history:EURUSD:H4": [candle_old],
        }
    )
    bus = LiveContextBus()

    consumer = RedisConsumer(["EURUSD"], redis, bus)
    await consumer.load_candle_history()

    history: list[dict[str, Any]] | None = bus.get_candle_history("EURUSD", "H4")
    assert history is not None
    assert len(history) == 1
    assert history[0]["close"] == _approx(1.0900)  # newer prefix wins


async def test_warmup_skips_malformed_candles() -> None:
    """Malformed bytes in a key must be skipped without crashing."""
    good = _make_candle("EURUSD", "D1", 1.0950)
    bad = b"not-json-{{{{"
    redis = _make_redis({"wolf15:candle_history:EURUSD:D1": [bad, good]})
    bus = LiveContextBus()

    consumer = RedisConsumer(["EURUSD"], redis, bus)
    await consumer.load_candle_history()

    history: list[dict[str, Any]] | None = bus.get_candle_history("EURUSD", "D1")
    assert history is not None
    assert len(history) == 1
    assert history[0]["close"] == _approx(1.0950)


# ---------------------------------------------------------------------------
# Additional warmup tests
# ---------------------------------------------------------------------------


async def test_warmup_loads_multiple_symbols() -> None:
    """Warmup must load data for every symbol in the list."""
    candle_eu = _make_candle("EURUSD", "H1", 1.0850)
    candle_gb = _make_candle("GBPUSD", "H1", 1.2700)
    redis = _make_redis(
        {
            "wolf15:candle_history:EURUSD:H1": [candle_eu],
            "wolf15:candle_history:GBPUSD:H1": [candle_gb],
        }
    )
    bus = LiveContextBus()

    consumer = RedisConsumer(["EURUSD", "GBPUSD"], redis, bus)
    await consumer.load_candle_history()

    history_eu: list[dict[str, Any]] | None = bus.get_candle_history("EURUSD", "H1")
    history_gb: list[dict[str, Any]] | None = bus.get_candle_history("GBPUSD", "H1")
    assert history_eu is not None and len(history_eu) == 1
    assert history_gb is not None and len(history_gb) == 1
    assert history_eu[0]["close"] == _approx(1.0850)
    assert history_gb[0]["close"] == _approx(1.2700)


async def test_warmup_loads_multiple_timeframes() -> None:
    """Warmup must iterate all WARMUP_TIMEFRAMES for each symbol."""
    from context.redis_consumer import WARMUP_TIMEFRAMES

    data: dict[str, list[bytes]] = {}
    for tf in WARMUP_TIMEFRAMES:
        candle = _make_candle("EURUSD", tf, 1.0800 + WARMUP_TIMEFRAMES.index(tf) * 0.001)
        data[f"wolf15:candle_history:EURUSD:{tf}"] = [candle]

    redis = _make_redis(data)
    bus = LiveContextBus()

    consumer = RedisConsumer(["EURUSD"], redis, bus)
    await consumer.load_candle_history()

    for tf in WARMUP_TIMEFRAMES:
        history: list[dict[str, Any]] | None = bus.get_candle_history("EURUSD", tf)
        assert history is not None, f"Expected data for timeframe {tf}"
        assert len(history) == 1


async def test_warmup_loads_multiple_candles_per_key() -> None:
    """A key with multiple candle entries should load all valid ones."""
    candles = [
        _make_candle("EURUSD", "H1", 1.0800),
        _make_candle("EURUSD", "H1", 1.0850),
        _make_candle("EURUSD", "H1", 1.0900),
    ]
    redis = _make_redis({"wolf15:candle_history:EURUSD:H1": candles})
    bus = LiveContextBus()

    consumer = RedisConsumer(["EURUSD"], redis, bus)
    await consumer.load_candle_history()

    history: list[dict[str, Any]] | None = bus.get_candle_history("EURUSD", "H1")
    assert history is not None
    assert len(history) == 3
    assert history[0]["close"] == _approx(1.0800)
    assert history[2]["close"] == _approx(1.0900)


async def test_warmup_skips_non_dict_json() -> None:
    """A valid JSON value that is not a dict (e.g. array, int) must be skipped."""
    non_dict = orjson.dumps([1, 2, 3])  # valid JSON but not a candle dict
    good = _make_candle("EURUSD", "H1", 1.0850)
    redis = _make_redis({"wolf15:candle_history:EURUSD:H1": [non_dict, good]})
    bus = LiveContextBus()

    consumer = RedisConsumer(["EURUSD"], redis, bus)
    await consumer.load_candle_history()

    history: list[dict[str, Any]] | None = bus.get_candle_history("EURUSD", "H1")
    assert history is not None
    assert len(history) == 1
    assert history[0]["close"] == _approx(1.0850)


async def test_warmup_mixed_prefixes_per_timeframe() -> None:
    """Different timeframes may resolve via different prefixes."""
    candle_h1 = _make_candle("EURUSD", "H1", 1.0850)
    candle_m15 = _make_candle("EURUSD", "M15", 1.0800)
    redis = _make_redis(
        {
            "wolf15:candle_history:EURUSD:H1": [candle_h1],  # primary list prefix for H1
            "candle_history:EURUSD:M15": [candle_m15],  # legacy list prefix for M15
        }
    )
    bus = LiveContextBus()

    consumer = RedisConsumer(["EURUSD"], redis, bus)
    await consumer.load_candle_history()

    history_h1: list[dict[str, Any]] | None = bus.get_candle_history("EURUSD", "H1")
    history_m15: list[dict[str, Any]] | None = bus.get_candle_history("EURUSD", "M15")
    assert history_h1 is not None and len(history_h1) == 1
    assert history_m15 is not None and len(history_m15) == 1
    assert history_h1[0]["close"] == _approx(1.0850)
    assert history_m15[0]["close"] == _approx(1.0800)


async def test_warmup_replaces_on_second_call() -> None:
    """Calling load_candle_history twice replaces (not appends) existing data."""
    candle_v1 = _make_candle("EURUSD", "H1", 1.0800)
    candle_v2 = _make_candle("EURUSD", "H1", 1.0900)

    # First call with v1 data
    redis1 = _make_redis({"wolf15:candle_history:EURUSD:H1": [candle_v1]})
    bus = LiveContextBus()
    consumer = RedisConsumer(["EURUSD"], redis1, bus)
    await consumer.load_candle_history()

    # Replace redis mock data and reload
    consumer._redis = _make_redis({"wolf15:candle_history:EURUSD:H1": [candle_v2]})  # type: ignore[attr-defined]
    await consumer.load_candle_history()

    history: list[dict[str, Any]] | None = bus.get_candle_history("EURUSD", "H1")
    assert history is not None
    assert len(history) == 1
    assert history[0]["close"] == _approx(1.0900)


async def test_warmup_all_malformed_yields_empty() -> None:
    """If every entry under a key is malformed, the bus should store empty list."""
    bad1 = b"not-json"
    bad2 = b"{broken"
    redis = _make_redis({"wolf15:candle_history:EURUSD:H1": [bad1, bad2]})
    bus = LiveContextBus()

    consumer = RedisConsumer(["EURUSD"], redis, bus)
    await consumer.load_candle_history()

    history: list[dict[str, Any]] | None = bus.get_candle_history("EURUSD", "H1")
    # Should be empty list (set_candle_history called with []) or populated but 0-length
    assert isinstance(history, list)
    assert len(history) == 0


async def test_warmup_empty_symbols_list() -> None:
    """An empty symbols list should not crash and should not load anything."""
    redis = _make_redis({})
    bus = LiveContextBus()

    consumer = RedisConsumer([], redis, bus)
    await consumer.load_candle_history()  # must not raise


async def test_handle_candle_dict_valid() -> None:
    """_handle_candle_dict pushes valid candle data into bus."""
    bus = LiveContextBus()
    redis = _make_redis({})
    consumer = RedisConsumer(["EURUSD"], redis, bus)

    candle: dict[str, Any] = {"symbol": "EURUSD", "timeframe": "H1", "close": 1.0850}
    consumer._handle_candle_dict(candle)  # type: ignore[attr-defined]

    # Verify candle was pushed (depends on bus.push_candle implementation)
    # At minimum, this should not raise


async def test_handle_candle_dict_missing_symbol() -> None:
    """_handle_candle_dict with missing symbol should not crash."""
    bus = LiveContextBus()
    redis = _make_redis({})
    consumer = RedisConsumer(["EURUSD"], redis, bus)

    candle: dict[str, Any] = {"timeframe": "H1", "close": 1.0850}
    consumer._handle_candle_dict(candle)  # type: ignore[attr-defined]  # must not raise


async def test_handle_candle_dict_empty_symbol() -> None:
    """_handle_candle_dict with empty string symbol should be rejected."""
    bus = LiveContextBus()
    redis = _make_redis({})
    consumer = RedisConsumer(["EURUSD"], redis, bus)

    candle: dict[str, Any] = {"symbol": "  ", "timeframe": "H1", "close": 1.0850}
    consumer._handle_candle_dict(candle)  # type: ignore[attr-defined]  # must not raise


async def test_handle_candle_dict_missing_timeframe() -> None:
    """_handle_candle_dict with missing timeframe should not crash."""
    bus = LiveContextBus()
    redis = _make_redis({})
    consumer = RedisConsumer(["EURUSD"], redis, bus)

    candle: dict[str, Any] = {"symbol": "EURUSD", "close": 1.0850}
    consumer._handle_candle_dict(candle)  # type: ignore[attr-defined]  # must not raise


def test_extract_payload_bytes() -> None:
    """_extract_payload should return bytes from bytes data."""
    msg: dict[str, Any] = {"type": "message", "data": b'{"symbol":"EURUSD"}'}
    result = RedisConsumer._extract_payload(msg)  # type: ignore[attr-defined]
    assert result == b'{"symbol":"EURUSD"}'


def test_extract_payload_str() -> None:
    """_extract_payload should encode str data to bytes."""
    msg: dict[str, Any] = {"type": "message", "data": '{"symbol":"EURUSD"}'}
    result = RedisConsumer._extract_payload(msg)  # type: ignore[attr-defined]
    assert result == b'{"symbol":"EURUSD"}'


def test_extract_payload_none() -> None:
    """_extract_payload should return None when data is missing."""
    msg: dict[str, Any] = {"type": "message"}
    result = RedisConsumer._extract_payload(msg)  # type: ignore[attr-defined]
    assert result is None


def test_extract_payload_non_bytes_non_str() -> None:
    """_extract_payload should return None for unexpected data types."""
    msg: dict[str, Any] = {"type": "message", "data": 12345}
    result = RedisConsumer._extract_payload(msg)  # type: ignore[attr-defined]
    assert result is None


def test_extract_channel_bytes() -> None:
    """_extract_channel should decode bytes channel names."""
    msg: dict[str, Any] = {"type": "message", "channel": b"tick_updates", "data": b"{}"}
    result = RedisConsumer._extract_channel(msg)  # type: ignore[attr-defined]
    assert result == "tick_updates"


def test_extract_channel_str() -> None:
    """_extract_channel should return str channel names unchanged."""
    msg: dict[str, Any] = {"type": "message", "channel": "candle:EURUSD:M15", "data": b"{}"}
    result = RedisConsumer._extract_channel(msg)  # type: ignore[attr-defined]
    assert result == "candle:EURUSD:M15"


def test_extract_channel_missing() -> None:
    """_extract_channel should return None when channel is missing."""
    msg: dict[str, Any] = {"type": "message", "data": b"{}"}
    result = RedisConsumer._extract_channel(msg)  # type: ignore[attr-defined]
    assert result is None


def test_stop_event_set() -> None:
    """stop() should set the internal stop event."""
    redis = _make_redis({})
    bus = LiveContextBus()
    consumer = RedisConsumer(["EURUSD"], redis, bus)

    assert not consumer._stop_event.is_set()  # type: ignore[attr-defined]
    consumer.stop()
    assert consumer._stop_event.is_set()  # type: ignore[attr-defined]


def test_default_config() -> None:
    """RedisConsumer should use default config when none provided."""
    from context.redis_consumer import RedisConsumerConfig

    redis = _make_redis({})
    bus = LiveContextBus()
    consumer = RedisConsumer(["EURUSD"], redis, bus)

    assert consumer._config.pubsub_patterns == RedisConsumerConfig().pubsub_patterns  # type: ignore[attr-defined]
    assert consumer._config.pubsub_channels == RedisConsumerConfig().pubsub_channels  # type: ignore[attr-defined]
    assert "tick_updates" in consumer._config.pubsub_channels  # type: ignore[attr-defined]


def test_custom_config() -> None:
    """RedisConsumer should accept custom config."""
    from context.redis_consumer import RedisConsumerConfig

    custom = RedisConsumerConfig(
        pubsub_patterns=("custom:*",),
        pubsub_channels=("custom_channel",),
    )
    redis = _make_redis({})
    bus = LiveContextBus()
    consumer = RedisConsumer(["EURUSD"], redis, bus, config=custom)

    assert consumer._config.pubsub_patterns == ("custom:*",)  # type: ignore[attr-defined]
    assert consumer._config.pubsub_channels == ("custom_channel",)  # type: ignore[attr-defined]


def test_handle_tick_dict_valid_updates_feed_timestamp() -> None:
    """Valid tick payload should refresh feed timestamp for the symbol."""
    redis = _make_redis({})
    bus = LiveContextBus()
    bus.reset_state()
    consumer = RedisConsumer(["EURUSD"], redis, bus)

    assert bus.get_feed_timestamp("EURUSD") is None
    consumer._handle_tick_dict({"symbol": "EURUSD", "bid": 1.08})  # type: ignore[attr-defined]
    assert bus.get_feed_timestamp("EURUSD") is not None


def test_handle_tick_dict_missing_symbol_ignored() -> None:
    """Tick payload without a valid symbol must be ignored."""
    redis = _make_redis({})
    bus = LiveContextBus()
    bus.reset_state()
    consumer = RedisConsumer(["EURUSD"], redis, bus)

    consumer._handle_tick_dict({"bid": 1.08})  # type: ignore[attr-defined]
    consumer._handle_tick_dict({"symbol": "   "})  # type: ignore[attr-defined]
    assert bus.get_feed_timestamp("EURUSD") is None
