"""Dependency injection for Finnhub WS client."""

from __future__ import annotations

import logging
from typing import Any

from redis.asyncio import Redis

from context.live_context_bus import LiveContextBus
from ingest.finnhub_ws import FinnhubWebSocket

logger = logging.getLogger(__name__)

# Default majors + gold — aligned with pairs config
_DEFAULT_SYMBOLS: list[str] = [
    "OANDA:EUR_USD",
    "OANDA:GBP_JPY",
    "OANDA:USD_JPY",
    "OANDA:GBP_USD",
    "OANDA:AUD_USD",
    "OANDA:XAU_USD",
]

# Build reverse symbol mapping: Finnhub format → internal format
# Example: "OANDA:EUR_USD" → "EURUSD"
_SYMBOL_REVERSE_MAP: dict[str, str] = {
    finnhub_sym: finnhub_sym.split(":")[-1].replace("_", "")
    for finnhub_sym in _DEFAULT_SYMBOLS
}


async def create_finnhub_ws(
    redis: Redis,  # type: ignore[type-arg]
    symbols: list[str] | None = None,
) -> FinnhubWebSocket:
    """Factory for FinnhubWebSocket with defaults.

    Args:
        redis: Shared async Redis client.
        symbols: Forex symbols to subscribe. Defaults to majors.

    Returns:
        Configured FinnhubWebSocket instance.
    """
    return FinnhubWebSocket(
        redis=redis,
        on_message=_handle_tick,
        symbols=symbols or _DEFAULT_SYMBOLS,
    )


async def _handle_tick(data: dict[str, Any]) -> None:
    """Process incoming tick and route to LiveContextBus.

    Normalizes Finnhub tick format to internal format and dispatches
    to LiveContextBus for downstream consumers. NO analysis or decision
    logic here - pure ingestion zone.

    Finnhub tick format:
        {"type": "trade", "data": [{"p": price, "s": "OANDA:EUR_USD", "t": ts_ms, "v": vol}]}

    Internal tick format (per context_keys.py TICK dict):
        {"symbol": "EURUSD", "bid": float, "ask": float, "timestamp": float_seconds, "source": "finnhub_ws"}

    Note: Finnhub provides a single trade price (p) which represents the last traded price.
    Since we need both bid and ask for the internal format, we use the same price for both.
    This is acceptable for ingestion purposes as downstream consumers can apply spread models
    if needed.

    Args:
        data: Raw tick dict from Finnhub WebSocket with type and data fields.
    """
    try:
        msg_type = data.get("type", "unknown")

        if msg_type != "trade":
            logger.debug(
                "Ignoring non-trade message",
                extra={"msg_type": msg_type},
            )
            return

        trades = data.get("data", [])
        if not isinstance(trades, list):
            logger.warning(
                "Invalid trades data format - expected list",
                extra={"raw_data": str(data)[:200]},
            )
            return

        for tick in trades:
            # Extract raw fields
            finnhub_symbol = tick.get("s", "")
            price = tick.get("p")
            ts_ms = tick.get("t")

            # Validate required fields
            if not finnhub_symbol or price is None or ts_ms is None:
                logger.warning(
                    "Skipping incomplete tick",
                    extra={"raw_tick": tick},
                )
                continue

            # Reverse map symbol: OANDA:EUR_USD → EURUSD
            internal_symbol = _SYMBOL_REVERSE_MAP.get(finnhub_symbol)

            # Skip if unmapped (not in our configured symbols)
            if internal_symbol is None:
                logger.debug(
                    "Skipping unmapped symbol",
                    extra={"finnhub_symbol": finnhub_symbol},
                )
                continue

            # Convert timestamp: milliseconds → seconds
            try:
                timestamp_seconds = float(ts_ms) / 1000.0
            except (TypeError, ValueError) as exc:
                logger.warning(
                    "Invalid timestamp format",
                    extra={
                        "ts_ms": ts_ms,
                        "error": str(exc),
                    },
                )
                continue

            # Normalize to internal format
            # Since Finnhub provides single price, use it for both bid and ask
            normalized_tick = {
                "symbol": internal_symbol,
                "bid": float(price),
                "ask": float(price),
                "timestamp": timestamp_seconds,
                "source": "finnhub_ws",
            }

            logger.debug(
                "Tick normalized",
                extra={
                    "symbol": internal_symbol,
                    "price": price,
                    "timestamp": timestamp_seconds,
                },
            )

            # Route to LiveContextBus
            # This handles both local mode (deque) and redis mode (Redis XADD + HSET + PUBLISH)
            LiveContextBus().update_tick(normalized_tick)

    except (KeyError, TypeError, ValueError) as exc:
        logger.error(
            "Tick processing error",
            extra={"error": str(exc), "raw_data": str(data)[:200]},
        )
