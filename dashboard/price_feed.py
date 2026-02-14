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

from threading import Lock
from typing import Optional

from loguru import logger

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
        self._rw_lock = Lock()
        logger.info("PriceFeed service initialized")

    def update_prices(self) -> int:
        """
        Poll LiveContextBus for latest ticks and update Redis cache.

        Returns:
            Number of symbols updated
        """
        updated_count = 0

        try:
            # Get all recent ticks from context bus
            snapshot = self._context_bus.snapshot()
            ticks = snapshot.get("ticks", [])

            if not ticks:
                logger.debug("No ticks available from LiveContextBus")
                return 0

            # Group by symbol and keep latest tick per symbol
            latest_ticks: dict[str, dict] = {}
            for tick in reversed(ticks):  # Reversed so we get most recent first
                symbol = tick.get("symbol")
                if symbol and symbol not in latest_ticks:
                    latest_ticks[symbol] = tick

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
                logger.debug(f"Updated prices for {updated_count} symbols")

        except Exception as exc:
            logger.error(f"Price feed update failed: {exc}")

        return updated_count

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
            logger.debug(f"No price data for {symbol}")
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
            # Scan for all PRICE:* keys
            # Note: In production, consider maintaining a set of active symbols
            # For now, we'll scan with pattern matching
            pattern = f"{self._redis_prefix}:PRICE:*"

            # Get client for scanning
            client = self._redis.client

            # Use SCAN to find all price keys
            cursor = 0
            while True:
                cursor, keys = client.scan(cursor, match=pattern, count=100)

                for key in keys:
                    # Extract symbol from key
                    symbol = key.split(":")[-1]

                    # Get price data
                    price_json = self._redis.get(key)
                    if price_json:
                        prices[symbol] = json.loads(price_json)

                if cursor == 0:
                    break

        except Exception as exc:
            logger.error(f"Failed to get all prices: {exc}")

        return prices

    def get_latest_tick_from_bus(self, symbol: str) -> dict | None:
        """
        Get latest tick directly from LiveContextBus (bypass Redis).

        Useful for immediate access without waiting for update cycle.

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
