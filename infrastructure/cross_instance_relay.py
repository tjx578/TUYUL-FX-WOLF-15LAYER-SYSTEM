"""
Cross-instance WebSocket relay via Redis Pub/Sub.

Zone: infrastructure/ — message transport only, no business logic.

Problem:
  When the API service is horizontally scaled (N replicas), each instance
  has its own ``ConnectionManager`` with its own set of WebSocket clients.
  A ``broadcast()`` on instance A only reaches clients connected to A.

Solution:
  ``CrossInstanceRelay`` wraps a ``ConnectionManager`` to additionally
  publish every broadcast to a Redis Pub/Sub channel.  Each instance
  subscribes to peer broadcasts and relays them to its local manager.

  ⚠️  Redis Pub/Sub is ephemeral — messages during subscriber disconnect
  are lost.  This is acceptable because:
    1. WebSocket reconnects trigger replay_buffer (ring buffer per manager).
    2. Clients have stale detection + snapshot bootstrap.
    3. This relay is a best-effort fan-out for real-time push, not for
       durable delivery (use Redis Streams for that).

Usage (in ws_routes.py or app startup):
    from infrastructure.cross_instance_relay import CrossInstanceRelay

    relay = CrossInstanceRelay()
    await relay.start({"prices": price_manager, "trades": trade_manager, ...})
    # ... on shutdown:
    await relay.stop()

    # Instead of manager.broadcast(msg), use:
    await relay.broadcast("prices", msg)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

import redis.asyncio as aioredis

from infrastructure.redis_client import get_client
from state.pubsub_channels import WS_CROSS_INSTANCE_PREFIX

logger = logging.getLogger(__name__)

# Unique instance ID to avoid re-processing own messages
_INSTANCE_ID = os.getpid()


class CrossInstanceRelay:
    """
    Publish WS broadcasts to Redis Pub/Sub and subscribe to peer broadcasts.

    Each manager name maps to a dedicated channel:
        wolf15:ws:relay:{manager_name}

    Message format (JSON):
        {"instance": <pid>, "payload": <original broadcast dict>}

    Messages originating from this instance are ignored on receive.
    """

    def __init__(self, redis_client: aioredis.Redis | None = None) -> None:
        self._redis: aioredis.Redis | None = redis_client
        self._managers: dict[str, object] = {}  # name → ConnectionManager
        self._pubsub: aioredis.client.PubSub | None = None  # pyright: ignore[reportAttributeAccessIssue]
        self._listener_task: asyncio.Task[None] | None = None
        self._running = False

    async def _ensure_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = await get_client()
        return self._redis

    async def start(self, managers: dict[str, object]) -> None:
        """
        Begin listening for cross-instance broadcasts.

        Args:
            managers: Mapping of manager name → ConnectionManager instance.
                      Each manager must have an async ``broadcast`` method.
        """
        if self._running:
            return

        self._managers = managers
        self._running = True

        client = await self._ensure_redis()
        self._pubsub = client.pubsub()

        channels = [f"{WS_CROSS_INSTANCE_PREFIX}{name}" for name in managers]
        await self._pubsub.subscribe(*channels)  # pyright: ignore[reportOptionalMemberAccess]

        logger.info(
            "CrossInstanceRelay started: channels=%s, instance=%s",
            channels, _INSTANCE_ID,
        )

        self._listener_task = asyncio.create_task(self._listen())

    async def _listen(self) -> None:
        """Listen for peer broadcasts and relay to local managers."""
        assert self._pubsub is not None
        try:
            async for message in self._pubsub.listen():
                if not self._running:
                    break
                if message["type"] != "message":
                    continue

                channel = message["channel"]
                if isinstance(channel, bytes):
                    channel = channel.decode()

                data_raw = message["data"]
                if isinstance(data_raw, bytes):
                    data_raw = data_raw.decode()

                try:
                    envelope = json.loads(data_raw)
                except (json.JSONDecodeError, TypeError):
                    logger.debug("CrossInstanceRelay: invalid JSON, skipping")
                    continue

                # Skip own messages
                if envelope.get("instance") == _INSTANCE_ID:
                    continue

                payload = envelope.get("payload")
                if not isinstance(payload, dict):
                    continue

                # Extract manager name from channel suffix
                manager_name = channel.removeprefix(WS_CROSS_INSTANCE_PREFIX)
                manager = self._managers.get(manager_name)
                if manager is None:
                    continue

                # Relay to local clients (call broadcast directly to push + buffer)
                try:
                    broadcast_fn = getattr(manager, "broadcast", None)
                    if broadcast_fn is not None:
                        await broadcast_fn(payload)
                except Exception:
                    logger.exception(
                        "CrossInstanceRelay: relay failed for %s", manager_name,
                    )

        except asyncio.CancelledError:
            pass
        except Exception:
            if self._running:
                logger.exception("CrossInstanceRelay: listener crashed")

    async def broadcast(self, manager_name: str, message: dict) -> None:
        """
        Broadcast to local clients AND publish to Redis for peer instances.

        Call this instead of ``manager.broadcast(msg)`` when relay is active.
        """
        # Local broadcast first (low latency for our own clients)
        manager = self._managers.get(manager_name)
        if manager is not None:
            broadcast_fn = getattr(manager, "broadcast", None)
            if broadcast_fn is not None:
                await broadcast_fn(message)

        # Publish to Redis for peer instances
        client = await self._ensure_redis()
        channel = f"{WS_CROSS_INSTANCE_PREFIX}{manager_name}"
        envelope = json.dumps({"instance": _INSTANCE_ID, "payload": message})
        await client.publish(channel, envelope)

    async def stop(self) -> None:
        """Stop listening and clean up."""
        self._running = False
        if self._pubsub:
            await self._pubsub.unsubscribe()
            await self._pubsub.aclose()
            self._pubsub = None
        if self._listener_task and not self._listener_task.done():
            self._listener_task.cancel()
            self._listener_task = None
        logger.info("CrossInstanceRelay stopped")
