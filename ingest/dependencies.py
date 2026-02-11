"""Dependency injection for Finnhub WS client."""

from redis.asyncio import Redis

from ingest.finnhub_ws import FinnhubWebSocket


async def create_finnhub_ws(
    redis: Redis,
    symbols: list[str] | None = None,
) -> FinnhubWebSocket:
    """Factory for FinnhubWebSocket with defaults.

    Args:
        redis: Shared async Redis client.
        symbols: Forex symbols to subscribe. Defaults to majors.

    Returns:
        Configured FinnhubWebSocket instance.
    """
    default_symbols = [
        "OANDA:EUR_USD",
        "OANDA:GBP_JPY",
        "OANDA:USD_JPY",
        "OANDA:GBP_USD",
        "OANDA:AUD_USD",
        "OANDA:XAU_USD",
    ]
    return FinnhubWebSocket(
        redis=redis,
        on_message=_handle_tick,
        symbols=symbols or default_symbols,
    )


async def _handle_tick(data: dict) -> None:
    """Process incoming tick and publish to Redis channel."""
    # Route to your existing FTA scoring / signal pipeline
    ...
