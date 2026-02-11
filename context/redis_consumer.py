"""
Redis Consumer for Engine Container.

Consumes tick/candle/news data from Redis and feeds it into the local
LiveContextBus, enabling the engine container to receive data from the
ingest container in a multi-container deployment.
"""

import asyncio

import orjson

from loguru import logger

from context.live_context_bus import LiveContextBus
from storage.redis_client import RedisClient


class RedisConsumer:
    """
    Consumes market data from Redis and populates local LiveContextBus.

    This runs as a background task in the engine container to receive:
      - Ticks from Redis Streams (using consumer groups)
      - Candles from Redis Pub/Sub
      - News from Redis Pub/Sub

    The consumed data is fed into the local LiveContextBus so all existing
    analysis code works unchanged.
    """

    def __init__(
        self,
        symbols: list[str],
        redis_client: RedisClient | None = None,
        context_bus: LiveContextBus | None = None,
    ) -> None:
        """
        Initialize Redis consumer.

        Args:
            symbols: List of trading pair symbols to consume.
            redis_client: Optional RedisClient instance.
            context_bus: Optional LiveContextBus instance.
        """
        self._symbols = symbols
        self._redis = redis_client or RedisClient()
        self._context_bus = context_bus or LiveContextBus()
        self._prefix = "wolf15"
        self._group_name = "engine_group"
        self._consumer_name = "engine_consumer_1"
        self._running = False
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        """Start all consumer tasks."""
        if self._running:
            logger.warning("RedisConsumer already running")
            return

        self._running = True
        logger.info(f"Starting RedisConsumer for symbols: {self._symbols}")

        # Create consumer groups for tick streams
        await self._create_consumer_groups()

        # Start consumer tasks
        self._tasks = [
            asyncio.create_task(self._consume_ticks()),
            asyncio.create_task(self._consume_candles()),
            asyncio.create_task(self._consume_news()),
        ]

        logger.info("RedisConsumer started")

    async def stop(self) -> None:
        """Stop all consumer tasks."""
        if not self._running:
            return

        self._running = False
        logger.info("Stopping RedisConsumer...")

        # Cancel all tasks
        for task in self._tasks:
            task.cancel()

        # Wait for tasks to complete
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

        logger.info("RedisConsumer stopped")

    async def _create_consumer_groups(self) -> None:
        """Create consumer groups for all tick streams."""
        for symbol in self._symbols:
            stream_key = f"{self._prefix}:tick:{symbol}"
            try:
                # Run blocking Redis call in executor
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    self._redis.xgroup_create,
                    stream_key,
                    self._group_name,
                    "0",  # Start from beginning
                    True,  # Create stream if not exists
                )
                logger.debug(f"Consumer group {self._group_name} created for {stream_key}")
            except Exception as exc:
                logger.debug(f"Consumer group creation skipped for {stream_key}: {exc}")

    async def _consume_ticks(self) -> None:
        """
        Consume ticks from Redis Streams using consumer groups.

        Reads from tick:{symbol} streams and feeds into LiveContextBus.
        """
        logger.info("Tick consumer task started")

        # Build streams dict for XREADGROUP
        streams = {f"{self._prefix}:tick:{symbol}": ">" for symbol in self._symbols}

        while self._running:
            try:
                # XREADGROUP with blocking (1000ms timeout)
                result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    self._redis.xreadgroup,
                    self._group_name,
                    self._consumer_name,
                    streams,
                    10,  # Count: max 10 entries per stream
                    1000,  # Block: 1000ms
                )

                if result:
                    for _stream_name, entries in result:
                        for _entry_id, fields in entries:
                            tick_json = fields.get("data")
                            if tick_json:
                                try:
                                    tick = orjson.loads(tick_json)
                                    # Feed into local context bus
                                    self._context_bus.update_tick(tick)
                                    logger.debug(f"Tick consumed from Redis: {tick.get('symbol')}")
                                except Exception as parse_exc:
                                    logger.error(f"Failed to parse tick: {parse_exc}")

            except asyncio.CancelledError:
                logger.info("Tick consumer task cancelled")
                break
            except Exception as exc:
                logger.error(f"Error in tick consumer: {exc}")
                await asyncio.sleep(1)  # Backoff on error

        logger.info("Tick consumer task stopped")

    async def _consume_candles(self) -> None:
        """
        Consume candles from Redis Pub/Sub.

        Subscribes to candle:* channels and feeds into LiveContextBus.
        """
        logger.info("Candle consumer task started")

        # Create Pub/Sub instance
        pubsub = self._redis.pubsub()

        try:
            # Subscribe to candle channels for all symbols and timeframes
            channels = []
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

            await asyncio.get_event_loop().run_in_executor(None, pubsub.subscribe, *channels)
            logger.info(f"Subscribed to {len(channels)} candle channels")

            while self._running:
                try:
                    # Get message with timeout
                    message = await asyncio.get_event_loop().run_in_executor(
                        None,
                        pubsub.get_message,
                        True,
                        1.0,  # Timeout: 1 second
                    )

                    if message and message["type"] == "message":
                        candle_json = message["data"]
                        try:
                            candle = orjson.loads(candle_json)
                            # Feed into local context bus
                            self._context_bus.update_candle(candle)
                            logger.debug(
                                f"Candle consumed from Redis: "
                                f"{candle.get('symbol')} "
                                f"{candle.get('timeframe')}"
                            )
                        except Exception as parse_exc:
                            logger.error(f"Failed to parse candle: {parse_exc}")

                except asyncio.CancelledError:
                    logger.info("Candle consumer task cancelled")
                    break
                except Exception as exc:
                    logger.error(f"Error in candle consumer: {exc}")
                    await asyncio.sleep(1)

        finally:
            await asyncio.get_event_loop().run_in_executor(None, pubsub.unsubscribe)
            await asyncio.get_event_loop().run_in_executor(None, pubsub.close)

        logger.info("Candle consumer task stopped")

    async def _consume_news(self) -> None:
        """
        Consume news from Redis Pub/Sub.

        Subscribes to news_updates channel and feeds into LiveContextBus.
        """
        logger.info("News consumer task started")

        # Create Pub/Sub instance
        pubsub = self._redis.pubsub()

        try:
            # Subscribe to news channel
            await asyncio.get_event_loop().run_in_executor(None, pubsub.subscribe, "news_updates")
            logger.info("Subscribed to news_updates channel")

            while self._running:
                try:
                    # Get message with timeout
                    message = await asyncio.get_event_loop().run_in_executor(
                        None,
                        pubsub.get_message,
                        True,
                        1.0,  # Timeout: 1 second
                    )

                    if message and message["type"] == "message":
                        news_json = message["data"]
                        try:
                            news = orjson.loads(news_json)
                            # Feed into local context bus
                            self._context_bus.update_news(news)
                            logger.debug("News consumed from Redis")
                        except Exception as parse_exc:
                            logger.error(f"Failed to parse news: {parse_exc}")

                except asyncio.CancelledError:
                    logger.info("News consumer task cancelled")
                    break
                except Exception as exc:
                    logger.error(f"Error in news consumer: {exc}")
                    await asyncio.sleep(1)

        finally:
            await asyncio.get_event_loop().run_in_executor(None, pubsub.unsubscribe)
            await asyncio.get_event_loop().run_in_executor(None, pubsub.close)

        logger.info("News consumer task stopped")
