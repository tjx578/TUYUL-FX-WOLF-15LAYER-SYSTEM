"""Unit tests for ingest_service.py."""

import asyncio
import importlib
import sys
import types
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context.system_state import SystemState, SystemStateManager


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
    SystemStateManager().reset()
    fake_redis = MagicMock()
    fake_redis.aclose = AsyncMock()

    with patch.object(ingest_service_module, "_connect_redis_with_retry", new=AsyncMock(return_value=fake_redis)):  # noqa: SIM117
        with patch.object(ingest_service_module, "_has_stale_cache", new=AsyncMock(return_value=False)):
            with patch.object(
                ingest_service_module, "_run_warmup", new=AsyncMock(side_effect=RuntimeError("ping failed"))
            ):
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
            "H1": [{"open": 1.08, "high": 1.12, "low": 1.07, "close": 1.1}],
            "H4": [{"open": 1.03, "high": 1.06, "low": 1.02, "close": 1.05}],
            "D1": [{"open": 0.98, "high": 1.02, "low": 0.97, "close": 1.0}],
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


def test_ingest_service_does_not_reference_live_state(ingest_service_module: Any) -> None:
    """Startup should use valid SystemState members only (no LIVE)."""
    source_path = ingest_service_module.__file__
    assert source_path is not None
    with open(source_path, encoding="utf-8") as handle:
        source = handle.read()
    assert "SystemState.LIVE" not in source


@pytest.mark.asyncio
async def test_main_resets_system_state_after_runtime_failure(
    ingest_service_module: Any,
) -> None:
    """Runtime retry path should reset SystemStateManager between attempts."""
    ingest_service_module._shutdown_event = asyncio.Event()

    async def fake_run_ingest_services(_has_api_key: bool) -> None:
        ingest_service_module._shutdown_event.set()
        raise RuntimeError("boom")

    with patch.object(ingest_service_module, "_validate_api_key", return_value=True):  # noqa: SIM117
        with patch.object(ingest_service_module, "init_persistent_storage", new=AsyncMock()):
            with patch.object(
                ingest_service_module,
                "shutdown_persistent_storage",
                new=AsyncMock(),
            ):
                with patch.object(
                    ingest_service_module,
                    "run_ingest_services",
                    side_effect=fake_run_ingest_services,
                ):
                    with patch.object(ingest_service_module, "_health_probe") as probe:
                        probe.start = AsyncMock()
                        probe.stop = AsyncMock()
                        probe.set_detail = MagicMock()
                        probe.set_readiness_check = MagicMock()
                        with (
                            patch.object(
                                ingest_service_module.SystemStateManager,
                                "reset",
                                autospec=True,
                            ) as reset_mock,
                            patch.object(ingest_service_module.asyncio, "sleep", new=AsyncMock()),
                        ):
                            await ingest_service_module.main(_bootstrap_probe=probe)

    assert reset_mock.call_count == 1


@pytest.mark.asyncio
async def test_bootstrap_cache_and_warmup_prefers_stale_cache(
    ingest_service_module: Any,
) -> None:
    fake_redis = MagicMock()
    system_state = SystemStateManager()
    system_state.reset()
    system_state.set_state(ingest_service_module.SystemState.WARMING_UP)

    with patch.object(ingest_service_module, "_has_stale_cache", new=AsyncMock(return_value=True)):  # noqa: SIM117
        with patch.object(ingest_service_module, "_run_warmup", new=AsyncMock()) as warmup_mock:
            result, redis_has_data, mode = await ingest_service_module._bootstrap_cache_and_warmup(
                redis=fake_redis,
                system_state=system_state,
                enabled_symbols=["EURUSD"],
            )

    assert result == {}
    assert redis_has_data is True
    assert mode == "stale_cache"
    warmup_mock.assert_not_called()


def test_set_startup_mode_flags_degraded_on_stale_cache(
    ingest_service_module: Any,
) -> None:
    ingest_service_module._ingest_ready = False
    ingest_service_module._ingest_degraded = False

    ingest_service_module._set_startup_mode(
        mode="stale_cache",
        warmup_results={},
        redis_has_data=True,
    )

    assert ingest_service_module._ingest_ready is False
    assert ingest_service_module._ingest_degraded is True


# ── P0-1: Ingest state machine crash-loop prevention ──────────────────────


@pytest.mark.asyncio
async def test_run_ingest_services_resets_state_at_entry(
    ingest_service_module: Any,
) -> None:
    """run_ingest_services() must reset SystemStateManager at entry so retries
    start from a clean INITIALIZING state even if main()'s reset() was suppressed."""
    system_state = SystemStateManager()
    # Simulate a prior run that left state in DEGRADED
    system_state.reset()
    system_state.set_state(ingest_service_module.SystemState.WARMING_UP)
    system_state.set_state(ingest_service_module.SystemState.DEGRADED)

    ingest_service_module._shutdown_event = asyncio.Event()

    fake_redis = MagicMock()
    fake_redis.aclose = AsyncMock()

    # Let it crash after Redis connect so we can inspect state at the reset point.
    with (
        patch.object(
            ingest_service_module,
            "_connect_redis_with_retry",
            new=AsyncMock(return_value=fake_redis),
        ),
        patch.object(
            ingest_service_module,
            "_bootstrap_cache_and_warmup",
            new=AsyncMock(side_effect=RuntimeError("test-crash")),
        ),
        pytest.raises(RuntimeError, match="test-crash"),
    ):
        await ingest_service_module.run_ingest_services(has_api_key=True)

    # After the reset+set_state(WARMING_UP) at entry, state must be WARMING_UP
    # (bootstrap crashed before it could change it further).
    assert system_state.get_state() == ingest_service_module.SystemState.WARMING_UP


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "prior_state",
    [
        SystemState.WARMING_UP,
        SystemState.READY,
        SystemState.DEGRADED,
        SystemState.ERROR,
    ],
)
async def test_run_ingest_services_idempotent_from_any_prior_state(
    ingest_service_module: Any,
    prior_state: "SystemState",
) -> None:
    """run_ingest_services() must not crash regardless of the prior SystemState."""
    system_state = SystemStateManager()
    # Force arbitrary prior state
    with system_state._rw_lock:
        system_state._state = prior_state

    ingest_service_module._shutdown_event = asyncio.Event()

    fake_redis = MagicMock()
    fake_redis.aclose = AsyncMock()

    with (
        patch.object(
            ingest_service_module,
            "_connect_redis_with_retry",
            new=AsyncMock(return_value=fake_redis),
        ),
        patch.object(
            ingest_service_module,
            "_bootstrap_cache_and_warmup",
            new=AsyncMock(side_effect=RuntimeError("bail")),
        ),
        pytest.raises(RuntimeError, match="bail"),
    ):
        await ingest_service_module.run_ingest_services(has_api_key=True)

    # Should have reset → INITIALIZING → WARMING_UP; bootstrap crash kept WARMING_UP
    assert system_state.get_state() == ingest_service_module.SystemState.WARMING_UP


@pytest.mark.asyncio
async def test_retry_loop_clears_warmup_report(
    ingest_service_module: Any,
) -> None:
    """On retry, reset() in run_ingest_services clears stale warmup report."""
    from context.system_state import WarmupStatus

    system_state = SystemStateManager()
    system_state.reset()
    system_state.set_state(ingest_service_module.SystemState.WARMING_UP)
    # Seed a leftover warmup report from a prior run
    with system_state._rw_lock:
        system_state._warmup_report["EURUSD"] = WarmupStatus(symbol="EURUSD")
    assert system_state.get_warmup_report() != {}

    ingest_service_module._shutdown_event = asyncio.Event()

    fake_redis = MagicMock()
    fake_redis.aclose = AsyncMock()

    with (
        patch.object(
            ingest_service_module,
            "_connect_redis_with_retry",
            new=AsyncMock(return_value=fake_redis),
        ),
        patch.object(
            ingest_service_module,
            "_bootstrap_cache_and_warmup",
            new=AsyncMock(side_effect=RuntimeError("bail")),
        ),
        pytest.raises(RuntimeError, match="bail"),
    ):
        await ingest_service_module.run_ingest_services(has_api_key=True)

    # reset() at entry should have cleared the warmup report
    assert system_state.get_warmup_report() == {}
