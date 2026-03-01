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

from config_loader import CONFIG
from context.live_context_bus import LiveContextBus
from ingest.finnhub_ws import FinnhubSymbolMapper, FinnhubWebSocket
from ingest.spread_estimator import estimate_spread

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

# ── Tick-filter config (loaded from config/finnhub.yaml) ──────────
_TICK_CFG: dict[str, Any] = CONFIG.get("finnhub", {}).get("tick_filter", {})

# Per-symbol spike rejection thresholds (percentage) — config-driven
SPIKE_THRESHOLDS: dict[str, float] = {
    str(k): float(v)
    for k, v in _TICK_CFG.get("spike_thresholds", {}).items()
} or {
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

_last_prices: dict[str, float] = {}
_last_timestamps: dict[str, float] = {}

# ── Tick deduplication state ──────────────────────────────────────
# Key: (symbol, price, exchange_ts)  →  monotonic time of last accept
_dedup_cache: dict[tuple[str, float, float], float] = {}
_DEDUP_CACHE_MAX = 5_000  # evict oldest when exceeded


def _is_duplicate_tick(symbol: str, price: float, exchange_ts: float) -> bool:
    """Return True if an identical tick was already accepted within the dedup window."""
    key = (symbol, price, exchange_ts)
    now = time.monotonic()
    prev = _dedup_cache.get(key)
    if prev is not None and (now - prev) < _DEDUP_WINDOW_SECONDS:
        return True
    # Evict stale entries lazily when cache grows too large
    if len(_dedup_cache) >= _DEDUP_CACHE_MAX:
        cutoff = now - _DEDUP_WINDOW_SECONDS * 2
        stale_keys = [k for k, v in _dedup_cache.items() if v < cutoff]
        for k in stale_keys:
            del _dedup_cache[k]
    _dedup_cache[key] = now
    return False


# ── Tick rate metrics ─────────────────────────────────────────────
@dataclass
class _TickRateCounter:
    """Sliding-window tick counter per symbol."""

    _window_sec: float = 10.0
    _timestamps: dict[str, deque[float]] = field(default_factory=lambda: dict[str, deque[float]]())
    _rejected: dict[str, int] = field(default_factory=lambda: dict[str, int]())
    _duplicates: dict[str, int] = field(default_factory=lambda: dict[str, int]())

    def record(self, symbol: str) -> None:
        """Record an accepted tick."""
        dq = self._timestamps.setdefault(symbol, deque())
        dq.append(time.monotonic())

    def record_rejected(self, symbol: str) -> None:
        self._rejected[symbol] = self._rejected.get(symbol, 0) + 1

    def record_duplicate(self, symbol: str) -> None:
        self._duplicates[symbol] = self._duplicates.get(symbol, 0) + 1

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

    Auto-resets baseline price if:
    - This is the first tick for the symbol, OR
    - No tick received for this symbol in the last 60 seconds (prevents false
      spikes after WS reconnects or session gaps)

    Args:
        symbol: Trading pair symbol
        new_price: New tick price

    Returns:
        True if tick is valid, False if spike detected
    """
    now = time.monotonic()
    last_price = _last_prices.get(symbol)
    last_ts = _last_timestamps.get(symbol)

    # First tick or stale price -> always accept as new baseline
    if last_price is None or (
        last_ts is not None and (now - last_ts) > _STALENESS_THRESHOLD_SECONDS
    ):
        reason = "first_tick" if last_price is None else "stale_baseline"
        logger.info(
            "Tick baseline reset",
            extra={
                "symbol": symbol,
                "price": new_price,
                "reason": reason,
            },
        )
        _last_prices[symbol] = new_price
        _last_timestamps[symbol] = now
        return True

    threshold = _get_spike_threshold(symbol)
    deviation = abs(new_price - last_price) / last_price * 100

    if deviation > threshold:
        logger.warning(
            "Tick spike rejected",
            extra={
                "symbol": symbol,
                "new_price": new_price,
                "last_price": last_price,
                "deviation_pct": round(deviation, 4),
                "threshold_pct": threshold,
            },
        )
        return False

    # Valid tick - update timestamp
    _last_timestamps[symbol] = now
    return True


def _build_tick_handler(
    *,
    mapper: FinnhubSymbolMapper,
    allowed_symbols: set[str],
    candle_callback: Callable[[str, float, datetime, float], None] | None = None,
) -> Callable[[dict[str, Any]], Awaitable[None]]:
    """Create WS message handler that normalizes and writes ticks to context."""
    context_bus = LiveContextBus()

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
                    continue

                # ── Spike filter ──
                if not _is_valid_tick(internal_symbol, tick_price):
                    tick_metrics.record_rejected(internal_symbol)
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
                context_bus.update_tick(normalized_tick)  # type: ignore[arg-type]
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


async def create_finnhub_ws(
    redis: Redis,
    symbols: list[str] | None = None,
    candle_callback: Callable[[str, float, datetime, float], None] | None = None,
) -> FinnhubWebSocket:
    """Factory for FinnhubWebSocket with defaults and tick normalization."""
    mapper = FinnhubSymbolMapper(prefix="OANDA")
    internal_symbols = symbols or _enabled_symbols()
    allowed_symbols = set(internal_symbols)
    external_symbols = [mapper.register(symbol) for symbol in internal_symbols]

    return FinnhubWebSocket(
        redis=redis,
        on_message=_build_tick_handler(
            mapper=mapper,
            allowed_symbols=allowed_symbols,
            candle_callback=candle_callback,
        ), # pyright: ignore[reportArgumentType]
        symbols=external_symbols,
    )


async def create_default_finnhub_ws() -> FinnhubWebSocket:
    """Factory that builds Redis client and configured Finnhub WS instance."""
    redis_url = os.getenv("REDIS_URL", _DEFAULT_REDIS_URL)
    redis: Redis = Redis.from_url(redis_url, decode_responses=True)  # type: ignore[misc]
    return await create_finnhub_ws(redis=redis)
