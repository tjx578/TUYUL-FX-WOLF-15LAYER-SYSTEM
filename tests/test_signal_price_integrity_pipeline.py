from __future__ import annotations

import time
from typing import Any

from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline


class _PriceContextBus:
    def __init__(self, *, bid: float, ask: float, feed_timestamp: float, low: float, high: float) -> None:
        self.tick = {"symbol": "CHFJPY", "bid": bid, "ask": ask}
        self.feed_timestamp = feed_timestamp
        self.candle = {
            "symbol": "CHFJPY",
            "timeframe": "M1",
            "low": low,
            "high": high,
            "timestamp": feed_timestamp,
        }

    def get_latest_tick(self, symbol: str) -> dict[str, Any]:
        assert symbol == "CHFJPY"
        return dict(self.tick)

    def get_feed_timestamp(self, symbol: str) -> float:
        assert symbol == "CHFJPY"
        return self.feed_timestamp

    def get_candle_history(self, symbol: str, timeframe: str, count: int | None = None) -> list[dict[str, Any]]:
        assert (symbol, timeframe) == ("CHFJPY", "M1")
        return [dict(self.candle)]


def _pipeline(bus: _PriceContextBus) -> WolfConstitutionalPipeline:
    pipeline = WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)
    pipeline._context_bus = bus
    return pipeline


def _payload() -> dict[str, Any]:
    return {
        "symbol": "CHFJPY",
        "signal_valid_price": 200.7375,
        "entry_reference_price": 200.7375,
        "entry_zone": [200.721, 200.735],
        "main_support": 200.640,
        "main_resistance": 200.7375,
    }


def test_pipeline_replaces_stale_reference_level_with_observed_mid(monkeypatch):
    monkeypatch.setenv("SIGNAL_PRICE_INTEGRITY_ENABLED", "true")
    now = time.time()
    pipeline = _pipeline(
        _PriceContextBus(
            bid=200.661,
            ask=200.663,
            feed_timestamp=now,
            low=200.640,
            high=200.673,
        )
    )
    payload = _payload()

    pipeline._attach_signal_price_integrity(payload)

    assert payload["price_integrity_valid"] is True
    assert payload["signal_valid_price"] == 200.662
    assert payload["entry_reference_price"] == 200.7375
    assert payload["reference_signal_price"] == 200.7375
    assert payload["reference_resistance"] == 200.7375


def test_pipeline_marks_stale_quote_without_reusing_reference_price(monkeypatch):
    monkeypatch.setenv("SIGNAL_PRICE_INTEGRITY_ENABLED", "true")
    monkeypatch.setenv("SIGNAL_PRICE_MAX_QUOTE_AGE_SECONDS", "5")
    pipeline = _pipeline(
        _PriceContextBus(
            bid=200.661,
            ask=200.663,
            feed_timestamp=time.time() - 10.0,
            low=200.640,
            high=200.673,
        )
    )
    payload = _payload()

    pipeline._attach_signal_price_integrity(payload)

    assert payload["price_integrity_valid"] is False
    assert payload["price_integrity_reason"] == "PRICE_CONTEXT_STALE"
    assert payload["reference_signal_price"] == 200.7375
    assert payload["signal_valid_price"] is None
    assert payload["observed_mid"] == 200.662


def test_old_tick_stays_stale_even_when_shared_bus_timestamp_is_fresh(monkeypatch):
    monkeypatch.setenv("SIGNAL_PRICE_INTEGRITY_ENABLED", "true")
    monkeypatch.setenv("SIGNAL_PRICE_MAX_QUOTE_AGE_SECONDS", "5")
    pipeline = _pipeline(
        _PriceContextBus(
            bid=200.661,
            ask=200.663,
            feed_timestamp=time.time(),
            low=200.640,
            high=200.673,
        )
    )
    pipeline._context_bus.tick["last_seen_ts"] = time.time() - 10.0
    payload = _payload()

    pipeline._attach_signal_price_integrity(payload)

    assert payload["price_integrity_valid"] is False
    assert payload["price_integrity_reason"] == "PRICE_CONTEXT_STALE"
    assert payload["signal_valid_price"] is None


def test_pipeline_rejects_quote_outside_contemporaneous_m1_range(monkeypatch):
    monkeypatch.setenv("SIGNAL_PRICE_INTEGRITY_ENABLED", "true")
    pipeline = _pipeline(
        _PriceContextBus(
            bid=200.7365,
            ask=200.7385,
            feed_timestamp=time.time(),
            low=200.640,
            high=200.673,
        )
    )
    payload = _payload()

    pipeline._attach_signal_price_integrity(payload)

    assert payload["price_integrity_valid"] is False
    assert payload["price_integrity_reason"] == "PRICE_CONTEXT_OUT_OF_RANGE"
    assert payload["signal_valid_price"] is None
    assert payload["observed_mid"] == 200.7375
    assert payload["reference_signal_price"] == 200.7375


def test_pipeline_fails_closed_when_independent_range_is_unavailable(monkeypatch):
    monkeypatch.setenv("SIGNAL_PRICE_INTEGRITY_ENABLED", "true")
    pipeline = _pipeline(
        _PriceContextBus(
            bid=200.661,
            ask=200.663,
            feed_timestamp=time.time(),
            low=0.0,
            high=0.0,
        )
    )
    pipeline._context_bus.candle = {}
    payload = _payload()

    pipeline._attach_signal_price_integrity(payload)

    assert payload["price_integrity_valid"] is False
    assert payload["price_integrity_reason"] == "PRICE_CONTEXT_STALE"
    assert payload["price_range_source"] == "UNAVAILABLE"
    assert payload["signal_valid_price"] is None
    assert payload["entry_reference_price"] == 200.7375
