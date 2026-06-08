"""Tests for _seed_from_redis retry-with-backoff logic in startup/candle_seeding.py."""

from __future__ import annotations

from types import SimpleNamespace
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
    bus.get_warmup_bar_count = MagicMock(side_effect=lambda _symbol, _tf: 30 if call_count["n"] >= ready_after else 0)
    bus.get_candles = MagicMock(return_value=[])

    async def fake_load():
        call_count["n"] += 1

    consumer = AsyncMock()
    consumer.load_candle_history = AsyncMock(side_effect=fake_load)

    return bus, consumer, call_count


def _make_threshold_bus(counts_by_attempt: list[int]):
    """Return a bus mock that reports H1 count from ``counts_by_attempt``."""
    call_count = {"n": 0}

    def _current_count() -> int:
        idx = min(max(call_count["n"] - 1, 0), len(counts_by_attempt) - 1)
        return counts_by_attempt[idx]

    def check_warmup(symbol: str, min_bars: dict[str, int]) -> dict[str, Any]:
        have = _current_count()
        need = int(min_bars.get("H1", 30))
        missing = max(0, need - have)
        return {
            "ready": missing == 0,
            "bars": {"H1": have},
            "required": {"H1": need},
            "missing": {} if missing == 0 else {"H1": missing},
        }

    bus = MagicMock()
    bus.check_warmup = MagicMock(side_effect=check_warmup)
    bus.get_warmup_bar_count = MagicMock(side_effect=lambda _symbol, _tf: _current_count())
    bus.get_candles = MagicMock(return_value=[])

    async def fake_load():
        call_count["n"] += 1

    consumer = AsyncMock()
    consumer.load_candle_history = AsyncMock(side_effect=fake_load)
    return bus, consumer


@pytest.mark.asyncio
async def test_seed_succeeds_first_try(monkeypatch: pytest.MonkeyPatch) -> None:
    """Data available on first attempt — no retries needed."""
    bus, consumer, _ = _make_bus_mock(ready_after=0)

    monkeypatch.setenv("ENGINE_WARMUP_MAX_RETRIES", "3")
    monkeypatch.setenv("ENGINE_WARMUP_RETRY_DELAY_SEC", "0")

    with (
        patch("context.redis_consumer.RedisConsumer", return_value=consumer),
        patch("context.live_context_bus.LiveContextBus", return_value=bus),
        patch("infrastructure.redis_client.get_client", new=AsyncMock(return_value=MagicMock())),
        patch("core.redis_consumer_fix.sanitize_redis_keys", new=AsyncMock()),
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
        patch("infrastructure.redis_client.get_client", new=AsyncMock(return_value=MagicMock())),
        patch("core.redis_consumer_fix.sanitize_redis_keys", new=AsyncMock()),
        patch("infrastructure.redis_url.get_redis_url", return_value="redis://localhost"),
    ):
        from startup.candle_seeding import _seed_from_redis

        await _seed_from_redis(_TEST_PAIRS)

    # Should have called load 3 times (failed twice, succeeded on third)
    assert consumer.load_candle_history.await_count == 3


@pytest.mark.asyncio
async def test_seed_waits_for_configured_h1_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    """Redis seeding should not release analysis at 28/30 H1 bars."""
    bus, consumer = _make_threshold_bus([28, 28, 30])

    monkeypatch.setenv("ENGINE_WARMUP_MAX_RETRIES", "5")
    monkeypatch.setenv("ENGINE_WARMUP_RETRY_DELAY_SEC", "0")

    with (
        patch("context.redis_consumer.RedisConsumer", return_value=consumer),
        patch("context.live_context_bus.LiveContextBus", return_value=bus),
        patch("infrastructure.redis_client.get_client", new=AsyncMock(return_value=MagicMock())),
        patch("core.redis_consumer_fix.sanitize_redis_keys", new=AsyncMock()),
        patch("infrastructure.redis_url.get_redis_url", return_value="redis://localhost"),
    ):
        from startup.candle_seeding import _seed_from_redis

        result = await _seed_from_redis(_TEST_PAIRS, {"H1": 30})

    assert result["status"] == "ok"
    assert consumer.load_candle_history.await_count == 3


@pytest.mark.asyncio
async def test_seed_exhausts_retries_degraded_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Redis never has data — function still completes (degraded mode, no crash)."""
    bus, consumer, _ = _make_bus_mock(ready_after=999)  # never ready

    monkeypatch.setenv("ENGINE_WARMUP_MAX_RETRIES", "3")
    monkeypatch.setenv("ENGINE_WARMUP_RETRY_DELAY_SEC", "0")
    monkeypatch.setenv("ENGINE_WARMUP_PG_RECOVERY_ENABLED", "false")

    with (
        patch("context.redis_consumer.RedisConsumer", return_value=consumer),
        patch("context.live_context_bus.LiveContextBus", return_value=bus),
        patch("infrastructure.redis_client.get_client", new=AsyncMock(return_value=MagicMock())),
        patch("core.redis_consumer_fix.sanitize_redis_keys", new=AsyncMock()),
        patch("infrastructure.redis_url.get_redis_url", return_value="redis://localhost"),
    ):
        from startup.candle_seeding import _seed_from_redis

        # Must not raise — degraded mode
        await _seed_from_redis(_TEST_PAIRS)

    # All retries exhausted
    assert consumer.load_candle_history.await_count == 3


@pytest.mark.asyncio
async def test_seed_tries_postgres_recovery_before_exhausting_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """PostgreSQL recovery should not wait for the full Redis retry budget."""
    pg_restored = {"done": False}

    def check_warmup(_symbol: str, _min_bars: dict[str, int]) -> dict[str, Any]:
        return {"ready": pg_restored["done"]}

    bus = MagicMock()
    bus.check_warmup = MagicMock(side_effect=check_warmup)
    bus.get_warmup_bar_count = MagicMock(side_effect=lambda _symbol, _tf: 30 if pg_restored["done"] else 0)
    bus.get_candles = MagicMock(return_value=[])

    consumer = AsyncMock()
    consumer.load_candle_history = AsyncMock()

    async def fake_pg_restore(_pairs: list[str], _bus: Any) -> int:
        pg_restored["done"] = True
        return 4

    monkeypatch.setenv("ENGINE_WARMUP_MAX_RETRIES", "10")
    monkeypatch.setenv("ENGINE_WARMUP_RETRY_DELAY_SEC", "0")
    monkeypatch.setenv("ENGINE_WARMUP_PG_RECOVERY_AFTER_RETRIES", "2")

    from startup import candle_seeding

    pg_restore = AsyncMock(side_effect=fake_pg_restore)
    with (
        patch("context.redis_consumer.RedisConsumer", return_value=consumer),
        patch("context.live_context_bus.LiveContextBus", return_value=bus),
        patch("infrastructure.redis_client.get_client", new=AsyncMock(return_value=MagicMock())),
        patch("core.redis_consumer_fix.sanitize_redis_keys", new=AsyncMock()),
        patch("infrastructure.redis_url.get_redis_url", return_value="redis://localhost"),
        patch.object(candle_seeding, "_try_restore_from_postgres", new=pg_restore),
    ):
        result = await candle_seeding._seed_from_redis(_TEST_PAIRS, {"H1": 30})

    assert result == {
        "source": "postgres_fallback",
        "seeded_pairs": len(_TEST_PAIRS),
        "attempts": 2,
        "status": "recovered",
    }
    assert consumer.load_candle_history.await_count == 2
    pg_restore.assert_awaited_once_with(_TEST_PAIRS, bus)


@pytest.mark.asyncio
async def test_seed_allows_quorum_start_when_two_symbols_remain_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    """28/30 ready symbols should not stall the whole engine until retry 60."""
    pairs = [f"SYM{i:02d}" for i in range(30)]
    ready_pairs = set(pairs[:28])

    def check_warmup(symbol: str, _min_bars: dict[str, int]) -> dict[str, Any]:
        return {"ready": symbol in ready_pairs}

    bus = MagicMock()
    bus.check_warmup = MagicMock(side_effect=check_warmup)
    bus.get_warmup_bar_count = MagicMock(side_effect=lambda symbol, _tf: 30 if symbol in ready_pairs else 0)
    bus.get_candles = MagicMock(return_value=[])

    consumer = AsyncMock()
    consumer.load_candle_history = AsyncMock()

    monkeypatch.setenv("ENGINE_WARMUP_MAX_RETRIES", "60")
    monkeypatch.setenv("ENGINE_WARMUP_RETRY_DELAY_SEC", "0")
    monkeypatch.setenv("ENGINE_WARMUP_PG_RECOVERY_AFTER_RETRIES", "2")
    monkeypatch.setenv("ENGINE_WARMUP_PARTIAL_START_AFTER_RETRIES", "2")
    monkeypatch.setenv("ENGINE_WARMUP_QUORUM_RATIO", "0.90")

    from startup import candle_seeding

    pg_restore = AsyncMock(return_value=0)
    with (
        patch("context.redis_consumer.RedisConsumer", return_value=consumer),
        patch("context.live_context_bus.LiveContextBus", return_value=bus),
        patch("infrastructure.redis_client.get_client", new=AsyncMock(return_value=MagicMock())),
        patch("core.redis_consumer_fix.sanitize_redis_keys", new=AsyncMock()),
        patch("infrastructure.redis_url.get_redis_url", return_value="redis://localhost"),
        patch.object(candle_seeding, "_try_restore_from_postgres", new=pg_restore),
    ):
        result = await candle_seeding._seed_from_redis(pairs, {"H1": 30})

    assert result == {
        "source": "redis",
        "seeded_pairs": 28,
        "attempts": 2,
        "status": "partial",
        "blocked_pairs": ["SYM28", "SYM29"],
    }
    assert consumer.load_candle_history.await_count == 2
    pg_restore.assert_awaited_once_with(pairs, bus)


@pytest.mark.asyncio
async def test_rest_top_up_repairs_missing_h1(monkeypatch: pytest.MonkeyPatch) -> None:
    """Engine startup can repair Redis seed shortfalls before analysis starts."""
    from startup.candle_seeding import _top_up_missing_from_hybrid_provider

    bus = MagicMock()
    bus.check_warmup = MagicMock(
        return_value={
            "ready": False,
            "bars": {"H1": 28},
            "required": {"H1": 30},
            "missing": {"H1": 2},
        }
    )
    bus.get_warmup_bar_count = MagicMock(return_value=28)
    bus.get_candles = MagicMock(return_value=[])
    bus.set_candle_history = MagicMock()

    fake_provider = MagicMock()
    fake_provider.fetch = AsyncMock(
        return_value=SimpleNamespace(
            candles=[{"symbol": "XAGUSD", "timeframe": "H1", "close": 30.0}] * 50,
            provider="twelve_data",
            reason="substitute_first",
            attempts=("twelve_data",),
        )
    )

    with patch("ingest.hybrid_candle_provider.HybridCandleProvider", return_value=fake_provider):
        repaired = await _top_up_missing_from_hybrid_provider(["XAGUSD"], {"H1": 30}, bus)

    assert repaired == 1
    fake_provider.fetch.assert_awaited_once_with("XAGUSD", "H1", 50)
    bus.set_candle_history.assert_called_once()
