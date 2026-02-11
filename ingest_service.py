"""
Standalone Ingest Service for Docker Multi-Container Setup

This service runs data ingestion (Finnhub WebSocket, News, and CandleBuilder)
and writes to Redis via RedisContextBridge.

Used by docker-compose.yml with CONTEXT_MODE=redis.
"""

import asyncio
import os
import signal
import sys

from typing import Any

import loguru # pyright: ignore[reportMissingImports]
import redis # pyright: ignore[reportMissingImports]

from ingest.candle_builder import CandleBuilder
from ingest.dependencies import create_finnhub_ws
from ingest.finnhub_news import FinnhubNews


def get_redis_client() -> "redis.Redis[Any]":
    """
    Create and return a Redis client from REDIS_URL environment variable.

    Returns:
        redis.Redis: Redis client instance
    """
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    return redis.from_url(redis_url)  # type: ignore[return-value]

# Global shutdown event
_shutdown_event: asyncio.Event | None = None


def _validate_api_key() -> bool:
    """
    Validate Finnhub API key on startup.

    Returns:
        bool: True if API key is valid, False otherwise
    """
    api_key = os.getenv("FINNHUB_API_KEY", "")

    if not api_key or api_key == "YOUR_FINNHUB_API_KEY":
        loguru.logger.warning(
            "╔════════════════════════════════════════════════════════════╗\n"
            "║  WARNING: FINNHUB_API_KEY not configured                 ║\n"
            "║  Ingest service running in DRY RUN mode                   ║\n"
            "║  No live data feed available                              ║\n"
            "║  Set FINNHUB_API_KEY environment variable for live data  ║\n"
            "╚════════════════════════════════════════════════════════════╝"
        )
        return False

    loguru.logger.info("✓ FINNHUB_API_KEY validated")
    return True


async def run_ingest_services(has_api_key: bool) -> None:
    """
    Run data ingestion services concurrently.

    Launches three concurrent tasks:
    - FinnhubWebSocket: Real-time tick data
    - FinnhubNews: News feed
    - CandleBuilder: Aggregates ticks into H1/M15/M5 candles

    All data is written to Redis via RedisContextBridge (CONTEXT_MODE=redis).

    Args:
        has_api_key: Whether a valid Finnhub API key is configured
    """
    if not has_api_key:
        loguru.logger.info("Skipping ingest services - no API key configured")
        loguru.logger.info("Keeping ingest container alive (DRY RUN mode)...")
        # Keep container alive but don't do anything
        while True:
            if _shutdown_event and _shutdown_event.is_set():
                break
            await asyncio.sleep(1)
        return

    # Initialize ingest services
    redis_client = get_redis_client()
    ws_feed = await create_finnhub_ws(redis=redis_client)
    news_feed = FinnhubNews()
    candle_builder = CandleBuilder()

    loguru.logger.info("Starting ingest services: WebSocket, News, CandleBuilder")
    loguru.logger.info("Writing data to Redis (CONTEXT_MODE=redis)")

    # Run all three services concurrently
    try:
        await asyncio.gather(
            ws_feed.run(),
            news_feed.run(),
            candle_builder.run(),
        )
    except asyncio.CancelledError:
        loguru.logger.info("Ingest services cancelled - shutting down")
        raise


def _handle_signal(signum: int, frame) -> None:
    """
    Handle shutdown signals gracefully.

    Args:
        signum: Signal number
        frame: Current stack frame
    """
    signal_name = signal.Signals(signum).name
    loguru.logger.info(f"Received {signal_name} - initiating graceful shutdown...")

    if _shutdown_event:
        _shutdown_event.set()


async def main() -> None:
    """
    Main entry point for ingest service.

    Sets up signal handlers, validates API key, and runs ingest services.
    """
    global _shutdown_event
    _shutdown_event = asyncio.Event()

    # Configure logging — split streams for Railway compatibility
    loguru.logger.remove()

    # INFO/WARNING → stdout (Railway classifies as "info")
    loguru.logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan> - "
        "<level>{message}</level>",
        level="INFO",
        filter=lambda record: record["level"].no < 40,  # Below ERROR
    )

    # ERROR/CRITICAL → stderr (Railway classifies as "error")
    loguru.logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan> - "
        "<level>{message}</level>",
        level="ERROR",
    )

    loguru.logger.info("=" * 70)
    loguru.logger.info("TUYUL FX WOLF - Standalone Ingest Service")
    loguru.logger.info("=" * 70)

    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    # Validate API key
    has_api_key = _validate_api_key()

    # Validate CONTEXT_MODE
    context_mode = os.getenv("CONTEXT_MODE", "local").lower()
    if context_mode != "redis":
        loguru.logger.warning(f"CONTEXT_MODE={context_mode} - expected 'redis' for multi-container setup")
        loguru.logger.warning("Data will be written to local memory only (not shared)")
    else:
        redis_url = os.getenv("REDIS_URL", "")
        loguru.logger.info(f"✓ CONTEXT_MODE=redis, REDIS_URL={redis_url}")

    # Run ingest services
    try:
        await run_ingest_services(has_api_key)
    except KeyboardInterrupt:
        loguru.logger.info("KeyboardInterrupt received")
    except Exception as exc:
        loguru.logger.exception(f"Ingest service failed: {exc}")
        sys.exit(1)
    finally:
        loguru.logger.info("Ingest service shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
