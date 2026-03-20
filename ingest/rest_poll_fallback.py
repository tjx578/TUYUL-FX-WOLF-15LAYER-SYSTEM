"""
REST polling fallback — hybrid mode.

Activates in two scenarios:
1. **WS fully down** — polls all symbols (original behaviour).
2. **WS connected but specific pairs silent** — polls only the pairs
   that haven't received a WebSocket tick within the silence threshold
   (e.g. exotic/minor crosses on Finnhub's OANDA feed).
"""

import asyncio
import time
from typing import Any

import orjson
from loguru import logger

from config_loader import load_finnhub
from context.live_context_bus import LiveContextBus
from ingest.finnhub_candles import FinnhubCandleError, FinnhubCandleFetcher
from ingest.finnhub_ws import is_forex_market_open
from storage.candle_persistence import enqueue_candle_dict


class RestPollFallback:
    """Periodic REST candle poller — hybrid WS-down / per-symbol-silence mode.

    Parameters
    ----------
    ws_connected_fn:
        Callable returning True when the WebSocket is connected.
    symbols:
        List of internal symbols to poll (e.g. ``["EURUSD", "XAUUSD"]``).
    """

    def __init__(
        self,
        ws_connected_fn: Any,
        symbols: list[str],
        redis_client: Any = None,
    ) -> None:
        super().__init__()
        cfg = load_finnhub()
        rest_poll_cfg = cfg.get("rest_poll_fallback", {})

        self._ws_connected = ws_connected_fn
        self._symbols = symbols
        self._redis = redis_client
        self._redis_maxlen = 300

        # Polling interval while WS is down (seconds)
        self._poll_interval: float = float(rest_poll_cfg.get("poll_interval_sec", 90))
        # Grace period before first poll after WS disconnect (seconds)
        self._grace_sec: float = float(rest_poll_cfg.get("grace_before_poll_sec", 30))
        # How many M15 bars to fetch per poll cycle
        self._bars: int = int(rest_poll_cfg.get("bars", 4))
        # Also refresh H1 during fallback
        self._refresh_h1: bool = bool(rest_poll_cfg.get("refresh_h1", True))
        self._h1_bars: int = int(rest_poll_cfg.get("h1_bars", 2))
        # Per-symbol silence check interval (when WS is up)
        self._silence_check_interval: float = float(rest_poll_cfg.get("silence_check_interval_sec", 60))

        self._fetcher = FinnhubCandleFetcher()
        self._context_bus = LiveContextBus()
        self._running = False

        logger.info(
            f"RestPollFallback initialized: interval={self._poll_interval}s, "
            f"grace={self._grace_sec}s, m15_bars={self._bars}, "
            f"refresh_h1={self._refresh_h1}, symbols={len(self._symbols)}"
        )

    async def run(self) -> None:
        """Main loop — hybrid: WS-down full poll + per-symbol silence poll."""
        self._running = True
        logger.info("RestPollFallback started — monitoring WS connection + per-symbol silence")

        while self._running:
            try:
                if not self._ws_connected():
                    # ── WS fully down path (original behaviour) ──
                    logger.info(f"WS disconnected — waiting {self._grace_sec:.0f}s grace before REST polling")
                    await asyncio.sleep(self._grace_sec)

                    if self._ws_connected():
                        logger.info("WS reconnected during grace period — skipping REST poll")
                        continue

                    logger.warning("WS still disconnected after grace — activating full REST poll fallback")
                    await self._poll_loop_ws_down()
                    logger.info("REST poll fallback deactivated — WS reconnected")
                else:
                    # ── WS connected: check for per-symbol silence ──
                    silent = self._get_silent_pairs()
                    if silent:
                        logger.info(
                            f"WS connected but {len(silent)} pairs silent — "
                            f"REST polling: {', '.join(sorted(silent))}"
                        )
                        if is_forex_market_open():
                            for symbol in silent:
                                if not self._running:
                                    break
                                await self._poll_symbol(symbol)
                    await asyncio.sleep(self._silence_check_interval)

            except asyncio.CancelledError:
                logger.info("RestPollFallback cancelled")
                raise
            except Exception:
                logger.exception("RestPollFallback unexpected error — restarting loop")
                await asyncio.sleep(5)

    def _get_silent_pairs(self) -> list[str]:
        """Return pairs whose last WS tick exceeds the silence threshold."""
        from ingest.dependencies import PAIR_WS_SILENCE_THRESHOLD_S, _pair_last_tick_ts

        now = time.time()
        silent: list[str] = []
        for symbol in self._symbols:
            last = _pair_last_tick_ts.get(symbol, 0.0)
            if now - last > PAIR_WS_SILENCE_THRESHOLD_S:
                silent.append(symbol)
        return silent

    async def _poll_loop_ws_down(self) -> None:
        """Fetch M15 (and optionally H1) candles until WS reconnects."""
        cycle = 0
        while self._running and not self._ws_connected():
            # Skip REST calls when forex market is closed (weekend)
            if not is_forex_market_open():
                logger.info("Forex market closed (weekend) — skipping REST poll cycle")
                await asyncio.sleep(self._poll_interval)
                continue

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
        from ingest.finnhub_key_manager import finnhub_keys  # noqa: PLC0415

        # ── GUARD: skip REST poll while Finnhub key is in cooldown ────
        key_statuses = finnhub_keys.status()
        if key_statuses and all(k["suspended"] for k in key_statuses):
            remaining = max(k["cooldown_remaining_sec"] for k in key_statuses)
            logger.warning(
                "[RestPoll] Finnhub key suspended (%.0fs cooldown) — "
                "skipping REST poll for %s, WS candle builder akan catchup",
                remaining,
                symbol,
            )
            return

        try:
            m15_candles = await self._fetcher.fetch(symbol, "M15", self._bars)
            for candle in m15_candles:
                self._context_bus.update_candle(candle)
            await self._push_candles_to_redis(m15_candles)

            if m15_candles:
                logger.debug(f"REST poll: seeded {len(m15_candles)} M15 bars for {symbol}")

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
                    await self._push_candles_to_redis(h1_candles)
                    h4_candles = self._fetcher.aggregate_h4(h1_candles)
                    for candle in h4_candles:
                        self._context_bus.update_candle(candle)
                    await self._push_candles_to_redis(h4_candles)

            except FinnhubCandleError as exc:
                logger.warning(f"REST poll H1 failed for {symbol}: {exc}")
            except Exception as exc:
                logger.error(f"REST poll H1 unexpected error for {symbol}: {exc}")

    async def stop(self) -> None:
        """Signal the fallback scheduler to stop."""
        self._running = False
        logger.info("RestPollFallback stopping")

    async def _push_candles_to_redis(self, candles: list[dict[str, Any]]) -> None:
        """RPUSH candle dicts to Redis history lists (best-effort)."""
        if not self._redis or not candles:
            return
        for candle in candles:
            symbol = candle.get("symbol")
            timeframe = candle.get("timeframe")
            if not symbol or not timeframe:
                continue
            key = f"wolf15:candle_history:{symbol}:{timeframe}"
            try:
                candle_json = orjson.dumps(candle).decode("utf-8")
                await self._redis.rpush(key, candle_json)
                await self._redis.ltrim(key, -self._redis_maxlen, -1)
                enqueue_candle_dict(candle)
            except Exception as exc:
                logger.warning("[RestPoll] RPUSH failed %s: %s", key, exc)
