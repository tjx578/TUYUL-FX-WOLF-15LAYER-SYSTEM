"""
REST polling fallback — hybrid mode.

Activates in two scenarios:
1. **WS fully down** — polls all symbols (original behaviour).
2. **WS connected but specific pairs silent** — polls only the pairs
   that haven't received a WebSocket tick within the silence threshold
   (e.g. exotic/minor crosses on Finnhub's OANDA feed).
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from typing import Any

import orjson
from loguru import logger

from config_loader import load_finnhub
from context.live_context_bus import LiveContextBus
from core.redis_keys import candle_history, channel_candle
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

    # TTL for candle history keys (6 hours)
    _HISTORY_TTL_SEC = 6 * 3600

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

        # Track redis write stats for diagnostics
        self._redis_writes: int = 0
        self._redis_skips: int = 0

        # Log redis client status at init for visibility
        if self._redis is None:
            logger.error(
                "[RestPoll] redis_client is None at init! "
                "All candle writes will be silently skipped. "
                "Check ingest_service.py redis_client injection."
            )
        else:
            logger.info(
                "[RestPoll] redis_client injected OK: %s",
                type(self._redis).__name__,
            )

        logger.info(
            "RestPollFallback initialized: interval=%.1fs, grace=%.1fs, m15_bars=%d, refresh_h1=%s, symbols=%d",
            self._poll_interval,
            self._grace_sec,
            self._bars,
            self._refresh_h1,
            len(self._symbols),
        )

    async def run(self) -> None:
        """Main loop — hybrid: WS-down full poll + per-symbol silence poll."""
        self._running = True
        logger.info("RestPollFallback started — monitoring WS connection + per-symbol silence")

        while self._running:
            try:
                if not self._ws_connected():
                    # ── WS fully down path (original behaviour) ──
                    logger.info(
                        "WS disconnected — waiting %.0fs grace before REST polling",
                        self._grace_sec,
                    )
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
                            "WS connected but %d pairs silent — REST polling: %s",
                            len(silent),
                            ", ".join(sorted(silent)),
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
            logger.info(
                "REST poll cycle #%d for %d symbols",
                cycle,
                len(self._symbols),
            )

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

    # ── FIX: ensure candle dicts always contain symbol + timeframe ──
    @staticmethod
    def _normalize_candles(
        candles: list[dict[str, Any]],
        symbol: str,
        timeframe: str,
    ) -> list[dict[str, Any]]:
        """Inject symbol/timeframe into candle dicts if missing.

        FinnhubCandleFetcher.fetch() may return candle dicts parsed
        from the REST API response ({c,h,l,o,t,v}) without symbol
        and timeframe fields — those are parameters of the fetch call,
        not fields in Finnhub's response payload.

        Without this normalization, _push_candles_to_redis() silently
        skips every candle because candle.get("symbol") returns None.
        """
        normalized: list[dict[str, Any]] = []
        for candle in candles:
            c = dict(candle)  # shallow copy — don't mutate upstream data
            if not c.get("symbol"):
                c["symbol"] = symbol
            if not c.get("timeframe"):
                c["timeframe"] = timeframe
            normalized.append(c)
        return normalized

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
            # ── FIX: normalize before context bus + redis push ──
            m15_candles = self._normalize_candles(m15_candles, symbol, "M15")

            for candle in m15_candles:
                self._context_bus.update_candle(candle)
            await self._push_candles_to_redis(m15_candles)

            if m15_candles:
                logger.debug(
                    "REST poll: seeded %d M15 bars for %s",
                    len(m15_candles),
                    symbol,
                )

        except FinnhubCandleError as exc:
            logger.warning("REST poll M15 failed for %s: %s", symbol, exc)
        except Exception as exc:
            logger.error("REST poll M15 unexpected error for %s: %s", symbol, exc)

        if self._refresh_h1:
            try:
                h1_candles = await self._fetcher.fetch(symbol, "H1", self._h1_bars)
                # ── FIX: normalize H1 candles ──
                h1_candles = self._normalize_candles(h1_candles, symbol, "H1")

                for candle in h1_candles:
                    self._context_bus.update_candle(candle)

                if h1_candles:
                    await self._push_candles_to_redis(h1_candles)
                    # Also aggregate H4
                    h4_candles = self._fetcher.aggregate_h4(h1_candles)
                    # ── FIX: normalize H4 candles ──
                    h4_candles = self._normalize_candles(h4_candles, symbol, "H4")
                    for candle in h4_candles:
                        self._context_bus.update_candle(candle)
                    await self._push_candles_to_redis(h4_candles)

            except FinnhubCandleError as exc:
                logger.warning("REST poll H1 failed for %s: %s", symbol, exc)
            except Exception as exc:
                logger.error("REST poll H1 unexpected error for %s: %s", symbol, exc)

    async def stop(self) -> None:
        """Signal the fallback scheduler to stop."""
        self._running = False
        logger.info(
            "RestPollFallback stopping — redis writes=%d, skips=%d",
            self._redis_writes,
            self._redis_skips,
        )

    async def _push_candles_to_redis(self, candles: list[dict[str, Any]]) -> None:
        """RPUSH candle dicts to Redis history lists (best-effort).

        Candles are grouped by key so each unique key receives a single
        RPUSH with all its values, one LTRIM, and one EXPIRE, reducing
        round trips from (rpush + ltrim + expire + publish) × N to
        (rpush + ltrim + expire) × K + publish × N  (K = unique keys ≤ N).
        """
        if not candles:
            return

        if not self._redis:
            self._redis_skips += len(candles)
            # Log loudly on first skip, then throttle
            if self._redis_skips <= len(candles):
                logger.error(
                    "[RestPoll] REDIS CLIENT IS NONE — "
                    "cannot write %d candles to Redis! "
                    "Total skipped: %d. "
                    "Fix: pass redis_client to RestPollFallback.__init__()",
                    len(candles),
                    self._redis_skips,
                )
            elif self._redis_skips % 100 == 0:
                logger.error(
                    "[RestPoll] Still no redis_client — %d candles skipped so far",
                    self._redis_skips,
                )
            return

        written_in_batch = 0

        # ── Group valid candles by Redis key to batch writes ─────────────────
        # Reduces round trips: 4 × N → 3 × K + N  (K = unique keys, K ≤ N).
        key_batches: dict[str, list[tuple[str, str, dict[str, Any]]]] = defaultdict(list)
        for candle in candles:
            symbol = candle.get("symbol")
            timeframe = candle.get("timeframe")
            if not symbol or not timeframe:
                # ── FIX: log skip instead of silent continue ──
                logger.warning(
                    "[RestPoll] Candle skipped — missing symbol=%s timeframe=%s keys=%s",
                    symbol,
                    timeframe,
                    list(candle.keys())[:8],
                )
                continue
            key = candle_history(symbol, timeframe)
            candle_json = orjson.dumps(candle).decode("utf-8")
            pub_channel = channel_candle(symbol, timeframe)
            key_batches[key].append((candle_json, pub_channel, candle))

        for key, items in key_batches.items():
            try:
                # Push all candles for this key in one RPUSH call, then trim/expire once
                await self._redis.rpush(key, *[item[0] for item in items])
                await self._redis.ltrim(key, -self._redis_maxlen, -1)
                await self._redis.expire(key, self._HISTORY_TTL_SEC)
                for candle_json, pub_channel, candle in items:
                    enqueue_candle_dict(candle)
                    # Notify engine-side RedisConsumer via Pub/Sub
                    await self._redis.publish(pub_channel, candle_json)
                self._redis_writes += len(items)
                written_in_batch += len(items)
            except Exception as exc:
                logger.warning("[RestPoll] RPUSH failed %s: %s", key, exc)

        if written_in_batch > 0:
            logger.info(
                "[RestPoll] Wrote %d/%d candles to Redis (%s/%s) — total writes: %d",
                written_in_batch,
                len(candles),
                candles[0].get("symbol", "?"),
                candles[0].get("timeframe", "?"),
                self._redis_writes,
            )
        elif candles:
            logger.warning(
                "[RestPoll] 0/%d candles written — all skipped! First candle keys: %s",
                len(candles),
                list(candles[0].keys())[:10],
            )
