"""
Unified CandleBuilder — multi-timeframe OHLCV aggregation.

Supports M1→M15, M15→H1, and arbitrary aggregation via config.
This is the single source of truth for candle construction in the pipeline.

Zone: ingest (data pipeline). No analysis side-effects.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum


class Timeframe(Enum):
    """Supported output timeframes."""

    M1 = ("M1", 1)
    M5 = ("M5", 5)
    M15 = ("M15", 15)
    H1 = ("H1", 60)
    H4 = ("H4", 240)
    D1 = ("D1", 1440)

    def __init__(self, label: str, minutes: int) -> None:
        self.label = label
        self.minutes = minutes

    @staticmethod
    def from_str(s: str) -> Timeframe:
        mapping = {tf.label: tf for tf in Timeframe}
        if s.upper() not in mapping:
            raise ValueError(f"Unknown timeframe: {s!r}. Valid: {list(mapping)}")
        return mapping[s.upper()]


@dataclass
class Candle:
    """Immutable OHLCV candle."""

    symbol: str
    timeframe: str  # e.g. "M15", "H1"
    open_time: datetime  # UTC, period start (inclusive)
    close_time: datetime  # UTC, period end (exclusive)
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    tick_count: int = 0
    complete: bool = False

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "open_time": self.open_time.isoformat(),
            "close_time": self.close_time.isoformat(),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "tick_count": self.tick_count,
            "complete": self.complete,
        }


def _align_to_period(dt: datetime, period_minutes: int) -> datetime:
    """Align a datetime down to the start of its period bucket (UTC)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    epoch = datetime(2000, 1, 1, tzinfo=UTC)
    delta = dt - epoch
    total_minutes = delta.total_seconds() / 60
    aligned_minutes = math.floor(total_minutes / period_minutes) * period_minutes
    return epoch + timedelta(minutes=aligned_minutes)


@dataclass
class _CandleAccumulator:
    """Mutable accumulator for building a single candle in progress."""

    symbol: str
    timeframe: str
    period_minutes: int
    open_time: datetime | None = None
    close_time: datetime | None = None
    open: float | None = None
    high: float = -math.inf
    low: float = math.inf
    close: float | None = None
    volume: float = 0.0
    tick_count: int = 0

    def reset(self, open_time: datetime) -> None:
        self.open_time = open_time
        self.close_time = open_time + timedelta(minutes=self.period_minutes)
        self.open = None
        self.high = -math.inf
        self.low = math.inf
        self.close = None
        self.volume = 0.0
        self.tick_count = 0

    def update(self, price: float, volume: float = 0.0) -> None:
        if self.open is None:
            self.open = price
        self.high = max(self.high, price)
        self.low = min(self.low, price)
        self.close = price
        self.volume += volume
        self.tick_count += 1

    def update_from_candle(self, candle: Candle) -> None:
        """Aggregate a completed sub-candle into this accumulator."""
        if self.open is None:
            self.open = candle.open
        self.high = max(self.high, candle.high)
        self.low = min(self.low, candle.low)
        self.close = candle.close
        self.volume += candle.volume
        self.tick_count += candle.tick_count

    def emit(self) -> Candle:
        if self.open is None or self.close is None:
            raise ValueError("Cannot emit candle with no price data")
        return Candle(
            symbol=self.symbol,
            timeframe=self.timeframe,
            open_time=self.open_time,  # type: ignore[arg-type]
            close_time=self.close_time,  # type: ignore[arg-type]
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
            tick_count=self.tick_count,
            complete=True,
        )

    @property
    def is_empty(self) -> bool:
        return self.open is None


# Callback type: called each time a candle completes
OnCandleComplete = Callable[[Candle], None]


class CandleBuilder:
    """
    Multi-timeframe candle builder.

    Supports two modes of feeding:
    1. **Tick mode**: feed raw ticks via `on_tick()` → builds base timeframe candles.
    2. **Candle aggregation mode**: feed completed lower-TF candles via
       `on_candle()` → builds higher-TF candles (e.g. M15 → H1).

    Usage example — tick → M15 → H1 chain:

        def on_h1(candle: Candle):
            print("H1 complete:", candle)

        def on_m15(candle: Candle):
            h1_builder.on_candle(candle)

        m15_builder = CandleBuilder("EURUSD", Timeframe.M15, on_complete=on_m15)
        h1_builder  = CandleBuilder("EURUSD", Timeframe.H1,  on_complete=on_h1)

        for tick in tick_stream:
            m15_builder.on_tick(tick.price, tick.time, tick.volume)
    """

    def __init__(
        self,
        symbol: str,
        timeframe: Timeframe,
        on_complete: OnCandleComplete | None = None,
    ) -> None:
        self.symbol = symbol
        self.timeframe = timeframe
        self.on_complete = on_complete
        self._acc = _CandleAccumulator(
            symbol=symbol,
            timeframe=timeframe.label,
            period_minutes=timeframe.minutes,
        )
        self._completed: list[Candle] = []

    # ------------------------------------------------------------------
    # Public API — Tick feeding (build candles from raw prices)
    # ------------------------------------------------------------------

    def on_tick(
        self,
        price: float,
        timestamp: datetime,
        volume: float = 0.0,
    ) -> Candle | None:
        """
        Feed a single tick. Returns a completed Candle if the tick
        triggered a period rollover, otherwise None.
        """
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)

        period_start = _align_to_period(timestamp, self.timeframe.minutes)

        # First tick ever or new period
        if self._acc.open_time is None or period_start != self._acc.open_time:
            completed = self._maybe_close()
            self._acc.reset(period_start)
            self._acc.update(price, volume)
            return completed

        self._acc.update(price, volume)
        return None

    # ------------------------------------------------------------------
    # Public API — Candle aggregation (build higher TF from lower TF)
    # ------------------------------------------------------------------

    def on_candle(self, candle: Candle) -> Candle | None:
        """
        Feed a completed lower-timeframe candle to aggregate into a
        higher-timeframe candle. Returns the completed higher-TF candle
        when its period rolls over, otherwise None.

        The sub-candle's open_time determines which higher-TF period it
        belongs to.
        """
        if not candle.complete:
            return None  # only aggregate finalized candles

        period_start = _align_to_period(candle.open_time, self.timeframe.minutes)

        if self._acc.open_time is None or period_start != self._acc.open_time:
            completed = self._maybe_close()
            self._acc.reset(period_start)
            self._acc.update_from_candle(candle)
            return completed

        self._acc.update_from_candle(candle)
        return None

    # ------------------------------------------------------------------
    # Public API — Force-close & state
    # ------------------------------------------------------------------

    def flush(self) -> Candle | None:
        """Force-close the current accumulator (e.g. end-of-session)."""
        return self._maybe_close()

    @property
    def completed_candles(self) -> list[Candle]:
        """All candles completed during the lifetime of this builder."""
        return list(self._completed)

    @property
    def current_partial(self) -> Candle | None:
        """Return the in-progress candle (not yet complete), or None."""
        if self._acc.is_empty:
            return None
        return Candle(
            symbol=self._acc.symbol,
            timeframe=self._acc.timeframe,
            open_time=self._acc.open_time,  # type: ignore[arg-type]
            close_time=self._acc.close_time,  # type: ignore[arg-type]
            open=self._acc.open,  # type: ignore[arg-type]
            high=self._acc.high,
            low=self._acc.low,
            close=self._acc.close,  # type: ignore[arg-type]
            volume=self._acc.volume,
            tick_count=self._acc.tick_count,
            complete=False,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _maybe_close(self) -> Candle | None:
        """Close the current accumulator if it has data. Returns completed candle or None."""
        if self._acc.is_empty:
            return None
        candle = self._acc.emit()
        self._completed.append(candle)
        if self.on_complete:
            try:
                # Use publish_candle_sync if available
                from context.redis_context_bridge import publish_candle_sync

                publish_candle_sync(candle)
            except ImportError:
                # Fallback: call the callback as-is
                self.on_complete(candle)
            except Exception as exc:
                import logging

                logging.getLogger(__name__).error(
                    "[CandleBuilder] Sync Redis write failed for %s/%s: %s",
                    candle.get("symbol"),
                    candle.get("timeframe"),
                    exc,
                )
        return candle


class MultiTimeframeCandleBuilder:
    """
    Convenience class that chains tick → M15 → H1 (and more) in a single call.

    Usage:
        def on_candle(candle: Candle):
            store(candle)  # receives both M15 and H1 candles

        mtf = MultiTimeframeCandleBuilder("EURUSD", on_any_complete=on_candle)
        for tick in stream:
            mtf.on_tick(tick.price, tick.time, tick.volume)
    """

    def __init__(
        self,
        symbol: str,
        timeframes: list[Timeframe] | None = None,
        on_any_complete: OnCandleComplete | None = None,
    ) -> None:
        if timeframes is None:
            timeframes = [Timeframe.M15, Timeframe.H1]

        # Sort ascending by minutes so we can chain them
        timeframes = sorted(timeframes, key=lambda tf: tf.minutes)
        if len(timeframes) == 0:
            raise ValueError("At least one timeframe required")

        self.symbol = symbol
        self.on_any_complete = on_any_complete
        self._builders: dict[str, CandleBuilder] = {}
        self._chain: list[str] = []  # ordered labels for chaining

        # Build the chain: smallest TF gets ticks, each feeds the next
        for i, tf in enumerate(timeframes):
            label = tf.label

            def _make_callback(tf_label: str, next_idx: int, tfs: list[Timeframe]) -> OnCandleComplete:
                def cb(candle: Candle) -> None:
                    # Notify caller
                    if self.on_any_complete:
                        self.on_any_complete(candle)
                    # Feed to next higher TF builder (if any)
                    if next_idx < len(tfs):
                        next_label = tfs[next_idx].label
                        self._builders[next_label].on_candle(candle)

                return cb

            builder = CandleBuilder(
                symbol=symbol,
                timeframe=tf,
                on_complete=_make_callback(label, i + 1, timeframes),
            )
            self._builders[label] = builder
            self._chain.append(label)

    def on_tick(self, price: float, timestamp: datetime, volume: float = 0.0) -> None:
        """Feed a tick into the base (smallest) timeframe builder."""
        base_label = self._chain[0]
        self._builders[base_label].on_tick(price, timestamp, volume)

    def flush_all(self) -> list[Candle]:
        """Flush all builders (end of session). Returns all flushed candles."""
        flushed: list[Candle] = []
        for label in self._chain:
            c = self._builders[label].flush()
            if c is not None:
                flushed.append(c)
        return flushed

    def get_builder(self, timeframe: Timeframe) -> CandleBuilder | None:
        return self._builders.get(timeframe.label)
