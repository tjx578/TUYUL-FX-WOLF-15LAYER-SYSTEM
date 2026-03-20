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

from core.redis_keys import (
    CANDLE_HISTORY_MAXLEN as _CANDLE_HISTORY_MAXLEN,
)
from core.redis_keys import (
    candle_history as _candle_history_key,
)
from core.redis_keys import (
    channel_candle,
    latest_candle,
)
from storage.redis_client import RedisClient

# === TTL Constants ===
# Latest tick: 24 hours housekeeping TTL — keeps last-known price available.
# Staleness is detected via the `last_seen_ts` field INSIDE the hash, NOT via key expiry.
# The long TTL only exists for garbage collection; it does NOT define freshness.
# This prevents data loss during temporary WS disconnects (rate limits, weekends).
LATEST_TICK_TTL_SECONDS: int = 86400  # 24h housekeeping only

# No TTL on candle keys — Redis has persistent volume.
# Data stays until explicitly deleted or trimmed by LTRIM.
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
      - latest_tick hashes: 24h housekeeping TTL (staleness via last_seen_ts field, NOT key expiry)
      - candle hashes: no TTL (persistent, overwritten on each new candle)
      - candle history lists: no TTL (capped by LTRIM to 300 entries)
      - latest_news: 24h TTL (set via SET ex=)
    """

    def __init__(self, redis_client: RedisClient | None = None) -> None:
        """
        Initialize Redis context bridge.

        Args:
            redis_client: Optional RedisClient instance (uses singleton if None).
        """
        super().__init__()
        self._redis = redis_client or RedisClient()
        self._prefix = "wolf15"  # Namespace prefix for all keys
        self._tick_stream_maxlen = 10000  # Max entries per tick stream

    def write_tick(self, tick: dict[str, Any]) -> None:
        """
        Write tick to Redis Streams + Hash + Pub/Sub.

        Operations:
          1. XADD to stream "tick:{symbol}" with maxlen cap
          2. HSET to "latest_tick:{symbol}" with ``last_seen_ts`` field
             (freshness is computed from this timestamp, NOT key expiry)
          3. PUBLISH to "tick_updates" channel for real-time notification

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

            # 2. HSET latest tick + last_seen_ts for freshness classification
            import time as _time

            latest_key = f"{self._prefix}:latest_tick:{symbol}"
            self._redis.hset(
                latest_key,
                mapping={
                    "data": tick_json,
                    "last_seen_ts": str(_time.time()),
                },
            )

            # P0: No EXPIRE on latest_tick keys.  Freshness is determined
            # solely from the `last_seen_ts` field inside the hash.
            # Removing the TTL prevents stale data from silently vanishing
            # and being misclassified as NO_PRODUCER (never had data)
            # instead of STALE_PRESERVED (data present but aged out).
            # Redis memory is bounded by the number of configured pairs
            # (one small hash per symbol), so expiry is unnecessary.

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
          3. RPUSH+LTRIM candle history list (capped at 300 entries)

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
            channel = channel_candle(symbol, timeframe)
            self._redis.publish(channel, candle_json)

            # 2. HSET latest candle + last_seen_ts (no TTL — persistent until overwritten)
            import time as _time

            hash_key = latest_candle(symbol, timeframe)
            self._redis.hset(
                hash_key,
                mapping={
                    "data": candle_json,
                    "last_seen_ts": str(_time.time()),
                },
            )

            # 3. Append to candle history list (enables engine warmup on startup)
            #    LTRIM caps size; no TTL so data survives restarts.
            try:
                list_key = _candle_history_key(symbol, timeframe)
                self._redis.client.rpush(list_key, candle_json)
                self._redis.client.ltrim(list_key, -_CANDLE_HISTORY_MAXLEN, -1)
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
            Tick dictionary or None if not found.  Includes ``last_seen_ts``
            if present in the hash (written by write_tick).
        """
        try:
            key = f"{self._prefix}:latest_tick:{symbol}"
            raw_map = self._redis.hgetall(key)
            if not raw_map:
                return None
            data_str = raw_map.get("data")
            if not data_str:
                return None
            tick = orjson.loads(data_str)
            # Attach last_seen_ts from hash so readers can compute freshness
            last_seen = raw_map.get("last_seen_ts")
            if last_seen:
                tick["last_seen_ts"] = float(last_seen)
            return tick
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
            Candle dictionary or None if not found.  Includes ``last_seen_ts``
            if present in the hash (written by write_candle).
        """
        try:
            key = latest_candle(symbol, timeframe)
            raw_map = self._redis.hgetall(key)
            if not raw_map:
                return None
            data_str = raw_map.get("data")
            if not data_str:
                return None
            candle = orjson.loads(data_str)
            last_seen = raw_map.get("last_seen_ts")
            if last_seen:
                candle["last_seen_ts"] = float(last_seen)
            return candle
        except Exception as exc:
            logger.error(f"Failed to read latest candle from Redis: {exc}")
            return None

    def read_candle_history(self, symbol: str, timeframe: str, count: int = 0) -> list[dict[str, Any]]:
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
            raw: list[bytes]
            if count > 0:
                raw = list(self._redis.client.lrange(list_key, -count, -1))  # type: ignore[arg-type]
            else:
                raw = list(self._redis.client.lrange(list_key, 0, -1))  # type: ignore[arg-type]
            candles: list[dict[str, Any]] = []
            for item in raw:
                with contextlib.suppress(Exception):
                    candles.append(orjson.loads(item))
            return candles
        except Exception as exc:
            logger.error(f"Failed to read candle history from Redis for {symbol} {timeframe}: {exc}")
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
