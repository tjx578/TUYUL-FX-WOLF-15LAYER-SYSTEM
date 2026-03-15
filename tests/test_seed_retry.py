"""Tests for _seed_from_redis retry-with-backoff logic in startup/candle_seeding.py."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Minimal PAIRS list used by the module under test
_TEST_PAIRS = ["EURUSD", "GBPUSD"]


def _make_bus_mock(ready_after: int):
    """Return a LiveContextBus mock whose check_warmup returns ready after N calls.

    `ready_after` = number of load_candle_history invocations before data appears.
    0 means data is available on the first attempt.
    """
    call_count = {"n": 0}

    def check_warmup(symbol: str, min_bars: dict[str, int]) -> dict[str, Any]:
        if call_count["n"] >= ready_after:
            return {"ready": True}
        return {"ready": False}

    bus = MagicMock()
    bus.check_warmup = MagicMock(side_effect=check_warmup)

    async def fake_load():
        call_count["n"] += 1

    consumer = AsyncMock()
    consumer.load_candle_history = AsyncMock(side_effect=fake_load)

    return bus, consumer, call_count


@pytest.mark.asyncio
async def test_seed_succeeds_first_try(monkeypatch: pytest.MonkeyPatch) -> None:
    """Data available on first attempt — no retries needed."""
    bus, consumer, _ = _make_bus_mock(ready_after=0)

    monkeypatch.setenv("ENGINE_WARMUP_MAX_RETRIES", "3")
    monkeypatch.setenv("ENGINE_WARMUP_RETRY_DELAY_SEC", "0")

    with (
        patch("context.redis_consumer.RedisConsumer", return_value=consumer),
        patch("context.live_context_bus.LiveContextBus", return_value=bus),
        patch("infrastructure.redis_url.get_redis_url", return_value="redis://localhost"),
    ):
        from startup.candle_seeding import _seed_from_redis

        await _seed_from_redis(_TEST_PAIRS)

    # load_candle_history called exactly once
    assert consumer.load_candle_history.await_count == 1


@pytest.mark.asyncio
async def test_seed_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Data appears on attempt 3 — first 2 attempts see empty Redis."""
    bus, consumer, _ = _make_bus_mock(ready_after=3)

    monkeypatch.setenv("ENGINE_WARMUP_MAX_RETRIES", "5")
    monkeypatch.setenv("ENGINE_WARMUP_RETRY_DELAY_SEC", "0")  # no actual wait in tests

    with (
        patch("context.redis_consumer.RedisConsumer", return_value=consumer),
        patch("context.live_context_bus.LiveContextBus", return_value=bus),
        patch("infrastructure.redis_url.get_redis_url", return_value="redis://localhost"),
    ):
        from startup.candle_seeding import _seed_from_redis

        await _seed_from_redis(_TEST_PAIRS)

    # Should have called load 3 times (failed twice, succeeded on third)
    assert consumer.load_candle_history.await_count == 3


@pytest.mark.asyncio
async def test_seed_exhausts_retries_degraded_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Redis never has data — function still completes (degraded mode, no crash)."""
    bus, consumer, _ = _make_bus_mock(ready_after=999)  # never ready

    monkeypatch.setenv("ENGINE_WARMUP_MAX_RETRIES", "3")
    monkeypatch.setenv("ENGINE_WARMUP_RETRY_DELAY_SEC", "0")

    with (
        patch("context.redis_consumer.RedisConsumer", return_value=consumer),
        patch("context.live_context_bus.LiveContextBus", return_value=bus),
        patch("infrastructure.redis_url.get_redis_url", return_value="redis://localhost"),
    ):
        from startup.candle_seeding import _seed_from_redis

        # Must not raise — degraded mode
        await _seed_from_redis(_TEST_PAIRS)

    # All retries exhausted
    assert consumer.load_candle_history.await_count == 3
