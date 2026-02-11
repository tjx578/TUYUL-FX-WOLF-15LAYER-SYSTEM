"""Dependency injection utilities for Finnhub WS client."""

from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any

from redis.asyncio import Redis  # pyright: ignore[reportMissingImports]

from config_loader import CONFIG
from context.live_context_bus import LiveContextBus
from ingest.finnhub_ws import FinnhubSymbolMapper, FinnhubWebSocket

logger = logging.getLogger(__name__)

_DEFAULT_REDIS_URL = "redis://localhost:6379/0"


def _enabled_symbols() -> list[str]:
    """Return enabled internal symbols from config."""
    symbols = CONFIG["pairs"].get("symbols", [])
    return [str(symbol) for symbol in symbols if symbol]


def _build_tick_handler(
    *,
    mapper: FinnhubSymbolMapper,
) -> Callable[[dict[str, Any]], Awaitable[None]]:
    """Create WS message handler that normalizes and writes ticks to context."""
    context_bus = LiveContextBus()

    async def _handle_tick(data: dict[str, Any]) -> None:
        try:
            if data.get("type") != "trade":
                return

            trades = data.get("data", [])
            for trade in trades:
                external_symbol = trade.get("s")
                price = trade.get("p")
                timestamp = trade.get("t")

                if not external_symbol or price is None or timestamp is None:
                    logger.debug("Skipping incomplete trade payload")
                    continue

                internal_symbol = mapper.to_internal(str(external_symbol))
                normalized_tick = {
                    "symbol": internal_symbol,
                    "bid": float(price),
                    "ask": float(price),
                    "timestamp": int(timestamp),
                    "source": "finnhub",
                }
                context_bus.update_tick(normalized_tick)
        except (TypeError, ValueError) as exc:
            logger.error(
                "Tick processing error",
                extra={"error": str(exc), "raw_data": str(data)[:200]},
            )

    return _handle_tick


async def create_finnhub_ws(
    redis: Redis,
    symbols: list[str] | None = None,
) -> FinnhubWebSocket:
    """Factory for FinnhubWebSocket with defaults and tick normalization."""
    mapper = FinnhubSymbolMapper(prefix="OANDA")
    internal_symbols = symbols or _enabled_symbols()
    external_symbols = [mapper.register(symbol) for symbol in internal_symbols]

    return FinnhubWebSocket(
        redis=redis,
        on_message=_build_tick_handler(mapper=mapper),
        symbols=external_symbols,
    )


async def create_default_finnhub_ws() -> FinnhubWebSocket:
    """Factory that builds Redis client and configured Finnhub WS instance."""
    redis_url = os.getenv("REDIS_URL", _DEFAULT_REDIS_URL)
    redis = Redis.from_url(redis_url, decode_responses=True)
    return await create_finnhub_ws(redis=redis)
