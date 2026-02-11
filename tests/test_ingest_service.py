"""Unit tests for ingest_service.py."""

import asyncio
import importlib
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def ingest_service_module():
    """Load ingest_service with lightweight stubs for heavy dependencies."""
    fake_candle_module = types.ModuleType("ingest.candle_builder")
    fake_news_module = types.ModuleType("ingest.finnhub_news")

    class FakeRunner:
        async def run(self):
            return None

    fake_candle_module.CandleBuilder = FakeRunner
    fake_news_module.FinnhubNews = FakeRunner

    with patch.dict(
        sys.modules,
        {
            "ingest.candle_builder": fake_candle_module,
            "ingest.finnhub_news": fake_news_module,
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
    ingest_service_module,
) -> None:
    """No-API-key path should idle until shutdown event is set."""
    ingest_service_module._shutdown_event = asyncio.Event()
    ingest_service_module._shutdown_event.set()

    await ingest_service_module.run_ingest_services(has_api_key=False)


@pytest.mark.asyncio
async def test_run_ingest_services_closes_redis_when_ping_fails(
    ingest_service_module,
) -> None:
    """Redis client should be closed if setup fails after client creation."""
    fake_redis = MagicMock()
    fake_redis.ping = AsyncMock(side_effect=RuntimeError("ping failed"))
    fake_redis.aclose = AsyncMock()

    with patch.object(ingest_service_module, "_build_redis_client", return_value=fake_redis):
        with pytest.raises(RuntimeError, match="ping failed"):
            await ingest_service_module.run_ingest_services(has_api_key=True)

    fake_redis.aclose.assert_awaited_once()
