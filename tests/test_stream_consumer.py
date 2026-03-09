"""
Tests for infrastructure/stream_consumer.py.

Validates: XACK after processing, PEL recovery, exponential backoff integration,
dynamic consumer name, no run_in_executor.

Uses mock Redis — no real server needed.
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, patch

import pytest

from infrastructure.backoff import BackoffConfig
from infrastructure.consumer_identity import generate_consumer_name
from infrastructure.stream_consumer import (
    ConsumerConfig,
    StreamBinding,
    StreamConsumer,
    StreamPriority,
)

# ─── Consumer Identity ───────────────────────────────────────

class TestConsumerIdentity:
    def test_auto_generated(self) -> None:
        name = generate_consumer_name(prefix="test")
        assert name.startswith("test_")
        assert str(os.getpid()) in name

    def test_explicit_override(self) -> None:
        name = generate_consumer_name(prefix="x", override="custom_1")
        assert name == "custom_1"

    def test_env_override(self) -> None:
        with patch.dict(os.environ, {"REDIS_CONSUMER_NAME": "from_env"}):
            assert generate_consumer_name() == "from_env"

    def test_explicit_beats_env(self) -> None:
        with patch.dict(os.environ, {"REDIS_CONSUMER_NAME": "env"}):
            assert generate_consumer_name(override="explicit") == "explicit"

    def test_unique_across_prefixes(self) -> None:
        n1 = generate_consumer_name(prefix="engine")
        n2 = generate_consumer_name(prefix="dashboard")
        assert n1 != n2


# ─── Construction ─────────────────────────────────────────────

class TestStreamConsumerConstruction:
    def test_empty_bindings_raises(self) -> None:
        with pytest.raises(ValueError, match="At least one"):
            StreamConsumer(bindings=[])

    def test_dynamic_consumer_name(self) -> None:
        binding = StreamBinding(
            stream="s", group="g", callback=AsyncMock(),
        )
        consumer = StreamConsumer(
            bindings=[binding],
            config=ConsumerConfig(consumer_prefix="unit"),
        )
        assert consumer.consumer_name.startswith("unit_")

    def test_explicit_consumer_name(self) -> None:
        consumer = StreamConsumer(
            bindings=[StreamBinding(stream="s", group="g", callback=AsyncMock())],
            config=ConsumerConfig(consumer_name="fixed_42"),
        )
        assert consumer.consumer_name == "fixed_42"

    def test_initial_stats(self) -> None:
        consumer = StreamConsumer(
            bindings=[StreamBinding(stream="s", group="g", callback=AsyncMock())],
        )
        s = consumer.stats
        assert s["messages_processed"] == 0
        assert s["messages_acked"] == 0
        assert s["messages_failed"] == 0
        assert s["pending_recovered"] == 0
        assert s["reconnects"] == 0
        assert s["running"] is False

    def test_backoff_config_in_stats_log(self) -> None:
        """Ensure custom backoff config is accepted."""
        cfg = ConsumerConfig(
            backoff=BackoffConfig(initial=2.0, maximum=60.0, factor=3.0),
        )
        consumer = StreamConsumer(
            bindings=[StreamBinding(stream="s", group="g", callback=AsyncMock())],
            config=cfg,
        )
        assert consumer.stats["running"] is False  # Just verify no crash


# ─── XACK: Process + Acknowledge ─────────────────────────────

class TestProcessAndAck:
    """Core fix: XACK must happen after successful callback, not before."""

    @pytest.mark.asyncio
    async def test_success_calls_callback_then_xack(self) -> None:
        callback = AsyncMock()
        mock_redis = AsyncMock()
        mock_redis.xack = AsyncMock(return_value=1)

        binding = StreamBinding(
            stream="signals:l12",
            group="engine_grp",
            callback=callback,
        )
        consumer = StreamConsumer(
            bindings=[binding],
            redis_client=mock_redis,
        )

        success = await consumer._process_and_ack(
            binding, "1700000000000-0",
            {"symbol": "EURUSD", "verdict": "EXECUTE", "confidence": "0.88"},
        )

        assert success is True

        # Callback called with correct args
        callback.assert_awaited_once_with(
            "signals:l12",
            "1700000000000-0",
            {"symbol": "EURUSD", "verdict": "EXECUTE", "confidence": "0.88"},
        )

        # XACK called with stream, group, message_id
        mock_redis.xack.assert_awaited_once_with(
            "signals:l12", "engine_grp", "1700000000000-0",
        )

        assert consumer.stats["messages_processed"] == 1
        assert consumer.stats["messages_acked"] == 1
        assert consumer.stats["messages_failed"] == 0

    @pytest.mark.asyncio
    async def test_callback_failure_no_xack(self) -> None:
        """If callback raises, message must NOT be ACK'd (stays in PEL)."""
        callback = AsyncMock(side_effect=ValueError("bad data"))
        mock_redis = AsyncMock()
        mock_redis.xack = AsyncMock()

        binding = StreamBinding(
            stream="candles:m1", group="grp", callback=callback,
        )
        consumer = StreamConsumer(
            bindings=[binding], redis_client=mock_redis,
        )

        success = await consumer._process_and_ack(
            binding, "msg-001", {"symbol": "GBPUSD"},
        )

        assert success is False
        mock_redis.xack.assert_not_awaited()  # Critical: no ACK
        assert consumer.stats["messages_failed"] == 1
        assert consumer.stats["messages_acked"] == 0

    @pytest.mark.asyncio
    async def test_multiple_messages_independent_ack(self) -> None:
        """Each message gets its own ACK — failure of one doesn't block others."""
        call_count = 0

        async def selective_callback(
            stream: str, msg_id: str, fields: dict[str, str],
        ) -> None:
            nonlocal call_count
            call_count += 1
            if fields.get("fail") == "true":
                raise RuntimeError("selective failure")

        mock_redis = AsyncMock()
        mock_redis.xack = AsyncMock(return_value=1)

        binding = StreamBinding(
            stream="s", group="g", callback=selective_callback,
        )
        consumer = StreamConsumer(
            bindings=[binding], redis_client=mock_redis,
        )

        r1 = await consumer._process_and_ack(
            binding, "1", {"symbol": "A"},
        )
        r2 = await consumer._process_and_ack(
            binding, "2", {"symbol": "B", "fail": "true"},
        )
        r3 = await consumer._process_and_ack(
            binding, "3", {"symbol": "C"},
        )

        assert r1 is True
        assert r2 is False
        assert r3 is True
        assert consumer.stats["messages_acked"] == 2
        assert consumer.stats["messages_failed"] == 1
        assert mock_redis.xack.await_count == 2  # Only 2 ACKs, not 3


# ─── PEL Recovery ────────────────────────────────────────────

class TestPELRecovery:
    @pytest.mark.asyncio
    async def test_recovers_pending_messages(self) -> None:
        callback = AsyncMock()
        mock_redis = AsyncMock()
        mock_redis.xreadgroup = AsyncMock(return_value=[
            ("signals:l12", [
                ("aaa-0", {"symbol": "EURUSD", "verdict": "EXECUTE"}),
                ("bbb-0", {"symbol": "GBPUSD", "verdict": "HOLD"}),
            ]),
        ])
        mock_redis.xack = AsyncMock(return_value=1)

        binding = StreamBinding(
            stream="signals:l12", group="grp", callback=callback,
        )
        consumer = StreamConsumer(
            bindings=[binding], redis_client=mock_redis,
        )

        recovered = await consumer._recover_pending(binding)

        assert recovered == 2
        assert callback.await_count == 2
        assert mock_redis.xack.await_count == 2
        assert consumer.stats["pending_recovered"] == 2

    @pytest.mark.asyncio
    async def test_empty_pel_returns_zero(self) -> None:
        mock_redis = AsyncMock()
        mock_redis.xreadgroup = AsyncMock(return_value=[])

        binding = StreamBinding(
            stream="s", group="g", callback=AsyncMock(),
        )
        consumer = StreamConsumer(
            bindings=[binding], redis_client=mock_redis,
        )

        assert await consumer._recover_pending(binding) == 0

    @pytest.mark.asyncio
    async def test_empty_fields_acked_without_callback(self) -> None:
        """Messages with empty fields (already delivered) should just be ACK'd."""
        callback = AsyncMock()
        mock_redis = AsyncMock()
        mock_redis.xreadgroup = AsyncMock(return_value=[
            ("s", [
                ("ghost-0", {}),  # Empty fields
                ("real-0", {"data": "value"}),  # Real message
            ]),
        ])
        mock_redis.xack = AsyncMock(return_value=1)

        binding = StreamBinding(stream="s", group="g", callback=callback)
        consumer = StreamConsumer(
            bindings=[binding], redis_client=mock_redis,
        )

        recovered = await consumer._recover_pending(binding)

        assert recovered == 1  # Only the real message counts
        assert callback.await_count == 1  # Ghost not sent to callback
        assert mock_redis.xack.await_count == 2  # Both ACK'd


class TestReplaySemantics:
    @pytest.mark.asyncio
    async def test_replay_group_history_replays_and_acks(self) -> None:
        callback = AsyncMock()
        mock_redis = AsyncMock()
        mock_redis.xgroup_setid = AsyncMock(return_value=True)
        mock_redis.xreadgroup = AsyncMock(side_effect=[
            [("signals:l12", [("1-0", {"symbol": "EURUSD"})])],
            [],
        ])
        mock_redis.xack = AsyncMock(return_value=1)

        binding = StreamBinding(stream="signals:l12", group="grp", callback=callback)
        consumer = StreamConsumer(
            bindings=[binding],
            redis_client=mock_redis,
            config=ConsumerConfig(replay_start_id="0-0", replay_max_messages=10),
        )
        consumer._running = True

        replayed = await consumer._replay_group_history(binding)

        assert replayed == 1
        assert consumer.stats["replayed_messages"] == 1
        callback.assert_awaited_once()
        mock_redis.xgroup_setid.assert_awaited_once_with(
            name="signals:l12",
            groupname="grp",
            id="0-0",
        )
        mock_redis.xack.assert_awaited_once_with("signals:l12", "grp", "1-0")


# ─── Stream Priority ─────────────────────────────────────────

class TestStreamPriority:
    def test_default_is_important(self) -> None:
        b = StreamBinding(stream="s", group="g", callback=AsyncMock())
        assert b.priority == StreamPriority.IMPORTANT

    def test_critical(self) -> None:
        b = StreamBinding(
            stream="s", group="g", callback=AsyncMock(),
            priority=StreamPriority.CRITICAL,
        )
        assert b.priority == StreamPriority.CRITICAL

    def test_ephemeral(self) -> None:
        b = StreamBinding(
            stream="s", group="g", callback=AsyncMock(),
            priority=StreamPriority.EPHEMERAL,
        )
        assert b.priority == StreamPriority.EPHEMERAL


# ─── Lifecycle ────────────────────────────────────────────────

class TestLifecycle:
    @pytest.mark.asyncio
    async def test_stop_clears_running(self) -> None:
        consumer = StreamConsumer(
            bindings=[StreamBinding(stream="s", group="g", callback=AsyncMock())],
        )
        consumer._running = True
        await consumer.stop()
        assert consumer._running is False
        assert consumer.stats["running"] is False

    @pytest.mark.asyncio
    async def test_stop_cancels_tasks(self) -> None:
        consumer = StreamConsumer(
            bindings=[StreamBinding(stream="s", group="g", callback=AsyncMock())],
        )
        consumer._running = True

        # Create a mock task
        async def hang_forever() -> None:
            await asyncio.sleep(3600)

        task = asyncio.create_task(hang_forever())
        consumer._tasks = [task]

        await consumer.stop()
        assert task.cancelled() or task.done()
        assert len(consumer._tasks) == 0
