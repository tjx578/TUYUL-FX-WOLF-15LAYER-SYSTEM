"""
Redis Consumer for Engine Container.

Consumes tick/candle/news data from Redis and feeds it into the local
LiveContextBus, enabling the engine container to receive data from the
ingest container in a multi-container deployment.

TCP_OVERWINDOW mitigation
-------------------------
Previous implementation wrapped **synchronous** redis-py calls in
``run_in_executor``.  Each ``get_message`` poll round-tripped through a
thread-pool, creating micro-stalls that let the Redis output buffer grow
faster than the app drained it.  Railway's network then dropped packets
whose sequence number exceeded the receiver's advertised TCP window
(``dropCause: TCP_OVERWINDOW``).

This rewrite uses **native async redis** (``redis.asyncio``) so all I/O
is non-blocking and the event loop drains the socket continuously.
"""

from __future__ import annotations

import asyncio
from typing import Any

import orjson
from loguru import logger

# Re-export type for callers that inject their own client
from redis.asyncio import Redis as AsyncRedis  # noqa: F401

from context.live_context_bus import LiveContextBus
from context.redis_config import create_redis_client


class RedisConsumer:
    """
    Consumes market data from Redis and populates local LiveContextBus.

    Uses **async redis** (``redis.asyncio``) for tick streams and pub/sub
    so the event loop drains data without thread-pool overhead, reducing
    TCP back-pressure that causes ``TCP_OVERWINDOW`` drops on Railway.
    """

    def __init__(
        self,
        symbols: list[str],
        redis_client: AsyncRedis | None = None,
        context_bus: LiveContextBus | None = None,
    ) -> None:
        """
        Initialize Redis consumer.

        Args:
            symbols: List of trading pair symbols to consume.
            redis_client: Optional *async* Redis instance.
            context_bus: Optional LiveContextBus instance.
        """
        self._symbols = symbols
        self._redis: AsyncRedis = redis_client or create_redis_client()
        self._context_bus = context_bus or LiveContextBus()
        self._prefix = "wolf15"
        self._group_name = "engine_group"
        self._consumer_name = "engine_consumer_1"
        self._running = False
        self._tasks: list[asyncio.Task[None]] = []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start all consumer tasks."""
        if self._running:
            logger.warning("RedisConsumer already running")
            return

        self._running = True
        logger.info(f"Starting RedisConsumer for symbols: {self._symbols}")

        await self._create_consumer_groups()

        self._tasks = [
            asyncio.create_task(self._consume_ticks(), name="rc-ticks"),
            asyncio.create_task(self._consume_candles(), name="rc-candles"),
            asyncio.create_task(self._consume_news(), name="rc-news"),
        ]

        logger.info("RedisConsumer started (native async)")

    async def stop(self) -> None:
        """Stop all consumer tasks and close the async connection."""
        if not self._running:
            return

        self._running = False
        logger.info("Stopping RedisConsumer...")

        for task in self._tasks:
            task.cancel()

        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

        # Close the async redis connection cleanly
        try:  # noqa: SIM105
            await self._redis.aclose()  # type: ignore[union-attr]
        except Exception:
            pass

        logger.info("RedisConsumer stopped")

    # ------------------------------------------------------------------
    # Consumer groups
    # ------------------------------------------------------------------

    async def _create_consumer_groups(self) -> None:
        """Create consumer groups for all tick streams (async)."""
        for symbol in self._symbols:
            stream_key = f"{self._prefix}:tick:{symbol}"
            try:
                await self._redis.xgroup_create(  # type: ignore[arg-type]
                    name=stream_key,
                    groupname=self._group_name,
                    id="0",
                    mkstream=True,
                )
                logger.debug(f"Consumer group {self._group_name} created for {stream_key}")
            except Exception as exc:
                # BUSYGROUP = already exists, perfectly fine
                if "BUSYGROUP" not in str(exc):
                    logger.debug(f"Consumer group creation skipped for {stream_key}: {exc}")

    # ------------------------------------------------------------------
    # Tick stream consumer (XREADGROUP — native async)
    # ------------------------------------------------------------------

    async def _consume_ticks(self) -> None:
        """Consume ticks from Redis Streams using consumer groups (async)."""
        logger.info("Tick consumer task started (async)")

        streams: dict[str, str] = {
            f"{self._prefix}:tick:{symbol}": ">" for symbol in self._symbols
        }

        while self._running:
            try:
                result: Any = await self._redis.xreadgroup(
                    groupname=self._group_name,
                    consumername=self._consumer_name,
                    streams=streams,  # type: ignore[arg-type]
                    count=50,        # larger batch → fewer round-trips
                    block=1000,
                )

                if result:
                    for _stream_name, entries in result:
                        for _entry_id, fields in entries:
                            tick_json = fields.get("data")
                            if tick_json:
                                try:
                                    tick = orjson.loads(tick_json)
                                    self._context_bus.update_tick(tick)
                                except Exception as parse_exc:
                                    logger.error(f"Failed to parse tick: {parse_exc}")

            except asyncio.CancelledError:
                logger.info("Tick consumer task cancelled")
                break
            except Exception as exc:
                logger.error(f"Error in tick consumer: {exc}")
                await asyncio.sleep(1)

        logger.info("Tick consumer task stopped")

    # ------------------------------------------------------------------
    # Candle pub/sub consumer (native async)
    # ------------------------------------------------------------------

    async def _consume_candles(self) -> None:
        """Subscribe to candle channels and feed into LiveContextBus (async)."""
        logger.info("Candle consumer task started (async)")

        pubsub = self._redis.pubsub()

        try:
            channels: list[str] = []
            for symbol in self._symbols:
                channels.extend(
                    [
                        f"candle:{symbol}:M15",
                        f"candle:{symbol}:H1",
                        f"candle:{symbol}:H4",
                        f"candle:{symbol}:D1",
                        f"candle:{symbol}:W1",
                    ]
                )

            await pubsub.subscribe(*channels)
            logger.info(f"Subscribed to {len(channels)} candle channels (async)")

            while self._running:
                try:
                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True,
                        timeout=1.0,
                    )

                    if message and message["type"] == "message":
                        candle_json = message.get("data")
                        if candle_json is None:
                            continue
                        try:
                            candle = orjson.loads(candle_json)
                            self._context_bus.update_candle(candle)
                        except Exception as parse_exc:
                            logger.error(f"Failed to parse candle: {parse_exc}")

                except asyncio.CancelledError:
                    logger.info("Candle consumer task cancelled")
                    break
                except Exception as exc:
                    logger.error(f"Error in candle consumer: {exc}")
                    await asyncio.sleep(1)

        finally:
            await pubsub.unsubscribe()
            await pubsub.aclose()

        logger.info("Candle consumer task stopped")

    # ------------------------------------------------------------------
    # News pub/sub consumer (native async)
    # ------------------------------------------------------------------

    async def _consume_news(self) -> None:
        """Subscribe to news channel and feed into LiveContextBus (async)."""
        logger.info("News consumer task started (async)")

        pubsub = self._redis.pubsub()

        try:
            await pubsub.subscribe("news_updates")
            logger.info("Subscribed to news_updates channel (async)")

            while self._running:
                try:
                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True,
                        timeout=1.0,
                    )

                    if message and message["type"] == "message":
                        news_json = message.get("data")
                        if news_json is None:
                            continue
                        try:
                            news = orjson.loads(news_json)
                            self._context_bus.update_news(news)
                        except Exception as parse_exc:
                            logger.error(f"Failed to parse news: {parse_exc}")

                except asyncio.CancelledError:
                    logger.info("News consumer task cancelled")
                    break
                except Exception as exc:
                    logger.error(f"Error in news consumer: {exc}")
                    await asyncio.sleep(1)

        finally:
            await pubsub.unsubscribe()
            await pubsub.aclose()

        logger.info("News consumer task stopped")
