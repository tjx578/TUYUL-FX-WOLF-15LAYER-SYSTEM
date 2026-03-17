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
    fake_rest_poll_module = types.ModuleType("ingest.rest_poll_fallback")
    fake_market_news_module = types.ModuleType("ingest.finnhub_market_news")
    fake_h1_scheduler_module = types.ModuleType("ingest.h1_refresh_scheduler")
    fake_macro_scheduler_module = types.ModuleType("ingest.macro_monthly_scheduler")
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
    fake_rest_poll_module.RestPollFallback = FakeRunner  # type: ignore[attr-defined]
    fake_market_news_module.FinnhubMarketNews = FakeRunner  # type: ignore[attr-defined]
    fake_h1_scheduler_module.H1RefreshScheduler = FakeRunner  # type: ignore[attr-defined]
    fake_macro_scheduler_module.MacroMonthlyScheduler = FakeRunner  # type: ignore[attr-defined]
    fake_macro_module.MacroRegimeEngine = MagicMock  # type: ignore[attr-defined]

    with patch.dict(
        sys.modules,
        {
            "websockets": fake_websockets_module,
            "ingest.candle_builder": fake_candle_module,
            "ingest.calendar_news": fake_news_module,
            "ingest.dependencies": fake_dependencies_module,
            "ingest.rest_poll_fallback": fake_rest_poll_module,
            "ingest.finnhub_market_news": fake_market_news_module,
            "ingest.h1_refresh_scheduler": fake_h1_scheduler_module,
            "ingest.macro_monthly_scheduler": fake_macro_scheduler_module,
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


# ── Redis candle history seeding tests ─────────────────────────────────────


@pytest.mark.asyncio
async def test_seed_redis_writes_h1_keys(
    ingest_service_module: Any,
) -> None:
    """_seed_redis_candle_history must write REST-warmed timeframe keys (H1, H4, D1)
    to Redis via temp key + atomic RENAME. M15 is NOT produced by ingest."""
    fake_redis = MagicMock()
    fake_redis.llen = AsyncMock(return_value=1)
    fake_redis.delete = AsyncMock()
    fake_redis.rpush = AsyncMock()
    fake_redis.rename = AsyncMock()

    warmup_results = {
        "EURUSD": {
            "H1": [{"close": 1.1}],
            "H4": [{"close": 1.05}],
            "D1": [{"close": 1.0}],
        }
    }

    await ingest_service_module._seed_redis_candle_history(fake_redis, warmup_results)

    # rpush goes to temp keys
    rpush_keys = [call.args[0] for call in fake_redis.rpush.call_args_list]
    assert "wolf15:candle_history:EURUSD:H1:_seed_tmp" in rpush_keys
    assert "wolf15:candle_history:EURUSD:H4:_seed_tmp" in rpush_keys
    assert "wolf15:candle_history:EURUSD:D1:_seed_tmp" in rpush_keys

    # rename swaps temp → actual key
    rename_calls = [(call.args[0], call.args[1]) for call in fake_redis.rename.call_args_list]
    assert ("wolf15:candle_history:EURUSD:H1:_seed_tmp", "wolf15:candle_history:EURUSD:H1") in rename_calls
    assert ("wolf15:candle_history:EURUSD:H4:_seed_tmp", "wolf15:candle_history:EURUSD:H4") in rename_calls
    assert ("wolf15:candle_history:EURUSD:D1:_seed_tmp", "wolf15:candle_history:EURUSD:D1") in rename_calls

    # M15 must NOT appear — it is built from tick data, not REST
    assert "wolf15:candle_history:EURUSD:M15:_seed_tmp" not in rpush_keys


@pytest.mark.asyncio
async def test_seed_redis_still_pushes_when_delete_fails(
    ingest_service_module: Any,
) -> None:
    """DELETE errors on temp key must not block RPUSH attempt."""
    fake_redis = MagicMock()
    fake_redis.llen = AsyncMock(return_value=1)
    fake_redis.delete = AsyncMock(side_effect=RuntimeError("READONLY"))
    fake_redis.rpush = AsyncMock()
    fake_redis.rename = AsyncMock()

    warmup_results = {
        "EURUSD": {
            "H1": [
                {
                    "symbol": "EURUSD",
                    "timeframe": "H1",
                    "open": 1.0,
                    "high": 1.1,
                    "low": 0.9,
                    "close": 1.05,
                    "volume": 1,
                    "source": "rest_api",
                }
            ]
        }
    }

    await ingest_service_module._seed_redis_candle_history(fake_redis, warmup_results)

    # rpush should still be called despite delete failure
    fake_redis.rpush.assert_awaited_once()


def test_cold_start_m15_removed_from_module(
    ingest_service_module: Any,
) -> None:
    """_cold_start_m15_for_warmup must not exist on ingest_service.

    M15 comes from tick data (CandleBuilder), never from REST.
    Fetching M15 from REST violates the architecture.
    """
    assert not hasattr(
        ingest_service_module, "_cold_start_m15_for_warmup"
    ), "_cold_start_m15_for_warmup still present — should have been removed. M15 must come from tick data only."


@pytest.mark.asyncio
async def test_seed_redis_chunks_large_payload(
    ingest_service_module: Any,
) -> None:
    """When candle count exceeds the chunk size, rpush must be called multiple times.

    _SEED_RPUSH_CHUNK_SIZE = 50, so 120 candles → 3 rpush calls (50 + 50 + 20),
    all to the temp key. Then a single rename swaps temp → actual.
    """
    fake_redis = MagicMock()
    fake_redis.llen = AsyncMock(return_value=120)
    fake_redis.delete = AsyncMock()
    fake_redis.rpush = AsyncMock()
    fake_redis.rename = AsyncMock()

    candles = [{"close": float(i)} for i in range(120)]
    warmup_results = {"EURUSD": {"H1": candles}}

    await ingest_service_module._seed_redis_candle_history(fake_redis, warmup_results)

    # 120 candles ÷ 50 chunk size = 3 calls (50 + 50 + 20)
    assert fake_redis.rpush.await_count == 3
    # Each call's first arg is the temp Redis key
    for call in fake_redis.rpush.call_args_list:
        assert call.args[0] == "wolf15:candle_history:EURUSD:H1:_seed_tmp"
    # Verify chunk sizes: first two chunks hold 50, last holds 20
    chunk_sizes = [len(call.args) - 1 for call in fake_redis.rpush.call_args_list]
    assert chunk_sizes == [50, 50, 20]
    # Single rename at the end
    fake_redis.rename.assert_awaited_once_with(
        "wolf15:candle_history:EURUSD:H1:_seed_tmp",
        "wolf15:candle_history:EURUSD:H1",
    )


# ── Conditional warmup tests (Redis-first skip) ──────────────────────────────


@pytest.mark.asyncio
async def test_has_stale_cache_returns_true_when_candle_key_exists(
    ingest_service_module: Any,
) -> None:
    """_has_stale_cache must return True when at least one candle_history key has data."""
    fake_redis = MagicMock()

    async def mock_scan(cursor: int, match: str, count: int) -> tuple[int, list[str]]:
        if cursor == 0:
            return (0, ["wolf15:candle_history:EURUSD:H1"])
        return (0, [])

    fake_redis.scan = AsyncMock(side_effect=mock_scan)
    fake_redis.llen = AsyncMock(return_value=50)

    result = await ingest_service_module._has_stale_cache(fake_redis)
    assert result is True


@pytest.mark.asyncio
async def test_has_stale_cache_returns_false_when_no_candle_keys(
    ingest_service_module: Any,
) -> None:
    """_has_stale_cache must return False when SCAN yields no candle_history keys."""
    fake_redis = MagicMock()
    fake_redis.scan = AsyncMock(return_value=(0, []))

    result = await ingest_service_module._has_stale_cache(fake_redis)
    assert result is False
