"""
H1/H4 periodic refresh scheduler.

Refreshes H1 candles hourly and re-aggregates H4.
Detects price drift between REST and WebSocket feeds.
"""

from __future__ import annotations

import asyncio
from typing import Any

import orjson
from loguru import logger

from config_loader import get_enabled_symbols, load_finnhub
from context.live_context_bus import LiveContextBus
from context.system_state import SystemStateManager
from core.redis_keys import candle_history, channel_candle
from ingest.finnhub_candles import FinnhubCandleFetcher
from storage.candle_persistence import enqueue_candle_dict


class H1RefreshScheduler:
    """
    Periodic H1/H4 refresh scheduler.

    Runs every N seconds (default 3600) to:
    - Fetch latest H1 bars
    - Re-aggregate H4
    - Check price drift
    - Mark symbols as degraded if drift exceeds threshold
    """

    def __init__(self, redis_client: Any = None) -> None:
        self.config = load_finnhub()
        self.refresh_config = self.config.get("candles", {}).get("refresh", {})

        self.interval_sec = self.refresh_config.get("h1_interval_sec", 3600)
        self.h1_bars = self.refresh_config.get("h1_bars", 5)
        self.max_drift_pips = self.refresh_config.get("price_drift_max_pips", 50.0)
        self.m15_min_bars = self.refresh_config.get("m15_cold_start_min_bars", 10)
        self.m15_recovery_bars = self.refresh_config.get("m15_recovery_bars", 100)

        self.fetcher = FinnhubCandleFetcher()
        self.context_bus = LiveContextBus()
        self.system_state = SystemStateManager()
        self._redis = redis_client
        self._redis_maxlen = 300

        # Semaphore for concurrent refresh
        self.semaphore = asyncio.Semaphore(3)

        logger.info(
            f"H1RefreshScheduler initialized: interval={self.interval_sec}s, "
            f"bars={self.h1_bars}, max_drift={self.max_drift_pips} pips"
        )

    async def run(self) -> None:
        """Main refresh loop."""
        logger.info("H1RefreshScheduler started")

        # Wait for system to be ready before starting refresh
        while not self.system_state.is_ready():
            logger.debug("Waiting for system to be ready before starting H1 refresh...")
            await asyncio.sleep(10)

        while True:
            try:
                await asyncio.sleep(self.interval_sec)
                await self.refresh_all_symbols()
            except asyncio.CancelledError:
                logger.info("H1RefreshScheduler cancelled")
                raise
            except Exception as exc:
                logger.exception(f"H1 refresh error: {exc}")

    async def refresh_all_symbols(self) -> None:
        """Refresh H1/H4 for all enabled symbols and check M15 coldness."""
        enabled_symbols = get_enabled_symbols()
        if not enabled_symbols:
            logger.warning("No enabled symbols for H1 refresh")
            return

        logger.info(f"Starting H1 refresh for {len(enabled_symbols)} symbols")

        tasks = [self._refresh_symbol(symbol) for symbol in enabled_symbols]

        await asyncio.gather(*tasks, return_exceptions=True)

        # ── M15 cold start detection ──
        await self._check_m15_cold_start(enabled_symbols)

        logger.info("H1 refresh complete")

    async def _refresh_symbol(self, symbol: str) -> None:
        """
        Refresh H1/H4 for a single symbol.

        Args:
            symbol: Trading symbol
        """
        async with self.semaphore:
            try:
                # Fetch latest H1 bars
                h1_candles = await self.fetcher.fetch(symbol, "H1", self.h1_bars)

                if not h1_candles:
                    logger.warning(f"No H1 bars fetched for {symbol} during refresh")
                    return

                # Seed LiveContextBus
                for candle in h1_candles:
                    self.context_bus.update_candle(candle)
                await self._push_candles_to_redis(h1_candles)

                # Re-aggregate H4
                h4_candles = self.fetcher.aggregate_h4(h1_candles)
                for candle in h4_candles:
                    self.context_bus.update_candle(candle)
                await self._push_candles_to_redis(h4_candles)

                # Check price drift
                drift_check = self.context_bus.check_price_drift(symbol, self.max_drift_pips)

                if drift_check["drifted"]:
                    logger.warning(
                        f"{symbol} PRICE DRIFT DETECTED: "
                        f"{drift_check['drift_pips']:.1f} pips "
                        f"(REST={drift_check['rest_close']}, WS={drift_check['ws_mid']})"
                    )
                    self.system_state.mark_symbol_degraded(symbol, f"Price drift {drift_check['drift_pips']:.1f} pips")
                else:
                    logger.debug(f"{symbol} price drift OK: {drift_check['drift_pips']:.1f} pips")
                    # Check if symbol was degraded and can be recovered
                    self.system_state.mark_symbol_recovered(symbol)

                logger.debug(f"Refreshed {symbol}: {len(h1_candles)} H1, {len(h4_candles)} H4")

            except Exception as exc:
                logger.error(f"Error refreshing {symbol}: {exc}")

    async def _check_m15_cold_start(self, symbols: list[str]) -> None:
        """Detect symbols with stale/missing M15 data and trigger REST recovery.

        A symbol is considered "cold" if its M15 bar count in LiveContextBus
        is below ``m15_min_bars`` (default 10).  When cold symbols are found,
        ``FinnhubCandleFetcher.cold_start_m15()`` fetches M15 bars from REST
        and seeds them back into the bus.
        """
        cold_symbols: list[str] = []
        for symbol in symbols:
            m15_count = self.context_bus.get_warmup_bar_count(symbol, "M15")
            if m15_count < self.m15_min_bars:
                cold_symbols.append(symbol)

        if not cold_symbols:
            return

        logger.warning(
            "M15 cold start detected for %d symbols: %s — triggering REST recovery",
            len(cold_symbols),
            cold_symbols,
        )

        try:
            seeded = await self.fetcher.cold_start_m15(
                symbols=cold_symbols,
                bars=self.m15_recovery_bars,
            )
            for sym, count in seeded.items():
                logger.info(f"M15 cold-start recovered {count} bars for {sym}")
        except Exception as exc:
            logger.error(f"M15 cold-start recovery failed: {exc}")

    async def _push_candles_to_redis(self, candles: list[dict[str, Any]]) -> None:
        """RPUSH candle dicts to Redis history lists (best-effort)."""
        if not self._redis or not candles:
            return
        for candle in candles:
            symbol = candle.get("symbol")
            timeframe = candle.get("timeframe")
            if not symbol or not timeframe:
                continue
            key = candle_history(symbol, timeframe)
            try:
                candle_json = orjson.dumps(candle).decode("utf-8")
                await self._redis.rpush(key, candle_json)
                await self._redis.ltrim(key, -self._redis_maxlen, -1)
                enqueue_candle_dict(candle)
                # PUBLISH so engine RedisConsumer picks up refresh in real-time
                pub_channel = channel_candle(symbol, timeframe)
                await self._redis.publish(pub_channel, candle_json)
            except Exception as exc:
                logger.warning("[H1Refresh] Redis push failed %s: %s", key, exc)
