"""Dependency injection utilities for Finnhub WS client."""

from __future__ import annotations

import logging
import os
import time

from typing import TYPE_CHECKING, Any

from redis.asyncio import Redis  # pyright: ignore[reportMissingImports]

from config_loader import CONFIG
from context.live_context_bus import LiveContextBus
from ingest.finnhub_ws import FinnhubSymbolMapper, FinnhubWebSocket
from ingest.spread_estimator import estimate_spread

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

# Per-symbol spike rejection thresholds (percentage)
SPIKE_THRESHOLDS: dict[str, float] = {
    "XAUUSD": 2.0,   # Gold is volatile - 2% threshold
    "GBPJPY": 1.0,   # High-vol cross - 1% threshold
    "EURUSD": 0.5,   # Major pair - tight is fine
    "GBPUSD": 0.5,
    "USDJPY": 0.5,
    "AUDUSD": 0.5,
}
_DEFAULT_SPIKE_THRESHOLD: float = 0.5
_STALENESS_THRESHOLD_SECONDS: float = 60.0  # Reset baseline if no tick for 60s

# Legacy constant for backwards compatibility (tests)
MAX_DEVIATION_PCT: float = _DEFAULT_SPIKE_THRESHOLD

_last_prices: dict[str, float] = {}
_last_timestamps: dict[str, float] = {}

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


def _get_spike_threshold(symbol: str) -> float:
    """Return spike rejection threshold for a given symbol."""
    return SPIKE_THRESHOLDS.get(symbol, _DEFAULT_SPIKE_THRESHOLD)


def _is_valid_tick(symbol: str, new_price: float) -> bool:
    """
    Validate tick price against spike threshold with staleness detection.

    Auto-resets baseline price if:
    - This is the first tick for the symbol, OR
    - No tick received for this symbol in the last 60 seconds (prevents false
      spikes after WS reconnects or session gaps)

    Args:
        symbol: Trading pair symbol
        new_price: New tick price

    Returns:
        True if tick is valid, False if spike detected
    """
    now = time.monotonic()
    last_price = _last_prices.get(symbol)
    last_ts = _last_timestamps.get(symbol)

    # First tick or stale price -> always accept as new baseline
    if last_price is None or (
        last_ts is not None and (now - last_ts) > _STALENESS_THRESHOLD_SECONDS
    ):
        reason = "first_tick" if last_price is None else "stale_baseline"
        logger.info(
            "Tick baseline reset",
            extra={
                "symbol": symbol,
                "price": new_price,
                "reason": reason,
            },
        )
        _last_prices[symbol] = new_price
        _last_timestamps[symbol] = now
        return True

    threshold = _get_spike_threshold(symbol)
    deviation = abs(new_price - last_price) / last_price * 100

    if deviation > threshold:
        logger.warning(
            "Tick spike rejected",
            extra={
                "symbol": symbol,
                "new_price": new_price,
                "last_price": last_price,
                "deviation_pct": round(deviation, 4),
                "threshold_pct": threshold,
            },
        )
        return False

    # Valid tick - update timestamp
    _last_timestamps[symbol] = now
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

                tick_ts = float(timestamp) / 1000.0
                bid, ask = estimate_spread(
                    symbol=internal_symbol,
                    price=float(price),
                    timestamp=tick_ts,
                )

                normalized_tick = {
                    "symbol": internal_symbol,
                    "bid": bid,
                    "ask": ask,
                    "last": float(price),
                    "spread": round(ask - bid, 6),
                    "timestamp": tick_ts,
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
        on_message=_build_tick_handler(mapper=mapper, allowed_symbols=allowed_symbols), # pyright: ignore[reportArgumentType]
        symbols=external_symbols,
    )


async def create_default_finnhub_ws() -> FinnhubWebSocket:
    """Factory that builds Redis client and configured Finnhub WS instance."""
    redis_url = os.getenv("REDIS_URL", _DEFAULT_REDIS_URL)
    redis = Redis.from_url(redis_url, decode_responses=True)
    return await create_finnhub_ws(redis=redis)
