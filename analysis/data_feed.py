"""
Real-time data feed adapter for TUYUL FX analysis pipeline.
Supports multiple broker backends with staleness detection.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


class FeedStatus(Enum):
    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"
    STALE = "STALE"
    RECONNECTING = "RECONNECTING"


@dataclass
class Tick:
    symbol: str
    bid: float
    ask: float
    timestamp: float  # Unix epoch
    volume: float | None = None

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread_pips(self) -> float:
        """Spread in pips (assumes 5-digit pricing for FX)."""
        return (self.ask - self.bid) * 10_000


@dataclass
class CandleBar:
    symbol: str
    timeframe: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    timestamp: float
    is_closed: bool = False


@dataclass
class FeedHealth:
    status: FeedStatus
    last_tick_time: float
    latency_ms: float
    symbols_active: list[str] = field(default_factory=list)
    staleness_seconds: float = 0.0

    @property
    def is_healthy(self) -> bool:
        return self.status == FeedStatus.CONNECTED and self.staleness_seconds < 5.0


class DataFeedAdapter(ABC):
    """Abstract base for all broker data feed connections."""

    @abstractmethod
    async def connect(self) -> bool: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def subscribe(self, symbols: list[str], timeframes: list[str]) -> None: ...

    @abstractmethod
    def get_health(self) -> FeedHealth: ...


class StalenessGuard:
    """Detects when data feed goes stale -- prevents analysis on old data."""

    def __init__(self, max_stale_seconds: float = 5.0):
        self._max_stale = max_stale_seconds
        self._last_tick: dict[str, float] = {}

    def update(self, symbol: str) -> None:
        self._last_tick[symbol] = time.time()

    def is_stale(self, symbol: str) -> bool:
        last = self._last_tick.get(symbol)
        if last is None:
            return True
        return (time.time() - last) > self._max_stale

    def staleness(self, symbol: str) -> float:
        last = self._last_tick.get(symbol)
        if last is None:
            return float("inf")
        return time.time() - last

    def all_stale_symbols(self) -> list[str]:
        return [s for s in self._last_tick if self.is_stale(s)]


class FallbackTickFeedAdapter:
    """Manages a priority chain of DataFeedAdapter instances.

    When the primary feed disconnects or goes stale, automatically
    promotes the next healthy adapter in the chain.  This closes the
    single-data-source gap — if Finnhub is down the system can
    transparently fail over to an MT5 or other adapter.

    Zone: analysis/ — pure read-only feed management, no execution.
    """

    def __init__(
        self,
        adapters: list[DataFeedAdapter],
        *,
        max_stale_seconds: float = 10.0,
        failover_cooldown_seconds: float = 30.0,
    ) -> None:
        if not adapters:
            raise ValueError("FallbackTickFeedAdapter requires at least one adapter")
        self._adapters = adapters
        self._active_index: int = 0
        self._max_stale = max_stale_seconds
        self._cooldown = failover_cooldown_seconds
        self._last_failover: float = 0.0
        self._staleness = StalenessGuard(max_stale_seconds=max_stale_seconds)

    @property
    def active_adapter(self) -> DataFeedAdapter:
        return self._adapters[self._active_index]

    @property
    def active_index(self) -> int:
        return self._active_index

    def get_health(self) -> FeedHealth:
        return self.active_adapter.get_health()

    async def connect(self) -> bool:
        """Try connecting each adapter in order; return True on first success."""
        for i, adapter in enumerate(self._adapters):
            try:
                ok = await adapter.connect()
                if ok:
                    self._active_index = i
                    return True
            except Exception:
                continue
        return False

    async def disconnect(self) -> None:
        for adapter in self._adapters:
            with contextlib.suppress(Exception):
                await adapter.disconnect()

    async def subscribe(self, symbols: list[str], timeframes: list[str]) -> None:
        await self.active_adapter.subscribe(symbols, timeframes)

    def check_failover(self) -> bool:
        """Check active adapter health and failover if stale/disconnected.

        Returns True if a failover occurred.
        """
        now = time.time()
        if now - self._last_failover < self._cooldown:
            return False

        health = self.active_adapter.get_health()
        if health.is_healthy:
            return False

        # Try next adapter
        for offset in range(1, len(self._adapters)):
            candidate_idx = (self._active_index + offset) % len(self._adapters)
            candidate = self._adapters[candidate_idx]
            candidate_health = candidate.get_health()
            if candidate_health.status == FeedStatus.CONNECTED:
                self._active_index = candidate_idx
                self._last_failover = now
                return True

        return False

    def adapter_names(self) -> list[str]:
        return [type(a).__name__ for a in self._adapters]


class MT5DataFeed(DataFeedAdapter):
    """
    MetaTrader 5 data feed adapter via MetaTrader5 Python package.
    This is the primary adapter for live trading with MT5 brokers.
    """

    def __init__(self, login: int, password: str, server: str, path: str | None = None):
        self._login = login
        self._password = password
        self._server = server
        self._path = path
        self._connected = False
        self._staleness = StalenessGuard()
        self._subscribers: list[Callable[[Tick], None]] = []
        self._candle_subscribers: list[Callable[[CandleBar], None]] = []
        self._symbols: list[str] = []
        self._running = False

    async def connect(self) -> bool:
        try:
            import MetaTrader5 as mt5  # noqa: N813, PLC0415  # pyright: ignore[reportMissingImports]
        except ImportError:
            raise ImportError(  # noqa: B904
                "MetaTrader5 package not installed. Install with: pip install MetaTrader5"
            )

        init_kwargs = {}
        if self._path:
            init_kwargs["path"] = self._path

        if not mt5.initialize(**init_kwargs):
            return False

        authorized = mt5.login(
            login=self._login,
            password=self._password,
            server=self._server,
        )
        self._connected = bool(authorized)
        return self._connected

    async def disconnect(self) -> None:
        with contextlib.suppress(Exception):
            import MetaTrader5 as mt5  # noqa: N813, PLC0415  # pyright: ignore[reportMissingImports]

            mt5.shutdown()
        self._connected = False
        self._running = False

    async def subscribe(self, symbols: list[str], timeframes: list[str]) -> None:
        import MetaTrader5 as mt5  # noqa: N813, PLC0415  # pyright: ignore[reportMissingImports]

        self._symbols = symbols
        for symbol in symbols:
            mt5.symbol_select(symbol, True)

    def get_health(self) -> FeedHealth:
        max_staleness = 0.0
        for s in self._symbols:
            st = self._staleness.staleness(s)
            max_staleness = max(max_staleness, st)

        status = FeedStatus.CONNECTED if self._connected else FeedStatus.DISCONNECTED
        if self._connected and max_staleness > 5.0:
            status = FeedStatus.STALE

        return FeedHealth(
            status=status,
            last_tick_time=time.time(),
            latency_ms=0.0,  # TODO: measure actual latency
            symbols_active=self._symbols,
            staleness_seconds=max_staleness,
        )

    def on_tick(self, callback: Callable[[Tick], None]) -> None:
        self._subscribers.append(callback)

    def on_candle(self, callback: Callable[[CandleBar], None]) -> None:
        self._candle_subscribers.append(callback)

    async def poll_loop(self, interval: float = 0.1) -> None:
        """
        Poll MT5 for ticks. MT5 Python API is synchronous/poll-based,
        so we poll in an async loop.
        """
        import MetaTrader5 as mt5  # noqa: N813, PLC0415  # pyright: ignore[reportMissingImports]

        self._running = True
        while self._running:
            for symbol in self._symbols:
                tick = mt5.symbol_info_tick(symbol)
                if tick is not None:
                    t = Tick(
                        symbol=symbol,
                        bid=tick.bid,
                        ask=tick.ask,
                        timestamp=tick.time,
                        volume=getattr(tick, "volume_real", None),
                    )
                    self._staleness.update(symbol)
                    for cb in self._subscribers:
                        with contextlib.suppress(Exception):
                            cb(t)
            await asyncio.sleep(interval)
