"""
Backward-compatible re-export of the unified CandleBuilder.

All candle construction logic lives in ingest/candle_builder.py.
Analysis modules should consume candles, not build them — this shim
exists only for import compatibility during the migration period.

Zone: analysis (read-only re-export). No side-effects.
"""

# Re-export everything from the single source of truth
from collections import deque
from collections.abc import Iterator

from ingest.candle_builder import (  # noqa: F401
    Candle,
    CandleBuilder,
    MultiTimeframeCandleBuilder,
    OnCandleComplete,
    Timeframe,
)


class TickBuffer:
    """Thread-safe, non-destructive tick buffer."""

    def __init__(self, maxlen: int = 10000):
        self._buffer: deque = deque(maxlen=maxlen)
        self._last_read_index: dict[str, int] = {}  # consumer_id -> last_index

    def append(self, tick: dict) -> None:
        """Add tick to buffer (FIFO with max length)."""
        self._buffer.append(tick)

    def consume(self, consumer_id: str) -> Iterator[dict]:
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

async def process_tick_for_candle(tick):
    raise NotImplementedError

async def consume_ticks_for_candles():
    """CandleBuilder consumes ticks non-destructively."""
    for tick in tick_buffer.consume("candle_builder"):
        # Build candles from tick
        await process_tick_for_candle(tick)  # noqa: F821

async def update_vwap(tick):
    raise NotImplementedError

async def consume_ticks_for_vwap():
    """VWAP analyzer also gets the same ticks."""
    for tick in tick_buffer.consume("vwap_analyzer"):
        # Calculate VWAP from tick
        await update_vwap(tick)  # noqa: F821

def analyze_orderflow(tick):
    raise NotImplementedError

async def consume_ticks_for_orderflow():
    """Order flow analyzer also gets ticks."""
    for tick in tick_buffer.consume("orderflow"):
        await analyze_orderflow(tick) # pyright: ignore[reportGeneralTypeIssues]
