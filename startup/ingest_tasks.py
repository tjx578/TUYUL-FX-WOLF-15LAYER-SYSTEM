"""Ingest task composition — creates and runs all ingestion services concurrently.

Zone: startup/ — engine lifecycle. No market logic.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

from loguru import logger
from redis.asyncio import Redis as AsyncRedis

from config_loader import CONFIG, get_enabled_symbols
from ingest.calendar_news import CalendarNewsIngestor
from ingest.candle_builder import CandleBuilder
from ingest.dependencies import create_finnhub_ws
from ingest.finnhub_market_news import FinnhubMarketNews
from ingest.h1_refresh_scheduler import H1RefreshScheduler
from ingest.rest_poll_fallback import RestPollFallback

PAIRS: list[str] = get_enabled_symbols()


async def run_ingest_services(
    has_api_key: bool,
    redis: AsyncRedis,
    shutdown_event: asyncio.Event | None = None,
) -> None:
    """Run ingestion tasks concurrently in local mode."""
    if not has_api_key:
        logger.info("Skipping ingest services - no API key configured")
        while not (shutdown_event and shutdown_event.is_set()):  # noqa: ASYNC110
            await asyncio.sleep(1)
        return

    ws_feed = await create_finnhub_ws(redis=redis)
    rest_poll = RestPollFallback(
        ws_connected_fn=lambda: ws_feed.is_connected if ws_feed else False,
        symbols=PAIRS,
        redis_client=redis,
    )
    news_feed = CalendarNewsIngestor(redis_client=redis)
    market_news = FinnhubMarketNews()
    h1_refresh = H1RefreshScheduler(redis_client=redis)

    default_timeframe = CONFIG["settings"].get("default_timeframe", "1h")
    candle_builders = [CandleBuilder(symbol=pair, timeframe=default_timeframe) for pair in PAIRS]

    logger.info(
        "Starting ingest services: WebSocket, RestPollFallback, CalendarNews, MarketNews, CandleBuilder, H1Refresh"
    )
    try:
        cb_coros: list[Coroutine[Any, Any, Any]] = [cb.run() for cb in candle_builders]  # pyright: ignore[reportAttributeAccessIssue]
        await asyncio.gather(
            ws_feed.run(),
            rest_poll.run(),
            news_feed.run(),
            market_news.run(),
            h1_refresh.run(),
            *cb_coros,
        )
    except asyncio.CancelledError:
        logger.info("Ingest services cancelled - shutting down")
        raise
    finally:
        await ws_feed.stop()
        await rest_poll.stop()
        logger.info("Ingest services cleanup complete")
