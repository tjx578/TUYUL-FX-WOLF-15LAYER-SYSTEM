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
