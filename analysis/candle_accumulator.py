"""
Candle accumulator — builds OHLC candles from tick stream.

Zone: analysis/ — no execution side-effects.

Fixes applied:
- Gap detection: marks candles closed due to time discontinuity.
- Bounded completed list: deque(maxlen) prevents memory leak.
- No assert in production: explicit ValueError for invariants.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass


@dataclass
class Candle:
    """Completed OHLC candle with metadata."""
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    timestamp_open: float       # epoch seconds when candle opened
    timestamp_close: float      # epoch seconds when candle closed
    timeframe_seconds: float    # candle duration setting (e.g. 60.0 for M1)
    tick_count: int = 0
    has_gap: bool = False       # True if candle was force-closed due to time gap


@dataclass
class CandleAccumulatorConfig:
    """Configuration for candle accumulator."""
    timeframe_seconds: float = 60.0        # Candle period (e.g. 60 = M1)
    max_completed: int = 1000              # Max completed candles to retain
    gap_threshold_factor: float = 2.0      # If tick gap > factor * timeframe, mark as gap
    # e.g. for M1 (60s), gap detected if tick arrives > 120s after last tick


class _CandleBuilder:
    """Builds a single in-progress candle from ticks."""

    __slots__ = (
        "symbol", "open", "high", "low", "close",
        "volume", "timestamp_open", "tick_count",
    )

    def __init__(self, symbol: str, price: float, timestamp: float) -> None:
        self.symbol = symbol
        self.open = price
        self.high = price
        self.low = price
        self.close = price
        self.volume = 1
        self.timestamp_open = timestamp
        self.tick_count = 1

    def update(self, price: float) -> None:
        if price > self.high:
            self.high = price
        if price < self.low:
            self.low = price
        self.close = price
        self.volume += 1
        self.tick_count += 1

    def emit(self, timestamp_close: float, timeframe_seconds: float, has_gap: bool = False) -> Candle:
        """
        Finalize this builder into a completed Candle.

        Raises ValueError if invariants are violated (not assert — safe in -O mode).
        """
        if self.tick_count < 1:
            raise ValueError(
                f"Cannot emit candle with zero ticks: symbol={self.symbol}, "
                f"open_ts={self.timestamp_open}"
            )
        if self.high < self.low:
            raise ValueError(
                f"Candle invariant violated: high ({self.high}) < low ({self.low}), "
                f"symbol={self.symbol}"
            )
        if timestamp_close < self.timestamp_open:
            raise ValueError(
                f"Candle close timestamp ({timestamp_close}) < open timestamp "
                f"({self.timestamp_open}), symbol={self.symbol}"
            )

        return Candle(
            symbol=self.symbol,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
            timestamp_open=self.timestamp_open,
            timestamp_close=timestamp_close,
            timeframe_seconds=timeframe_seconds,
            tick_count=self.tick_count,
            has_gap=has_gap,
        )


class CandleAccumulator:
    """
    Accumulates ticks into OHLC candles for a single symbol.

    Features:
    - Time-based candle boundaries (configurable timeframe).
    - Gap detection: if a tick arrives after a significant time gap,
      the previous candle is force-closed with has_gap=True.
    - Bounded completed candle history (deque with maxlen).
    - No assert in production paths — explicit ValueError for invariants.

    Zone: analysis/ — pure data transformation, no execution side-effects.
    """

    def __init__(self, symbol: str, config: CandleAccumulatorConfig | None = None) -> None:
        self._symbol = symbol
        self._config = config or CandleAccumulatorConfig()
        self._current: _CandleBuilder | None = None
        self._last_tick_ts: float | None = None
        self._completed: deque[Candle] = deque(maxlen=self._config.max_completed)

        if self._config.timeframe_seconds <= 0:
            raise ValueError(
                f"timeframe_seconds must be positive, got {self._config.timeframe_seconds}"
            )
        if self._config.max_completed < 1:
            raise ValueError(
                f"max_completed must be >= 1, got {self._config.max_completed}"
            )

    @property
    def symbol(self) -> str:
        return self._symbol

    @property
    def completed(self) -> list[Candle]:
        """Return completed candles as a list (copy from deque)."""
        return list(self._completed)

    @property
    def completed_count(self) -> int:
        return len(self._completed)

    @property
    def current_builder(self) -> _CandleBuilder | None:
        """Expose current in-progress builder (read-only intent)."""
        return self._current

    def _candle_boundary(self, timestamp: float) -> float:
        """Calculate the candle boundary (start-of-period) for a given timestamp."""
        tf = self._config.timeframe_seconds
        return (timestamp // tf) * tf

    def _detect_gap(self, tick_ts: float) -> bool:
        """
        Detect if there is a significant time gap since previous tick.

        Returns True if gap detected, False otherwise.
        """
        if self._last_tick_ts is None:
            return False

        elapsed = tick_ts - self._last_tick_ts
        threshold = self._config.timeframe_seconds * self._config.gap_threshold_factor
        return elapsed > threshold

    def on_tick(self, price: float, timestamp: float | None = None) -> Candle | None:
        """
        Process a new tick. Returns a completed Candle if one was finalized,
        otherwise None.

        Args:
            price: The tick price (must be > 0).
            timestamp: Epoch seconds. If None, uses time.time().

        Returns:
            Completed Candle if a candle boundary was crossed, else None.

        Raises:
            ValueError: If price <= 0.
        """
        if price <= 0:
            raise ValueError(f"Tick price must be positive, got {price}")

        ts = timestamp if timestamp is not None else time.time()
        tick_boundary = self._candle_boundary(ts)
        completed_candle: Candle | None = None

        # Detect gap before processing
        is_gap = self._detect_gap(ts)

        if self._current is not None:
            current_boundary = self._candle_boundary(self._current.timestamp_open)

            # Check if tick belongs to a new candle period
            if tick_boundary > current_boundary:
                # Close current candle
                # Close timestamp = end of its period (or last tick ts if gap)
                close_ts = current_boundary + self._config.timeframe_seconds
                # If gap, use the boundary end as close time (not the new tick time)
                completed_candle = self._current.emit(
                    timestamp_close=min(close_ts, ts),
                    timeframe_seconds=self._config.timeframe_seconds,
                    has_gap=is_gap,
                )
                self._completed.append(completed_candle)
                self._current = None

        # Start new candle or update existing
        if self._current is None:
            self._current = _CandleBuilder(
                symbol=self._symbol,
                price=price,
                timestamp=ts,
            )
        else:
            self._current.update(price)

        self._last_tick_ts = ts
        return completed_candle

    def flush(self, timestamp: float | None = None) -> Candle | None:
        """
        Force-close the current candle (e.g. on shutdown or explicit flush).

        Returns the completed candle if there was one in progress, else None.
        """
        if self._current is None:
            return None

        ts = timestamp if timestamp is not None else time.time()
        candle = self._current.emit(
            timestamp_close=ts,
            timeframe_seconds=self._config.timeframe_seconds,
            has_gap=False,  # Explicit flush, not a gap
        )
        self._completed.append(candle)
        self._current = None
        return candle

    def reset(self) -> None:
        """Clear all state. Useful for testing."""
        self._current = None
        self._last_tick_ts = None
        self._completed.clear()
