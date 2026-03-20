"""
Tests for infrastructure/cross_instance_relay.py.

Validates: envelope format, self-message filtering, peer relay dispatch,
broadcast publishes to Redis, stop cleans up.

Uses mock Redis — no real server needed.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from infrastructure.cross_instance_relay import _INSTANCE_ID, CrossInstanceRelay
from state.pubsub_channels import WS_CROSS_INSTANCE_PREFIX


class FakeManager:
    """Minimal stand-in for ConnectionManager."""

    def __init__(self) -> None:
        self.broadcast = AsyncMock()


class TestCrossInstanceRelayBroadcast:
    """Test that broadcast() publishes to both local manager and Redis."""

    @pytest.mark.asyncio
    async def test_broadcast_calls_local_and_publishes(self) -> None:
        manager = FakeManager()
        mock_redis = AsyncMock()
        mock_redis.publish = AsyncMock()

        relay = CrossInstanceRelay(redis_client=mock_redis)
        relay._managers = {"prices": manager}
        relay._running = True

        msg = {"type": "PriceUpdated", "payload": {"EURUSD": 1.1234}}
        await relay.broadcast("prices", msg)

        # Local broadcast was called
        manager.broadcast.assert_awaited_once_with(msg)

        # Redis publish was called with correct channel and envelope
        expected_channel = f"{WS_CROSS_INSTANCE_PREFIX}prices"
        mock_redis.publish.assert_awaited_once()
        call_args = mock_redis.publish.call_args
        assert call_args[0][0] == expected_channel

        envelope = json.loads(call_args[0][1])
        assert envelope["instance"] == _INSTANCE_ID
        assert envelope["payload"] == msg

    @pytest.mark.asyncio
    async def test_broadcast_unknown_manager_still_publishes(self) -> None:
        mock_redis = AsyncMock()
        mock_redis.publish = AsyncMock()

        relay = CrossInstanceRelay(redis_client=mock_redis)
        relay._managers = {}
        relay._running = True

        msg = {"type": "tick"}
        await relay.broadcast("unknown_mgr", msg)

        # Redis publish still happens (peer instances may have this manager)
        mock_redis.publish.assert_awaited_once()


class TestCrossInstanceRelayFiltering:
    """Test that _listen filters out own-instance messages."""

    @pytest.mark.asyncio
    async def test_own_instance_messages_are_skipped(self) -> None:
        manager = FakeManager()
        relay = CrossInstanceRelay()
        relay._managers = {"prices": manager}
        relay._running = True

        # Simulate receiving our own message
        own_envelope = json.dumps({"instance": _INSTANCE_ID, "payload": {"x": 1}})

        # Create a mock pubsub that yields one message then stops
        mock_pubsub = AsyncMock()

        async def fake_listen():
            yield {
                "type": "message",
                "channel": f"{WS_CROSS_INSTANCE_PREFIX}prices",
                "data": own_envelope.encode(),
            }
            relay._running = False  # stop the loop

        mock_pubsub.listen = fake_listen
        relay._pubsub = mock_pubsub

        await relay._listen()

        # Manager should NOT have been called (own message filtered)
        manager.broadcast.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_peer_instance_messages_are_relayed(self) -> None:
        manager = FakeManager()
        relay = CrossInstanceRelay()
        relay._managers = {"trades": manager}
        relay._running = True

        peer_payload = {"type": "TradeUpdated", "trade_id": "abc"}
        peer_envelope = json.dumps({"instance": 99999, "payload": peer_payload})

        mock_pubsub = AsyncMock()

        async def fake_listen():
            yield {
                "type": "message",
                "channel": f"{WS_CROSS_INSTANCE_PREFIX}trades",
                "data": peer_envelope.encode(),
            }
            relay._running = False

        mock_pubsub.listen = fake_listen
        relay._pubsub = mock_pubsub

        await relay._listen()

        # Manager should have been called with the peer's payload
        manager.broadcast.assert_awaited_once_with(peer_payload)

    @pytest.mark.asyncio
    async def test_invalid_json_is_skipped(self) -> None:
        manager = FakeManager()
        relay = CrossInstanceRelay()
        relay._managers = {"risk": manager}
        relay._running = True

        mock_pubsub = AsyncMock()

        async def fake_listen():
            yield {
                "type": "message",
                "channel": f"{WS_CROSS_INSTANCE_PREFIX}risk",
                "data": b"not-valid-json{{{",
            }
            relay._running = False

        mock_pubsub.listen = fake_listen
        relay._pubsub = mock_pubsub

        await relay._listen()

        manager.broadcast.assert_not_awaited()


class TestCrossInstanceRelayStop:
    """Test cleanup on stop."""

    @pytest.mark.asyncio
    async def test_stop_cleans_up(self) -> None:
        relay = CrossInstanceRelay()
        mock_pubsub = AsyncMock()
        relay._pubsub = mock_pubsub
        relay._running = True

        dummy_task = asyncio.create_task(asyncio.sleep(100))
        relay._listener_task = dummy_task

        await relay.stop()

        assert relay._running is False
        mock_pubsub.unsubscribe.assert_awaited_once()
        mock_pubsub.aclose.assert_awaited_once()
        assert relay._pubsub is None
        # Task gets cancel signal; await it to let CancelledError propagate
        with pytest.raises(asyncio.CancelledError):
            await dummy_task
