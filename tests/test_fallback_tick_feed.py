"""Tests for FallbackTickFeedAdapter — failover chain for data feed adapters."""

from __future__ import annotations

import time

import pytest

from analysis.data_feed import (
    DataFeedAdapter,
    FallbackTickFeedAdapter,
    FeedHealth,
    FeedStatus,
)


class _FakeFeed(DataFeedAdapter):
    """Controllable fake adapter for testing."""

    def __init__(self, name: str, *, healthy: bool = True) -> None:
        self.name = name
        self._healthy = healthy
        self._connected = healthy

    async def connect(self) -> bool:
        return self._healthy

    async def disconnect(self) -> None:
        self._connected = False

    async def subscribe(self, symbols: list[str], timeframes: list[str]) -> None:
        pass

    def get_health(self) -> FeedHealth:
        status = FeedStatus.CONNECTED if self._healthy else FeedStatus.DISCONNECTED
        return FeedHealth(
            status=status,
            last_tick_time=time.time(),
            latency_ms=1.0,
            symbols_active=[],
            staleness_seconds=0.0 if self._healthy else 999.0,
        )

    def set_healthy(self, healthy: bool) -> None:
        self._healthy = healthy


class TestFallbackTickFeedAdapter:
    """Tests for the multi-adapter failover chain."""

    def test_requires_at_least_one_adapter(self) -> None:
        with pytest.raises(ValueError, match="at least one"):
            FallbackTickFeedAdapter([])

    def test_active_adapter_defaults_to_first(self) -> None:
        a = _FakeFeed("primary")
        b = _FakeFeed("secondary")
        chain = FallbackTickFeedAdapter([a, b])
        assert chain.active_index == 0
        assert chain.active_adapter is a

    @pytest.mark.asyncio
    async def test_connect_uses_first_available(self) -> None:
        a = _FakeFeed("primary", healthy=False)
        b = _FakeFeed("secondary", healthy=True)
        chain = FallbackTickFeedAdapter([a, b])
        ok = await chain.connect()
        assert ok is True
        assert chain.active_index == 1

    @pytest.mark.asyncio
    async def test_connect_all_fail(self) -> None:
        a = _FakeFeed("primary", healthy=False)
        b = _FakeFeed("secondary", healthy=False)
        chain = FallbackTickFeedAdapter([a, b])
        ok = await chain.connect()
        assert ok is False

    def test_check_failover_when_primary_down(self) -> None:
        a = _FakeFeed("primary", healthy=True)
        b = _FakeFeed("secondary", healthy=True)
        chain = FallbackTickFeedAdapter([a, b], failover_cooldown_seconds=0.0)
        assert chain.active_index == 0

        # Primary goes down
        a.set_healthy(False)
        failed_over = chain.check_failover()
        assert failed_over is True
        assert chain.active_index == 1

    def test_check_failover_respects_cooldown(self) -> None:
        a = _FakeFeed("primary", healthy=True)
        b = _FakeFeed("secondary", healthy=True)
        chain = FallbackTickFeedAdapter([a, b], failover_cooldown_seconds=60.0)

        a.set_healthy(False)
        # First failover succeeds
        assert chain.check_failover() is True
        # Second failover blocked by cooldown
        b.set_healthy(False)
        assert chain.check_failover() is False

    def test_check_failover_no_healthy_candidate(self) -> None:
        a = _FakeFeed("primary", healthy=False)
        b = _FakeFeed("secondary", healthy=False)
        chain = FallbackTickFeedAdapter([a, b], failover_cooldown_seconds=0.0)
        assert chain.check_failover() is False

    def test_healthy_primary_no_failover(self) -> None:
        a = _FakeFeed("primary", healthy=True)
        b = _FakeFeed("secondary", healthy=True)
        chain = FallbackTickFeedAdapter([a, b], failover_cooldown_seconds=0.0)
        assert chain.check_failover() is False
        assert chain.active_index == 0

    def test_adapter_names(self) -> None:
        a = _FakeFeed("primary")
        b = _FakeFeed("secondary")
        chain = FallbackTickFeedAdapter([a, b])
        assert chain.adapter_names() == ["_FakeFeed", "_FakeFeed"]

    @pytest.mark.asyncio
    async def test_disconnect_all(self) -> None:
        a = _FakeFeed("primary")
        b = _FakeFeed("secondary")
        chain = FallbackTickFeedAdapter([a, b])
        await chain.disconnect()
        assert a._connected is False
        assert b._connected is False

    def test_get_health_delegates(self) -> None:
        a = _FakeFeed("primary", healthy=True)
        chain = FallbackTickFeedAdapter([a])
        health = chain.get_health()
        assert health.status == FeedStatus.CONNECTED
        assert health.is_healthy is True
