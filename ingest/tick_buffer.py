"""
Bounded tick buffer with backpressure for the WS → Redis ingest path.

When the WebSocket receives ticks faster than Redis can consume them,
this buffer prevents unbounded memory growth by:

1. Buffering ticks in a bounded ``asyncio.Queue``.
2. Dropping oldest ticks when the queue is full (LIFO eviction: newest
   ticks are more valuable than stale ones).
3. Tracking drop counts via Prometheus-compatible metrics.

Usage in the ingest pipeline::

    from ingest.tick_buffer import TickBackpressureBuffer

    buffer = TickBackpressureBuffer(max_size=10_000)
    await buffer.start()

    # Producer (WS handler) — non-blocking
    buffer.try_put({"symbol": "EURUSD", "price": 1.0850, "ts": ...})

    # Consumer (Redis writer) — blocking
    async for tick in buffer.consume():
        await redis.xadd(...)

    await buffer.stop()

Zone: ingest/ — transport buffering only, no market logic.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from core.metrics import Counter, Gauge, get_registry

logger = logging.getLogger(__name__)

_R = get_registry()

TICK_BUFFER_SIZE: Gauge = _R.gauge(
    "wolf_tick_buffer_size",
    "Current number of ticks in the backpressure buffer",
    label_names=(),
)

TICK_BUFFER_DROPS: Counter = _R.counter(
    "wolf_tick_buffer_drops_total",
    "Number of ticks dropped due to backpressure (buffer full)",
    label_names=("symbol",),
)

TICK_BUFFER_THROUGHPUT: Counter = _R.counter(
    "wolf_tick_buffer_consumed_total",
    "Number of ticks successfully consumed from the buffer",
    label_names=(),
)


class TickBackpressureBuffer:
    """Bounded async buffer for tick data with drop-oldest backpressure.

    Parameters
    ----------
    max_size : int
        Maximum number of tick dicts the buffer can hold.
        When full, the oldest tick is evicted to make room.
    drain_batch : int
        Number of ticks to yield per consume iteration (batching
        reduces per-tick async overhead).
    """

    def __init__(
        self,
        max_size: int = 10_000,
        drain_batch: int = 100,
    ) -> None:
        if max_size < 1:
            raise ValueError(f"max_size must be >= 1, got {max_size}")
        self._max_size = max_size
        self._drain_batch = max(1, drain_batch)
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=max_size)
        self._running = False
        self._total_drops = 0
        self._total_enqueued = 0

    @property
    def max_size(self) -> int:
        return self._max_size

    @property
    def current_size(self) -> int:
        return self._queue.qsize()

    @property
    def total_drops(self) -> int:
        return self._total_drops

    @property
    def total_enqueued(self) -> int:
        return self._total_enqueued

    @property
    def utilization(self) -> float:
        """Buffer utilization as a fraction (0.0 to 1.0)."""
        return self._queue.qsize() / self._max_size if self._max_size > 0 else 0.0

    def try_put(self, tick: dict[str, Any]) -> bool:
        """Attempt to enqueue a tick without blocking.

        If the buffer is full, evicts the oldest tick and enqueues the new one.
        Returns True if enqueued without eviction, False if an eviction occurred.
        """
        try:
            self._queue.put_nowait(tick)
            self._total_enqueued += 1
            TICK_BUFFER_SIZE.set(self._queue.qsize())
            return True
        except asyncio.QueueFull:
            # Evict oldest tick to make room for the newer one
            try:
                dropped = self._queue.get_nowait()
                self._total_drops += 1
                symbol = dropped.get("symbol", "UNKNOWN")
                TICK_BUFFER_DROPS.labels(symbol=symbol).inc()
            except asyncio.QueueEmpty:
                pass

            try:
                self._queue.put_nowait(tick)
                self._total_enqueued += 1
                TICK_BUFFER_SIZE.set(self._queue.qsize())
            except asyncio.QueueFull:
                # Should not happen after eviction, but be safe
                self._total_drops += 1
                symbol = tick.get("symbol", "UNKNOWN")
                TICK_BUFFER_DROPS.labels(symbol=symbol).inc()
            return False

    async def get(self) -> dict[str, Any]:
        """Get a single tick from the buffer, blocking if empty."""
        tick = await self._queue.get()
        TICK_BUFFER_SIZE.set(self._queue.qsize())
        TICK_BUFFER_THROUGHPUT.inc()
        return tick

    async def get_batch(self, max_items: int | None = None) -> list[dict[str, Any]]:
        """Get up to `max_items` ticks from the buffer.

        Returns at least one tick (blocks until available),
        then drains up to `max_items` without blocking.
        """
        batch_size = max_items or self._drain_batch
        batch: list[dict[str, Any]] = []

        # Block for first tick
        first = await self._queue.get()
        batch.append(first)

        # Drain remaining without blocking
        while len(batch) < batch_size:
            try:
                tick = self._queue.get_nowait()
                batch.append(tick)
            except asyncio.QueueEmpty:
                break

        TICK_BUFFER_SIZE.set(self._queue.qsize())
        TICK_BUFFER_THROUGHPUT.inc(len(batch))
        return batch

    async def start(self) -> None:
        """Mark the buffer as running."""
        self._running = True
        logger.info(
            "TickBackpressureBuffer started (max_size=%d, drain_batch=%d)",
            self._max_size,
            self._drain_batch,
        )

    async def stop(self) -> None:
        """Signal the buffer to stop. Consumers should check is_running."""
        self._running = False
        logger.info(
            "TickBackpressureBuffer stopped (enqueued=%d, drops=%d, remaining=%d)",
            self._total_enqueued,
            self._total_drops,
            self._queue.qsize(),
        )

    @property
    def is_running(self) -> bool:
        return self._running

    def stats(self) -> dict[str, Any]:
        """Return buffer statistics snapshot."""
        return {
            "max_size": self._max_size,
            "current_size": self._queue.qsize(),
            "total_enqueued": self._total_enqueued,
            "total_drops": self._total_drops,
            "utilization": round(self.utilization, 4),
            "running": self._running,
        }
