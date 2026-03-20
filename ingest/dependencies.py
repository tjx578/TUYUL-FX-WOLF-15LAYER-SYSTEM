"""Dependency injection utilities for Finnhub WS client."""

from __future__ import annotations

import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from redis.asyncio import Redis

from analysis.latency_tracker import LatencyTracker
from analysis.signal_conditioner import SignalConditioner
from analysis.tick_filter import (
    DedupCache,
    SpikeFilter,
    TickFilterConfig,
)
from config_loader import CONFIG
from context.live_context_bus import LiveContextBus
from ingest.finnhub_ws import FinnhubSymbolMapper, FinnhubWebSocket
from ingest.spread_estimator import estimate_spread
from ingest.tick_dlq import get_dlq

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

# ── Tick-filter config (loaded from config/finnhub.yaml) ──────────
_TICK_CFG: dict[str, Any] = CONFIG.get("finnhub", {}).get("tick_filter", {})
_SC_CFG: dict[str, Any] = CONFIG.get("finnhub", {}).get("signal_conditioning", {})

# Per-symbol spike rejection thresholds (percentage) — config-driven
SPIKE_THRESHOLDS: dict[str, float] = {str(k): float(v) for k, v in _TICK_CFG.get("spike_thresholds", {}).items()} or {
    # Inline fallback only if config section is absent entirely
    "XAUUSD": 2.0,
    "GBPJPY": 1.0,
    "EURUSD": 0.5,
    "GBPUSD": 0.5,
    "USDJPY": 0.5,
    "AUDUSD": 0.5,
}
_DEFAULT_SPIKE_THRESHOLD: float = float(_TICK_CFG.get("default_spike_pct", 0.5))
_STALENESS_THRESHOLD_SECONDS: float = float(_TICK_CFG.get("staleness_sec", 60.0))
_DEDUP_WINDOW_SECONDS: float = float(_TICK_CFG.get("dedup_window_sec", 0.05))

# Legacy constant for backwards compatibility (tests)
MAX_DEVIATION_PCT: float = _DEFAULT_SPIKE_THRESHOLD

# ── Unified tick filter instances (single source: analysis.tick_filter) ──
_ingest_filter_config = TickFilterConfig(
    spike_threshold_pct=_DEFAULT_SPIKE_THRESHOLD,
    staleness_seconds=_STALENESS_THRESHOLD_SECONDS,
    dedup_ttl_seconds=_DEDUP_WINDOW_SECONDS,
    dedup_max_size=5_000,
    dedup_evict_batch=500,
    per_symbol_spike_pct=dict(SPIKE_THRESHOLDS),
)
_spike_filter = SpikeFilter(_ingest_filter_config)
_unified_dedup = DedupCache(_ingest_filter_config)

# ── Real-time signal conditioning state (tick-path preprocessor) ──
_signal_conditioner = SignalConditioner.from_config(_SC_CFG)
_SC_TICK_WINDOW: int = max(20, int(_SC_CFG.get("realtime_window_ticks", 128)))
_SC_MIN_PRICES: int = max(5, int(_SC_CFG.get("realtime_min_prices", 20)))
_symbol_tick_prices: dict[str, deque[float]] = {}


# ── Legacy proxy dicts — kept for backward-compatible test access ─
# Tests import _last_prices / _last_timestamps and mutate them directly.
# These proxy dicts synchronise writes with the underlying SpikeFilter store.


class _LastPriceProxy(dict[str, float]):
    """Dict proxy that mirrors writes into the SpikeFilter's LastPriceStore."""

    def __setitem__(self, symbol: str, price: float) -> None:
        super().__setitem__(symbol, price)
        _spike_filter.price_store.update(symbol, price, time.monotonic())

    def clear(self) -> None:
        super().clear()
        _spike_filter.clear()


class _LastTimestampProxy(dict[str, float]):
    """Dict proxy that mirrors writes into the SpikeFilter's LastPriceStore."""

    def __setitem__(self, symbol: str, ts: float) -> None:
        super().__setitem__(symbol, ts)
        # Sync timestamp into the underlying store (price unchanged)
        entry = _spike_filter.price_store.get(symbol)
        if entry is not None:
            _spike_filter.price_store.update(symbol, entry.price, ts)

    def clear(self) -> None:
        super().clear()
        _spike_filter.clear()


_last_prices: dict[str, float] = _LastPriceProxy()
_last_timestamps: dict[str, float] = _LastTimestampProxy()
_last_exchange_ts_ms: dict[str, float] = {}

# ── Tick deduplication state (legacy alias kept for test imports) ──


class _DedupCacheProxy(dict):
    """Legacy proxy: clear() also resets the unified DedupCache."""

    def clear(self) -> None:
        super().clear()
        _unified_dedup.clear()


_dedup_cache: dict[tuple[str, float, float], float] = _DedupCacheProxy()
_DEDUP_CACHE_MAX = 5_000  # kept for backward compat


def _is_duplicate_tick(symbol: str, price: float, exchange_ts: float) -> bool:
    """Return True if an identical tick was already accepted within the dedup window.

    Delegates to unified DedupCache from analysis.tick_filter.
    """
    key = f"{symbol}:{price}:{exchange_ts}"
    return _unified_dedup.is_duplicate(key, time.monotonic())


def _is_out_of_order_tick(symbol: str, exchange_ts_ms: float) -> bool:
    """Return True when exchange timestamp goes backwards for a symbol."""
    previous = _last_exchange_ts_ms.get(symbol)
    if previous is None:
        _last_exchange_ts_ms[symbol] = exchange_ts_ms
        return False

    if exchange_ts_ms < previous:
        return True

    _last_exchange_ts_ms[symbol] = exchange_ts_ms
    return False


def _update_realtime_conditioning(
    context_bus: LiveContextBus,
    symbol: str,
    price: float,
    ts: float,
) -> None:
    """Update per-symbol conditioning from live ticks and publish to context bus."""
    window = _symbol_tick_prices.setdefault(symbol, deque(maxlen=_SC_TICK_WINDOW))
    window.append(price)

    if len(window) < _SC_MIN_PRICES:
        return

    conditioned = _signal_conditioner.condition_prices(list(window))
    diagnostics: dict[str, str | float | int] = {
        **conditioned.diagnostics(),
        "source": "tick_realtime",
        "timestamp": ts,
    }
    context_bus.update_conditioned_returns(
        symbol=symbol,
        returns=conditioned.conditioned_returns,
        diagnostics=diagnostics,
    )


# ── Tick rate metrics ─────────────────────────────────────────────
@dataclass
class _TickRateCounter:
    """Sliding-window tick counter per symbol."""

    _window_sec: float = 10.0
    _timestamps: dict[str, deque[float]] = field(default_factory=lambda: dict[str, deque[float]]())
    _rejected: dict[str, int] = field(default_factory=lambda: dict[str, int]())
    _duplicates: dict[str, int] = field(default_factory=lambda: dict[str, int]())
    _out_of_order: dict[str, int] = field(default_factory=lambda: dict[str, int]())

    def record(self, symbol: str) -> None:
        """Record an accepted tick."""
        dq = self._timestamps.setdefault(symbol, deque())
        dq.append(time.monotonic())

    def record_rejected(self, symbol: str) -> None:
        self._rejected[symbol] = self._rejected.get(symbol, 0) + 1

    def record_duplicate(self, symbol: str) -> None:
        self._duplicates[symbol] = self._duplicates.get(symbol, 0) + 1

    def record_out_of_order(self, symbol: str) -> None:
        self._out_of_order[symbol] = self._out_of_order.get(symbol, 0) + 1

    def ticks_per_second(self, symbol: str) -> float:
        """Return ticks/sec over the sliding window for *symbol*."""
        dq = self._timestamps.get(symbol)
        if not dq:
            return 0.0
        now = time.monotonic()
        cutoff = now - self._window_sec
        while dq and dq[0] < cutoff:
            dq.popleft()
        return len(dq) / self._window_sec

    def snapshot(self) -> dict[str, dict[str, float | int]]:
        """Return per-symbol rate + rejection stats."""
        now = time.monotonic()
        result: dict[str, dict[str, float | int]] = {}
        for symbol, dq in self._timestamps.items():
            cutoff = now - self._window_sec
            while dq and dq[0] < cutoff:
                dq.popleft()
            result[symbol] = {
                "ticks_per_sec": round(len(dq) / self._window_sec, 2),
                "rejected": self._rejected.get(symbol, 0),
                "duplicates": self._duplicates.get(symbol, 0),
                "out_of_order": self._out_of_order.get(symbol, 0),
            }
        return result


tick_metrics = _TickRateCounter()

from infrastructure.redis_url import get_redis_url  # noqa: E402

_DEFAULT_REDIS_URL = get_redis_url()
_DEFAULT_SYMBOLS = [
    "OANDA:EUR_USD",
    "OANDA:GBP_JPY",
    "OANDA:USD_JPY",
    "OANDA:GBP_USD",
    "OANDA:AUD_USD",
    "OANDA:XAU_USD",
]
_SYMBOL_REVERSE_MAP: dict[str, str] = {
    symbol: symbol.replace("OANDA:", "").replace("_", "") for symbol in _DEFAULT_SYMBOLS
}


def _enabled_symbols() -> list[str]:
    """Return enabled internal symbols from config."""
    pairs = CONFIG.get("pairs", {}).get("pairs", [])
    enabled = [str(pair.get("symbol", "")) for pair in pairs if pair.get("enabled", True)]
    return [symbol for symbol in enabled if symbol]


def _get_spike_threshold(symbol: str) -> float:
    """Return spike rejection threshold for a given symbol."""
    return SPIKE_THRESHOLDS.get(symbol, _DEFAULT_SPIKE_THRESHOLD)


def _is_valid_tick(symbol: str, new_price: float) -> bool:
    """
    Validate tick price against spike threshold with staleness detection.

    Delegates to the unified SpikeFilter from analysis.tick_filter while
    keeping the legacy proxy dicts in sync for backward compatibility.

    Args:
        symbol: Trading pair symbol
        new_price: New tick price

    Returns:
        True if tick is valid, False if spike detected
    """
    result = _spike_filter.check(symbol, new_price, time.monotonic())

    if result.accepted:
        # Sync legacy proxy dicts
        dict.__setitem__(_last_prices, symbol, new_price)
        dict.__setitem__(_last_timestamps, symbol, time.monotonic())
        if result.reason in ("first_tick", "stale_override_accepted"):
            reason = "first_tick" if result.reason == "first_tick" else "stale_baseline"
            logger.info(
                "Tick baseline reset",
                extra={"symbol": symbol, "price": new_price, "reason": reason},
            )
        return True

    # Spike rejected
    entry = _spike_filter.price_store.get(symbol)
    last_price = entry.price if entry else None
    logger.warning(
        "Tick spike rejected",
        extra={
            "symbol": symbol,
            "new_price": new_price,
            "last_price": last_price,
            "deviation_pct": round(result.pct_change, 4) if result.pct_change else None,
            "threshold_pct": _get_spike_threshold(symbol),
        },
    )
    return False


def _build_tick_handler(
    *,
    mapper: FinnhubSymbolMapper,
    allowed_symbols: set[str],
    candle_callback: Callable[[str, float, datetime, float], None] | None = None,
    tick_redis_callback: Callable[[dict[str, Any]], None] | None = None,
) -> Callable[[dict[str, Any]], Awaitable[None]]:
    """Create WS message handler that normalizes and writes ticks to context."""
    context_bus = LiveContextBus()
    _latency_tracker = LatencyTracker()

    async def _handle_tick(data: dict[str, Any]) -> None:
        try:
            if data.get("type") != "trade":
                return

            trades_raw: Any = data.get("data", [])
            if not isinstance(trades_raw, list):
                logger.warning("Invalid Finnhub trade payload format")
                return
            trades: list[dict[str, Any]] = cast(list[dict[str, Any]], trades_raw)
            for trade in trades:
                external_symbol = trade.get("s")
                price: Any = trade.get("p")
                timestamp = trade.get("t")

                if not external_symbol or price is None or timestamp is None:
                    logger.debug("Skipping incomplete trade payload")
                    continue

                internal_symbol = mapper.to_internal(str(external_symbol))
                if internal_symbol not in allowed_symbols:
                    logger.warning(
                        "Skipping unmapped symbol from Finnhub stream",
                        extra={"external_symbol": external_symbol},
                    )
                    continue

                tick_price = float(price)
                tick_ts_raw = float(timestamp)

                # ── Dedup: reject identical (symbol+price+ts) within window ──
                if _is_duplicate_tick(internal_symbol, tick_price, tick_ts_raw):
                    tick_metrics.record_duplicate(internal_symbol)
                    dlq = get_dlq()
                    if dlq is not None:
                        await dlq.push(
                            symbol=internal_symbol,
                            price=tick_price,
                            exchange_ts=tick_ts_raw,
                            reason="duplicate",
                        )
                    continue

                # ── Ordering guard: reject exchange timestamps that go backwards ──
                if _is_out_of_order_tick(internal_symbol, tick_ts_raw):
                    tick_metrics.record_out_of_order(internal_symbol)
                    dlq = get_dlq()
                    if dlq is not None:
                        await dlq.push(
                            symbol=internal_symbol,
                            price=tick_price,
                            exchange_ts=tick_ts_raw,
                            reason="out_of_order",
                        )
                    continue

                # ── Spike filter ──
                if not _is_valid_tick(internal_symbol, tick_price):
                    tick_metrics.record_rejected(internal_symbol)
                    dlq = get_dlq()
                    if dlq is not None:
                        await dlq.push(
                            symbol=internal_symbol,
                            price=tick_price,
                            exchange_ts=tick_ts_raw,
                            reason="spike_rejected",
                            details={
                                "threshold_pct": _get_spike_threshold(internal_symbol),
                            },
                        )
                    continue

                # Update last known price
                _last_prices[internal_symbol] = tick_price

                tick_ts = tick_ts_raw / 1000.0
                bid, ask = estimate_spread(
                    symbol=internal_symbol,
                    price=tick_price,
                    timestamp=tick_ts,
                )

                normalized_tick: dict[str, Any] = {
                    "symbol": internal_symbol,
                    "bid": bid,
                    "ask": ask,
                    "last": tick_price,
                    "spread": round(ask - bid, 6),
                    "timestamp": tick_ts,
                    "source": "finnhub_ws",
                }
                context_bus.update_tick(normalized_tick)
                _latency_tracker.record_tick(internal_symbol)

                # Persist tick to Redis for cross-container staleness tracking
                if tick_redis_callback is not None:
                    tick_redis_callback(normalized_tick)

                _update_realtime_conditioning(
                    context_bus=context_bus,
                    symbol=internal_symbol,
                    price=tick_price,
                    ts=tick_ts,
                )
                tick_metrics.record(internal_symbol)

                # Wire to CandleBuilder if callback provided
                if candle_callback and internal_symbol in allowed_symbols:
                    tick_dt = datetime.fromtimestamp(tick_ts, tz=UTC)
                    candle_callback(internal_symbol, tick_price, tick_dt, 0.0)
        except (TypeError, ValueError) as exc:
            logger.error(
                "Tick processing error",
                extra={"error": str(exc), "raw_data": str(data)[:200]},
            )

    return _handle_tick


async def handle_tick(data: dict[str, Any]) -> None:
    """Backwards-compatible default tick handler used by tests and local callers."""
    mapper = FinnhubSymbolMapper(prefix="OANDA")
    for internal_symbol in _SYMBOL_REVERSE_MAP.values():
        mapper.register(internal_symbol)
    handler = _build_tick_handler(mapper=mapper, allowed_symbols=set(_SYMBOL_REVERSE_MAP.values()))
    await handler(data)


# Module-level alias for test access (the real implementation is a closure inside
# _build_tick_handler — this default handler is equivalent for unit testing)
_handle_tick = handle_tick


async def create_finnhub_ws(
    redis: Redis,
    symbols: list[str] | None = None,
    candle_callback: Callable[[str, float, datetime, float], None] | None = None,
) -> FinnhubWebSocket:
    """Factory for FinnhubWebSocket with defaults and tick normalization."""
    # Initialise DLQ singleton (idempotent — safe to call multiple times)
    from ingest.tick_dlq import init_dlq

    init_dlq(redis)

    mapper = FinnhubSymbolMapper(prefix="OANDA")
    internal_symbols = symbols or _enabled_symbols()
    allowed_symbols = set(internal_symbols)
    external_symbols = [mapper.register(symbol) for symbol in internal_symbols]

    # Wire tick → Redis persistence so wolf15:latest_tick:{symbol} stays current.
    # Uses RedisContextBridge.write_tick() which does XADD + HSET + PUBLISH.
    from context.redis_context_bridge import RedisContextBridge  # noqa: PLC0415

    bridge: RedisContextBridge | None = None
    try:
        bridge = RedisContextBridge()
    except Exception:
        logger.warning("Failed to create RedisContextBridge for tick persistence — skipping")

    def _tick_to_redis(tick: dict[str, Any]) -> None:
        if bridge is not None:
            try:  # noqa: SIM105
                bridge.write_tick(tick)
            except Exception:
                pass  # Best-effort; don't break tick processing

    return FinnhubWebSocket(
        redis=redis,
        on_message=_build_tick_handler(
            mapper=mapper,
            allowed_symbols=allowed_symbols,
            candle_callback=candle_callback,
            tick_redis_callback=_tick_to_redis if bridge else None,
        ),
        symbols=external_symbols,
    )


async def create_default_finnhub_ws() -> FinnhubWebSocket:
    """Factory that builds Redis client and configured Finnhub WS instance."""
    redis_url = os.getenv("REDIS_URL", _DEFAULT_REDIS_URL)
    redis: Redis = Redis.from_url(redis_url, decode_responses=True)
    return await create_finnhub_ws(redis=redis)
