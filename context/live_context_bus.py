"""
Live Context Bus
Single Source of Truth for live market state.

Supports two modes via CONTEXT_MODE environment variable:
  - local (default): In-memory storage, single-process only
  - redis: Redis-backed storage for multi-container deployments
"""

import os
from collections import defaultdict, deque
from threading import Lock
from typing import Optional

from loguru import logger

from context.context_validator import ContextValidator
from utils.timezone_utils import now_utc


class LiveContextBus:
    """
    Centralized, thread-safe market state container.

    Supports two modes:
      - CONTEXT_MODE=local (default): In-memory only, for local dev/testing
      - CONTEXT_MODE=redis: Writes to Redis for multi-container setups
    """

    _instance: Optional["LiveContextBus"] = None
    _lock = Lock()

    def __new__(cls) -> "LiveContextBus":
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super().__new__(cls)
                    cls._instance._init()
        return cls._instance

    def _init(self) -> None:
        """Initialize context bus based on CONTEXT_MODE."""
        # Always maintain local storage for backward compatibility
        self._tick_buffer = deque(maxlen=10000)
        self._candle_store = defaultdict(dict)  # symbol -> tf -> candle
        self._candle_history = defaultdict(
            lambda: defaultdict(lambda: deque(maxlen=50))
        )  # symbol -> tf -> deque of candles
        self._news_store = {}
        self._meta = {}
        self._rw_lock = Lock()

        # Check mode and initialize Redis bridge if needed
        self._mode = os.getenv("CONTEXT_MODE", "local").lower()
        self._redis_bridge: Optional["RedisContextBridge"] = None

        if self._mode == "redis":
            try:
                # Lazy import to avoid circular dependency
                from context.redis_context_bridge import RedisContextBridge
                self._redis_bridge = RedisContextBridge()
                logger.info("LiveContextBus initialized in REDIS mode")
            except Exception as exc:
                logger.error(
                    f"Failed to initialize Redis bridge: {exc}. "
                    "Falling back to local mode."
                )
                self._mode = "local"
                self._redis_bridge = None
        else:
            logger.info("LiveContextBus initialized in LOCAL mode")

    # =========================
    # WRITE METHODS (INGEST ONLY)
    # =========================

    def update_tick(self, tick: dict) -> None:
        """
        Update tick data.

        In local mode: Stores in in-memory buffer.
        In Redis mode: Stores locally AND writes to Redis.
        """
        if not ContextValidator.validate_tick(tick):
            logger.warning("Invalid tick rejected")
            return

        with self._rw_lock:
            self._tick_buffer.append(tick)

        # If Redis mode, also write to Redis
        if self._mode == "redis" and self._redis_bridge:
            try:
                self._redis_bridge.write_tick(tick)
            except Exception as exc:
                logger.error(f"Failed to write tick to Redis: {exc}")

    def update_candle(self, candle: dict) -> None:
        """
        Update candle data.

        In local mode: Stores in in-memory store.
        In Redis mode: Stores locally AND writes to Redis.
        """
        if not ContextValidator.validate_candle(candle):
            logger.warning("Invalid candle rejected")
            return

        symbol = candle["symbol"]
        tf = candle["timeframe"]

        with self._rw_lock:
            self._candle_store[symbol][tf] = candle
            # Also add to history buffer
            self._candle_history[symbol][tf].append(candle)

        # If Redis mode, also write to Redis
        if self._mode == "redis" and self._redis_bridge:
            try:
                self._redis_bridge.write_candle(candle)
            except Exception as exc:
                logger.error(f"Failed to write candle to Redis: {exc}")

    def update_news(self, news: dict) -> None:
        """
        Update news data.

        In local mode: Stores in in-memory store.
        In Redis mode: Stores locally AND writes to Redis.
        """
        if not ContextValidator.validate_news(news):
            logger.warning("Invalid news payload rejected")
            return

        with self._rw_lock:
            self._news_store = news
            self._meta["news_updated_at"] = now_utc()

        # If Redis mode, also write to Redis
        if self._mode == "redis" and self._redis_bridge:
            try:
                self._redis_bridge.write_news(news)
            except Exception as exc:
                logger.error(f"Failed to write news to Redis: {exc}")

    # =========================
    # READ METHODS (EVERYONE ELSE)
    # =========================

    def consume_ticks(self):
        """
        Used by CandleBuilder ONLY.
        """
        with self._rw_lock:
            ticks = list(self._tick_buffer)
            self._tick_buffer.clear()
            return ticks

    def get_latest_tick(self, symbol: str):
        with self._rw_lock:
            for tick in reversed(self._tick_buffer):
                if tick["symbol"] == symbol:
                    return tick
        return None

    def get_candle(self, symbol: str, timeframe: str):
        with self._rw_lock:
            return self._candle_store.get(symbol, {}).get(timeframe)

    def get_all_candles(self, timeframe: str):
        with self._rw_lock:
            return {
                symbol: tf_map.get(timeframe)
                for symbol, tf_map in self._candle_store.items()
                if timeframe in tf_map
            }

    def get_candle_history(
        self, symbol: str, timeframe: str, count: int = 20
    ) -> list:
        """
        Get historical candles for a symbol and timeframe.

        Args:
            symbol: Trading pair symbol
            timeframe: Timeframe (M15, H1, etc.)
            count: Number of candles to return (default 20, max 50)

        Returns:
            List of candles, newest first
        """
        with self._rw_lock:
            history = self._candle_history.get(symbol, {}).get(timeframe, deque())
            # Return last N candles, newest first
            candles = list(history)
            return candles[-count:] if len(candles) > count else candles

    def get_news(self):
        with self._rw_lock:
            return self._news_store

    def snapshot(self):
        """
        Read-only snapshot for analysis / dashboard.
        """
        with self._rw_lock:
            return {
                "ticks": list(self._tick_buffer),
                "candles": dict(self._candle_store),
                "news": self._news_store,
                "meta": self._meta,
            }
