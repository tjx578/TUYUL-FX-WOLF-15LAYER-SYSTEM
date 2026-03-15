import asyncio
import datetime

from loguru import logger

from analysis.macro.macro_regime_engine import MacroRegimeEngine
from ingest.finnhub_candles import FinnhubCandleFetcher


class MacroMonthlyScheduler:
    """Auto-refresh MN candles and run macro regime analysis on month change."""

    def __init__(self, symbols: list[str], redis_client=None):
        self.symbols = symbols
        self.fetcher = FinnhubCandleFetcher()
        self.engine = MacroRegimeEngine(redis_client)
        self.last_month = None

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

                # Recompute macro regime
                self.engine.update_macro_state(symbol)

                logger.info(f"MN refreshed and regime updated for {symbol}")
            except Exception as exc:
                logger.error(f"Failed to refresh MN for {symbol}: {exc}")
