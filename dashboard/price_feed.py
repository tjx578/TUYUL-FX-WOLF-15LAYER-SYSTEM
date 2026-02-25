"""
Price Feed Service - Dashboard's price sensor.

Leverages existing Finnhub infrastructure:
  - Reads latest ticks from LiveContextBus (which already has Finnhub WS data)
  - Stores latest bid/ask per symbol in Redis (PRICE:{symbol})
  - Provides get_price() and get_all_prices() for dashboard consumption
  - Runs as background task polling LiveContextBus

Redis key structure:
  PRICE:XAUUSD = {"bid": 2034.25, "ask": 2034.38, "ts": 1707580800.0, "source": "finnhub_ws"}

CRITICAL:
  - This is a SENSOR, not a brain
  - NO signal generation
  - NO market analysis
  - NO trading decisions
  - Dashboard uses prices ONLY for monitoring state transitions
"""

import json
import os
import time
from threading import Lock
from typing import Optional

from loguru import logger

from config_loader import CONFIG
from context.live_context_bus import LiveContextBus
from storage.redis_client import RedisClient


class PriceFeed:
    """
    Thread-safe price feed service for dashboard.

    Reads from LiveContextBus and caches in Redis for fast dashboard access.
    Pure sensor - no decision logic.
    """

    _instance: Optional["PriceFeed"] = None
    _lock = Lock()

    def __new__(cls) -> "PriceFeed":
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super().__new__(cls)
                    cls._instance._init()
        return cls._instance

    def _init(self) -> None:
        """Initialize price feed service."""
        self._context_bus = LiveContextBus()
        self._redis = RedisClient()
        self._redis_prefix = os.getenv("REDIS_PREFIX", "wolf15")
        self._context_mode = os.getenv("CONTEXT_MODE", "local").lower()
        self._rw_lock = Lock()
        self._enabled_symbols: list[str] = [
            p["symbol"]
            for p in CONFIG.get("pairs", {}).get("pairs", [])
            if p.get("enabled", True)
        ]
        self._last_no_tick_warn: float = 0.0
        logger.info(
            f"PriceFeed service initialized "
            f"(context_mode={self._context_mode}, symbols={len(self._enabled_symbols)})"
        )

    def update_prices(self) -> int:
        """
        Poll LiveContextBus for latest ticks and update Redis cache.
        Also fires the WS price event to wake any waiting WebSocket loops.
        Returns:
            Number of symbols updated
        """
        updated_count = 0

        try:
            # Get all recent ticks from context bus
            snapshot = self._context_bus.snapshot()
            ticks = snapshot.get("ticks", [])

            # Group by symbol and keep latest tick per symbol
            latest_ticks: dict[str, dict] = {}
            for tick in reversed(ticks):  # Reversed so we get most recent first
                symbol = tick.get("symbol")
                if symbol and symbol not in latest_ticks:
                    latest_ticks[symbol] = tick

            # Fallback: if local buffer empty and CONTEXT_MODE=redis,
            # read latest ticks directly from Redis hash keys.
            if not latest_ticks and self._context_mode == "redis":
                latest_ticks = self._read_ticks_from_redis()

            if not latest_ticks:
                now = time.monotonic()
                # Throttle warning to once per 30 s to avoid log flood
                if now - self._last_no_tick_warn > 30.0:
                    logger.warning(
                        "No ticks available from LiveContextBus or Redis. "
                        "Check: FINNHUB_API_KEY set? Ingest running? "
                        f"CONTEXT_MODE={self._context_mode}, "
                        f"EMBED_INGEST={os.getenv('EMBED_INGEST', 'false')}"
                    )
                    self._last_no_tick_warn = now
                return 0

            # Update Redis with latest prices
            for symbol, tick in latest_ticks.items():
                try:
                    price_data = {
                        "bid": tick.get("bid", 0.0),
                        "ask": tick.get("ask", 0.0),
                        "ts": tick.get("timestamp", 0.0),
                        "source": tick.get("source", "unknown"),
                    }

                    # Store in Redis with 60-second expiry
                    redis_key = f"{self._redis_prefix}:PRICE:{symbol}"
                    self._redis.set(
                        redis_key,
                        json.dumps(price_data),
                        ex=60,  # Expire after 60 seconds if not updated
                    )
                    updated_count += 1

                except Exception as exc:
                    logger.error(f"Failed to update price for {symbol}: {exc}")

            if updated_count > 0:
                # Signal WS price event to wake waiting WebSocket loops
                self._fire_price_event()

        except Exception as exc:
            logger.error(f"Price feed update failed: {exc}")

        return updated_count

    @staticmethod
    def _fire_price_event() -> None:
        """Notify the WS price stream that new prices are available.

        Uses a lazy import to avoid circular dependency at module load time.
        Silently ignores errors (WS module may not be loaded yet).
        """
        try:
            import asyncio  # noqa: PLC0415

            from api.ws_routes import notify_price_update  # noqa: PLC0415

            # If we're already in an event loop, schedule; otherwise ignore
            try:
                loop = asyncio.get_running_loop()
                loop.call_soon_threadsafe(
                    lambda: asyncio.ensure_future(notify_price_update())
                )
            except RuntimeError:
                pass  # No running event loop — skip
        except ImportError:
            pass  # ws_routes not available

    def _read_ticks_from_redis(self) -> dict[str, dict]:
        """Read latest ticks from Redis hash keys (fallback when local buffer empty).

        Reads ``wolf15:latest_tick:{symbol}`` hashes written by
        ``RedisContextBridge.write_tick()`` in the ingest container.

        Returns:
            Dict mapping symbol -> tick dict.
        """
        latest: dict[str, dict] = {}
        errors: list[str] = []
        for symbol in self._enabled_symbols:
            try:
                key = f"{self._redis_prefix}:latest_tick:{symbol}"
                tick_json = self._redis.hget(key, "data")
                if tick_json:
                    import orjson  # noqa: PLC0415

                    tick = orjson.loads(tick_json)
                    latest[symbol] = tick
            except Exception as exc:
                errors.append(f"{symbol}: {exc}")
        if errors and not latest:
            # Only warn once when ALL symbols fail (connection issue)
            logger.warning(f"Redis tick fallback failed ({len(errors)} symbols): {errors[0]}")
        return latest

    def get_price(self, symbol: str) -> dict[str, float] | None:
        """
        Get latest price for a symbol.

        Args:
            symbol: Trading pair symbol (e.g., "EURUSD")

        Returns:
            Dictionary with bid, ask, ts, source if available, else None
        """
        try:
            redis_key = f"{self._redis_prefix}:PRICE:{symbol}"
            price_json = self._redis.get(redis_key)

            if price_json:
                return json.loads(price_json)
            return None
        except Exception as exc:
            logger.error(f"Failed to get price for {symbol}: {exc}")
            return None

    def get_all_prices(self) -> dict[str, dict[str, float]]:
        """
        Get latest prices for all symbols.

        Returns:
            Dictionary mapping symbol -> price data
        """
        prices = {}

        try:
            # Get all PRICE:* keys using Redis scan
            pattern = f"{self._redis_prefix}:PRICE:*"
            cursor = 0

            while True:
                # Use the synchronous scan interface from RedisClient
                result = self._redis.client.scan(cursor, match=pattern, count=100)
                if isinstance(result, tuple):
                    cursor, keys_list = result
                else:
                    # Fallback for type compatibility
                    logger.warning("Unexpected scan result type, breaking scan loop")
                    break

                for key in keys_list:
                    # Extract symbol from key
                    symbol = key.decode().split(":")[-1] if isinstance(key, bytes) else key.split(":")[-1]

                    # Get price data
                    redis_key = f"{self._redis_prefix}:PRICE:{symbol}"
                    price_json = self._redis.get(redis_key)
                    if price_json:
                        prices[symbol] = json.loads(price_json)

                if cursor == 0:
                    break

        except Exception as exc:
            logger.error(f"Failed to get all prices: {exc}")

        return prices

    def get_latest_prices(self) -> dict[str, dict[str, float]]:
        """
        Alias for get_all_prices() for dashboard API compatibility.
        """
        return self.get_all_prices()

    def get_latest_tick_from_bus(self, symbol: str) -> dict | None:
        """
        Get latest tick directly from LiveContextBus (bypass Redis).

        Args:
            symbol: Trading pair symbol

        Returns:
            Tick dictionary if available, else None
        """
        try:
            return self._context_bus.get_latest_tick(symbol)
        except Exception as exc:
            logger.error(f"Failed to get tick from context bus for {symbol}: {exc}")
            return None

# Singleton instance for imports
price_feed = PriceFeed()
