"""
Redis Stream publisher — native async, reliable delivery.

Zone: infrastructure/ — message transport only.
"""

from __future__ import annotations

import logging
import time

import redis.asyncio as aioredis

from infrastructure.redis_client import get_client

logger = logging.getLogger(__name__)


class StreamPublisher:
    """
    Publish messages to Redis Streams.

    Native async — no run_in_executor.
    Supports maxlen trimming to prevent unbounded stream growth.
    """

    def __init__(
        self,
        redis_client: aioredis.Redis | None = None,
        default_maxlen: int = 10_000,
    ) -> None:
        self._redis: aioredis.Redis | None = redis_client
        self._default_maxlen = default_maxlen

    async def _ensure_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = await get_client()
        return self._redis

    async def publish(
        self,
        stream: str,
        fields: dict[str, str],
        maxlen: int | None = None,
        approximate: bool = True,
    ) -> str:
        """
        Publish a message to a Redis Stream.

        Args:
            stream: Stream key name.
            fields: Message fields (must be str → str).
            maxlen: Max stream length (trims oldest). None uses default.
            approximate: Use ~ for MAXLEN (more efficient).

        Returns:
            The message ID assigned by Redis.
        """
        client = await self._ensure_redis()
        trim_len = maxlen if maxlen is not None else self._default_maxlen

        message_id: str = await client.xadd(
            name=stream,
            fields=fields, # pyright: ignore[reportArgumentType]
            maxlen=trim_len,
            approximate=approximate,
        )

        logger.debug("Published to %s: id=%s fields=%s", stream, message_id, list(fields.keys()))
        return message_id

    async def publish_signal(
        self,
        stream: str,
        symbol: str,
        verdict: str,
        confidence: float,
        extra: dict[str, str] | None = None,
    ) -> str:
        """Convenience: publish a Layer-12 signal to a stream."""
        fields: dict[str, str] = {
            "symbol": symbol,
            "verdict": verdict,
            "confidence": str(confidence),
            "timestamp": str(time.time()),
        }
        if extra:
            fields.update(extra)
        return await self.publish(stream, fields)
