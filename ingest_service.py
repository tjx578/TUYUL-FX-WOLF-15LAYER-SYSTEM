"""Standalone ingest service for multi-container deployments."""

import asyncio
import os
import signal
import sys

from loguru import logger  # pyright: ignore[reportMissingImports]
from redis.asyncio import Redis as AsyncRedis

from context.system_state import SystemState, SystemStateManager
from ingest.candle_builder import CandleBuilder
from ingest.dependencies import create_finnhub_ws
from ingest.finnhub_candles import FinnhubCandleFetcher
from ingest.macro_monthly_scheduler import MacroMonthlyScheduler
from analysis.macro_regime_engine import MacroRegimeEngine
from config_loader import CONFIG
from ingest.finnhub_market_news import FinnhubMarketNews
from ingest.finnhub_news import FinnhubNews
from ingest.h1_refresh_scheduler import H1RefreshScheduler

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
    """Run Finnhub WS, news, and candle builder loops."""
    if not has_api_key:
        logger.info("Skipping ingest services - no API key configured")
        while not (_shutdown_event and _shutdown_event.is_set()):
            await asyncio.sleep(1)
        return

    redis = _build_redis_client()
    await redis.ping()
    logger.info("Redis connection validated")

    # Initialize system state manager
    system_state = SystemStateManager()
    system_state.set_state(SystemState.WARMING_UP)

    # Warmup: fetch historical candles
    logger.info("Starting warmup: fetching historical candles from Finnhub REST API")
    try:
        fetcher = FinnhubCandleFetcher()
        warmup_results = await fetcher.warmup_all()
        
        # Validate warmup results
        system_state.validate_warmup(warmup_results)
        
        # Run macro regime analysis using MN data (if warmup provided history)
        enabled_symbols = CONFIG.get("pairs", {}).get("symbols", [])
        try:
            macro_engine = MacroRegimeEngine()
            for symbol in enabled_symbols:
                try:
                    macro_engine.update_macro_state(symbol)
                except Exception as e:
                    logger.error(f"Macro regime failed for {symbol}: {e}")
        except Exception:
            logger.exception("Failed to initialize MacroRegimeEngine")

        # Set state based on validation
        warmup_report = system_state.get_warmup_report()
        incomplete_count = sum(
            1 for status in warmup_report.values() 
            if status.status.value != "COMPLETE"
        )
        
        if incomplete_count == 0:
            system_state.set_state(SystemState.READY)
            logger.info("Warmup complete - system state: READY")
        else:
            system_state.set_state(SystemState.DEGRADED)
            logger.warning(
                f"Warmup complete with {incomplete_count} incomplete symbols - "
                "system state: DEGRADED"
            )
            
    except Exception as exc:
        logger.error(f"Warmup failed (non-fatal): {exc}")
        system_state.set_state(SystemState.DEGRADED)

    # Start ingest services
    ws_feed = await create_finnhub_ws(redis=redis)
    news_feed = FinnhubNews()
    market_news = FinnhubMarketNews()
    candle_builder = CandleBuilder()
    h1_refresh = H1RefreshScheduler()

    logger.info(
        "Starting ingest services: WebSocket, News, MarketNews, "
        "CandleBuilder (M15), H1Refresh"
    )
    try:
        await asyncio.gather(
            ws_feed.run(),
            news_feed.run(),
            market_news.run(),
            candle_builder.run(),
            h1_refresh.run(),
            # Start monthly macro scheduler in background
            MacroMonthlyScheduler(enabled_symbols).run(),
        )
    except asyncio.CancelledError:
        logger.info("Ingest services cancelled - shutting down")
        raise
    finally:
        await ws_feed.stop()
        await redis.aclose()
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
