"""Tests for ingest_service stale-cache degraded-mode readiness logic."""

from __future__ import annotations

import importlib
import sys
import types
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Shared fixture (mirrors the pattern in test_ingest_service.py)
# ---------------------------------------------------------------------------


@pytest.fixture
def ingest_service_module() -> Any:
    """Reload ingest_service with all heavy dependencies stubbed."""
    fake_websockets = types.ModuleType("websockets")
    fake_websockets.connect = AsyncMock()  # type: ignore[attr-defined]
    fake_websockets_asyncio = types.ModuleType("websockets.asyncio")
    fake_websockets_asyncio_client = types.ModuleType("websockets.asyncio.client")
    fake_websockets_asyncio_client.connect = AsyncMock()  # type: ignore[attr-defined]

    fake_candle = types.ModuleType("ingest.candle_builder")
    fake_news = types.ModuleType("ingest.calendar_news")
    fake_deps = types.ModuleType("ingest.dependencies")
    fake_macro = types.ModuleType("analysis.macro.macro_regime_engine")
    fake_rest_poll = types.ModuleType("ingest.rest_poll_fallback")

    class _Runner:
        def __init__(self, *a: object, **kw: object) -> None:
            super().__init__()

        async def run(self) -> None:
            pass

    class _Timeframe:
        M15 = "M15"

    fake_candle.CandleBuilder = _Runner  # type: ignore[attr-defined]
    fake_candle.Timeframe = _Timeframe  # type: ignore[attr-defined]
    fake_news.CalendarNewsIngestor = _Runner  # type: ignore[attr-defined]
    fake_deps.create_finnhub_ws = AsyncMock()  # type: ignore[attr-defined]
    fake_macro.MacroRegimeEngine = MagicMock  # type: ignore[attr-defined]
    fake_rest_poll.RestPollFallback = _Runner  # type: ignore[attr-defined]

    with patch.dict(
        sys.modules,
        {
            "websockets": fake_websockets,
            "websockets.asyncio": fake_websockets_asyncio,
            "websockets.asyncio.client": fake_websockets_asyncio_client,
            "ingest.candle_builder": fake_candle,
            "ingest.calendar_news": fake_news,
            "ingest.dependencies": fake_deps,
            "ingest.rest_poll_fallback": fake_rest_poll,
            "analysis.macro.macro_regime_engine": fake_macro,
        },
    ):
        mod = importlib.import_module("ingest_service")
        mod = importlib.reload(mod)
        try:
            yield mod
        finally:
            sys.modules.pop("ingest_service", None)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestIngestReadinessDegradedMode:
    """_ingest_readiness() requires startup + producer heartbeat health."""

    def test_readiness_false_when_both_flags_false(
        self, ingest_service_module: Any
    ) -> None:
        ingest_service_module._ingest_ready = False
        ingest_service_module._ingest_degraded = False
        ingest_service_module._producer_present = False
        ingest_service_module._producer_last_heartbeat_ts = 0.0
        assert ingest_service_module._ingest_readiness() is False

    def test_readiness_true_when_ingest_ready(self, ingest_service_module: Any) -> None:
        ingest_service_module._ingest_ready = True
        ingest_service_module._ingest_degraded = False
        ingest_service_module._producer_present = True
        ingest_service_module._producer_last_heartbeat_ts = ingest_service_module.time()
        assert ingest_service_module._ingest_readiness() is True

    def test_readiness_true_when_degraded_if_producer_healthy(
        self, ingest_service_module: Any
    ) -> None:
        ingest_service_module._ingest_ready = False
        ingest_service_module._ingest_degraded = True
        ingest_service_module._producer_present = True
        ingest_service_module._producer_last_heartbeat_ts = ingest_service_module.time()
        assert ingest_service_module._ingest_readiness() is True

    def test_readiness_false_when_producer_missing(
        self, ingest_service_module: Any
    ) -> None:
        ingest_service_module._ingest_ready = True
        ingest_service_module._ingest_degraded = False
        ingest_service_module._producer_present = False
        ingest_service_module._producer_last_heartbeat_ts = ingest_service_module.time()
        assert ingest_service_module._ingest_readiness() is False

    def test_readiness_false_when_producer_heartbeat_stale(
        self, ingest_service_module: Any
    ) -> None:
        ingest_service_module._ingest_ready = True
        ingest_service_module._ingest_degraded = False
        ingest_service_module._producer_present = True
        ingest_service_module._producer_last_heartbeat_ts = (
            ingest_service_module.time()
            - ingest_service_module._PRODUCER_FRESHNESS_SEC
            - 1
        )
        assert ingest_service_module._ingest_readiness() is False


class TestHasStaleCacheFunction:
    """_has_stale_cache() should correctly detect cached candle keys."""

    @pytest.mark.asyncio
    async def test_returns_true_when_cache_key_found(
        self, ingest_service_module: Any
    ) -> None:
        mock_redis = AsyncMock()
        mock_redis.scan = AsyncMock(
            side_effect=[(0, ["wolf15:candle_history:EURUSD:H1"])]
        )
        mock_redis.llen = AsyncMock(return_value=50)

        result = await ingest_service_module._has_stale_cache(mock_redis)
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_no_keys(self, ingest_service_module: Any) -> None:
        mock_redis = AsyncMock()
        mock_redis.scan = AsyncMock(side_effect=[(0, [])])

        result = await ingest_service_module._has_stale_cache(mock_redis)
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_key_empty(
        self, ingest_service_module: Any
    ) -> None:
        mock_redis = AsyncMock()
        mock_redis.scan = AsyncMock(
            side_effect=[(0, ["wolf15:candle_history:EURUSD:H1"])]
        )
        mock_redis.llen = AsyncMock(return_value=0)

        result = await ingest_service_module._has_stale_cache(mock_redis)
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_scan_exception(
        self, ingest_service_module: Any
    ) -> None:
        mock_redis = AsyncMock()
        mock_redis.scan = AsyncMock(side_effect=ConnectionError("redis down"))

        result = await ingest_service_module._has_stale_cache(mock_redis)
        assert result is False

    @pytest.mark.asyncio
    async def test_iterates_multiple_scan_pages(
        self, ingest_service_module: Any
    ) -> None:
        """Should iterate cursor pages until cursor returns 0."""
        mock_redis = AsyncMock()
        mock_redis.scan = AsyncMock(
            side_effect=[
                (42, []),
                (0, ["wolf15:candle_history:GBPUSD:H4"]),
            ]
        )
        mock_redis.llen = AsyncMock(return_value=10)

        result = await ingest_service_module._has_stale_cache(mock_redis)
        assert result is True


class TestWarmupCircuitBreakerOnModule:
    """Confirm _warmup_circuit is a CircuitBreaker on the ingest_service module."""

    def test_warmup_circuit_exists(self, ingest_service_module: Any) -> None:
        from infrastructure.circuit_breaker import CircuitBreaker  # noqa: PLC0415

        assert isinstance(ingest_service_module._warmup_circuit, CircuitBreaker)

    def test_warmup_circuit_starts_closed(self, ingest_service_module: Any) -> None:
        from infrastructure.circuit_breaker import CircuitState  # noqa: PLC0415

        assert ingest_service_module._warmup_circuit.state is CircuitState.CLOSED
