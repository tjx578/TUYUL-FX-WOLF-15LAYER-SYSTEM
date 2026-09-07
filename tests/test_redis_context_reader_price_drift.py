"""Price-drift semantics for the Redis-backed context reader."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from api.redis_context_reader import RedisContextReader


def test_rest_close_vs_live_mid_is_observational_only() -> None:
    reader = RedisContextReader()
    now = datetime.now(UTC)
    closed = now.replace(minute=0, second=0, microsecond=0)
    rest = {
        "symbol": "XAUUSD",
        "timeframe": "H1",
        "close": 4437.405,
        "source": "rest_api",
        "provider": "finnhub",
        "provider_feed": "finnhub_rest",
        "provider_symbol": "OANDA:XAU_USD",
        "complete": True,
        "open_time": closed - timedelta(hours=1),
        "close_time": closed,
        "received_at_utc": now,
    }
    with (
        patch.object(reader, "get_candles", return_value=[rest]),
        patch.object(
            reader,
            "get_latest_tick",
            return_value={"bid": 4428.155, "ask": 4428.355},
        ),
    ):
        result = reader.check_price_drift("XAUUSD", 50.0)

    assert result["comparable"] is False
    assert result["reason"] == "MISSING_WS_CLOSED_H1"
    assert result["actionable"] is False
    assert result["drifted"] is False
    assert result["drift_pips"] == 0.0
    assert result["observed_live_gap_pips"] == pytest.approx(91.5)
    assert result["max_drift_pips"] == 50.0
