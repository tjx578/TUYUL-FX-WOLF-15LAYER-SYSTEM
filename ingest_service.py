"""Standalone ingest service for multi-container deployments."""

import asyncio
import os
import signal
import sys

from loguru import logger  # pyright: ignore[reportMissingImports]
from redis.asyncio import Redis as AsyncRedis

from ingest.candle_builder import CandleBuilder
from ingest.dependencies import create_finnhub_ws
from ingest.finnhub_news import FinnhubNews

_shutdown_event: asyncio.Event | None = None


def _validate_api_key() -> bool:
    api_key = os.getenv("FINNHUB_API_KEY", "")
    if not api_key or api_key == "YOUR_FINNHUB_API_KEY":
        logger.warning("WARNING: FINNHUB_API_KEY not configured; ingest running in DRY RUN mode.")
        return False
    logger.info("FINNHUB_API_KEY validated")
    return True


def _build_redis_client() -> AsyncRedis:
    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        logger.info("Using REDIS_URL for ingest service")
        return AsyncRedis.from_url(redis_url, encoding="utf-8", decode_responses=True)

    redis_host = os.getenv("REDIS_HOST", "localhost")
    redis_port = int(os.getenv("REDIS_PORT", "6379"))
    redis_password = os.getenv("REDIS_PASSWORD", "")
    redis_db = int(os.getenv("REDIS_DB", "0"))
    logger.info(f"Using Redis: {redis_host}:{redis_port}/{redis_db}")
    return AsyncRedis(
        host=redis_host,
        port=redis_port,
        password=redis_password if redis_password else None,
        db=redis_db,
        encoding="utf-8",
        decode_responses=True,
    )


async def run_ingest_services(has_api_key: bool) -> None:
  # noqa: PLR0912, RUF100
    """Run Finnhub WS, news, and candle builder loops."""
    if not has_api_key:
        logger.info("Skipping ingest services - no API key configured")
        while not (_shutdown_event and _shutdown_event.is_set()):  # noqa: ASYNC110
            await asyncio.sleep(1)
        return

    redis: AsyncRedis | None = None
    ws_feed = None
    news_feed = None
    candle_builder = None

    try:
        redis = _build_redis_client()
        await redis.ping() # pyright: ignore[reportGeneralTypeIssues]
        logger.info("Redis connection validated")
    except Exception as e:
        logger.error(f"Error connecting to Redis: {e}")
        raise

    try:
        ws_feed = await create_finnhub_ws(redis=redis)
        news_feed = FinnhubNews()
        candle_builder = CandleBuilder()

        logger.info("Starting ingest services: WebSocket, News, CandleBuilder")
        await asyncio.gather(
            ws_feed.run(),
            news_feed.run(),
            candle_builder.run(),
        )
    except asyncio.CancelledError:
        logger.info("Ingest services cancelled - shutting down")
        raise
    finally:
        cleanup_errors = []
        if ws_feed is not None:
            try:
                await ws_feed.stop()
            except Exception as e:
                logger.error(f"Error stopping ws_feed: {e}")
                cleanup_errors.append(("ws_feed.stop()", e))
        if news_feed is not None:
            try:
                await news_feed.stop() # pyright: ignore[reportAttributeAccessIssue]
            except Exception as e:
                logger.error(f"Error stopping news_feed: {e}")
                cleanup_errors.append(("news_feed.stop()", e))
        if candle_builder is not None:
            try:
                await candle_builder.stop() # pyright: ignore[reportAttributeAccessIssue]
            except Exception as e:
                logger.error(f"Error stopping candle_builder: {e}")
                cleanup_errors.append(("candle_builder.stop()", e))
        if redis is not None:
            try:
                await redis.aclose()
            except Exception as e:
                logger.error(f"Error closing redis: {e}")
                cleanup_errors.append(("redis.aclose()", e))

        if cleanup_errors:
            logger.warning(f"Cleanup completed with {len(cleanup_errors)} error(s)")
        logger.info("Ingest service cleanup complete")


def _handle_signal(signum: int, frame) -> None:
    signal_name = signal.Signals(signum).name
    logger.info(f"Received {signal_name} - initiating graceful shutdown...")
    if _shutdown_event:
        _shutdown_event.set()


async def main() -> None:
    global _shutdown_event
    _shutdown_event = asyncio.Event()

    logger.remove()
    logger.add(
        sys.stdout,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>"
        ),
        level="INFO",
        filter=lambda record: record["level"].no < 40,
    )
    logger.add(
        sys.stderr,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>"
        ),
        level="ERROR",
    )

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    has_api_key = _validate_api_key()

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
