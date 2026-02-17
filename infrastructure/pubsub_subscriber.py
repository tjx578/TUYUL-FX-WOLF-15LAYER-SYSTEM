"""
Redis Pub/Sub subscriber — ONLY for ephemeral notifications.

Zone: infrastructure/ — message transport only.

IMPORTANT: Pub/Sub is fire-and-forget. Messages during disconnect are LOST.
Use this ONLY for:
- Heartbeats
- Cache invalidation signals
- Status notifications

For critical data (candles, signals, news), use StreamConsumer instead.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

import redis.asyncio as aioredis

from infrastructure.redis_client import get_client

logger = logging.getLogger(__name__)


class PubSubSubscriber:
    """
    Async Pub/Sub subscriber for ephemeral notifications only.

    WARNING: Messages during disconnect are lost. For durable delivery,
    use StreamConsumer (XREADGROUP + XACK).
    """

    def __init__(
        self,
        channels: dict[str, Callable[[dict], Awaitable[None]]],
        redis_client: aioredis.Redis | None = None,
        reconnect_delay: float = 2.0,
    ) -> None:
        """
        Args:
            channels: Mapping of channel name → async callback.
            redis_client: Optional pre-existing async Redis client.
            reconnect_delay: Seconds between reconnect attempts.
        """
        if not channels:
            raise ValueError("At least one channel subscription is required")

        self._channels = channels
        self._redis: aioredis.Redis | None = redis_client
        self._reconnect_delay = reconnect_delay
        self._running = False
        self._pubsub: aioredis.client.PubSub | None = None # type: ignore

    async def _ensure_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = await get_client()
        return self._redis

    async def start(self) -> None:
        """Start listening. Reconnects automatically on failure."""
        self._running = True

        while self._running:
            try:
                client = await self._ensure_redis()
                self._pubsub = client.pubsub()
                await self._pubsub.subscribe(*self._channels.keys()) # pyright: ignore[reportOptionalMemberAccess]

                logger.info("PubSub subscribed: channels=%s (ephemeral only)",
                            list(self._channels.keys()))

                async for message in self._pubsub.listen(): # pyright: ignore[reportOptionalMemberAccess]
                    if not self._running:
                        break
                    if message["type"] != "message":
                        continue

                    channel = message["channel"]
                    if isinstance(channel, bytes):
                        channel = channel.decode()

                    callback = self._channels.get(channel)
                    if callback:
                        try:
                            await callback(message)
                        except Exception:
                            logger.exception("PubSub callback error: channel=%s", channel)

            except asyncio.CancelledError:
                break
            except Exception:
                if not self._running:
                    break
                logger.warning("PubSub connection lost. Reconnecting in %.1fs...",
                               self._reconnect_delay)
                self._redis = None
                await asyncio.sleep(self._reconnect_delay)

    async def stop(self) -> None:
        """Graceful shutdown."""
        self._running = False
        if self._pubsub:
            await self._pubsub.unsubscribe()
            await self._pubsub.aclose()
            self._pubsub = None
        logger.info("PubSub subscriber stopped")
