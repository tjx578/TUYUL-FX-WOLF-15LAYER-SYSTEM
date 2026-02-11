"""Dependency injection for Finnhub WS client."""

from __future__ import annotations

import logging
from typing import Any

from redis.asyncio import Redis

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
    """Process incoming tick and publish to Redis channel.

    Dispatches normalized tick data to downstream consumers
    via Redis pub/sub. NO analysis or decision logic here.

    Args:
        data: Normalized tick dict from FinnhubWebSocket._listen.
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
        for tick in trades:
            symbol = tick.get("s", "")
            price = tick.get("p")
            ts = tick.get("t")

            if not symbol or price is None or ts is None:
                logger.warning(
                    "Skipping incomplete tick",
                    extra={"raw_tick": tick},
                )
                continue

            logger.debug(
                "Tick received",
                extra={
                    "symbol": symbol,
                    "price": price,
                    "timestamp": ts,
                },
            )
            # TODO: publish to Redis channel / LiveContextBus
            # setelah integrasi dengan main.py entrypoint

    except (KeyError, TypeError, ValueError) as exc:
        logger.error(
            "Tick processing error",
            extra={"error": str(exc), "raw_data": str(data)[:200]},
        )
