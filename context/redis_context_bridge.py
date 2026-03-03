"""
Redis-backed Context Bridge for cross-container communication.

This module provides Redis-based implementations for sharing market data
(ticks, candles, news) between the ingest and engine containers.

Uses:
  - Redis Streams for tick data (durable, ordered, supports consumer groups)
  - Redis Pub/Sub for candle updates and news (lightweight real-time push)
  - Redis Hash for latest tick per symbol (fast lookup)
"""

import contextlib
from typing import Any

import orjson
from loguru import logger

from storage.redis_client import RedisClient

# === TTL Constants ===
# Latest tick: 60s - acts as stale feed circuit breaker.
# If no tick arrives in 60s, key expires -> downstream knows feed is dead.
LATEST_TICK_TTL_SECONDS: int = 60

# Candle hash: 4 hours - covers full session overlap (e.g., London+NY).
# Candles older than this are stale and should not inform decisions.
CANDLE_HASH_TTL_SECONDS: int = 4 * 3600  # 14400s

# Candle history list: 6 hours - long enough for engine restart/reconnect
# to load warmup data that ingest already fetched.
CANDLE_HISTORY_TTL_SECONDS: int = 6 * 3600  # 21600s

# Max candle history entries per symbol/timeframe in Redis
CANDLE_HISTORY_MAXLEN: int = 300


class RedisContextBridge:
    """
    Redis-backed bridge for cross-container context sharing.

    Publish side (ingest container):
      - write_tick(): XADD to stream, HSET latest tick, PUBLISH notification
      - write_candle(): PUBLISH to channel, HSET latest candle
      - write_news(): PUBLISH to channel, SET news data

    Consume side (engine container):
      - Handled by RedisConsumer class separately

    TTL Policy:
      - tick streams: MAXLEN ~10,000 (auto-trim on XADD)
      - latest_tick hashes: 60s TTL (stale feed detection)
      - candle hashes: 4h TTL (session-relevant window)
      - latest_news: 24h TTL (set via SET ex=)
    """

    def __init__(self, redis_client: RedisClient | None = None) -> None:
        """
        Initialize Redis context bridge.

        Args:
            redis_client: Optional RedisClient instance (uses singleton if None).
        """
        self._redis = redis_client or RedisClient()
        self._prefix = "wolf15"  # Namespace prefix for all keys
        self._tick_stream_maxlen = 10000  # Max entries per tick stream

    def write_tick(self, tick: dict[str, Any]) -> None:
        """
        Write tick to Redis Streams + Hash + Pub/Sub.

        Operations:
          1. XADD to stream "tick:{symbol}" with maxlen cap
          2. HSET to "latest_tick:{symbol}" for fast latest-tick lookup
          3. EXPIRE on latest_tick key (60s stale feed detection)
          4. PUBLISH to "tick_updates" channel for real-time notification

        Args:
            tick: Tick dictionary with keys: symbol, bid, ask, timestamp, source
        """
        symbol = tick.get("symbol")
        if not symbol:
            logger.warning("Tick missing symbol field, skipping Redis write")
            return

        try:
            # Serialize tick to JSON
            tick_json = orjson.dumps(tick).decode("utf-8")

            # 1. XADD to stream (auto-trimmed by maxlen)
            stream_key = f"{self._prefix}:tick:{symbol}"
            self._redis.xadd(
                stream_key,
                {"data": tick_json},
                maxlen=self._tick_stream_maxlen,
                approximate=True,
            )

            # 2. HSET latest tick
            latest_key = f"{self._prefix}:latest_tick:{symbol}"
            self._redis.hset(latest_key, mapping={"data": tick_json})

            # 3. Set TTL - resets countdown on every tick.
            #    If no tick in 60s -> key expires -> stale feed detected.
            self._redis.client.expire(latest_key, LATEST_TICK_TTL_SECONDS)

            # 4. PUBLISH notification
            self._redis.publish("tick_updates", tick_json)

        except Exception as exc:
            logger.error(f"Failed to write tick to Redis for {symbol}: {exc}")

    def write_candle(self, candle: dict[str, Any]) -> None:
        """
        Write candle to Redis Pub/Sub + Hash.

        Operations:
          1. PUBLISH to channel "candle:{symbol}:{timeframe}"
          2. HSET to "candle:{symbol}:{timeframe}" for latest candle storage
          3. EXPIRE on candle hash key (4h session window)

        Args:
            candle: Candle dictionary with keys: symbol, timeframe, open, high,
                    low, close, timestamp
        """
        symbol = candle.get("symbol")
        timeframe = candle.get("timeframe")
        if not symbol or not timeframe:
            logger.warning("Candle missing symbol/timeframe fields, skipping Redis write")
            return

        try:
            # Serialize candle to JSON
            candle_json = orjson.dumps(candle).decode("utf-8")

            # 1. PUBLISH to channel
            channel = f"candle:{symbol}:{timeframe}"
            self._redis.publish(channel, candle_json)

            # 2. HSET latest candle
            hash_key = f"{self._prefix}:candle:{symbol}:{timeframe}"
            self._redis.hset(hash_key, mapping={"data": candle_json})

            # 3. Set TTL - candle data expires after session relevance window
            self._redis.client.expire(hash_key, CANDLE_HASH_TTL_SECONDS)

            # 4. Append to candle history list (enables engine warmup on startup)
            try:
                list_key = f"{self._prefix}:candle_history:{symbol}:{timeframe}"
                self._redis.client.rpush(list_key, candle_json)
                self._redis.client.ltrim(list_key, -CANDLE_HISTORY_MAXLEN, -1)
                self._redis.client.expire(list_key, CANDLE_HISTORY_TTL_SECONDS)
            except Exception as exc:
                logger.error(f"Failed to write candle history list for {symbol} {timeframe}: {exc}")

        except Exception as exc:
            logger.error(f"Failed to write candle to Redis for {symbol} {timeframe}: {exc}")

    def write_news(self, news: dict[str, Any]) -> None:
        """
        Write news to Redis Pub/Sub.

        Operations:
          1. PUBLISH to channel "news_updates"
          2. SET to "latest_news" for persistence (24h TTL already set)

        Args:
            news: News dictionary payload
        """
        try:
            # Serialize news to JSON
            news_json = orjson.dumps(news).decode("utf-8")

            # 1. PUBLISH to channel
            self._redis.publish("news_updates", news_json)

            # 2. SET latest news (already has TTL via ex=86400)
            key = f"{self._prefix}:latest_news"
            self._redis.set(key, news_json, ex=86400)  # 24h expiration

        except Exception as exc:
            logger.error(f"Failed to write news to Redis: {exc}")

    def read_latest_tick(self, symbol: str) -> dict[str, Any] | None:
        """
        Read latest tick for a symbol from Redis Hash.

        Args:
            symbol: Trading pair symbol.

        Returns:
            Tick dictionary or None if not found (also None if feed is stale
            and TTL has expired the key).
        """
        try:
            key = f"{self._prefix}:latest_tick:{symbol}"
            tick_json = self._redis.hget(key, "data")
            if tick_json:
                return orjson.loads(tick_json)
            return None
        except Exception as exc:
            logger.error(f"Failed to read latest tick from Redis: {exc}")
            return None

    def read_latest_candle(self, symbol: str, timeframe: str) -> dict[str, Any] | None:
        """
        Read latest candle for a symbol/timeframe from Redis Hash.

        Args:
            symbol: Trading pair symbol.
            timeframe: Timeframe (e.g., "M15", "H1").

        Returns:
            Candle dictionary or None if not found.
        """
        try:
            key = f"{self._prefix}:candle:{symbol}:{timeframe}"
            candle_json = self._redis.hget(key, "data")
            if candle_json:
                return orjson.loads(candle_json)
            return None
        except Exception as exc:
            logger.error(f"Failed to read latest candle from Redis: {exc}")
            return None

    def read_candle_history(
        self, symbol: str, timeframe: str, count: int = 0
    ) -> list[dict[str, Any]]:
        """
        Read candle history list from Redis.

        Used by engine container on startup to load warmup data that
        ingest already fetched, avoiding the pub/sub race condition.

        Args:
            symbol: Trading pair symbol.
            timeframe: Timeframe (e.g., "H1", "H4", "D1").
            count: Max candles to return (0 = all available).

        Returns:
            List of candle dicts, oldest first.
        """
        try:
            list_key = f"{self._prefix}:candle_history:{symbol}:{timeframe}"
            if count > 0:
                raw = self._redis.client.lrange(list_key, -count, -1)
            else:
                raw = self._redis.client.lrange(list_key, 0, -1)
            candles: list[dict[str, Any]] = []
            for item in raw:
                with contextlib.suppress(Exception):
                    candles.append(orjson.loads(item))
            return candles
        except Exception as exc:
            logger.error(
                f"Failed to read candle history from Redis for {symbol} {timeframe}: {exc}"
            )
            return []

    def read_latest_news(self) -> dict[str, Any] | None:
        """
        Read latest news from Redis.

        Returns:
            News dictionary or None if not found.
        """
        try:
            key = f"{self._prefix}:latest_news"
            news_json = self._redis.get(key)
            if news_json:
                return orjson.loads(news_json)
            return None
        except Exception as exc:
            logger.error(f"Failed to read latest news from Redis: {exc}")
            return None
