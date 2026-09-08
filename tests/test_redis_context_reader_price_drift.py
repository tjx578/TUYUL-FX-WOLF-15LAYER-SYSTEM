"""Price-drift semantics for the Redis-backed context reader."""

from __future__ import annotations

from unittest.mock import patch

from api.redis_context_reader import RedisContextReader


def test_rest_close_vs_live_mid_is_observational_only() -> None:
    reader = RedisContextReader()
    with (
        patch.object(reader, "get_candles", return_value=[{"close": 4437.405}]),
        patch.object(
            reader,
            "get_latest_tick",
            return_value={"bid": 4428.155, "ask": 4428.355},
        ),
    ):
        result = reader.check_price_drift("XAUUSD", 50.0)

    assert result["comparable"] is False
    assert result["reason"] == "REST_H1_CLOSE_VS_WS_LIVE_MID_NOT_COMPARABLE"
    assert result["drifted"] is False
    assert result["drift_pips"] == 0.0
    assert result["observed_live_gap_pips"] == 91.5
    assert result["max_drift_pips"] == 50.0
