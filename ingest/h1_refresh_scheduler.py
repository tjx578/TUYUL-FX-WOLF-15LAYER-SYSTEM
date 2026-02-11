"""
H1/H4 periodic refresh scheduler.

Refreshes H1 candles hourly and re-aggregates H4.
Detects price drift between REST and WebSocket feeds.
"""

import asyncio

from datetime import UTC, datetime

from loguru import logger

from config_loader import CONFIG, load_finnhub
from context.live_context_bus import LiveContextBus
from context.system_state import SystemStateManager
from ingest.finnhub_candles import FinnhubCandleFetcher


class H1RefreshScheduler:
    """
    Periodic H1/H4 refresh scheduler.
    
    Runs every N minutes (default 60) to:
    - Fetch latest H1 bars
    - Re-aggregate H4
    - Check price drift
    - Mark symbols as degraded if drift exceeds threshold
    """
    
    def __init__(self) -> None:
        self.config = load_finnhub()
        self.refresh_config = self.config.get("candles", {}).get("refresh", {})
        
        self.interval_sec = self.refresh_config.get("h1_interval_sec", 3600)
        self.h1_bars = self.refresh_config.get("h1_bars", 5)
        self.max_drift_pips = self.refresh_config.get("price_drift_max_pips", 50.0)
        
        self.fetcher = FinnhubCandleFetcher()
        self.context_bus = LiveContextBus()
        self.system_state = SystemStateManager()
        
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
        """Refresh H1/H4 for all enabled symbols."""
        enabled_symbols = CONFIG["pairs"].get("symbols", [])
        if not enabled_symbols:
            logger.warning("No enabled symbols for H1 refresh")
            return
        
        logger.info(f"Starting H1 refresh for {len(enabled_symbols)} symbols")
        
        tasks = []
        for symbol in enabled_symbols:
            tasks.append(self._refresh_symbol(symbol))
        
        await asyncio.gather(*tasks, return_exceptions=True)
        
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
                
                # Re-aggregate H4
                h4_candles = self.fetcher._aggregate_h4(h1_candles)
                for candle in h4_candles:
                    self.context_bus.update_candle(candle)
                
                # Check price drift
                drift_check = self.context_bus.check_price_drift(symbol, self.max_drift_pips)
                
                if drift_check["drifted"]:
                    logger.warning(
                        f"{symbol} PRICE DRIFT DETECTED: "
                        f"{drift_check['drift_pips']:.1f} pips "
                        f"(REST={drift_check['rest_close']}, WS={drift_check['ws_mid']})"
                    )
                    self.system_state.mark_symbol_degraded(
                        symbol, 
                        f"Price drift {drift_check['drift_pips']:.1f} pips"
                    )
                else:
                    logger.debug(
                        f"{symbol} price drift OK: {drift_check['drift_pips']:.1f} pips"
                    )
                    # Check if symbol was degraded and can be recovered
                    self.system_state.mark_symbol_recovered(symbol)
                
                logger.debug(
                    f"Refreshed {symbol}: {len(h1_candles)} H1, {len(h4_candles)} H4"
                )
                
            except Exception as exc:
                logger.error(f"Error refreshing {symbol}: {exc}")
