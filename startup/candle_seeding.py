"""Candle seeding (warmup) on engine startup.

Zone: startup/ — one-shot initialisation, no execution side-effects.

Strategy depends on CONTEXT_MODE env var:
  - redis : load candle history from Redis Lists (populated by ingest container)
  - local : fetch historical candles directly from Finnhub REST API
"""

from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from redis.asyncio import Redis as AsyncRedis

__all__ = ["seed_candles_on_startup"]


async def seed_candles_on_startup(pairs: list[str], warmup_min_bars: dict[str, int]) -> None:
    """Seed candle history into LiveContextBus BEFORE the analysis loop starts."""
    context_mode = os.getenv("CONTEXT_MODE", "local").lower()
    logger.info(f"[SEED] Seeding candles on startup (mode={context_mode}, pairs={len(pairs)})")

    if context_mode == "redis":
        await _seed_from_redis(pairs)
    else:
        await _seed_from_finnhub(pairs)

    # Verify warmup status
    from context.live_context_bus import LiveContextBus  # noqa: PLC0415

    bus = LiveContextBus()
    ready_count = 0
    for pair in pairs:
        status = bus.check_warmup(pair, warmup_min_bars)
        if status.get("ready"):
            ready_count += 1
        else:
            logger.warning(f"[SEED] {pair} warmup still insufficient after seeding: {status.get('missing')}")
    logger.info(f"[SEED] Warmup ready: {ready_count}/{len(pairs)} pairs")


async def _seed_from_redis(pairs: list[str]) -> None:
    """Load candle history from Redis Lists into LiveContextBus.

    Retries with backoff when Redis has no data yet (race condition: engine
    starts before ingest finishes seeding).
    """
    max_retries = int(os.getenv("ENGINE_WARMUP_MAX_RETRIES", "15"))
    retry_delay = float(os.getenv("ENGINE_WARMUP_RETRY_DELAY_SEC", "10"))

    try:
        from context.live_context_bus import LiveContextBus  # noqa: PLC0415
        from context.redis_consumer import RedisConsumer  # noqa: PLC0415
        from infrastructure.redis_url import get_redis_url  # noqa: PLC0415

        redis_url = get_redis_url()
        from redis.asyncio import Redis as AsyncRedis  # noqa: PLC0415

        redis_client: AsyncRedis = AsyncRedis.from_url(redis_url)
        try:
            consumer = RedisConsumer(symbols=pairs, redis_client=redis_client)
            bus = LiveContextBus()

            _h4_warmup = {"H1": 1, "H4": 5}
            _htf_verify = {"D1": 1, "W1": 1, "MN": 1}

            for attempt in range(1, max_retries + 1):
                await consumer.load_candle_history()

                h1_count = sum(1 for pair in pairs if bus.check_warmup(pair, _h4_warmup).get("ready"))

                if h1_count > 0:
                    logger.info(
                        "[SEED] Redis candle history loaded into LiveContextBus "
                        "(%d/%d pairs with H1 data, attempt %d). "
                        "M15 will arrive from tick stream after ~15 min.",
                        h1_count,
                        len(pairs),
                        attempt,
                    )

                    for pair in pairs:
                        htf_status = bus.check_warmup(pair, _htf_verify)
                        if htf_status.get("missing"):
                            missing_tfs = list(htf_status["missing"].keys())
                            logger.warning(
                                "[SEED] %s missing higher-TF data: %s — "
                                "L1 context/regime analysis may be degraded "
                                "until ingest delivers these timeframes.",
                                pair,
                                missing_tfs,
                            )
                    return

                if attempt < max_retries:
                    logger.warning(
                        "[SEED] No candle data in Redis yet (H1=%d, attempt %d/%d) — waiting %.0fs",
                        h1_count,
                        attempt,
                        max_retries,
                        retry_delay,
                    )
                    await asyncio.sleep(retry_delay)

            logger.critical(
                "[SEED] Redis still empty after %d retries (%.0fs total wait). "
                "Engine will continue in DEGRADED mode — analysis will be blind "
                "until live candles arrive.",
                max_retries,
                max_retries * retry_delay,
            )
        finally:
            await redis_client.aclose()
    except Exception as exc:
        logger.error(f"[SEED] Failed to seed from Redis: {exc}")


async def _seed_from_finnhub(pairs: list[str]) -> None:
    """Fetch historical candles from Finnhub REST API into LiveContextBus."""
    from ingest.finnhub_key_manager import finnhub_keys  # noqa: PLC0415

    if not finnhub_keys.available:
        logger.warning("[SEED] No Finnhub API key — skipping REST warmup")
        return
    try:
        from ingest.finnhub_candles import FinnhubCandleFetcher  # noqa: PLC0415

        fetcher = FinnhubCandleFetcher()
        results = await fetcher.warmup_all()
        total = sum(len(candles) for tfs in results.values() for candles in tfs.values())
        logger.info(f"[SEED] Finnhub warmup complete: {len(results)} symbols, {total} total bars")

        m15_seeded = await fetcher.cold_start_m15(bars=100)
        m15_total = sum(m15_seeded.values())
        logger.info(f"[SEED] M15 cold-start: {len(m15_seeded)} symbols, {m15_total} total bars")
    except Exception as exc:
        logger.error(f"[SEED] Failed to seed from Finnhub: {exc}")
