"""Tests for stale data / death spiral fixes.

Covers:
  - FIX 1: _feed_staleness_seconds reads correct Redis hash key
  - FIX 2: Kill switch auto-recovery when feed becomes fresh again
  - FIX 4: set_verdict publishes to Redis Stream (durable) in addition to pub/sub
  - FIX 5: load_candle_history_with_retry retries until data available
"""

from __future__ import annotations

import json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ═══════════════════════════════════════════════════════════════════
# FIX 1: _feed_staleness_seconds key mismatch
# ═══════════════════════════════════════════════════════════════════


class TestFeedStalenessSecondsKeyFix:
    """_feed_staleness_seconds must read wolf15:latest_tick:{pair} (Hash HGET)."""

    @pytest.mark.asyncio
    async def test_returns_inf_when_no_pair_given(self) -> None:
        """Empty pair → inf (cannot determine staleness without symbol)."""
        from api.allocation_router import _feed_staleness_seconds  # type: ignore[attr-defined]

        result = await _feed_staleness_seconds("")
        assert result == float("inf")

    @pytest.mark.asyncio
    async def test_reads_wolf15_hash_key_not_ctx_tick_latest(self) -> None:
        """Must use HGET wolf15:latest_tick:{pair} data, NOT GET ctx:tick:latest."""
        from api.allocation_router import _feed_staleness_seconds  # type: ignore[attr-defined]

        tick_ts = time.time() - 5.0  # 5 s ago → fresh
        tick_json = json.dumps({"symbol": "EURUSD", "timestamp": tick_ts})

        mock_redis = AsyncMock()
        # HGET should return the JSON; old GET ctx:tick:latest would return None
        mock_redis.hget = AsyncMock(return_value=tick_json.encode())

        with patch("api.allocation_router.get_client", new=AsyncMock(return_value=mock_redis)):
            result = await _feed_staleness_seconds("EURUSD")

        assert result == pytest.approx(5.0, abs=1.0)
        mock_redis.hget.assert_called_once_with("wolf15:latest_tick:EURUSD", "data")

    @pytest.mark.asyncio
    async def test_returns_inf_when_hash_key_missing(self) -> None:
        """Expired/missing key (None from HGET) → inf."""
        from api.allocation_router import _feed_staleness_seconds  # type: ignore[attr-defined]

        mock_redis = AsyncMock()
        mock_redis.hget = AsyncMock(return_value=None)

        with patch("api.allocation_router.get_client", new=AsyncMock(return_value=mock_redis)):
            result = await _feed_staleness_seconds("EURUSD")

        assert result == float("inf")

    @pytest.mark.asyncio
    async def test_returns_inf_when_timestamp_is_zero(self) -> None:
        """Tick with timestamp=0 → inf (invalid data)."""
        from api.allocation_router import _feed_staleness_seconds  # type: ignore[attr-defined]

        tick_json = json.dumps({"symbol": "EURUSD", "timestamp": 0.0})
        mock_redis = AsyncMock()
        mock_redis.hget = AsyncMock(return_value=tick_json.encode())

        with patch("api.allocation_router.get_client", new=AsyncMock(return_value=mock_redis)):
            result = await _feed_staleness_seconds("EURUSD")

        assert result == float("inf")

    @pytest.mark.asyncio
    async def test_returns_inf_on_redis_exception(self) -> None:
        """Redis error → inf (fail safe)."""
        from api.allocation_router import _feed_staleness_seconds  # type: ignore[attr-defined]

        mock_redis = AsyncMock()
        mock_redis.hget = AsyncMock(side_effect=ConnectionError("Redis down"))

        with patch("api.allocation_router.get_client", new=AsyncMock(return_value=mock_redis)):
            result = await _feed_staleness_seconds("EURUSD")

        assert result == float("inf")

    @pytest.mark.asyncio
    async def test_never_reads_old_ctx_tick_latest_key(self) -> None:
        """The old broken key ctx:tick:latest must never be accessed."""
        from api.allocation_router import _feed_staleness_seconds  # type: ignore[attr-defined]

        mock_redis = AsyncMock()
        mock_redis.hget = AsyncMock(return_value=None)
        mock_redis.get = AsyncMock(return_value=None)  # should never be called

        with patch("api.allocation_router.get_client", new=AsyncMock(return_value=mock_redis)):
            await _feed_staleness_seconds("GBPUSD")

        mock_redis.get.assert_not_called()


# ═══════════════════════════════════════════════════════════════════
# FIX 2: Kill switch auto-recovery
# ═══════════════════════════════════════════════════════════════════


def _make_fresh_kill_switch(monkeypatch: Any) -> Any:
    """Reset the singleton and patch out Redis calls."""
    from risk.kill_switch import GlobalKillSwitch

    GlobalKillSwitch._instance = None
    monkeypatch.setenv("STALE_DATA_THRESHOLD_SEC", "60")
    monkeypatch.setattr("risk.kill_switch.redis_client.get", lambda *_a, **_kw: None)
    monkeypatch.setattr("risk.kill_switch.redis_client.set", lambda *_a, **_kw: None)
    return GlobalKillSwitch()


class TestKillSwitchAutoRecovery:
    """evaluate_and_trip must auto-disable when feed was stale but is now fresh."""

    def test_auto_trips_on_stale_feed(self, monkeypatch: Any) -> None:
        """Feed stale ≥ threshold → enabled."""
        ks = _make_fresh_kill_switch(monkeypatch)
        ks.disable("RESET")
        result = ks.evaluate_and_trip(metrics={"feed_stale_seconds": 999.0})
        assert result["enabled"] is True
        assert "AUTO_FEED_STALE" in str(result["reason"])

    def test_auto_recovery_when_feed_fresh(self, monkeypatch: Any) -> None:
        """Kill switch enabled by feed-stale → auto-disabled when feed recovers."""
        ks = _make_fresh_kill_switch(monkeypatch)
        ks.disable("RESET")
        # Trip by stale feed
        ks.evaluate_and_trip(metrics={"feed_stale_seconds": 999.0})
        assert ks.is_enabled() is True
        # Feed recovers to < 50% of threshold (threshold default 60s → < 30s)
        result = ks.evaluate_and_trip(metrics={"feed_stale_seconds": 5.0})
        assert result["enabled"] is False
        assert "AUTO_RECOVERY" in str(result["reason"])

    def test_no_recovery_below_hysteresis_band(self, monkeypatch: Any) -> None:
        """Feed at exactly 50 % of threshold is NOT recovered (hysteresis < 0.5×)."""
        ks = _make_fresh_kill_switch(monkeypatch)
        ks.disable("RESET")
        # Trip with stale feed (threshold = 60s default)
        ks.evaluate_and_trip(metrics={"feed_stale_seconds": 61.0})
        assert ks.is_enabled() is True
        # 30 s = exactly 50 % → should NOT recover (condition is strictly <)
        result = ks.evaluate_and_trip(metrics={"feed_stale_seconds": 30.0})
        assert result["enabled"] is True

    def test_recovery_requires_auto_feed_stale_reason(self, monkeypatch: Any) -> None:
        """Manual enable must NOT be auto-reversed by feed recovery."""
        ks = _make_fresh_kill_switch(monkeypatch)
        ks.enable("MANUAL_TEST")
        # Feed is fresh — but reason is MANUAL, not AUTO_FEED_STALE
        result = ks.evaluate_and_trip(metrics={"feed_stale_seconds": 1.0})
        assert result["enabled"] is True

    def test_still_trips_for_dd_breach_even_if_feed_fresh(self, monkeypatch: Any) -> None:
        """Daily DD breach must still trip even when feed is fresh."""
        ks = _make_fresh_kill_switch(monkeypatch)
        ks.disable("RESET")
        result = ks.evaluate_and_trip(
            metrics={"daily_dd_percent": 99.0, "feed_stale_seconds": 1.0}
        )
        assert result["enabled"] is True
        assert "AUTO_DAILY_DD_BREACH" in str(result["reason"])

    def test_snapshot_unchanged_when_no_conditions_met(self, monkeypatch: Any) -> None:
        """When no thresholds breached and not auto-recoverable → snapshot returned."""
        ks = _make_fresh_kill_switch(monkeypatch)
        ks.disable("RESET")
        result = ks.evaluate_and_trip(metrics={"feed_stale_seconds": 0.0})
        assert result["enabled"] is False


# ═══════════════════════════════════════════════════════════════════
# FIX 4: set_verdict publishes to Redis Stream
# ═══════════════════════════════════════════════════════════════════


class TestSetVerdictRedisStream:
    """set_verdict must write to Redis Stream (durable) in addition to pub/sub."""

    def test_set_verdict_calls_xadd(self) -> None:
        """set_verdict must call redis.xadd with VERDICT_STREAM key."""
        from storage.l12_cache import VERDICT_STREAM, set_verdict

        xadd_calls: list[tuple[Any, ...]] = []

        mock_client = MagicMock()
        mock_client.set = MagicMock()
        mock_client.xadd = MagicMock(side_effect=lambda *a, **kw: xadd_calls.append((a, kw)))
        mock_client.publish = MagicMock()

        with patch("storage.l12_cache.redis_client", mock_client):
            set_verdict("EURUSD", {"verdict": "HOLD", "confidence": 0.8})

        assert len(xadd_calls) == 1, "xadd must be called exactly once"
        stream_key = xadd_calls[0][0][0]
        assert stream_key == VERDICT_STREAM

    def test_set_verdict_stream_payload_contains_pair(self) -> None:
        """Stream entry must include pair field for consumer routing."""
        from storage.l12_cache import set_verdict

        mock_client = MagicMock()
        mock_client.set = MagicMock()
        xadd_payload: dict[str, Any] = {}
        mock_client.xadd = MagicMock(side_effect=lambda _k, d, **_kw: xadd_payload.update(d))
        mock_client.publish = MagicMock()

        with patch("storage.l12_cache.redis_client", mock_client):
            set_verdict("GBPUSD", {"verdict": "EXECUTE", "confidence": 0.9})

        assert xadd_payload.get("pair") == "GBPUSD"

    def test_set_verdict_still_publishes_pubsub(self) -> None:
        """Pub/Sub publish must still be called for backward compat."""
        from storage.l12_cache import VERDICT_READY_CHANNEL, set_verdict

        mock_client = MagicMock()
        mock_client.set = MagicMock()
        mock_client.xadd = MagicMock()
        mock_client.publish = MagicMock()

        with patch("storage.l12_cache.redis_client", mock_client):
            set_verdict("EURUSD", {"verdict": "HOLD", "confidence": 0.5})

        mock_client.publish.assert_called_once()
        channel_arg = mock_client.publish.call_args[0][0]
        assert channel_arg == VERDICT_READY_CHANNEL

    def test_set_verdict_xadd_failure_does_not_raise(self) -> None:
        """xadd failure must be silently suppressed — pub/sub still fires."""
        from storage.l12_cache import set_verdict

        mock_client = MagicMock()
        mock_client.set = MagicMock()
        mock_client.xadd = MagicMock(side_effect=Exception("Stream unavailable"))
        mock_client.publish = MagicMock()

        with patch("storage.l12_cache.redis_client", mock_client):
            # Must not raise
            set_verdict("EURUSD", {"verdict": "HOLD", "confidence": 0.5})

        mock_client.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_verdict_async_calls_xadd(self) -> None:
        """set_verdict_async must also publish to Redis Stream."""
        from storage.l12_cache import VERDICT_STREAM, set_verdict_async

        xadd_calls: list[tuple[Any, ...]] = []

        mock_client = AsyncMock()
        mock_client.set = AsyncMock()
        mock_client.xadd = AsyncMock(side_effect=lambda *a, **kw: xadd_calls.append((a, kw)))
        mock_client.publish = AsyncMock()

        with patch("storage.l12_cache.get_client", new=AsyncMock(return_value=mock_client)):
            await set_verdict_async("EURUSD", {"verdict": "HOLD", "confidence": 0.7})

        assert len(xadd_calls) == 1
        stream_key = xadd_calls[0][0][0]
        assert stream_key == VERDICT_STREAM


# ═══════════════════════════════════════════════════════════════════
# FIX 5: load_candle_history_with_retry
# ═══════════════════════════════════════════════════════════════════


class TestLoadCandleHistoryWithRetry:
    """load_candle_history_with_retry retries warmup until data appears."""

    @pytest.fixture()
    def fresh_bus(self):
        from context.live_context_bus import LiveContextBus

        LiveContextBus._instance = None  # type: ignore[assignment]
        bus = LiveContextBus()
        yield bus
        LiveContextBus._instance = None  # type: ignore[assignment]

    @pytest.mark.asyncio
    async def test_returns_true_on_first_attempt(self, fresh_bus) -> None:
        """If data is available immediately, returns True on first call."""
        import orjson

        from context.redis_consumer import RedisConsumer

        candles = [
            {
                "symbol": "EURUSD",
                "timeframe": "H1",
                "open": 1.1,
                "high": 1.11,
                "low": 1.09,
                "close": 1.105,
                "volume": 100,
                "timestamp": "2024-01-01T00:00:00+00:00",
            }
            for _ in range(25)
        ]
        serialized = [orjson.dumps(c) for c in candles]

        mock_redis = AsyncMock()

        async def mock_lrange(key: str, start: int, end: int) -> list[bytes]:
            if "candle_history:EURUSD:H1" in key:
                return serialized
            return []

        mock_redis.lrange = AsyncMock(side_effect=mock_lrange)

        consumer = RedisConsumer(
            symbols=["EURUSD"],
            redis_client=mock_redis,
            context_bus=fresh_bus,
        )
        result = await consumer.load_candle_history_with_retry(max_retries=3, base_delay=0.01)
        assert result is True

    @pytest.mark.asyncio
    async def test_retries_and_returns_true_when_data_appears(self, fresh_bus) -> None:
        """Returns True when data appears on a later retry attempt."""
        import orjson

        from context.redis_consumer import RedisConsumer

        call_count = {"n": 0}
        candles = [
            {
                "symbol": "EURUSD",
                "timeframe": "H1",
                "open": 1.1,
                "high": 1.11,
                "low": 1.09,
                "close": 1.105,
                "volume": 100,
                "timestamp": "2024-01-01T00:00:00+00:00",
            }
            for _ in range(20)
        ]
        serialized = [orjson.dumps(c) for c in candles]

        async def mock_lrange(key: str, start: int, end: int) -> list[bytes]:
            call_count["n"] += 1
            # Return data only after first attempt
            if call_count["n"] > 1 and "candle_history:EURUSD:H1" in key:
                return serialized
            return []

        mock_redis = AsyncMock()
        mock_redis.lrange = AsyncMock(side_effect=mock_lrange)

        consumer = RedisConsumer(
            symbols=["EURUSD"],
            redis_client=mock_redis,
            context_bus=fresh_bus,
        )
        result = await consumer.load_candle_history_with_retry(max_retries=5, base_delay=0.01)
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_max_retries_exhausted(self, fresh_bus) -> None:
        """Returns False after all retries without data."""
        from context.redis_consumer import RedisConsumer

        mock_redis = AsyncMock()
        mock_redis.lrange = AsyncMock(return_value=[])

        consumer = RedisConsumer(
            symbols=["EURUSD"],
            redis_client=mock_redis,
            context_bus=fresh_bus,
        )
        result = await consumer.load_candle_history_with_retry(max_retries=2, base_delay=0.01)
        assert result is False

    @pytest.mark.asyncio
    async def test_method_exists_and_is_async(self, fresh_bus) -> None:
        """RedisConsumer exposes load_candle_history_with_retry as a coroutine."""
        import inspect

        from context.redis_consumer import RedisConsumer

        mock_redis = AsyncMock()
        mock_redis.lrange = AsyncMock(return_value=[])

        consumer = RedisConsumer(
            symbols=["EURUSD"],
            redis_client=mock_redis,
            context_bus=fresh_bus,
        )
        assert hasattr(consumer, "load_candle_history_with_retry")
        assert inspect.iscoroutinefunction(consumer.load_candle_history_with_retry)
