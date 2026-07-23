"""Regression tests for process-wide Finnhub REST quota coordination."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ingest.finnhub_candles import FinnhubCandleFetcher
from ingest.finnhub_rest_budget import (
    FinnhubRestBudget,
    FinnhubRestCooldownError,
    finnhub_rest_budget,
)


@pytest.fixture(autouse=True)
def _reset_shared_budget() -> None:
    finnhub_rest_budget.reset_for_tests()
    yield
    finnhub_rest_budget.reset_for_tests()


@pytest.mark.asyncio
async def test_budget_spaces_slots_shared_by_independent_callers() -> None:
    budget = FinnhubRestBudget()
    clock = {"now": 100.0}
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock["now"] += seconds

    with (
        patch("ingest.finnhub_rest_budget.time.monotonic", side_effect=lambda: clock["now"]),
        patch("ingest.finnhub_rest_budget.asyncio.sleep", side_effect=fake_sleep),
    ):
        await budget.wait_for_slot(0.5)
        await budget.wait_for_slot(0.5)

    assert sleeps == [0.5]


@pytest.mark.asyncio
async def test_budget_rejects_io_while_cooldown_active() -> None:
    budget = FinnhubRestBudget()
    budget.defer_for(10)

    with pytest.raises(FinnhubRestCooldownError) as exc_info:
        await budget.wait_for_slot(0)

    assert exc_info.value.retry_after_sec > 0


@pytest.mark.asyncio
async def test_fetcher_uses_fallback_without_http_during_key_cooldown() -> None:
    fetcher = FinnhubCandleFetcher()
    fetcher.request_delay = 0
    fetcher._key_manager = MagicMock()
    fetcher._key_manager.current_key.return_value = "suspended-key"
    fetcher._key_manager.next_available_in.return_value = 30.0
    fallback = [{"symbol": "EURUSD", "timeframe": "H1", "source": "fallback"}]
    fetcher.try_fallback = AsyncMock(return_value=fallback)

    client = MagicMock()
    with patch("ingest.finnhub_candles.httpx.AsyncClient", return_value=client):
        result = await fetcher.fetch("EURUSD", "H1", bars=1)

    assert result == fallback
    client.get.assert_not_called()
    fetcher.try_fallback.assert_awaited_once_with("EURUSD", "H1", 1)
