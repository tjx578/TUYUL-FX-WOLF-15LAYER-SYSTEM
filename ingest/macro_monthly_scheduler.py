from __future__ import annotations

import asyncio
import datetime
from typing import Any

import orjson
from loguru import logger

from analysis.macro.macro_regime_engine import MacroRegimeEngine
from core.redis_keys import candle_history, channel_candle
from ingest.finnhub_candles import FinnhubCandleFetcher
from storage.candle_persistence import enqueue_candle_dict


class MacroMonthlyScheduler:
    """Auto-refresh MN candles and run macro regime analysis on month change."""

    def __init__(self, symbols: list[str], redis_client: Any = None):
        self.symbols = symbols
        self.fetcher = FinnhubCandleFetcher()
        self.engine = MacroRegimeEngine(redis_client)
        self._redis = redis_client
        self._redis_maxlen = 300
        self.last_month: tuple[int, int] | None = None

    async def run(self) -> None:
        logger.info("MacroMonthlyScheduler started")
        while True:
            try:
                await self._check_and_refresh()
                await asyncio.sleep(3600)  # check hourly
            except asyncio.CancelledError:
                logger.info("MacroMonthlyScheduler cancelled")
                return
            except Exception as exc:
                logger.error(f"MacroMonthlyScheduler error: {exc}")
                await asyncio.sleep(3600)

    async def _check_and_refresh(self) -> None:
        now = datetime.datetime.utcnow()  # noqa: DTZ003
        current_key = (now.year, now.month)

        if self.last_month is None:
            # Initialize without triggering refresh immediately
            self.last_month = current_key
            return

        if current_key != self.last_month:
            logger.info(f"Month changed: {self.last_month} -> {current_key}")
            await self._refresh_all()
            self.last_month = current_key

    async def _refresh_all(self) -> None:
        for symbol in self.symbols:
            try:
                logger.debug(f"Refreshing MN for {symbol}")
                mn_candles = await self.fetcher.fetch(symbol, "MN", bars=120)
                if not mn_candles:
                    logger.warning(f"No MN candles for {symbol}")
                    continue

                for candle in mn_candles:
                    self.fetcher.context_bus.update_candle(candle)
                await self._push_candles_to_redis(mn_candles)

                # Recompute macro regime
                self.engine.update_macro_state(symbol)

                logger.info(f"MN refreshed and regime updated for {symbol}")
            except Exception as exc:
                logger.error(f"Failed to refresh MN for {symbol}: {exc}")

    async def _push_candles_to_redis(self, candles: list[dict[str, Any]]) -> None:
        """RPUSH + PUBLISH MN candle dicts to Redis (best-effort)."""
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
                pub_channel = channel_candle(symbol, timeframe)
                await self._redis.publish(pub_channel, candle_json)
            except Exception as exc:
                logger.warning("[MacroMonthly] Redis push failed {}: {}", key, exc)
