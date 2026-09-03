"""
H1/H4 periodic refresh scheduler.

Refreshes H1 candles hourly and re-aggregates H4.
Detects price drift between REST and WebSocket feeds.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from importlib import import_module
from typing import Any, cast

import orjson
from loguru import logger

get_enabled_symbols = cast(Callable[[], list[str]], import_module("config_loader").get_enabled_symbols)
load_finnhub = cast(Callable[[], dict[str, Any]], import_module("config_loader").load_finnhub)
LiveContextBus = import_module("context.live_context_bus").LiveContextBus
_system_state_mod = import_module("context.system_state")
SystemState = _system_state_mod.SystemState
SystemStateManager = _system_state_mod.SystemStateManager
_redis_keys_mod = import_module("core.redis_keys")
candle_history = cast(Callable[[str, str], str], _redis_keys_mod.candle_history)
channel_candle = cast(Callable[[str, str], str], _redis_keys_mod.channel_candle)
latest_candle = cast(Callable[[str, str], str], _redis_keys_mod.latest_candle)
_finnhub_candles_mod = import_module("ingest.finnhub_candles")
FinnhubCandleFetcher = _finnhub_candles_mod.FinnhubCandleFetcher
_hybrid_candles_mod = import_module("ingest.hybrid_candle_provider")
HybridCandleProvider = _hybrid_candles_mod.HybridCandleProvider


def enqueue_candle_dict(candle: dict[str, Any]) -> None:
    """Best-effort persistence enqueue without hard-importing PostgreSQL deps."""
    try:
        _enqueue = import_module("storage.candle_persistence").enqueue_candle_dict
        _enqueue(candle)
    except Exception as exc:
        logger.debug("[H1Refresh] candle persistence enqueue skipped: {}", exc)


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
        # At least eight H1 bars are required so an arbitrary refresh boundary
        # contains one complete aligned H4 group plus the currently forming group.
        self.h1_bars = max(8, int(self.refresh_config.get("h1_bars", 8)))
        self.max_drift_pips = self.refresh_config.get("price_drift_max_pips", 50.0)
        self.m15_min_bars = self.refresh_config.get("m15_cold_start_min_bars", 10)
        self.m15_recovery_bars = self.refresh_config.get("m15_recovery_bars", 100)

        self.fetcher = FinnhubCandleFetcher()
        self.context_bus = LiveContextBus()
        self.system_state = SystemStateManager()
        self._redis = redis_client
        self._redis_maxlen = 300
        self._repair_provider = HybridCandleProvider(
            finnhub_fetcher=self.fetcher,
            redis_client=redis_client,
        )

        # Semaphore for concurrent refresh
        self.semaphore = asyncio.Semaphore(3)

        logger.info(
            f"H1RefreshScheduler initialized: interval={self.interval_sec}s, "
            f"bars={self.h1_bars}, max_drift={self.max_drift_pips} pips"
        )

    def _refresh_allowed(self) -> bool:
        """Allow refresh once bootstrap has reached READY or DEGRADED.

        DEGRADED stale-cache mode still needs this scheduler to run so it can
        repair stale H1/H4 data instead of waiting forever for READY.
        """
        if self.system_state.is_ready():
            return True
        with contextlib.suppress(Exception):
            return self.system_state.get_state() == SystemState.DEGRADED
        return False

    async def run(self) -> None:
        """Main refresh loop."""
        logger.info("H1RefreshScheduler started")

        # Wait for bootstrap to settle.  In stale-cache mode the system can be
        # DEGRADED until this refresh repairs cached H1/H4 data.
        while not self._refresh_allowed():
            logger.debug("Waiting for bootstrap before starting H1 refresh...")
            await asyncio.sleep(10)

        first_cycle = True
        while True:
            try:
                if first_cycle:
                    first_cycle = False
                else:
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

        Uses the hybrid REST repair chain. Finnhub is primary for all symbols;
        configured substitute providers are backups unless an emergency
        substitute-first override is enabled.

        Args:
            symbol: Trading symbol
        """
        async with self.semaphore:
            try:
                # Fetch latest H1 bars through hybrid repair:
                # Finnhub first, substitute providers only as backup by default.
                repair_result = await self._repair_provider.fetch(symbol, "H1", self.h1_bars)
                h1_candles: list[dict[str, Any]] = repair_result.candles
                provider_used = repair_result.provider

                if not h1_candles:
                    logger.warning(
                        "No H1 bars fetched for {} during refresh (reason={} attempts={})",
                        symbol,
                        repair_result.reason,
                        repair_result.attempts,
                    )
                    return

                logger.debug(
                    "[H1Refresh] {} H1 bars fetched for {} via {} ({})",
                    len(h1_candles),
                    symbol,
                    provider_used,
                    repair_result.reason,
                )

                # Retain forming provider observations durably, but expose only
                # explicitly closed bars to analysis/history consumers.
                for candle in h1_candles:
                    if candle.get("complete") is not True:
                        enqueue_candle_dict(candle)
                closed_h1 = [candle for candle in h1_candles if candle.get("complete") is True]
                if not closed_h1:
                    logger.info(
                        "[H1Refresh] {} returned only forming H1 bars; waiting for close refresh",
                        symbol,
                    )
                    return
                for candle in closed_h1:
                    self.context_bus.update_candle(candle)
                await self._push_candles_to_redis(closed_h1)

                # Re-aggregate H4
                h4_observations = self.fetcher.aggregate_h4(closed_h1)
                h4_candles = [candle for candle in h4_observations if candle.get("complete") is True]
                for candle in h4_candles:
                    self.context_bus.update_candle(candle)
                await self._push_candles_to_redis(h4_candles)

                # Check price drift
                drift_check = self.context_bus.check_price_drift(symbol, self.max_drift_pips)

                if drift_check.get("comparable") is not True:
                    logger.debug(
                        "{} price drift NOT EVALUATED: reason={} observed_live_gap_pips={}",
                        symbol,
                        drift_check.get("reason", "MISSING_COMPARABILITY_EVIDENCE"),
                        drift_check.get("observed_live_gap_pips"),
                    )
                elif drift_check["drifted"]:
                    logger.warning(
                        "{} PRICE DRIFT DETECTED: {:.1f} pips "
                        "(REST_H1={} WS_H1={} close_time={})",
                        symbol,
                        drift_check["drift_pips"],
                        drift_check["rest_close"],
                        drift_check.get("ws_h1_close"),
                        drift_check.get("rest_close_time"),
                    )
                    self.system_state.mark_symbol_degraded(symbol, f"Price drift {drift_check['drift_pips']:.1f} pips")
                else:
                    logger.debug("{} price drift OK: {:.1f} pips", symbol, drift_check["drift_pips"])
                    # Check if symbol was degraded and can be recovered
                    self.system_state.mark_symbol_recovered(symbol)

                logger.debug(f"Refreshed {symbol}: {len(closed_h1)} H1, {len(h4_candles)} H4")

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
        """RPUSH candle dicts to Redis history lists (best-effort, deduplicated)."""
        if not candles:
            return
        # Database observations are independent from Redis availability and
        # list-level duplicate suppression. This is what permits a later REST
        # refresh to promote the same provider window from forming to closed.
        for candle in candles:
            enqueue_candle_dict(candle)
        if not self._redis:
            return
        import time as _time  # noqa: PLC0415

        candle_bridge = import_module("core.candle_bridge_fix")
        is_duplicate_candle = candle_bridge.is_duplicate_candle
        replace_candle_history_entry = candle_bridge.replace_candle_history_entry

        for candle in candles:
            symbol = candle.get("symbol")
            timeframe = candle.get("timeframe")
            if not symbol or not timeframe:
                continue
            key = candle_history(symbol, timeframe)
            try:
                # ── Dedup: skip candles whose open_time already in Redis tail ──
                if await is_duplicate_candle(self._redis, key, candle):
                    replaced = await replace_candle_history_entry(self._redis, key, candle)
                    if not replaced:
                        logger.debug("[H1Refresh] Dedup skip {} {}", symbol, timeframe)
                        continue
                    candle_json = orjson.dumps(candle).decode("utf-8")
                    await self._redis.publish(channel_candle(symbol, timeframe), candle_json)
                    await self._redis.hset(
                        latest_candle(symbol, timeframe),
                        mapping={
                            "data": candle_json,
                            "last_seen_ts": str(_time.time()),
                        },
                    )
                    continue

                candle_json = orjson.dumps(candle).decode("utf-8")
                await self._redis.rpush(key, candle_json)
                await self._redis.ltrim(key, -self._redis_maxlen, -1)
                # PUBLISH so engine RedisConsumer picks up refresh in real-time
                pub_channel = channel_candle(symbol, timeframe)
                await self._redis.publish(pub_channel, candle_json)
                # Update latest_candle hash so pipeline staleness check
                # sees fresh data from REST-sourced candles (not only WS).
                hash_key = latest_candle(symbol, timeframe)
                await self._redis.hset(
                    hash_key,
                    mapping={
                        "data": candle_json,
                        "last_seen_ts": str(_time.time()),
                    },
                )
            except Exception as exc:
                logger.warning("[H1Refresh] Redis push failed {}: {}", key, exc)
