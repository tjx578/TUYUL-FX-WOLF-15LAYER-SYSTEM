"""Unit tests for ingest_service.py."""

import asyncio
import importlib
import sys
import types
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def ingest_service_module():
    """Load ingest_service with lightweight stubs for heavy dependencies."""
    # Stub WebSocket and other heavy dependencies first
    fake_websockets_module = types.ModuleType("websockets")
    fake_websockets_module.connect = AsyncMock()  # type: ignore[attr-defined]

    fake_candle_module = types.ModuleType("ingest.candle_builder")
    fake_news_module = types.ModuleType("ingest.calendar_news")
    fake_dependencies_module = types.ModuleType("ingest.dependencies")
    fake_macro_module = types.ModuleType("analysis.macro.macro_regime_engine")

    class FakeRunner:
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__()

        async def run(self):
            return None

    class FakeTimeframe:
        M15 = "M15"

    fake_candle_module.CandleBuilder = FakeRunner  # type: ignore[attr-defined]
    fake_candle_module.Timeframe = FakeTimeframe  # type: ignore[attr-defined]
    fake_news_module.CalendarNewsIngestor = FakeRunner  # type: ignore[attr-defined]
    fake_dependencies_module.create_finnhub_ws = AsyncMock()  # type: ignore[attr-defined]
    fake_macro_module.MacroRegimeEngine = MagicMock  # type: ignore[attr-defined]

    with patch.dict(
        sys.modules,
        {
            "websockets": fake_websockets_module,
            "ingest.candle_builder": fake_candle_module,
            "ingest.calendar_news": fake_news_module,
            "ingest.dependencies": fake_dependencies_module,
            "analysis.macro.macro_regime_engine": fake_macro_module,
        },
    ):
        module = importlib.import_module("ingest_service")
        module = importlib.reload(module)
        try:
            yield module
        finally:
            # Ensure no cross-test contamination from a preloaded ingest_service.
            sys.modules.pop("ingest_service", None)


@pytest.mark.asyncio
async def test_run_ingest_services_no_api_key_exits_on_shutdown_event(
    ingest_service_module: Any,
) -> None:
    """No-API-key path should idle until shutdown event is set."""
    ingest_service_module._shutdown_event = asyncio.Event()

    # Start the service as a task with shutdown event unset
    task = asyncio.create_task(ingest_service_module.run_ingest_services(has_api_key=False))

    # Give it a moment to enter the idle loop (increased for CI stability)
    await asyncio.sleep(0.5)

    # Task should still be running (pending)
    assert not task.done(), "Task should be waiting for shutdown event"

    # Now set the shutdown event
    ingest_service_module._shutdown_event.set()

    # Task should complete
    await asyncio.wait_for(task, timeout=2.0)


@pytest.mark.asyncio
async def test_run_ingest_services_closes_redis_when_ping_fails(
    ingest_service_module: Any,
) -> None:
    """Redis client should be closed if setup fails after client creation."""
    fake_redis = MagicMock()
    fake_redis.ping = AsyncMock(side_effect=RuntimeError("ping failed"))
    fake_redis.aclose = AsyncMock()

    with patch.object(ingest_service_module, "_build_redis_client", return_value=fake_redis):  # noqa: SIM117
        with pytest.raises(RuntimeError, match="ping failed"):
            await ingest_service_module.run_ingest_services(has_api_key=True)

    fake_redis.aclose.assert_awaited_once()


# ── M15 cold-start Redis seeding tests ─────────────────────────────


@pytest.mark.asyncio
async def test_cold_start_m15_merges_into_warmup_results(
    ingest_service_module: Any,
) -> None:
    """_cold_start_m15_for_warmup should fetch M15 for each symbol
    and merge candles into warmup_results."""
    fake_fetcher = MagicMock()
    fake_fetcher.context_bus = MagicMock()

    async def fake_fetch(symbol: str, tf: str, bars: int) -> list[dict[str, object]]:
        return [{"symbol": symbol, "timeframe": tf, "close": 1.0}]

    fake_fetcher.fetch = AsyncMock(side_effect=fake_fetch)

    warmup_results: dict[str, dict[str, list[dict[str, object]]]] = {
        "EURUSD": {"H1": [{"close": 1.1}]},
        "GBPUSD": {"H1": [{"close": 1.3}]},
    }

    await ingest_service_module._cold_start_m15_for_warmup(
        fake_fetcher, ["EURUSD", "GBPUSD"], warmup_results, bars=50
    )

    # M15 should now be present for both symbols
    assert "M15" in warmup_results["EURUSD"]
    assert "M15" in warmup_results["GBPUSD"]
    # Existing H1 data must be preserved
    assert "H1" in warmup_results["EURUSD"]
    assert "H1" in warmup_results["GBPUSD"]
    # fetch called once per symbol with M15
    assert fake_fetcher.fetch.await_count == 2
    # context_bus.update_candle called for each candle
    assert fake_fetcher.context_bus.update_candle.call_count == 2


@pytest.mark.asyncio
async def test_cold_start_m15_noop_for_empty_symbols(
    ingest_service_module: Any,
) -> None:
    """Empty symbol list → nothing happens."""
    warmup_results: dict[str, dict[str, list[dict[str, object]]]] = {}
    fake_fetcher = MagicMock()
    fake_fetcher.fetch = AsyncMock()

    await ingest_service_module._cold_start_m15_for_warmup(
        fake_fetcher, [], warmup_results
    )

    fake_fetcher.fetch.assert_not_awaited()
    assert warmup_results == {}


@pytest.mark.asyncio
async def test_seed_redis_includes_m15(
    ingest_service_module: Any,
) -> None:
    """_seed_redis_candle_history must write M15 keys to Redis when present in warmup_results."""
    fake_pipe = MagicMock()
    fake_pipe.rpush = MagicMock()
    fake_pipe.expire = MagicMock()
    fake_pipe.execute = AsyncMock(return_value=[])

    fake_redis = MagicMock()
    fake_redis.pipeline = MagicMock(return_value=fake_pipe)
    fake_redis.llen = AsyncMock(return_value=0)

    warmup_results = {
        "EURUSD": {
            "H1": [{"close": 1.1}],
            "M15": [{"close": 1.2}, {"close": 1.3}],
        }
    }

    await ingest_service_module._seed_redis_candle_history(fake_redis, warmup_results)

    # Collect all rpush calls — should contain both H1 and M15 keys
    rpush_keys = [call.args[0] for call in fake_pipe.rpush.call_args_list]
    assert "wolf15:candle_history:EURUSD:M15" in rpush_keys
    assert "wolf15:candle_history:EURUSD:H1" in rpush_keys


@pytest.mark.asyncio
async def test_cold_start_m15_retries_on_total_failure(
    ingest_service_module: Any,
) -> None:
    """When ALL symbol fetches fail, _cold_start_m15_for_warmup should retry
    up to 3 times before giving up (0 symbols seeded)."""
    fake_fetcher = MagicMock()
    fake_fetcher.context_bus = MagicMock()
    fake_fetcher.fetch = AsyncMock(side_effect=RuntimeError("API down"))

    warmup_results: dict[str, dict[str, list[dict[str, object]]]] = {
        "EURUSD": {"H1": [{"close": 1.1}]},
    }

    await ingest_service_module._cold_start_m15_for_warmup(
        fake_fetcher, ["EURUSD"], warmup_results, bars=50
    )

    # fetch was called 3 times (1 symbol × 3 retry attempts)
    assert fake_fetcher.fetch.await_count == 3
    # M15 should NOT appear in warmup_results (all attempts failed)
    assert "M15" not in warmup_results.get("EURUSD", {})


@pytest.mark.asyncio
async def test_cold_start_m15_succeeds_on_second_attempt(
    ingest_service_module: Any,
) -> None:
    """If the first attempt fails but the second succeeds, should stop retrying."""
    fake_fetcher = MagicMock()
    fake_fetcher.context_bus = MagicMock()

    call_count = 0

    async def flaky_fetch(symbol: str, tf: str, bars: int) -> list[dict[str, object]]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("temporary failure")
        return [{"symbol": symbol, "timeframe": tf, "close": 1.0}]

    fake_fetcher.fetch = AsyncMock(side_effect=flaky_fetch)

    warmup_results: dict[str, dict[str, list[dict[str, object]]]] = {}

    await ingest_service_module._cold_start_m15_for_warmup(
        fake_fetcher, ["EURUSD"], warmup_results, bars=50
    )

    # Should have succeeded on attempt 2
    assert call_count == 2
    assert "M15" in warmup_results.get("EURUSD", {})
