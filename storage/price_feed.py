"""Latest-price read model over Redis PRICE:* hashes.

Canonical location — moved from dashboard/price_feed.py (PR-003).
"""

from __future__ import annotations

import contextlib
import time
from threading import Lock
from typing import Any, cast

from infrastructure.redis_client import get_client
from storage.redis_client import redis_client


class PriceFeed:
    """In-memory + Redis-backed read model for latest prices."""

    def __init__(self) -> None:
        self._prices: dict[str, dict[str, Any]] = {}
        self._lock = Lock()

    def update_price(self, symbol: str, bid: float, ask: float, ts: float | None = None) -> None:
        item = {
            "bid": float(bid),
            "ask": float(ask),
            "ts": float(ts if ts is not None else time.time()),
        }
        with self._lock:
            self._prices[symbol.upper()] = item

        with contextlib.suppress(Exception):
            redis_client.client.hset(f"PRICE:{symbol.upper()}", mapping=item)

    def get_latest_prices(self) -> dict[str, dict[str, Any]]:
        return self.get_all_prices()

    async def get_latest_prices_async(self) -> dict[str, dict[str, Any]]:
        return await self.get_all_prices_async()

    def get_all_prices(self) -> dict[str, dict[str, Any]]:
        prices: dict[str, dict[str, Any]] = {}
        with self._lock:
            prices.update(self._prices)

        with contextlib.suppress(Exception):
            for key in redis_client.client.scan_iter("PRICE:*"):
                symbol = str(key).split(":", 1)[1]
                payload = cast(dict[str, Any], redis_client.client.hgetall(key))
                if payload:
                    prices[symbol] = {
                        "bid": float(payload.get("bid", 0.0) or 0.0),
                        "ask": float(payload.get("ask", 0.0) or 0.0),
                        "ts": float(payload.get("ts", 0.0) or 0.0),
                    }

        return prices

    async def get_all_prices_async(self) -> dict[str, dict[str, Any]]:
        prices: dict[str, dict[str, Any]] = {}
        with self._lock:
            prices.update(self._prices)

        with contextlib.suppress(Exception):
            client = await get_client()
            async for key in client.scan_iter(match="PRICE:*"):
                symbol = str(key).split(":", 1)[1]
                payload = await client.hgetall(str(key))  # type: ignore[misc]  # redis.asyncio ResponseT
                if payload:
                    prices[symbol] = {
                        "bid": float(payload.get("bid", 0.0) or 0.0),
                        "ask": float(payload.get("ask", 0.0) or 0.0),
                        "ts": float(payload.get("ts", 0.0) or 0.0),
                    }

        return prices

    def get_price(self, symbol: str) -> dict[str, Any] | None:
        return self.get_all_prices().get(symbol.upper())

    async def get_price_async(self, symbol: str) -> dict[str, Any] | None:
        prices = await self.get_all_prices_async()
        return prices.get(symbol.upper())
