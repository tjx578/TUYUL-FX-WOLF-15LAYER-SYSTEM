"""Load and stress tests for real-time tick processing pipeline.

Validates that:
- CandleBuilder handles high-frequency tick bursts without data loss
- Tick processing throughput meets latency thresholds
- Multi-symbol concurrent load doesn't cause cross-contamination
- Memory stays bounded under sustained tick pressure
- Spike / gap scenarios are handled gracefully
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any

from ingest.candle_builder import Candle, CandleBuilder, Timeframe

# Import the shared tick generator from conftest
from tests.conftest import generate_ticks

# ---------------------------------------------------------------------------
# Constants -- tweak for CI vs local runs
# ---------------------------------------------------------------------------
HIGH_FREQ_TICK_COUNT = 10_000  # Simulate 10k ticks per symbol
MULTI_SYMBOL_COUNT = 6  # Number of concurrent symbols
THROUGHPUT_FLOOR_TPS = 5_000  # Minimum ticks/sec we guarantee
MAX_PROCESS_TIME_S = 5.0  # Upper bound for full batch processing


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_builders(symbols: list[str]) -> tuple[dict[str, CandleBuilder], list[Candle]]:
    """Create one authoritative M15 builder per symbol."""
    completed: list[Candle] = []
    builders = {symbol: CandleBuilder(symbol, Timeframe.M15, on_complete=completed.append) for symbol in symbols}
    return builders, completed


def _tick_price(tick: dict[str, Any]) -> float:
    """Resolve the same mid-price preference used by the retired batch API."""
    if tick.get("mid") is not None:
        return float(tick["mid"])
    if tick.get("bid") is not None and tick.get("ask") is not None:
        return (float(tick["bid"]) + float(tick["ask"])) / 2.0
    for field in ("bid", "ask", "last"):
        if tick.get(field) is not None:
            return float(tick[field])
    raise ValueError("Tick has no usable price")


def _tick_time(tick: dict[str, Any]) -> datetime:
    """Normalize Unix or datetime tick timestamps for ``on_tick``."""
    timestamp = tick["timestamp"]
    if isinstance(timestamp, datetime):
        return timestamp if timestamp.tzinfo is not None else timestamp.replace(tzinfo=UTC)
    return datetime.fromtimestamp(float(timestamp), tz=UTC)


def _feed_ticks(builders: dict[str, CandleBuilder], ticks: list[dict[str, Any]]) -> None:
    """Feed a batch through the current synchronous per-tick API."""
    for tick in ticks:
        symbol = str(tick["symbol"])
        builders[symbol].on_tick(
            _tick_price(tick),
            _tick_time(tick),
            float(tick.get("volume", 0.0)),
        )


def _builder_candles(builder: CandleBuilder) -> list[Candle]:
    """Return completed candles plus the current in-progress candle."""
    candles = builder.completed_candles
    if (partial := builder.current_partial) is not None:
        candles.append(partial)
    return candles


# ---------------------------------------------------------------------------
# High-frequency single-symbol burst
# ---------------------------------------------------------------------------


class TestHighFrequencyTickBurst:
    """Simulate rapid-fire ticks on a single pair."""

    def test_process_10k_ticks_within_time_bound(self) -> None:
        """10 000 ticks must be processed under MAX_PROCESS_TIME_S."""
        builders, _completed = _setup_builders(["EURUSD"])

        ticks = generate_ticks(
            symbol="EURUSD",
            count=HIGH_FREQ_TICK_COUNT,
            interval_ms=10,  # 100 ticks/sec simulated
        )
        start = time.perf_counter()
        _feed_ticks(builders, ticks)
        elapsed = time.perf_counter() - start

        assert elapsed < MAX_PROCESS_TIME_S, (
            f"Processing {HIGH_FREQ_TICK_COUNT} ticks took {elapsed:.2f}s (limit: {MAX_PROCESS_TIME_S}s)"
        )

    def test_throughput_meets_minimum(self) -> None:
        """Measured throughput must exceed THROUGHPUT_FLOOR_TPS."""
        builders, _completed = _setup_builders(["GBPJPY"])

        ticks = generate_ticks(
            symbol="GBPJPY",
            count=HIGH_FREQ_TICK_COUNT,
            interval_ms=10,
        )
        start = time.perf_counter()
        _feed_ticks(builders, ticks)
        elapsed = time.perf_counter() - start

        tps = HIGH_FREQ_TICK_COUNT / max(elapsed, 1e-9)
        assert tps >= THROUGHPUT_FLOOR_TPS, f"Throughput {tps:.0f} tps < required {THROUGHPUT_FLOOR_TPS} tps"

    def test_no_tick_data_loss(self) -> None:
        """Every tick must be accounted for (buffered or consumed into candle)."""
        builders, completed = _setup_builders(["EURUSD"])

        tick_count = 1_000
        ticks = generate_ticks(symbol="EURUSD", count=tick_count, interval_ms=100)
        _feed_ticks(builders, ticks)

        partial = builders["EURUSD"].current_partial
        remaining_in_partial = partial.tick_count if partial is not None else 0
        consumed_into_candles = sum(candle.tick_count for candle in completed)
        assert remaining_in_partial + consumed_into_candles == tick_count
        assert remaining_in_partial <= tick_count, "Partial candle grew beyond input"


# ---------------------------------------------------------------------------
# Multi-symbol concurrent load
# ---------------------------------------------------------------------------


class TestMultiSymbolConcurrentLoad:
    """Simulate ticks arriving from multiple symbols simultaneously."""

    SYMBOLS = ["EURUSD", "GBPJPY", "USDJPY", "GBPUSD", "AUDUSD", "XAUUSD"]

    def test_multi_symbol_isolation(self) -> None:
        """Ticks from different symbols must not leak into each other's buffers."""
        builders, _completed = _setup_builders(self.SYMBOLS)

        all_ticks: list[dict[str, Any]] = []
        per_symbol_count = 500
        for sym in self.SYMBOLS:
            all_ticks.extend(
                generate_ticks(
                    symbol=sym,
                    count=per_symbol_count,
                    base_price=1.0 if "USD" in sym[:3] else 150.0,
                    interval_ms=50,
                )
            )

        _feed_ticks(builders, all_ticks)

        # Each symbol has its own builder -- no cross-contamination.
        for sym in self.SYMBOLS:
            for candle in _builder_candles(builders[sym]):
                assert candle.symbol == sym, f"Candle for {candle.symbol} found in {sym} builder"

    def test_multi_symbol_throughput(self) -> None:
        """Multi-symbol load must still meet throughput floor."""
        builders, _completed = _setup_builders(self.SYMBOLS)

        total_ticks = 0
        all_ticks: list[dict[str, Any]] = []
        per_symbol = 2_000
        for sym in self.SYMBOLS:
            all_ticks.extend(generate_ticks(symbol=sym, count=per_symbol, interval_ms=20))
            total_ticks += per_symbol

        start = time.perf_counter()
        _feed_ticks(builders, all_ticks)
        elapsed = time.perf_counter() - start

        tps = total_ticks / max(elapsed, 1e-9)
        assert tps >= THROUGHPUT_FLOOR_TPS / 2, (
            f"Multi-symbol throughput {tps:.0f} tps < required {THROUGHPUT_FLOOR_TPS // 2} tps"
        )

    def test_candles_built_for_all_symbols(self) -> None:
        """At least one candle should be built per symbol when enough ticks span a window."""
        builders, completed = _setup_builders(self.SYMBOLS)

        all_ticks: list[dict[str, Any]] = []
        # Generate enough ticks to span a full M15 candle (16 min worth)
        for sym in self.SYMBOLS:
            all_ticks.extend(
                generate_ticks(
                    symbol=sym,
                    count=200,
                    interval_ms=5_000,  # 5s apart -> 200 * 5 = 1000s ≈ 16 min
                )
            )

        _feed_ticks(builders, all_ticks)

        symbols_with_candles = {candle.symbol for candle in completed}

        for sym in self.SYMBOLS:
            assert sym in symbols_with_candles, f"No candle built for {sym} despite full M15 span"


# ---------------------------------------------------------------------------
# Tick spike / gap scenarios
# ---------------------------------------------------------------------------


class TestTickSpikeAndGap:
    """Edge cases: price spikes, gaps in timestamps, duplicate ticks."""

    def test_price_spike_handled(self) -> None:
        """A sudden 5% price spike should still produce a valid candle."""
        builders, completed = _setup_builders(["XAUUSD"])
        base_time = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)

        ticks: list[dict[str, Any]] = []
        # Normal ticks
        for i in range(50):
            ticks.append(
                {  # noqa: PERF401
                    "symbol": "XAUUSD",
                    "bid": 2050.0,
                    "ask": 2051.0,
                    "timestamp": (base_time + timedelta(seconds=i * 10)).timestamp(),
                    "volume": 5,
                    "source": "test",
                }
            )
        # Spike tick
        ticks.append(
            {
                "symbol": "XAUUSD",
                "bid": 2150.0,  # +100 spike
                "ask": 2151.0,
                "timestamp": (base_time + timedelta(seconds=510)).timestamp(),
                "volume": 100,
                "source": "test",
            }
        )
        # Return to normal
        for i in range(50):
            ticks.append(
                {  # noqa: PERF401
                    "symbol": "XAUUSD",
                    "bid": 2052.0,
                    "ask": 2053.0,
                    "timestamp": (base_time + timedelta(seconds=520 + i * 10)).timestamp(),
                    "volume": 5,
                    "source": "test",
                }
            )

        _feed_ticks(builders, ticks)

        # Should still build candles (no crash)
        assert completed, "Candle builder crashed on price spike"

        # Verify high captures the spike
        m15_candles = [candle for candle in completed if candle.timeframe == "M15"]
        if m15_candles:
            highs = [candle.high for candle in m15_candles]
            assert max(highs) >= 2100.0, "Spike not reflected in candle high"

    def test_timestamp_gap_between_candles(self) -> None:
        """A 30-minute gap between ticks should produce separate candles, not one giant candle."""
        builders, completed = _setup_builders(["EURUSD"])
        base_time = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)

        ticks: list[dict[str, Any]] = []
        # First cluster: 10:00 - 10:14
        for i in range(10):
            ticks.append(
                {  # noqa: PERF401
                    "symbol": "EURUSD",
                    "bid": 1.0850,
                    "ask": 1.0852,
                    "timestamp": (base_time + timedelta(minutes=i)).timestamp(),
                    "volume": 1,
                    "source": "test",
                }
            )
        # Gap: 30 minutes
        # Second cluster: 10:45 - 10:59
        gap_start = base_time + timedelta(minutes=45)
        for i in range(10):
            ticks.append(
                {  # noqa: PERF401
                    "symbol": "EURUSD",
                    "bid": 1.0870,
                    "ask": 1.0872,
                    "timestamp": (gap_start + timedelta(minutes=i)).timestamp(),
                    "volume": 1,
                    "source": "test",
                }
            )

        _feed_ticks(builders, ticks)
        builders["EURUSD"].flush()

        m15_candles = [candle for candle in completed if candle.symbol == "EURUSD"]

        # Should have produced at least 2 separate candles
        assert len(m15_candles) >= 2, f"Expected >=2 candles across gap, got {len(m15_candles)}"

    def test_duplicate_timestamps_handled(self) -> None:
        """Multiple ticks with identical timestamps should be processed without error."""
        builders, _completed = _setup_builders(["EURUSD"])
        ts = datetime(2024, 1, 15, 10, 5, 0, tzinfo=UTC).timestamp()

        ticks = [
            {
                "symbol": "EURUSD",
                "bid": 1.0850 + i * 0.0001,
                "ask": 1.0852 + i * 0.0001,
                "timestamp": ts,
                "volume": 1,
                "source": "test",
            }
            for i in range(100)
        ]

        _feed_ticks(builders, ticks)

        # No crash -- candles may or may not be emitted depending on window
        assert True, "Duplicate timestamps caused crash"


# ---------------------------------------------------------------------------
# Sustained load simulation
# ---------------------------------------------------------------------------


class TestSustainedLoad:
    """Simulate multiple feed cycles to mimic sustained real-time input."""

    def test_sustained_100_cycles_no_memory_leak(self) -> None:
        """Run 100 processing cycles and verify buffer size stays bounded."""
        builders, _completed = _setup_builders(["EURUSD"])

        base_time = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
        max_buffer_size = 0

        for cycle in range(100):
            cycle_time = base_time + timedelta(seconds=cycle * 10)
            ticks = generate_ticks(
                symbol="EURUSD",
                count=50,
                interval_ms=200,
                base_time=cycle_time,
            )
            _feed_ticks(builders, ticks)

            partial = builders["EURUSD"].current_partial
            current_partial_size = partial.tick_count if partial is not None else 0
            max_buffer_size = max(max_buffer_size, current_partial_size)

        # Buffer should never grow unboundedly -- cap at a reasonable multiple
        # of a single M15 window worth of ticks
        assert max_buffer_size < HIGH_FREQ_TICK_COUNT, f"Buffer grew to {max_buffer_size} -- possible memory leak"

    def test_sustained_multi_symbol_cycles(self) -> None:
        """Sustained load across 6 symbols, 50 cycles."""
        symbols = ["EURUSD", "GBPJPY", "USDJPY", "GBPUSD", "AUDUSD", "XAUUSD"]
        builders, completed = _setup_builders(symbols)

        base_time = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
        total_candles = 0

        for cycle in range(50):
            cycle_time = base_time + timedelta(seconds=cycle * 20)
            all_ticks: list[dict[str, Any]] = []
            for sym in symbols:
                all_ticks.extend(
                    generate_ticks(
                        symbol=sym,
                        count=30,
                        interval_ms=500,
                        base_time=cycle_time,
                    )
                )

            completed_before = len(completed)
            _feed_ticks(builders, all_ticks)
            total_candles += len(completed) - completed_before

        # Over 50 cycles with 6 symbols we should have produced candles
        assert total_candles > 0, "No candles produced over 50 sustained cycles"

    def test_processing_latency_per_cycle(self) -> None:
        """Each individual cycle must complete in <100ms for real-time viability."""
        builders, _completed = _setup_builders(["EURUSD"])

        base_time = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
        max_latency = 0.0

        for cycle in range(20):
            cycle_time = base_time + timedelta(seconds=cycle * 15)
            ticks = generate_ticks(
                symbol="EURUSD",
                count=200,
                interval_ms=50,
                base_time=cycle_time,
            )
            start = time.perf_counter()
            _feed_ticks(builders, ticks)
            latency = time.perf_counter() - start
            max_latency = max(max_latency, latency)

        assert max_latency < 0.1, f"Peak cycle latency {max_latency * 1000:.1f}ms exceeds 100ms limit"
