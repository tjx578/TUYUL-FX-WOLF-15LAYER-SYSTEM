"""HybridCandleAggregator — display-only candle data aggregator for the dashboard.

Zone: api/ — read-only display. ZERO computation of market direction or trade decisions.

Architecture (Dual-Zone SSOT v5)
---------------------------------
  Zone A (micro-wave):
    Closed bars → wolf15:candle_history:{SYM}:{M1/M5/M15}  (Redis LIST, from ingest)
    Forming M15  → wolf15:candle:forming:{SYM}:M15          (Redis HASH, from ingest)

  Zone B (macro-strategy):
    Closed bars → wolf15:candle_history:{SYM}:{H1/H4/D1/W1} (Redis LIST, from ingest)
    Forming H1  → wolf15:candle:forming:{SYM}:H1             (Redis HASH, from ingest)

ALL data is fetched from Redis. This class NEVER:
  • Runs TRQ computations
  • Runs Monte Carlo simulations
  • Computes market direction
  • Modifies pipeline state

Feature flag
------------
USE_REDIS_FORMING=false → forming bars are built locally from tick data
                          (fallback when ingest service is not yet running)

Critical constraint
-------------------
ALL Redis calls MUST be async — ``infrastructure.redis_client.get_client()`` returns
an async client.  Using the sync ``storage.redis_client`` singleton would block the
asyncio event loop by ~300ms/sec for 30 pairs × 2 TF × ~2ms each.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import time
from typing import Any, TypedDict

from loguru import logger

# ── Feature flag ─────────────────────────────────────────────────────────────
_USE_REDIS_FORMING = os.getenv("USE_REDIS_FORMING", "true").strip().lower() not in ("false", "0", "no")

# ── Staleness threshold: flag forming bars older than this ───────────────────
FORMING_STALE_SEC = 15.0  # raised from 5s — 5s was too aggressive

# ── TRQ poller interval ───────────────────────────────────────────────────────
_TRQ_POLL_INTERVAL_SEC = 2.0


# ══════════════════════════════════════════════════════════════════════════════
#  Public types
# ══════════════════════════════════════════════════════════════════════════════


class CandleBar(TypedDict):
    """Display-only candle bar for the dashboard."""

    open: float
    high: float
    low: float
    close: float
    volume: float
    ts_open: float
    ts_close: float


class FormingBarData(TypedDict, total=False):
    """Forming (in-progress) candle bar with optional staleness flag."""

    open: float
    high: float
    low: float
    close: float
    volume: float
    tick_count: int
    ts_open: float
    ts_close: float
    stale: bool


# ══════════════════════════════════════════════════════════════════════════════
#  Pydantic schema for Redis forming bar payload validation
# ══════════════════════════════════════════════════════════════════════════════


def _parse_forming_bar(raw: dict[str, Any]) -> FormingBarData | None:
    """Parse and validate a raw Redis HGETALL dict into FormingBarData.

    Returns None if required fields are missing or prices are invalid.
    """
    try:
        result: FormingBarData = {
            "open": float(raw["open"]),
            "high": float(raw["high"]),
            "low": float(raw["low"]),
            "close": float(raw["close"]),
            "volume": float(raw.get("volume", 0)),
            "tick_count": int(raw.get("tick_count", 0)),
            "ts_open": float(raw["ts_open"]),
            "ts_close": float(raw["ts_close"]),
        }
        # Cross-field validation
        if result["high"] < result["low"]:
            return None
        for price_field in ("open", "high", "low", "close"):
            if result[price_field] <= 0:
                return None
        # Staleness check
        ts_written = float(raw.get("ts_written", 0))
        if ts_written > 0 and (time.time() - ts_written) > FORMING_STALE_SEC:
            result["stale"] = True
        return result
    except (KeyError, TypeError, ValueError):
        return None


# ══════════════════════════════════════════════════════════════════════════════
#  HybridCandleAggregator
# ══════════════════════════════════════════════════════════════════════════════


class HybridCandleAggregator:
    """Display-only candle aggregator for the dashboard WebSocket endpoint.

    Reads all data from Redis (async) — closed bars from history lists,
    forming bars from HASH keys written by FormingBarPublisher (ingest).

    When USE_REDIS_FORMING=false, falls back to local CandleBuilder instances
    fed by the tick stream (old behavior).

    Usage::

        agg = HybridCandleAggregator()
        await agg.start(symbols)
        # In WebSocket handler:
        snapshot = agg.get_combined_snapshot()
        forming  = agg.get_forming_bars()
        await agg.stop()
    """

    def __init__(self) -> None:
        self._symbols: list[str] = []
        self._async_redis: Any = None

        # Latest TRQ snapshot per symbol (display only)
        self._trq_cache: dict[str, dict[str, Any]] = {}

        # Fallback local builders when USE_REDIS_FORMING=false
        self._local_builders: dict[str, Any] = {}

        # Metrics
        self._redis_reads: int = 0
        self._redis_errors: int = 0
        self._start_ts: float = 0.0

        self._trq_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self, symbols: list[str]) -> None:
        """Initialize the aggregator with the given symbols.

        Obtains an async Redis client.  Falls back to thread-wrapped sync
        client if async client is unavailable.
        """
        self._symbols = list(symbols)
        self._start_ts = time.time()

        try:
            from infrastructure.redis_client import get_client

            self._async_redis = await get_client()
            logger.info("[HybridCandleAgg] Async Redis client obtained")
        except Exception as exc:
            logger.warning(
                "[HybridCandleAgg] Async Redis unavailable (%s) — will use sync fallback",
                exc,
            )
            self._async_redis = None

        if not _USE_REDIS_FORMING:
            self._init_local_builders()

        # Start TRQ poller background task
        self._trq_task = asyncio.create_task(self._trq_poller(), name="hybrid_candle_agg_trq")

        logger.info(
            "[HybridCandleAgg] Started — %d symbols, USE_REDIS_FORMING=%s",
            len(symbols),
            _USE_REDIS_FORMING,
        )

    async def stop(self) -> None:
        """Stop background tasks."""
        if self._trq_task is not None:
            self._trq_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._trq_task
            self._trq_task = None
        logger.info("[HybridCandleAgg] Stopped")

    # ------------------------------------------------------------------
    # Tick ingestion (for fallback local builders)
    # ------------------------------------------------------------------

    def ingest_tick(self, symbol: str, bid: float, ask: float, ts: float) -> None:
        """Feed a tick into local fallback builders (only used when USE_REDIS_FORMING=false)."""
        if not self._local_builders:
            return
        if symbol not in self._local_builders:
            return
        mid = round((bid + ask) / 2, 6)
        from datetime import UTC, datetime

        dt = datetime.fromtimestamp(ts, tz=UTC)
        for builder in self._local_builders[symbol].values():
            builder.on_tick(mid, dt, volume=1.0)

    # ------------------------------------------------------------------
    # Snapshot methods (called by WS endpoint)
    # ------------------------------------------------------------------

    def get_combined_snapshot(self, symbol_filter: str | None = None) -> dict[str, dict[str, CandleBar]]:
        """Return the latest closed bars snapshot for all (or one) symbols.

        Loads the most-recent closed bar from Redis for each symbol/TF combination.
        This is a synchronous wrapper; actual Redis reads happen via get_forming_bars.
        """
        # For the snapshot, return any locally cached closed bars.
        # The dashboard primarily uses forming bars for live display.
        symbols = [symbol_filter] if symbol_filter else self._symbols
        result: dict[str, dict[str, CandleBar]] = {sym: {} for sym in symbols}
        return result

    def get_forming_bars(self, symbol_filter: str | None = None) -> dict[str, dict[str, FormingBarData]]:
        """Return forming bars from Redis (or local builders if fallback mode).

        Returns empty dicts if Redis is not yet available; the WS endpoint
        handles empty gracefully (no crash, no stale display).

        Note: This is a synchronous method that returns cached data.
        The actual async Redis fetch is scheduled via ``_fetch_forming_bars``.
        """
        if not _USE_REDIS_FORMING:
            return self._get_local_forming_bars(symbol_filter)
        return self._get_cached_forming_bars(symbol_filter)

    def get_trq_snapshot(self, symbol_filter: str | None = None) -> dict[str, dict[str, Any]]:
        """Return cached TRQ pre-move snapshots for display."""
        if symbol_filter:
            return {symbol_filter: self._trq_cache.get(symbol_filter, {})}
        return dict(self._trq_cache)

    # ------------------------------------------------------------------
    # Async Redis fetchers (for active polling by WS endpoint)
    # ------------------------------------------------------------------

    async def fetch_forming_bars_async(self, symbol_filter: str | None = None) -> dict[str, dict[str, FormingBarData]]:
        """Fetch forming bars from Redis asynchronously.

        This is the primary method for the WS endpoint to call.
        Falls back to local builders when Redis is unavailable.
        """
        if not _USE_REDIS_FORMING:
            return self._get_local_forming_bars(symbol_filter)

        redis = await self._get_redis()
        if redis is None:
            return self._get_local_forming_bars(symbol_filter)

        symbols = [symbol_filter] if symbol_filter else self._symbols
        timeframes = ["M15", "H1"]
        result: dict[str, dict[str, FormingBarData]] = {}

        for sym in symbols:
            sym_bars: dict[str, FormingBarData] = {}
            for tf in timeframes:
                from core.redis_keys import candle_forming

                key = candle_forming(sym, tf)
                try:
                    raw: dict[Any, Any] = await redis.hgetall(key)
                    self._redis_reads += 1
                    if raw:
                        # Redis returns bytes or str depending on decode_responses
                        decoded: dict[str, Any] = {
                            (k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
                            for k, v in raw.items()
                        }
                        parsed = _parse_forming_bar(decoded)
                        if parsed is not None:
                            sym_bars[tf] = parsed
                except Exception as exc:
                    self._redis_errors += 1
                    logger.debug(
                        "[HybridCandleAgg] Redis forming bar read failed %s %s: %s",
                        sym,
                        tf,
                        exc,
                    )
            result[sym] = sym_bars

        return result

    # ------------------------------------------------------------------
    # Feed status metadata (for dashboard staleness awareness)
    # ------------------------------------------------------------------

    async def fetch_feed_meta_async(self, symbol_filter: str | None = None) -> dict[str, Any]:
        """Build per-symbol feed status + ingest health for the candle WS event.

        Returns a dict with:
            ingest_status: "HEALTHY" | "DEGRADED" | "NO_PRODUCER"
            provider_connected: bool
            symbols: { SYM: { feed_status, age_seconds } }

        This lets the dashboard distinguish between:
            - "WS disconnected, data is stale" → show warning banner
            - "Market closed, no ticks expected" → show idle state
            - "All good, data is live" → normal display
        """
        redis = await self._get_redis()
        meta: dict[str, Any] = {
            "ingest_status": "UNKNOWN",
            "provider_connected": False,
            "symbols": {},
        }
        if redis is None:
            return meta

        # Read ingest health (process + provider heartbeats)
        try:
            from state.heartbeat_classifier import read_ingest_health

            ingest_health = await read_ingest_health(redis)
            meta["ingest_status"] = ingest_health.state.value
            meta["provider_connected"] = ingest_health.provider.state.value == "ALIVE"
        except Exception as exc:
            logger.debug("[HybridCandleAgg] Ingest health read failed: {}", exc)

        # Per-symbol feed freshness from latest_tick timestamps
        symbols = [symbol_filter] if symbol_filter else self._symbols
        now = time.time()
        for sym in symbols:
            sym_meta: dict[str, Any] = {"feed_status": "NO_DATA", "age_seconds": None}
            try:
                from core.redis_keys import latest_tick as _latest_tick_key

                raw = await redis.hgetall(_latest_tick_key(sym))
                if raw:
                    decoded = {
                        (k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
                        for k, v in raw.items()
                    }
                    ts_val = decoded.get("last_seen_ts") or decoded.get("timestamp") or decoded.get("ts")
                    if ts_val is not None:
                        age = now - float(ts_val)
                        sym_meta["age_seconds"] = round(age, 1)
                        if age < 30:
                            sym_meta["feed_status"] = "LIVE"
                        elif age < 120:
                            sym_meta["feed_status"] = "DEGRADED"
                        else:
                            sym_meta["feed_status"] = "STALE"
            except Exception:
                pass
            meta["symbols"][sym] = sym_meta

        return meta

    # ------------------------------------------------------------------
    # Monitoring
    # ------------------------------------------------------------------

    def health(self) -> dict[str, Any]:
        """Return aggregator health metrics for monitoring endpoint."""
        return {
            "use_redis_forming": _USE_REDIS_FORMING,
            "symbols": len(self._symbols),
            "redis_reads": self._redis_reads,
            "redis_errors": self._redis_errors,
            "trq_symbols_cached": len(self._trq_cache),
            "uptime_sec": round(time.time() - self._start_ts, 1) if self._start_ts else 0,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_redis(self) -> Any:
        """Return async Redis client, attempting re-acquisition if None."""
        if self._async_redis is not None:
            return self._async_redis
        try:
            from infrastructure.redis_client import get_client

            self._async_redis = await get_client()
            return self._async_redis
        except Exception:
            pass
        # Final fallback: wrap sync client in thread executor (cached to avoid
        # recreating the wrapper on each call — thread-pool overhead from
        # asyncio.to_thread can be significant at 30+ symbols × 2 TF polling)
        try:
            from storage.redis_client import redis_client as _sync_redis

            class _ThreadWrappedRedis:
                """Minimal async wrapper around sync Redis for hgetall only."""

                def __init__(self, sync_client: Any) -> None:
                    self._c = sync_client

                async def hgetall(self, key: str) -> dict[str, Any]:
                    return await asyncio.to_thread(self._c.client.hgetall, key)

            self._async_redis = _ThreadWrappedRedis(_sync_redis)
            return self._async_redis
        except Exception:
            return None

    async def _trq_poller(self) -> None:
        """Background task: poll TRQ pre-move snapshots from Redis."""
        while True:
            try:
                await self._poll_trq()
            except Exception as exc:
                logger.debug("[HybridCandleAgg] TRQ poll error: {}", exc)
            await asyncio.sleep(_TRQ_POLL_INTERVAL_SEC)

    async def _poll_trq(self) -> None:
        """Fetch TRQ snapshots for all symbols from Redis."""
        redis = await self._get_redis()
        if redis is None:
            return

        # Lazy import to avoid ImportError if redis_keys not patched yet
        try:
            from core.redis_keys import trq_premove as _trq_premove
        except ImportError:
            return

        for sym in self._symbols:
            key = _trq_premove(sym)
            try:
                raw = await redis.hgetall(key)
                if raw:
                    decoded = {
                        (k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
                        for k, v in raw.items()
                    }
                    self._trq_cache[sym] = decoded
            except Exception:
                pass

    def _get_cached_forming_bars(self, symbol_filter: str | None) -> dict[str, dict[str, FormingBarData]]:
        """Return empty cached forming bars (data fetched async via fetch_forming_bars_async)."""
        symbols = [symbol_filter] if symbol_filter else self._symbols
        return {sym: {} for sym in symbols}

    def _get_local_forming_bars(self, symbol_filter: str | None) -> dict[str, dict[str, FormingBarData]]:
        """Build forming bars from local fallback CandleBuilders."""
        symbols = [symbol_filter] if symbol_filter else self._symbols
        result: dict[str, dict[str, FormingBarData]] = {}
        for sym in symbols:
            sym_bars: dict[str, FormingBarData] = {}
            builders = self._local_builders.get(sym, {})
            for tf_name, builder in builders.items():
                partial = builder.current_partial
                if partial is not None:
                    sym_bars[tf_name] = FormingBarData(
                        open=partial.open,
                        high=partial.high,
                        low=partial.low,
                        close=partial.close,
                        volume=partial.volume,
                        tick_count=partial.tick_count,
                        ts_open=partial.open_time.timestamp(),
                        ts_close=partial.close_time.timestamp(),
                    )
            result[sym] = sym_bars
        return result

    def _init_local_builders(self) -> None:
        """Initialize local CandleBuilder fallbacks (USE_REDIS_FORMING=false)."""
        try:
            from ingest.candle_builder import CandleBuilder, Timeframe

            for sym in self._symbols:
                self._local_builders[sym] = {
                    "M15": CandleBuilder(symbol=sym, timeframe=Timeframe.M15),
                    "H1": CandleBuilder(symbol=sym, timeframe=Timeframe.H1),
                }
        except Exception as exc:
            logger.warning("[HybridCandleAgg] Local builder init failed: {}", exc)
