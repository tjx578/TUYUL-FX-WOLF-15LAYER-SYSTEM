"""
CandleBuilder -- Multi-Timeframe Candle Construction

Build Strategy:
  - M15 & H1: Built real-time from tick stream (Finnhub Premium WebSocket)
  - H4, D1, W1, MN: Fetched from REST API (Finnhub /forex/candle)

No execution side-effects. Pure analysis module.
"""

from __future__ import annotations

import logging
import math
import time

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Optional
from urllib import parse, request
from urllib.error import URLError

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

class Timeframe(Enum):
    M15 = "M15"
    H1 = "H1"
    H4 = "H4"
    D1 = "D1"
    W1 = "W1"
    MN = "MN"

    @property
    def is_tick_built(self) -> bool:
        """True if this TF is built from tick stream."""
        return self in (Timeframe.M15, Timeframe.H1)

    @property
    def is_rest_fetched(self) -> bool:
        """True if this TF is fetched from REST API."""
        return self in (Timeframe.H4, Timeframe.D1, Timeframe.W1, Timeframe.MN)

    @property
    def seconds(self) -> int:
        """Duration of one candle in seconds."""
        _map = {
            Timeframe.M15: 15 * 60,
            Timeframe.H1: 60 * 60,
            Timeframe.H4: 4 * 60 * 60,
            Timeframe.D1: 24 * 60 * 60,
            Timeframe.W1: 7 * 24 * 60 * 60,
            Timeframe.MN: 30 * 24 * 60 * 60,  # approximate
        }
        return _map[self]

    @property
    def finnhub_resolution(self) -> str:
        """Finnhub REST API resolution string."""
        _map = {
            Timeframe.M15: "15",
            Timeframe.H1: "60",
            Timeframe.H4: "240",      # Finnhub premium
            Timeframe.D1: "D",
            Timeframe.W1: "W",
            Timeframe.MN: "M",
        }
        return _map[self]


@dataclass
class Candle:
    """Immutable OHLCV candle."""
    symbol: str
    timeframe: Timeframe
    timestamp: float          # UTC epoch -- candle open time
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    tick_count: int = 0
    is_closed: bool = False

    @property
    def datetime_utc(self) -> datetime:
        return datetime.fromtimestamp(self.timestamp, tz=UTC)

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe.value,
            "timestamp": self.timestamp,
            "datetime": self.datetime_utc.isoformat(),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "tick_count": self.tick_count,
            "is_closed": self.is_closed,
        }


@dataclass
class Tick:
    """Single price tick from WebSocket."""
    symbol: str
    price: float
    volume: float
    timestamp: float  # epoch ms from Finnhub, converted to seconds


# ---------------------------------------------------------------------------
# Tick-Built Candle Builder (M15 & H1)
# ---------------------------------------------------------------------------

class TickCandleBuilder:
    """
    Builds M15 and H1 candles from a real-time tick stream.

    One instance per (symbol, timeframe). Aligns candle boundaries to
    clean UTC intervals (e.g. H1 starts at :00, M15 at :00/:15/:30/:45).

    Usage:
        builder = TickCandleBuilder("OANDA:EUR_USD", Timeframe.M15)
        closed_candle = builder.on_tick(tick)
        if closed_candle:
            # emit / store the completed candle
    """

    def __init__(
        self,
        symbol: str,
        timeframe: Timeframe,
        on_candle_closed: Callable[[Candle], None] | None = None,
    ):
        if not timeframe.is_tick_built:
            raise ValueError(
                f"{timeframe.value} is not tick-built. "
                f"Only M15 and H1 are built from tick stream."
            )
        self.symbol = symbol
        self.timeframe = timeframe
        self.on_candle_closed = on_candle_closed

        self._current: Candle | None = None
        self._current_boundary: float = 0.0  # epoch of current candle open
        self._next_boundary: float = 0.0     # epoch when current candle closes

    # -- boundary alignment ------------------------------------------------

    @staticmethod
    def _align_to_interval(epoch: float, interval_seconds: int) -> float:
        """Floor-align an epoch timestamp to the nearest interval boundary."""
        return math.floor(epoch / interval_seconds) * interval_seconds

    def _compute_boundaries(self, tick_epoch: float) -> tuple[float, float]:
        """Return (candle_open_epoch, candle_close_epoch) for this tick."""
        interval = self.timeframe.seconds
        open_ts = self._align_to_interval(tick_epoch, interval)
        close_ts = open_ts + interval
        return open_ts, close_ts

    # -- tick ingestion ----------------------------------------------------

    def on_tick(self, tick: Tick) -> Optional[Candle]:  # noqa: UP045
        """
        Ingest a tick. Returns a *closed* Candle if the tick crossed a boundary,
        otherwise returns None.

        The closed candle is also dispatched via `on_candle_closed` callback
        if one was provided.
        """
        if tick.symbol != self.symbol:
            return None

        tick_epoch = tick.timestamp
        closed_candle: Candle | None = None

        # Check if tick falls outside current candle window
        if self._current is not None and tick_epoch >= self._next_boundary:
            # Close the current candle
            closed_candle = self._close_current()

        # If no current candle, start a new one
        if self._current is None:
            self._start_new_candle(tick)
        else:
            # Update current candle with tick
            self._update_candle(tick)

        return closed_candle

    def force_close(self) -> Candle | None:
        """
        Force-close the current candle (e.g. on disconnect / market close).
        Returns the closed candle or None.
        """
        if self._current is not None:
            return self._close_current()
        return None

    @property
    def current_candle(self) -> Candle | None:
        """Peek at the in-progress candle (not yet closed)."""
        return self._current

    # -- internal ----------------------------------------------------------

    def _start_new_candle(self, tick: Tick) -> None:
        open_ts, close_ts = self._compute_boundaries(tick.timestamp)
        self._current_boundary = open_ts
        self._next_boundary = close_ts
        self._current = Candle(
            symbol=self.symbol,
            timeframe=self.timeframe,
            timestamp=open_ts,
            open=tick.price,
            high=tick.price,
            low=tick.price,
            close=tick.price,
            volume=tick.volume,
            tick_count=1,
            is_closed=False,
        )
        logger.debug(
            "New %s candle started for %s at %s",
            self.timeframe.value,
            self.symbol,
            datetime.fromtimestamp(open_ts, tz=UTC).isoformat(),
        )

    def _update_candle(self, tick: Tick) -> None:
        c = self._current
        assert c is not None  # noqa: S101
        c.high = max(c.high, tick.price)
        c.low = min(c.low, tick.price)
        c.close = tick.price
        c.volume += tick.volume
        c.tick_count += 1

    def _close_current(self) -> Candle:
        c = self._current
        assert c is not None  # noqa: S101
        c.is_closed = True
        self._current = None

        logger.info(
            "Closed %s candle %s | O=%.5f H=%.5f L=%.5f C=%.5f V=%.1f ticks=%d",
            c.timeframe.value,
            c.symbol,
            c.open, c.high, c.low, c.close,
            c.volume, c.tick_count,
        )

        if self.on_candle_closed:
            self.on_candle_closed(c)

        return c


# ---------------------------------------------------------------------------
# REST Candle Fetcher (H4, D1, W1, MN)
# ---------------------------------------------------------------------------

class RESTCandleFetcher:
    """
    Fetches higher-timeframe candles from Finnhub REST API.

    H4, D1, W1, MN are fetched -- NOT built from ticks -- because:
      - These timeframes don't benefit from tick-by-tick construction.
      - REST gives clean, broker-aligned historical candles.
      - Reduces complexity and memory usage.

    Requires Finnhub premium API key for H4 (resolution "240").
    """

    FINNHUB_CANDLE_URL = "https://finnhub.io/api/v1/forex/candle"

    def __init__(self, api_key: str, rate_limit_delay: float = 0.5):
        if not api_key:
            raise ValueError("Finnhub API key is required for REST candle fetching.")
        self._api_key = api_key
        self._rate_limit_delay = rate_limit_delay

    def fetch_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        from_epoch: int | None = None,
        to_epoch: int | None = None,
        count: int = 200,
    ) -> list[Candle]:
        """
        Fetch candles from Finnhub REST API.

        Args:
            symbol: Finnhub forex symbol (e.g. "OANDA:EUR_USD")
            timeframe: Must be H4, D1, W1, or MN
            from_epoch: Start timestamp (seconds). Defaults to count*interval ago.
            to_epoch: End timestamp (seconds). Defaults to now.
            count: Number of candles if from_epoch not specified.

        Returns:
            List of Candle objects, sorted by timestamp ascending.

        Raises:
            ValueError: If timeframe is tick-built (M15/H1).
            RuntimeError: On API errors.
        """
        if timeframe.is_tick_built:
            raise ValueError(
                f"{timeframe.value} should be built from ticks, not fetched via REST. "
                f"Use TickCandleBuilder for M15 and H1."
            )

        now = int(time.time())
        if to_epoch is None:
            to_epoch = now
        if from_epoch is None:
            from_epoch = to_epoch - (count * timeframe.seconds)

        params = {
            "symbol": symbol,
            "resolution": timeframe.finnhub_resolution,
            "from": from_epoch,
            "to": to_epoch,
            "token": self._api_key,
        }

        # `requests` imported at module level to allow test patching

        logger.info(
            "Fetching %s candles for %s [%s -> %s]",
            timeframe.value,
            symbol,
            datetime.fromtimestamp(from_epoch, tz=UTC).isoformat(),
            datetime.fromtimestamp(to_epoch, tz=UTC).isoformat(),
        )

        try:
            query_string = parse.urlencode(params)
            url = f"{self.FINNHUB_CANDLE_URL}?{query_string}"
            resp = request.urlopen(url, timeout=15)  # noqa: S310
        except URLError as exc:
            raise RuntimeError(
                f"Finnhub REST request failed for {symbol} {timeframe.value}: {exc}"
            ) from exc

        data = resp.json()

        if data.get("s") == "no_data":
            logger.warning("No data returned for %s %s", symbol, timeframe.value)
            return []

        if data.get("s") != "ok":
            raise RuntimeError(
                f"Finnhub returned unexpected status for {symbol} {timeframe.value}: "
                f"{data.get('s', 'unknown')}. Response: {data}"
            )

        candles: list[Candle] = []
        timestamps = data.get("t", [])
        opens = data.get("o", [])
        highs = data.get("h", [])
        lows = data.get("l", [])
        closes = data.get("c", [])
        volumes = data.get("v", [])

        for i in range(len(timestamps)):
            candles.append(Candle(  # noqa: PERF401
                symbol=symbol,
                timeframe=timeframe,
                timestamp=float(timestamps[i]),
                open=opens[i],
                high=highs[i],
                low=lows[i],
                close=closes[i],
                volume=volumes[i] if i < len(volumes) else 0.0,
                tick_count=0,
                is_closed=True,
            ))

        logger.info(
            "Fetched %d %s candles for %s",
            len(candles), timeframe.value, symbol,
        )

        # Respect rate limit
        time.sleep(self._rate_limit_delay)

        return candles


# ---------------------------------------------------------------------------
# Multi-Timeframe Candle Manager
# ---------------------------------------------------------------------------

class CandleManager:
    """
    Unified manager for all timeframes.

    - M15 & H1: Managed via TickCandleBuilder instances (tick stream)
    - H4, D1, W1, MN: Managed via RESTCandleFetcher (periodic polling)

    This is the single entry point for the analysis pipeline to get candle data.
    """

    # Tick-built timeframes
    TICK_TIMEFRAMES = (Timeframe.M15, Timeframe.H1)
    # REST-fetched timeframes
    REST_TIMEFRAMES = (Timeframe.H4, Timeframe.D1, Timeframe.W1, Timeframe.MN)

    def __init__(
        self,
        symbols: list[str],
        api_key: str,
        on_candle_closed: Callable[[Candle], None] | None = None,
    ):
        self._symbols = symbols
        self._on_candle_closed = on_candle_closed

        # Tick builders: (symbol, timeframe) -> TickCandleBuilder
        self._tick_builders: dict[tuple[str, Timeframe], TickCandleBuilder] = {}
        for symbol in symbols:
            for tf in self.TICK_TIMEFRAMES:
                key = (symbol, tf)
                self._tick_builders[key] = TickCandleBuilder(
                    symbol=symbol,
                    timeframe=tf,
                    on_candle_closed=on_candle_closed,
                )

        # REST fetcher
        self._rest_fetcher = RESTCandleFetcher(api_key=api_key)

        # Candle history cache: (symbol, timeframe) -> list[Candle]
        self._candle_history: dict[tuple[str, Timeframe], list[Candle]] = {}

        logger.info(
            "CandleManager initialized -- symbols=%s, tick_tf=%s, rest_tf=%s",
            symbols,
            [tf.value for tf in self.TICK_TIMEFRAMES],
            [tf.value for tf in self.REST_TIMEFRAMES],
        )

    # -- Tick ingestion (M15 & H1) -----------------------------------------

    def on_tick(self, tick: Tick) -> list[Candle]:
        """
        Feed a tick into all tick-built builders for that symbol.
        Returns list of any candles that closed.
        """
        closed: list[Candle] = []
        for tf in self.TICK_TIMEFRAMES:
            key = (tick.symbol, tf)
            builder = self._tick_builders.get(key)
            if builder is None:
                continue
            result = builder.on_tick(tick)
            if result is not None:
                self._append_to_history(result)
                closed.append(result)
        return closed

    # -- REST fetch (H4, D1, W1, MN) --------------------------------------

    def fetch_rest_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        count: int = 200,
    ) -> list[Candle]:
        """
        Fetch higher-TF candles from REST API and cache them.
        """
        if timeframe.is_tick_built:
            raise ValueError(
                f"Use on_tick() for {timeframe.value}, not REST fetch."
            )
        candles = self._rest_fetcher.fetch_candles(
            symbol=symbol,
            timeframe=timeframe,
            count=count,
        )
        key = (symbol, timeframe)
        self._candle_history[key] = candles
        return candles

    def fetch_all_rest(self, count: int = 200) -> dict[tuple[str, Timeframe], list[Candle]]:
        """
        Fetch all REST timeframes for all symbols. Returns the full result dict.
        """
        results: dict[tuple[str, Timeframe], list[Candle]] = {}
        for symbol in self._symbols:
            for tf in self.REST_TIMEFRAMES:
                candles = self.fetch_rest_candles(symbol, tf, count=count)
                results[(symbol, tf)] = candles
        return results

    # -- Candle access -----------------------------------------------------

    def get_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        count: int | None = None,
    ) -> list[Candle]:
        """
        Get cached candles for a symbol + timeframe.
        For tick-built TFs this includes closed candles accumulated so far.
        """
        key = (symbol, timeframe)
        history = self._candle_history.get(key, [])
        if count is not None:
            return history[-count:]
        return list(history)

    def get_current_candle(
        self,
        symbol: str,
        timeframe: Timeframe,
    ) -> Candle | None:
        """
        Get the in-progress (not yet closed) candle for tick-built TFs.
        Returns None for REST TFs or if no candle is in progress.
        """
        key = (symbol, timeframe)
        builder = self._tick_builders.get(key)
        if builder is None:
            return None
        return builder.current_candle

    # -- Internal ----------------------------------------------------------

    def _append_to_history(self, candle: Candle) -> None:
        key = (candle.symbol, candle.timeframe)
        if key not in self._candle_history:
            self._candle_history[key] = []
        self._candle_history[key].append(candle)

    def force_close_all(self) -> list[Candle]:
        """Force-close all in-progress tick candles (e.g. on shutdown)."""
        closed: list[Candle] = []
        for builder in self._tick_builders.values():
            result = builder.force_close()
            if result is not None:
                self._append_to_history(result)
                closed.append(result)
        return closed
