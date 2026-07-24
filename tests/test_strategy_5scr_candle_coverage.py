from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from config_loader import get_enabled_symbols
from scripts.validate_strategy_5scr_candle_coverage import (
    _MINIMUM_BARS,
    validate_coverage,
)
from storage.postgres_client import pg_client


def _coverage_rows(*, missing: tuple[str, str] | None = None) -> list[dict[str, object]]:
    latest = datetime(2026, 7, 24, 12, tzinfo=UTC)
    return [
        {
            "symbol": symbol,
            "timeframe": timeframe,
            "candle_count": (0 if missing == (symbol, timeframe) else minimum),
            "latest_close_time": latest,
        }
        for symbol in get_enabled_symbols()
        for timeframe, minimum in _MINIMUM_BARS.items()
    ]


@pytest.mark.asyncio
async def test_all_30_pairs_ready_without_future_candles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetch = AsyncMock(side_effect=[_coverage_rows(), []])
    monkeypatch.setattr(pg_client, "fetch", fetch)

    result = await validate_coverage(
        symbols=get_enabled_symbols(),
        as_of_utc=datetime(2026, 7, 24, 12, tzinfo=UTC),
    )

    assert result["symbols"] == 30
    assert result["required_combinations"] == 150
    assert result["ready_combinations"] == 150
    assert result["future_candle_leakage_detected"] is False
    assert result["ready"] is True


@pytest.mark.asyncio
async def test_missing_timeframe_and_future_close_fail_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing = ("EURUSD", "H4")
    fetch = AsyncMock(
        side_effect=[
            _coverage_rows(missing=missing),
            [{"symbol": "EURUSD", "timeframe": "M15", "candle_count": 1}],
        ]
    )
    monkeypatch.setattr(pg_client, "fetch", fetch)

    result = await validate_coverage(
        symbols=get_enabled_symbols(),
        as_of_utc=datetime(2026, 7, 24, 12, tzinfo=UTC),
    )

    assert result["ready_combinations"] == 149
    assert result["missing_or_insufficient"][0]["symbol"] == "EURUSD"
    assert result["missing_or_insufficient"][0]["timeframe"] == "H4"
    assert result["future_candle_leakage_detected"] is True
    assert result["ready"] is False
