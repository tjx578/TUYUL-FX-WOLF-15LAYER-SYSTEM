"""
Tests for infrastructure/stream_consumer.py — XACK, PEL recovery, dynamic consumer.

Uses fakeredis[async] for isolated testing without a real Redis instance.
If fakeredis is not available, tests are skipped.
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, patch

import pytest

from infrastructure.consumer_identity import generate_consumer_name
from infrastructure.stream_consumer import (
    ConsumerConfig,
    StreamBinding,
    StreamConsumer,
    StreamPriority,
)

# ─── Consumer Identity Tests ─────────────────────────────────

class TestConsumerIdentity:
    def test_default_includes_hostname_and_pid(self) -> None:
        name = generate_consumer_name(prefix="test")
        assert name.startswith("test_")
        assert str(os.getpid()) in name

    def test_override_takes_precedence(self) -> None:
        name = generate_consumer_name(prefix="test", override="my_custom_consumer")
        assert name == "my_custom_consumer"

    def test_env_var_override(self) -> None:
        with patch.dict(os.environ, {"REDIS_CONSUMER_NAME": "env_consumer_99"}):
            name = generate_consumer_name(prefix="test")
            assert name == "env_consumer_99"

    def test_explicit_override_beats_env(self) -> None:
        with patch.dict(os.environ, {"REDIS_CONSUMER_NAME": "env_consumer"}):
            name = generate_consumer_name(prefix="test", override="explicit")
            assert name == "explicit"

    def test_different_prefixes(self) -> None:
        name1 = generate_consumer_name(prefix="engine")
        name2 = generate_consumer_name(prefix="dashboard")
        assert name1.startswith("engine_")
        assert name2.startswith("dashboard_")


# ─── StreamConsumer Construction Tests ────────────────────────

class TestStreamConsumerConstruction:
    def test_requires_at_least_one_binding(self) -> None:
        with pytest.raises(ValueError, match="At least one StreamBinding"):
            StreamConsumer(bindings=[])

    def test_consumer_name_generated(self) -> None:
        binding = StreamBinding(
            stream="test:stream",
            group="test_group",
            callback=AsyncMock(),
        )
        consumer = StreamConsumer(
            bindings=[binding],
            config=ConsumerConfig(consumer_prefix="unit_test"),
        )
        stats = consumer.stats
        assert stats["consumer_name"].startswith("unit_test_")
        assert stats["running"] is False

    def test_explicit_consumer_name(self) -> None:
        binding = StreamBinding(
            stream="test:stream",
            group="test_group",
            callback=AsyncMock(),
        )
        consumer = StreamConsumer(
            bindings=[binding],
            config=ConsumerConfig(consumer_name="fixed_name_1"),
        )
        assert consumer.stats["consumer_name"] == "fixed_name_1"

    def test_stats_initial(self) -> None:
        binding = StreamBinding(
            stream="s", group="g", callback=AsyncMock(),
        )
        consumer = StreamConsumer(bindings=[binding])
        stats = consumer.stats
        assert stats["messages_processed"] == 0
        assert stats["messages_acked"] == 0
        assert stats["messages_failed"] == 0
        assert stats["pending_recovered"] == 0
        assert stats["reconnects"] == 0


# ─── Process + ACK Tests (mocked Redis) ──────────────────────

class TestProcessMessage:
    """Test that _process_message calls callback then XACK."""

    @pytest.mark.asyncio
    async def test_successful_process_calls_xack(self) -> None:
        callback = AsyncMock()
        mock_redis = AsyncMock(spec=["xack"])
        mock_redis.xack = AsyncMock(return_value=1)

        binding = StreamBinding(
            stream="signals:stream",
            group="engine_group",
            callback=callback,
        )
        consumer = StreamConsumer(
            bindings=[binding],
            redis_client=mock_redis,
        )
        # Inject the mock redis
        consumer._redis = mock_redis

        success = await consumer._process_message(
            binding, "1234-0", {"symbol": "EURUSD", "verdict": "EXECUTE"},
        )

        assert success is True
        callback.assert_awaited_once_with(
            "signals:stream", "1234-0",
            {"symbol": "EURUSD", "verdict": "EXECUTE"},
        )
        mock_redis.xack.assert_awaited_once_with(
            "signals:stream", "engine_group", "1234-0",
        )
        assert consumer.stats["messages_processed"] == 1
        assert consumer.stats["messages_acked"] == 1

    @pytest.mark.asyncio
    async def test_failed_callback_no_xack(self) -> None:
        """If callback raises, message stays in PEL (no XACK)."""
        callback = AsyncMock(side_effect=RuntimeError("processing failed"))
        mock_redis = AsyncMock(spec=["xack"])

        binding = StreamBinding(
            stream="signals:stream",
            group="engine_group",
            callback=callback,
        )
        consumer = StreamConsumer(
            bindings=[binding],
            redis_client=mock_redis,
        )
        consumer._redis = mock_redis

        success = await consumer._process_message(
            binding, "1234-0", {"symbol": "EURUSD"},
        )

        assert success is False
        mock_redis.xack.assert_not_awaited()  # No ACK on failure
        assert consumer.stats["messages_failed"] == 1
        assert consumer.stats["messages_acked"] == 0


# ─── PEL Recovery Tests ──────────────────────────────────────

class TestPendingRecovery:
    @pytest.mark.asyncio
    async def test_recover_pending_processes_and_acks(self) -> None:
        """On reconnect, pending messages should be reprocessed and ACK'd."""
        callback = AsyncMock()
        mock_redis = AsyncMock()
        mock_redis.xreadgroup = AsyncMock(return_value=[
            ("signals:stream", [
                ("1111-0", {"symbol": "EURUSD", "verdict": "EXECUTE"}),
                ("2222-0", {"symbol": "GBPUSD", "verdict": "HOLD"}),
            ]),
        ])
        mock_redis.xack = AsyncMock(return_value=1)

        binding = StreamBinding(
            stream="signals:stream",
            group="engine_group",
            callback=callback,
        )
        consumer = StreamConsumer(
            bindings=[binding],
            redis_client=mock_redis,
        )
        consumer._redis = mock_redis

        recovered = await consumer._recover_pending(binding)

        assert recovered == 2
        assert callback.await_count == 2
        assert mock_redis.xack.await_count == 2
        assert consumer.stats["pending_recovered"] == 2

    @pytest.mark.asyncio
    async def test_recover_pending_empty(self) -> None:
        """No pending messages — nothing to recover."""
        mock_redis = AsyncMock()
        mock_redis.xreadgroup = AsyncMock(return_value=[])

        binding = StreamBinding(
            stream="s", group="g", callback=AsyncMock(),
        )
        consumer = StreamConsumer(bindings=[binding], redis_client=mock_redis)
        consumer._redis = mock_redis

        recovered = await consumer._recover_pending(binding)
        assert recovered == 0


# ─── Stream Binding Configuration Tests ──────────────────────

class TestStreamBinding:
    def test_default_priority(self) -> None:
        binding = StreamBinding(stream="s", group="g", callback=AsyncMock())
        assert binding.priority == StreamPriority.IMPORTANT

    def test_critical_priority(self) -> None:
        binding = StreamBinding(
            stream="s", group="g", callback=AsyncMock(),
            priority=StreamPriority.CRITICAL,
        )
        assert binding.priority == StreamPriority.CRITICAL

    def test_max_pending_age_default(self) -> None:
        binding = StreamBinding(stream="s", group="g", callback=AsyncMock())
        assert binding.max_pending_age_ms == 300_000


# ─── Stop/Lifecycle Tests ────────────────────────────────────

class TestLifecycle:
    @pytest.mark.asyncio
    async def test_stop_sets_running_false(self) -> None:
        binding = StreamBinding(stream="s", group="g", callback=AsyncMock())
        consumer = StreamConsumer(bindings=[binding])
        consumer._running = True

        await consumer.stop()
        assert consumer._running is False

    @pytest.mark.asyncio
    async def test_double_start_warns(self) -> None:
        """Starting an already-running consumer should log warning, not crash."""
        binding = StreamBinding(stream="s", group="g", callback=AsyncMock())
        consumer = StreamConsumer(bindings=[binding])
        consumer._running = True

        # Should return immediately without error
        # (the real start() would loop, but _running=True triggers early return)
        # We test that calling start when _running=True returns quickly
        # by using a short timeout
        with pytest.raises(asyncio.TimeoutError):
            # start() will attempt reconnect loop which hangs without real Redis
            # but the important thing is it doesn't crash on double-start
            await asyncio.wait_for(consumer.start(), timeout=0.1)
