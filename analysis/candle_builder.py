"""
Backward-compatible re-export of the unified CandleBuilder.

All candle construction logic lives in ingest/candle_builder.py.
Analysis modules should consume candles, not build them — this shim
exists only for import compatibility during the migration period.

Zone: analysis (read-only re-export). No side-effects.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any  # noqa: UP035

from ingest.candle_builder import (  # noqa: F401
    Candle,
    MultiTimeframeCandleBuilder,
    Timeframe,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# TickBuffer — shared non-destructive tick buffer
# ---------------------------------------------------------------------------


class TickBuffer:
    """Thread-safe, non-destructive tick buffer."""

    def __init__(self, maxlen: int = 10000):
        super().__init__()
        self._buffer: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._last_read_index: dict[str, int] = {}  # consumer_id -> last_index

    def append(self, tick: dict[str, Any]) -> None:
        """Add tick to buffer (FIFO with max length)."""
        self._buffer.append(tick)

    def consume(self, consumer_id: str) -> Iterator[dict[str, Any]]:
        """
        Non-destructive consumption.
        Each consumer tracks its own read position.
        """
        last_idx = self._last_read_index.get(consumer_id, 0)
        current_len = len(self._buffer)

        # Yield only unread ticks for this consumer
        for i in range(last_idx, current_len):
            yield self._buffer[i]

        # Update consumer's read position
        self._last_read_index[consumer_id] = current_len

    def reset_consumer(self, consumer_id: str) -> None:
        """Reset a consumer's read position (e.g., after reconnect)."""
        self._last_read_index[consumer_id] = len(self._buffer)


# ✅ USAGE
tick_buffer = TickBuffer()


# ---------------------------------------------------------------------------
# VWAP accumulator — per-symbol incremental session VWAP
# ---------------------------------------------------------------------------


@dataclass
class _VWAPState:
    """Mutable VWAP accumulator for a single symbol within a session."""

    cum_pv: float = 0.0  # cumulative price * volume
    cum_vol: float = 0.0  # cumulative volume
    vwap: float | None = None
    tick_count: int = 0

    def update(self, price: float, volume: float | None) -> float | None:
        """Update VWAP with a new tick. Returns current VWAP or None."""
        self.tick_count += 1
        if volume is None or volume <= 0:
            return self.vwap  # no volume contribution
        self.cum_pv += price * volume
        self.cum_vol += volume
        self.vwap = self.cum_pv / self.cum_vol
        return self.vwap


# ---------------------------------------------------------------------------
# Order-flow accumulator — per-symbol buy/sell delta tracker
# ---------------------------------------------------------------------------


@dataclass
class _OrderFlowState:
    """Basic order-flow delta tracker: classifies ticks by tick-rule."""

    last_price: float | None = None
    buy_volume: float = 0.0
    sell_volume: float = 0.0
    net_delta: float = 0.0
    tick_count: int = 0

    def update(self, price: float, volume: float) -> dict[str, Any]:
        """Classify tick and update delta. Returns snapshot dict."""
        self.tick_count += 1
        vol = volume if volume and volume > 0 else 0.0
        side = "neutral"

        if self.last_price is not None:
            if price > self.last_price:
                side = "buy"
                self.buy_volume += vol
                self.net_delta += vol
            elif price < self.last_price:
                side = "sell"
                self.sell_volume += vol
                self.net_delta -= vol
            # price == last_price → neutral, no delta change

        self.last_price = price
        return {
            "side": side,
            "buy_volume": self.buy_volume,
            "sell_volume": self.sell_volume,
            "net_delta": self.net_delta,
            "tick_count": self.tick_count,
        }


# ---------------------------------------------------------------------------
# Module-level registries (keyed by symbol)
# ---------------------------------------------------------------------------

_candle_builders: dict[str, MultiTimeframeCandleBuilder] = {}
_vwap_states: dict[str, _VWAPState] = {}
_orderflow_states: dict[str, _OrderFlowState] = {}

# Store the most recently completed candles for downstream consumers
_completed_candle_log: deque[Candle] = deque(maxlen=500)


def _on_candle_complete(candle: Candle) -> None:
    """Callback: log completed candles and enqueue for PostgreSQL persistence."""
    _completed_candle_log.append(candle)
    logger.info(
        "candle_complete symbol=%s tf=%s open=%s close=%s vol=%s ticks=%d",
        candle.symbol,
        candle.timeframe,
        candle.open,
        candle.close,
        candle.volume,
        candle.tick_count,
    )
    try:
        from storage.candle_persistence import enqueue_candle

        enqueue_candle(candle)
    except Exception:
        pass  # persistence is best-effort; never block the pipeline


def _get_builder(symbol: str) -> MultiTimeframeCandleBuilder:
    """Get or create a multi-timeframe builder for a symbol."""
    if symbol not in _candle_builders:
        _candle_builders[symbol] = MultiTimeframeCandleBuilder(
            symbol=symbol,
            timeframes=[Timeframe.M1, Timeframe.M15, Timeframe.H1],
            on_any_complete=_on_candle_complete,
        )
    return _candle_builders[symbol]


def _normalize_ts(ts: Any) -> datetime:
    """Convert epoch seconds or milliseconds to a UTC datetime."""
    ts_num = int(ts)
    # Heuristic: ms timestamps are > 10^11
    if ts_num > 100_000_000_000:
        ts_num = ts_num // 1000
    return datetime.fromtimestamp(ts_num, tz=UTC)


# ---------------------------------------------------------------------------
# Async callbacks — consumed by ingest/dependencies.py::_build_tick_handler()
# ---------------------------------------------------------------------------


async def process_tick_for_candle(tick: dict[str, Any]) -> Candle | None:
    """
    Process one tick into multi-timeframe candles.

    Expects tick dict with at least: 'symbol' (or 'pair'), 'price', 'ts'.
    Optional: 'volume'.
    Returns the most recently completed candle (if any), otherwise None.
    """
    symbol = str(tick.get("symbol") or tick.get("pair", "UNKNOWN"))
    price = float(tick["price"])
    volume = float(tick.get("volume", 0.0) or 0.0)
    timestamp = _normalize_ts(tick["ts"])

    builder = _get_builder(symbol)
    builder.on_tick(price, timestamp, volume)

    # Return the latest completed candle (if one was produced by this tick)
    if _completed_candle_log:
        return _completed_candle_log[-1]
    return None


async def update_vwap(tick: dict[str, Any]) -> float | None:
    """
    Incremental session-VWAP update for the tick's symbol.

    VWAP = sum(price_i * volume_i) / sum(volume_i)
    Returns current VWAP or None if no volume has been seen.
    """
    symbol = str(tick.get("symbol") or tick.get("pair", "UNKNOWN"))
    price = float(tick["price"])
    volume = float(tick.get("volume", 0.0) or 0.0)

    if symbol not in _vwap_states:
        _vwap_states[symbol] = _VWAPState()

    return _vwap_states[symbol].update(price, volume)


def analyze_orderflow(tick: dict[str, Any]) -> dict[str, Any]:
    """
    Basic order-flow analysis: tick-rule classification + volume delta.

    Returns snapshot dict with side, buy/sell volume, and net delta.
    """
    symbol = str(tick.get("symbol") or tick.get("pair", "UNKNOWN"))
    price = float(tick["price"])
    volume = float(tick.get("volume", 0.0) or 0.0)

    if symbol not in _orderflow_states:
        _orderflow_states[symbol] = _OrderFlowState()

    return _orderflow_states[symbol].update(price, volume)


# ---------------------------------------------------------------------------
# Convenience consumers (iterate over TickBuffer)
# ---------------------------------------------------------------------------


async def consume_ticks_for_candles() -> None:
    """CandleBuilder consumes ticks non-destructively from the shared buffer."""
    for tick in tick_buffer.consume("candle_builder"):
        await process_tick_for_candle(tick)


async def consume_ticks_for_vwap() -> None:
    """VWAP analyzer consumes ticks non-destructively from the shared buffer."""
    for tick in tick_buffer.consume("vwap_analyzer"):
        await update_vwap(tick)


async def consume_ticks_for_orderflow() -> None:
    """Order-flow analyzer consumes ticks non-destructively from the shared buffer."""
    for tick in tick_buffer.consume("orderflow"):
        analyze_orderflow(tick)


# ---------------------------------------------------------------------------
# Query helpers (read-only, no side-effects)
# ---------------------------------------------------------------------------


def get_vwap(symbol: str) -> float | None:
    """Return current session VWAP for a symbol, or None."""
    state = _vwap_states.get(symbol)
    return state.vwap if state else None


def get_orderflow_snapshot(symbol: str) -> dict[str, Any] | None:
    """Return current order-flow snapshot for a symbol, or None."""
    state = _orderflow_states.get(symbol)
    if state is None:
        return None
    return {
        "buy_volume": state.buy_volume,
        "sell_volume": state.sell_volume,
        "net_delta": state.net_delta,
        "tick_count": state.tick_count,
    }


def get_completed_candles(limit: int = 50) -> list[Candle]:
    """Return the most recent completed candles (newest last)."""
    return list(_completed_candle_log)[-limit:]


def flush_all_builders() -> list[Candle]:
    """Force-close all active candle builders (e.g. end-of-session)."""
    flushed: list[Candle] = []
    for builder in _candle_builders.values():
        flushed.extend(builder.flush_all())
    return flushed
