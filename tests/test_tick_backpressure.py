"""Tests for TickBackpressureBuffer — bounded buffer with drop-oldest eviction."""

from __future__ import annotations

import asyncio

import pytest

from ingest.tick_buffer import TickBackpressureBuffer


class TestTickBackpressureBuffer:
    """Tests for the bounded backpressure buffer."""

    def test_init_validates_max_size(self) -> None:
        with pytest.raises(ValueError, match="max_size must be >= 1"):
            TickBackpressureBuffer(max_size=0)

    def test_try_put_success(self) -> None:
        buf = TickBackpressureBuffer(max_size=10)
        ok = buf.try_put({"symbol": "EURUSD", "price": 1.085})
        assert ok is True
        assert buf.current_size == 1
        assert buf.total_enqueued == 1
        assert buf.total_drops == 0

    def test_try_put_evicts_oldest_when_full(self) -> None:
        buf = TickBackpressureBuffer(max_size=3)
        buf.try_put({"symbol": "EURUSD", "price": 1.0})
        buf.try_put({"symbol": "EURUSD", "price": 2.0})
        buf.try_put({"symbol": "EURUSD", "price": 3.0})
        assert buf.current_size == 3

        # This should evict the oldest (price=1.0)
        ok = buf.try_put({"symbol": "EURUSD", "price": 4.0})
        assert ok is False  # eviction occurred
        assert buf.total_drops == 1
        assert buf.current_size == 3

    @pytest.mark.asyncio
    async def test_get_returns_fifo(self) -> None:
        buf = TickBackpressureBuffer(max_size=10)
        buf.try_put({"symbol": "A", "price": 1.0})
        buf.try_put({"symbol": "B", "price": 2.0})
        t1 = await buf.get()
        t2 = await buf.get()
        assert t1["symbol"] == "A"
        assert t2["symbol"] == "B"

    @pytest.mark.asyncio
    async def test_get_batch(self) -> None:
        buf = TickBackpressureBuffer(max_size=100, drain_batch=5)
        for i in range(10):
            buf.try_put({"symbol": "X", "price": float(i)})

        batch = await buf.get_batch(max_items=5)
        assert len(batch) == 5
        assert batch[0]["price"] == 0.0
        assert buf.current_size == 5

    @pytest.mark.asyncio
    async def test_get_batch_partial(self) -> None:
        buf = TickBackpressureBuffer(max_size=100, drain_batch=10)
        buf.try_put({"symbol": "X", "price": 1.0})
        buf.try_put({"symbol": "X", "price": 2.0})

        batch = await buf.get_batch(max_items=10)
        assert len(batch) == 2  # only 2 available

    def test_utilization(self) -> None:
        buf = TickBackpressureBuffer(max_size=10)
        assert buf.utilization == 0.0
        for i in range(5):
            buf.try_put({"symbol": "X", "price": float(i)})
        assert buf.utilization == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_start_stop(self) -> None:
        buf = TickBackpressureBuffer(max_size=10)
        assert buf.is_running is False
        await buf.start()
        assert buf.is_running is True
        await buf.stop()
        assert buf.is_running is False

    def test_stats_snapshot(self) -> None:
        buf = TickBackpressureBuffer(max_size=5)
        buf.try_put({"symbol": "EURUSD", "price": 1.0})
        buf.try_put({"symbol": "EURUSD", "price": 2.0})

        stats = buf.stats()
        assert stats["max_size"] == 5
        assert stats["current_size"] == 2
        assert stats["total_enqueued"] == 2
        assert stats["total_drops"] == 0

    def test_heavy_backpressure_drops_oldest(self) -> None:
        """Fill buffer 2x capacity and verify drops are tracked."""
        buf = TickBackpressureBuffer(max_size=100)
        for i in range(200):
            buf.try_put({"symbol": "EURUSD", "price": float(i)})
        assert buf.current_size == 100
        assert buf.total_drops == 100
        assert buf.total_enqueued == 200

    @pytest.mark.asyncio
    async def test_concurrent_put_and_get(self) -> None:
        """Verify buffer works under concurrent producer/consumer."""
        buf = TickBackpressureBuffer(max_size=50)
        await buf.start()
        consumed: list[dict] = []

        async def producer() -> None:
            for i in range(100):
                buf.try_put({"symbol": "X", "price": float(i)})
                await asyncio.sleep(0)

        async def consumer() -> None:
            while len(consumed) < 50:
                try:
                    tick = await asyncio.wait_for(buf.get(), timeout=1.0)
                    consumed.append(tick)
                except TimeoutError:
                    break

        await asyncio.gather(producer(), consumer())
        await buf.stop()
        assert len(consumed) >= 10  # at least some consumed
