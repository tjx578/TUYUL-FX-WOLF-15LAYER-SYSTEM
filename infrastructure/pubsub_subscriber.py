"""
Redis Pub/Sub subscriber — ONLY for ephemeral notifications.

Zone: infrastructure/ — message transport only.

⚠️  WARNING: Messages during disconnect are PERMANENTLY LOST.
Use this ONLY for:
  - Heartbeats / liveness
  - Cache invalidation signals
  - Dashboard refresh hints

For critical data (candles, signals, news, trades), use StreamConsumer.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

import redis.asyncio as aioredis

from infrastructure.backoff import BackoffConfig, ExponentialBackoff
from infrastructure.redis_client import get_client

logger = logging.getLogger(__name__)


class PubSubSubscriber:
    """
    Async Pub/Sub for ephemeral-only notifications.

    Uses exponential backoff on reconnect (not sleep(1)).
    """

    def __init__(
        self,
        channels: dict[str, Callable[[dict], Awaitable[None]]],
        redis_client: aioredis.Redis | None = None,
        backoff_config: BackoffConfig | None = None,
    ) -> None:
        if not channels:
            raise ValueError("At least one channel is required")

        self._channels = channels
        self._redis: aioredis.Redis | None = redis_client
        self._backoff = ExponentialBackoff(
            backoff_config or BackoffConfig(initial=1.0, maximum=15.0),
        )
        self._running = False
        self._pubsub: aioredis.client.PubSub | None = None  # pyright: ignore[reportAttributeAccessIssue]

    async def start(self) -> None:
        """Start listening. Reconnects with exponential backoff."""
        self._running = True

        while self._running:
            try:
                if self._redis is None:
                    self._redis = await get_client()

                self._pubsub = self._redis.pubsub()
                await self._pubsub.subscribe(*self._channels.keys())  # pyright: ignore[reportOptionalMemberAccess]

                logger.info(
                    "PubSub subscribed (EPHEMERAL ONLY): channels=%s",
                    list(self._channels.keys()),
                )
                self._backoff.reset()

                async for message in self._pubsub.listen():  # pyright: ignore[reportOptionalMemberAccess]
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
                            logger.exception(
                                "PubSub callback error: channel=%s",
                                channel,
                            )

            except asyncio.CancelledError:
                break
            except Exception:
                if not self._running:
                    break
                delay = self._backoff.next_delay()
                logger.warning(
                    "PubSub lost. Reconnecting in %.2fs (attempt #%d)",
                    delay,
                    self._backoff.attempt,
                )
                self._redis = None
                await asyncio.sleep(delay)

    async def stop(self) -> None:
        self._running = False
        if self._pubsub:
            await self._pubsub.unsubscribe()
            await self._pubsub.aclose()
            self._pubsub = None
        logger.info("PubSub subscriber stopped")
