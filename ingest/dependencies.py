"""Dependency injection utilities for Finnhub WS client."""

from __future__ import annotations

import logging
import os

from typing import TYPE_CHECKING, Any

from redis.asyncio import Redis  # pyright: ignore[reportMissingImports]

from config_loader import CONFIG
from context.live_context_bus import LiveContextBus
from ingest.finnhub_ws import FinnhubSymbolMapper, FinnhubWebSocket

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

MAX_DEVIATION_PCT: float = 0.5  # 0.5% max deviation

_last_prices: dict[str, float] = {}

_DEFAULT_REDIS_URL = "redis://localhost:6379/0"
_DEFAULT_SYMBOLS = [
    "OANDA:EUR_USD",
    "OANDA:GBP_JPY",
    "OANDA:USD_JPY",
    "OANDA:GBP_USD",
    "OANDA:AUD_USD",
    "OANDA:XAU_USD",
]
_SYMBOL_REVERSE_MAP: dict[str, str] = {
    symbol: symbol.replace("OANDA:", "").replace("_", "") for symbol in _DEFAULT_SYMBOLS
}


def _enabled_symbols() -> list[str]:
    """Return enabled internal symbols from config."""
    pairs = CONFIG.get("pairs", {}).get("pairs", [])
    enabled = [str(pair.get("symbol", "")) for pair in pairs if pair.get("enabled", True)]
    return [symbol for symbol in enabled if symbol]


def _is_valid_tick(symbol: str, new_price: float) -> bool:
    """
    Validate tick price against spike threshold.

    Args:
        symbol: Trading pair symbol
        new_price: New tick price

    Returns:
        True if tick is valid, False if spike detected
    """
    last_price = _last_prices.get(symbol)
    if last_price is None:
        return True
    deviation = abs(new_price - last_price) / last_price * 100
    if deviation > MAX_DEVIATION_PCT:
        logger.warning(
            "Tick spike rejected",
            extra={
                "symbol": symbol,
                "new_price": new_price,
                "last_price": last_price,
                "deviation_pct": deviation,
            },
        )
        return False
    return True


def _build_tick_handler(
    *,
    mapper: FinnhubSymbolMapper,
    allowed_symbols: set[str],
) -> Callable[[dict[str, Any]], Awaitable[None]]:
    """Create WS message handler that normalizes and writes ticks to context."""
    context_bus = LiveContextBus()

    async def _handle_tick(data: dict[str, Any]) -> None:
        try:
            if data.get("type") != "trade":
                return

            trades = data.get("data", [])
            if not isinstance(trades, list):
                logger.warning("Invalid Finnhub trade payload format")
                return
            for trade in trades:
                external_symbol = trade.get("s")
                price = trade.get("p")
                timestamp = trade.get("t")

                if not external_symbol or price is None or timestamp is None:
                    logger.debug("Skipping incomplete trade payload")
                    continue

                internal_symbol = mapper.to_internal(str(external_symbol))
                if internal_symbol not in allowed_symbols:
                    logger.warning(
                        "Skipping unmapped symbol from Finnhub stream",
                        extra={"external_symbol": external_symbol},
                    )
                    continue

                # Validate tick spike
                if not _is_valid_tick(internal_symbol, float(price)):
                    continue

                # Update last known price
                _last_prices[internal_symbol] = float(price)

                normalized_tick = {
                    "symbol": internal_symbol,
                    "bid": float(price),
                    "ask": float(price),
                    "timestamp": float(timestamp) / 1000.0,
                    "source": "finnhub_ws",
                }
                context_bus.update_tick(normalized_tick)
        except (TypeError, ValueError) as exc:
            logger.error(
                "Tick processing error",
                extra={"error": str(exc), "raw_data": str(data)[:200]},
            )

    return _handle_tick


async def _handle_tick(data: dict[str, Any]) -> None:
    """Backwards-compatible default tick handler used by tests and local callers."""
    mapper = FinnhubSymbolMapper(prefix="OANDA")
    for internal_symbol in _SYMBOL_REVERSE_MAP.values():
        mapper.register(internal_symbol)
    handler = _build_tick_handler(mapper=mapper, allowed_symbols=set(_SYMBOL_REVERSE_MAP.values()))
    await handler(data)


async def create_finnhub_ws(
    redis: Redis,
    symbols: list[str] | None = None,
) -> FinnhubWebSocket:
    """Factory for FinnhubWebSocket with defaults and tick normalization."""
    mapper = FinnhubSymbolMapper(prefix="OANDA")
    internal_symbols = symbols or _enabled_symbols()
    allowed_symbols = set(internal_symbols)
    external_symbols = [mapper.register(symbol) for symbol in internal_symbols]

    return FinnhubWebSocket(
        redis=redis,
        on_message=_build_tick_handler(mapper=mapper, allowed_symbols=allowed_symbols),
        symbols=external_symbols,
    )


async def create_default_finnhub_ws() -> FinnhubWebSocket:
    """Factory that builds Redis client and configured Finnhub WS instance."""
    redis_url = os.getenv("REDIS_URL", _DEFAULT_REDIS_URL)
    redis = Redis.from_url(redis_url, decode_responses=True)
    return await create_finnhub_ws(redis=redis)
