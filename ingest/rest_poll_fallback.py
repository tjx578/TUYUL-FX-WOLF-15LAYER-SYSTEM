"""
REST polling fallback for when WebSocket is disconnected.

When the Finnhub WebSocket cannot connect or stays disconnected,
this scheduler periodically fetches M15 candles from the REST API
to keep the analysis pipeline fed with fresh data.

Activation is automatic: it polls only while ``ws_feed.is_connected``
is False.  Once WS reconnects, polling pauses until the next outage.
"""

import asyncio
from typing import Any

from loguru import logger

from config_loader import load_finnhub
from context.live_context_bus import LiveContextBus
from ingest.finnhub_candles import FinnhubCandleError, FinnhubCandleFetcher


class RestPollFallback:
    """Periodic REST candle poller that activates when WebSocket is down.

    Parameters
    ----------
    ws_connected_fn:
        Callable returning True when the WebSocket is connected.
        Typically ``lambda: ws_feed.is_connected``.
    symbols:
        List of internal symbols to poll (e.g. ``["EURUSD", "XAUUSD"]``).
    """

    def __init__(
        self,
        ws_connected_fn: Any,
        symbols: list[str],
    ) -> None:
        super().__init__()
        cfg = load_finnhub()
        rest_poll_cfg = cfg.get("rest_poll_fallback", {})

        self._ws_connected = ws_connected_fn
        self._symbols = symbols

        # Polling interval while WS is down (seconds)
        self._poll_interval: float = float(
            rest_poll_cfg.get("poll_interval_sec", 90)
        )
        # Grace period before first poll after WS disconnect (seconds)
        self._grace_sec: float = float(
            rest_poll_cfg.get("grace_before_poll_sec", 30)
        )
        # How many M15 bars to fetch per poll cycle
        self._bars: int = int(rest_poll_cfg.get("bars", 4))
        # Also refresh H1 during fallback
        self._refresh_h1: bool = bool(rest_poll_cfg.get("refresh_h1", True))
        self._h1_bars: int = int(rest_poll_cfg.get("h1_bars", 2))

        self._fetcher = FinnhubCandleFetcher()
        self._context_bus = LiveContextBus()
        self._running = False

        logger.info(
            f"RestPollFallback initialized: interval={self._poll_interval}s, "
            f"grace={self._grace_sec}s, m15_bars={self._bars}, "
            f"refresh_h1={self._refresh_h1}, symbols={len(self._symbols)}"
        )

    async def run(self) -> None:
        """Main loop — runs forever, polls only when WS is disconnected."""
        self._running = True
        logger.info("RestPollFallback started — monitoring WS connection state")

        while self._running:
            try:
                # Wait until WS is down
                await self._wait_for_ws_down()
                if not self._running:
                    break

                # Grace period: WS might reconnect quickly
                logger.info(
                    f"WS disconnected — waiting {self._grace_sec:.0f}s grace before REST polling"
                )
                await asyncio.sleep(self._grace_sec)

                # Re-check after grace
                if self._ws_connected():
                    logger.info("WS reconnected during grace period — skipping REST poll")
                    continue

                # Enter polling loop
                logger.warning(
                    "WS still disconnected after grace — activating REST poll fallback"
                )

                await self._poll_loop()

                # WS reconnected or stopped
                logger.info("REST poll fallback deactivated — WS reconnected")

            except asyncio.CancelledError:
                logger.info("RestPollFallback cancelled")
                raise
            except Exception:
                logger.exception("RestPollFallback unexpected error — restarting loop")
                await asyncio.sleep(5)

    async def _wait_for_ws_down(self) -> None:
        """Block until WS reports disconnected (or stopped)."""
        while self._running and self._ws_connected():
            await asyncio.sleep(5)

    async def _poll_loop(self) -> None:
        """Fetch M15 (and optionally H1) candles until WS reconnects."""
        cycle = 0
        while self._running and not self._ws_connected():
            cycle += 1
            logger.info(f"REST poll cycle #{cycle} for {len(self._symbols)} symbols")

            for symbol in self._symbols:
                if self._ws_connected():
                    return  # WS back — stop immediately
                await self._poll_symbol(symbol)

            # Sleep between cycles, checking WS state periodically
            elapsed = 0.0
            while elapsed < self._poll_interval and self._running:
                if self._ws_connected():
                    return
                await asyncio.sleep(min(5.0, self._poll_interval - elapsed))
                elapsed += 5.0

    async def _poll_symbol(self, symbol: str) -> None:
        """Fetch M15 + optional H1 for a single symbol and seed the context bus."""
        try:
            m15_candles = await self._fetcher.fetch(symbol, "M15", self._bars)
            for candle in m15_candles:
                self._context_bus.update_candle(candle)

            if m15_candles:
                logger.debug(
                    f"REST poll: seeded {len(m15_candles)} M15 bars for {symbol}"
                )

        except FinnhubCandleError as exc:
            logger.warning(f"REST poll M15 failed for {symbol}: {exc}")
        except Exception as exc:
            logger.error(f"REST poll M15 unexpected error for {symbol}: {exc}")

        if self._refresh_h1:
            try:
                h1_candles = await self._fetcher.fetch(symbol, "H1", self._h1_bars)
                for candle in h1_candles:
                    self._context_bus.update_candle(candle)

                # Also aggregate H4
                if h1_candles:
                    h4_candles = self._fetcher.aggregate_h4(h1_candles)
                    for candle in h4_candles:
                        self._context_bus.update_candle(candle)

            except FinnhubCandleError as exc:
                logger.warning(f"REST poll H1 failed for {symbol}: {exc}")
            except Exception as exc:
                logger.error(f"REST poll H1 unexpected error for {symbol}: {exc}")

    async def stop(self) -> None:
        """Signal the fallback scheduler to stop."""
        self._running = False
        logger.info("RestPollFallback stopping")
