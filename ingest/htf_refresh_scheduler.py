"""
Higher-Timeframe (D1/W1) periodic refresh scheduler.

D1 and W1 candles are seeded once at startup but never refreshed.
This scheduler fetches fresh D1 & W1 bars periodically so the
data-quality gate in the engine does not flag them as stale.

Follows the same pattern as H1RefreshScheduler.
"""

import asyncio
from collections import defaultdict
from typing import Any

import orjson
from loguru import logger

from config_loader import get_enabled_symbols, load_finnhub
from context.live_context_bus import LiveContextBus
from context.system_state import SystemStateManager
from core.redis_keys import candle_history, channel_candle
from ingest.finnhub_candles import FinnhubCandleFetcher
from storage.candle_persistence import enqueue_candle_dict


class HTFRefreshScheduler:
    """
    Periodic D1/W1 refresh scheduler.

    Runs every *interval_sec* (default 4 h) to:
    - Fetch latest D1 bars for all enabled symbols.
    - Fetch latest W1 bars for all enabled symbols.
    - RPUSH + PUBLISH to Redis so the engine container picks up the
      update via RedisConsumer pub/sub.
    """

    def __init__(self, redis_client: Any = None) -> None:
        config = load_finnhub()
        refresh_cfg = config.get("candles", {}).get("refresh", {})

        self.interval_sec: int = refresh_cfg.get("htf_interval_sec", 14400)  # 4 hours
        self.d1_bars: int = refresh_cfg.get("d1_bars", 10)
        self.w1_bars: int = refresh_cfg.get("w1_bars", 8)

        self.fetcher = FinnhubCandleFetcher()
        self.context_bus = LiveContextBus()
        self.system_state = SystemStateManager()
        self._redis = redis_client
        self._redis_maxlen = 300

        self.semaphore = asyncio.Semaphore(3)

        logger.info(
            "HTFRefreshScheduler initialized: interval={}s, d1_bars={}, w1_bars={}",
            self.interval_sec,
            self.d1_bars,
            self.w1_bars,
        )

    async def run(self) -> None:
        """Main refresh loop."""
        logger.info("HTFRefreshScheduler started")

        while not self.system_state.is_ready():
            logger.debug("HTFRefresh waiting for system ready…")
            await asyncio.sleep(10)

        while True:
            try:
                await asyncio.sleep(self.interval_sec)
                await self.refresh_all_symbols()
            except asyncio.CancelledError:
                logger.info("HTFRefreshScheduler cancelled")
                raise
            except Exception as exc:
                logger.exception("HTF refresh error: {}", exc)

    async def force_refresh_now(self) -> None:
        """Trigger an immediate D1/W1 refresh (e.g. after WS reconnect).

        Called from outside the regular loop to shorten the recovery window
        when HTF candles are stale due to a WS disconnect/reconnect cycle.
        """
        logger.info("HTFRefreshScheduler: force refresh triggered (WS reconnect)")
        try:
            await self.refresh_all_symbols()
        except Exception as exc:
            logger.error("HTFRefreshScheduler: force refresh failed: {}", exc)

    async def refresh_all_symbols(self) -> None:
        """Refresh D1/W1 for every enabled symbol."""
        symbols = get_enabled_symbols()
        if not symbols:
            logger.warning("No enabled symbols for HTF refresh")
            return

        logger.info("Starting D1/W1 refresh for {} symbols", len(symbols))

        tasks = [self._refresh_symbol(sym) for sym in symbols]
        await asyncio.gather(*tasks, return_exceptions=True)

        logger.info("D1/W1 refresh complete")

    async def _refresh_symbol(self, symbol: str) -> None:
        async with self.semaphore:
            try:
                # ── D1 ──
                d1 = await self.fetcher.fetch(symbol, "D1", self.d1_bars)
                if d1:
                    for c in d1:
                        self.context_bus.update_candle(c)
                    await self._push_candles_to_redis(d1)
                else:
                    logger.warning("No D1 bars fetched for {} during HTF refresh", symbol)

                # ── W1 ──
                w1 = await self.fetcher.fetch(symbol, "W1", self.w1_bars)
                if w1:
                    for c in w1:
                        self.context_bus.update_candle(c)
                    await self._push_candles_to_redis(w1)
                else:
                    logger.warning("No W1 bars fetched for {} during HTF refresh", symbol)

                logger.debug("HTF refreshed {}: D1={}, W1={}", symbol, len(d1 or []), len(w1 or []))
            except Exception as exc:
                logger.error("HTF refresh error for {}: {}", symbol, exc)

    async def _push_candles_to_redis(self, candles: list[dict[str, Any]]) -> None:
        """RPUSH + PUBLISH candle dicts to Redis (best-effort).

        Candles are grouped by key so each unique key receives a single
        RPUSH with all its values and one LTRIM, reducing round trips
        from (rpush + ltrim + publish) × N to
        (rpush + ltrim) × K + publish × N  (K = unique keys ≤ N).
        """
        if not self._redis or not candles:
            return

        # ── Group valid candles by Redis key to batch writes ─────────────────
        # Reduces round trips: 3 × N → 2 × K + N  (K = unique keys, K ≤ N).
        key_batches: dict[str, list[tuple[str, str, dict[str, Any]]]] = defaultdict(list)
        for candle in candles:
            symbol = candle.get("symbol")
            timeframe = candle.get("timeframe")
            if not symbol or not timeframe:
                continue
            key = candle_history(symbol, timeframe)
            candle_json = orjson.dumps(candle).decode("utf-8")
            pub_channel = channel_candle(symbol, timeframe)
            key_batches[key].append((candle_json, pub_channel, candle))

        for key, items in key_batches.items():
            try:
                # Push all candles for this key in one RPUSH call, then trim once
                await self._redis.rpush(key, *[item[0] for item in items])
                await self._redis.ltrim(key, -self._redis_maxlen, -1)
                for candle_json, pub_channel, candle in items:
                    enqueue_candle_dict(candle)
                    # PUBLISH so engine RedisConsumer sees the update in real-time
                    await self._redis.publish(pub_channel, candle_json)
            except Exception as exc:
                logger.warning("[HTFRefresh] Redis push failed {}: {}", key, exc)
