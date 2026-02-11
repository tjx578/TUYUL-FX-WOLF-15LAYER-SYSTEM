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
from typing import Optional

from loguru import logger
from redis.asyncio import Redis as AsyncRedis

from ingest.candle_builder import CandleBuilder
from ingest.dependencies import create_finnhub_ws
from ingest.finnhub_news import FinnhubNews

# Global shutdown event
_shutdown_event: Optional[asyncio.Event] = None


def _validate_api_key() -> bool:
    """
    Validate Finnhub API key on startup.

    Returns:
        bool: True if API key is valid, False otherwise
    """
    api_key = os.getenv("FINNHUB_API_KEY", "")

    if not api_key or api_key == "YOUR_FINNHUB_API_KEY":
        logger.warning(
            "╔════════════════════════════════════════════════════════════╗\n"
            "║  WARNING: FINNHUB_API_KEY not configured                 ║\n"
            "║  Ingest service running in DRY RUN mode                   ║\n"
            "║  No live data feed available                              ║\n"
            "║  Set FINNHUB_API_KEY environment variable for live data  ║\n"
            "╚════════════════════════════════════════════════════════════╝"
        )
        return False

    logger.info("✓ FINNHUB_API_KEY validated")
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
        logger.info("Skipping ingest services - no API key configured")
        logger.info("Keeping ingest container alive (DRY RUN mode)...")
        # Keep container alive but don't do anything
        while True:
            if _shutdown_event and _shutdown_event.is_set():
                break
            await asyncio.sleep(1)
        return

    # Build Redis connection from environment variables
    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        logger.info(f"Using REDIS_URL: {redis_url}")
        redis = AsyncRedis.from_url(
            redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    else:
        # Fallback to individual params
        redis_host = os.getenv("REDIS_HOST", "localhost")
        redis_port = int(os.getenv("REDIS_PORT", "6379"))
        redis_password = os.getenv("REDIS_PASSWORD", "")
        redis_db = int(os.getenv("REDIS_DB", "0"))
        
        logger.info(f"Using Redis: {redis_host}:{redis_port}/{redis_db}")
        redis = AsyncRedis(
            host=redis_host,
            port=redis_port,
            password=redis_password if redis_password else None,
            db=redis_db,
            encoding="utf-8",
            decode_responses=True,
        )

    try:
        # Validate Redis connection
        await redis.ping()
        logger.info("✓ Redis connection validated")

        # Initialize ingest services with factory
        ws_feed = await create_finnhub_ws(redis=redis)
        news_feed = FinnhubNews()
        candle_builder = CandleBuilder()

        logger.info("Starting ingest services: WebSocket, News, CandleBuilder")
        logger.info("Writing data to Redis (CONTEXT_MODE=redis)")

        # Run all three services concurrently
        try:
            await asyncio.gather(
                ws_feed.run(),
                news_feed.run(),
                candle_builder.run(),
            )
        except asyncio.CancelledError:
            logger.info("Ingest services cancelled - shutting down")
            await ws_feed.stop()
            raise

    finally:
        # Cleanup Redis connection
        await redis.aclose()
        logger.info("Redis connection closed")


def _handle_signal(signum: int, frame) -> None:
    """
    Handle shutdown signals gracefully.

    Args:
        signum: Signal number
        frame: Current stack frame
    """
    signal_name = signal.Signals(signum).name
    logger.info(f"Received {signal_name} - initiating graceful shutdown...")

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
    logger.remove()

    # INFO/WARNING → stdout (Railway classifies as "info")
    logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
               "<level>{level: <8}</level> | "
               "<cyan>{name}</cyan>:<cyan>{function}</cyan> - "
               "<level>{message}</level>",
        level="INFO",
        filter=lambda record: record["level"].no < 40,  # Below ERROR
    )

    # ERROR/CRITICAL → stderr (Railway classifies as "error")
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
               "<level>{level: <8}</level> | "
               "<cyan>{name}</cyan>:<cyan>{function}</cyan> - "
               "<level>{message}</level>",
        level="ERROR",
    )

    logger.info("=" * 70)
    logger.info("TUYUL FX WOLF - Standalone Ingest Service")
    logger.info("=" * 70)

    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    # Validate API key
    has_api_key = _validate_api_key()

    # Validate CONTEXT_MODE
    context_mode = os.getenv("CONTEXT_MODE", "local").lower()
    if context_mode != "redis":
        logger.warning(
            f"CONTEXT_MODE={context_mode} - expected 'redis' for multi-container setup"
        )
        logger.warning("Data will be written to local memory only (not shared)")
    else:
        redis_url = os.getenv("REDIS_URL", "")
        logger.info(f"✓ CONTEXT_MODE=redis, REDIS_URL={redis_url}")

    # Run ingest services
    try:
        await run_ingest_services(has_api_key)
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received")
    except Exception as exc:
        logger.exception(f"Ingest service failed: {exc}")
        sys.exit(1)
    finally:
        logger.info("Ingest service shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
