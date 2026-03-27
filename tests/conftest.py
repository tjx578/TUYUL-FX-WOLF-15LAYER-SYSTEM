"""Shared pytest fixtures and async test infrastructure.

Provides:
- Async event loop fixtures (via pytest-asyncio strict mode)
- Reusable mock factories for Redis, WebSocket, and context bus
- Tick data generators for stress/load tests
- Common test helpers
"""

from __future__ import annotations

import asyncio
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Async helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def event_loop_policy():
    """Use default event loop policy (override when needed)."""
    return asyncio.DefaultEventLoopPolicy()


# ---------------------------------------------------------------------------
# Mock factories
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_redis() -> MagicMock:
    """Pre-configured async Redis mock.

    Provides stub implementations for common Redis operations used by
    leader-election, pub/sub, and pipeline code.
    """
    redis = MagicMock()
    redis.ping = AsyncMock(return_value=True)
    redis.set = AsyncMock(return_value=True)
    redis.get = AsyncMock(return_value=None)
    redis.delete = AsyncMock(return_value=1)
    redis.expire = AsyncMock(return_value=True)
    redis.aclose = AsyncMock()
    redis.publish = AsyncMock(return_value=1)
    redis.close = AsyncMock()
    return redis


@pytest.fixture
def mock_context_bus() -> MagicMock:
    """Mock LiveContextBus with sensible defaults."""
    bus = MagicMock()
    bus.consume_ticks = MagicMock(return_value=[])
    bus.update_candle = MagicMock()
    bus.get = MagicMock(return_value=None)
    bus.set = MagicMock()
    return bus


@pytest.fixture
def mock_websocket() -> AsyncMock:
    """Mock WebSocket connection for Finnhub WS tests.

    The mock supports async iteration (``async for msg in ws``),
    ``send()``, ``close()``, and tracks the ``closed`` property.
    """
    ws = AsyncMock()
    ws.closed = False
    ws.send = AsyncMock()
    ws.close = AsyncMock()
    ws.recv = AsyncMock(return_value='{"type": "ping"}')

    # Support async iteration (empty by default; override __aiter__ in tests)
    ws.__aiter__ = MagicMock(return_value=iter([]))
    return ws


# ---------------------------------------------------------------------------
# Tick data generators
# ---------------------------------------------------------------------------


def generate_ticks(
    symbol: str = "EURUSD",
    count: int = 100,
    *,
    base_price: float = 1.0850,
    spread: float = 0.0002,
    interval_ms: int = 100,
    base_time: datetime | None = None,
) -> list[dict[str, Any]]:
    """Generate realistic tick data for testing.

    Args:
        symbol: Trading pair symbol.
        count: Number of ticks to generate.
        base_price: Starting mid price.
        spread: Bid/ask spread.
        interval_ms: Milliseconds between ticks.
        base_time: Starting timestamp (defaults to 2024-01-15 10:00 UTC).

    Returns:
        List of tick dicts with symbol, bid, ask, timestamp, volume, source.
    """
    import random as _rng  # noqa: PLC0415

    if base_time is None:
        base_time = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)

    ticks: list[dict[str, Any]] = []
    price = base_price
    for i in range(count):
        # Small random walk
        price += _rng.uniform(-0.0003, 0.0003)
        bid = round(price - spread / 2, 5)
        ask = round(price + spread / 2, 5)
        ts = base_time + timedelta(milliseconds=interval_ms * i)
        ticks.append(
            {
                "symbol": symbol,
                "bid": bid,
                "ask": ask,
                "timestamp": ts.timestamp(),
                "volume": _rng.randint(1, 50),
                "source": "test",
            }
        )
    return ticks


@pytest.fixture
def tick_generator():
    """Fixture wrapper around generate_ticks for parametric use."""
    return generate_ticks


# ---------------------------------------------------------------------------
# Timing helper
# ---------------------------------------------------------------------------


class Timer:
    """Simple wall-clock timer for performance assertions."""

    def __init__(self) -> None:
        self._start: float = 0
        self.elapsed: float = 0

    def __enter__(self) -> Timer:
        self._start = time.perf_counter()
        return self

    def __exit__(self, *_: object) -> None:
        self.elapsed = time.perf_counter() - self._start


@pytest.fixture
def timer() -> Timer:
    """Provide a reusable wall-clock timer."""
    return Timer()


@pytest.fixture
def price_watcher():
    """Mock PriceWatcher for tests -- no MT5 dependency."""

    class MockPriceWatcher:
        def __init__(self):
            self._prices: dict = {}
            self._watching: set = set()

        def watch(self, symbol: str):
            self._watching.add(symbol)

        def unwatch(self, symbol: str):
            self._watching.discard(symbol)

        def set_price(self, symbol: str, bid: float, ask: float):
            self._prices[symbol] = {
                "bid": bid,
                "ask": ask,
                "spread": round(ask - bid, 6),
            }

        def get_price(self, symbol: str) -> dict:
            return self._prices.get(symbol, {"bid": 0.0, "ask": 0.0, "spread": 0.0})

        def get_bid(self, symbol: str) -> float:
            return self.get_price(symbol)["bid"]

        def get_ask(self, symbol: str) -> float:
            return self.get_price(symbol)["ask"]

        def get_spread(self, symbol: str) -> float:
            return self.get_price(symbol)["spread"]

        @property
        def watching(self) -> set:
            return self._watching.copy()

        def is_watching(self, symbol: str) -> bool:
            return symbol in self._watching

    watcher = MockPriceWatcher()
    watcher.set_price("EURUSD", 1.08500, 1.08520)
    watcher.set_price("GBPUSD", 1.26100, 1.26130)
    watcher.set_price("USDJPY", 149.500, 149.520)
    watcher.set_price("XAUUSD", 2650.00, 2650.50)
    watcher.set_price("GBPJPY", 188.200, 188.240)
    return watcher
