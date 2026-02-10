"""
Ingest Service Entry Point

Runs the FinnhubWebSocket and CandleBuilder services.
In Redis mode, publishes data to Redis for the engine container to consume.
"""

import asyncio
import os

from loguru import logger

from ingest.finnhub_ws import FinnhubWebSocket
from ingest.candle_builder import CandleBuilder


async def main() -> None:
    """
    Start ingest services:
      - FinnhubWebSocket: Real-time price feed
      - CandleBuilder: Tick → M15/H1 candles
    """
    context_mode = os.getenv("CONTEXT_MODE", "local").lower()
    logger.info(f"Starting Ingest Service in {context_mode.upper()} mode")

    # Create service instances
    ws_feed = FinnhubWebSocket()
    candle_builder = CandleBuilder()

    # Start both services concurrently
    await asyncio.gather(
        ws_feed.run(),
        candle_builder.run(),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Ingest service shutting down...")
    except Exception as exc:
        logger.error(f"Ingest service fatal error: {exc}")
        raise
