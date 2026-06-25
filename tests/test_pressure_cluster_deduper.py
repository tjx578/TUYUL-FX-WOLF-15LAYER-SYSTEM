from __future__ import annotations

from analysis.pressure_cluster_deduper import (
    cluster_key,
    dedupe_pressure_clusters,
    price_bucket,
    summarize_pressure_clusters,
)


def test_price_bucket_groups_nearby_prices_by_pip_size() -> None:
    assert price_bucket(1.35701, 0.0001, bucket_pips=5) == price_bucket(1.35704, 0.0001, bucket_pips=5)


def test_pressure_cluster_deduper_collapses_duplicate_market_pressure() -> None:
    events = [
        {
            "timestamp": "2026-06-25T12:00:01Z",
            "signal_valid_time_utc": "2026-06-25T12:00:01Z",
            "symbol": "USDCAD",
            "raw_direction": "BUY",
            "signal_family": "SIGNAL_THROTTLE_PRESSURE",
            "status": "NO_TRADE_REASONED",
            "signal_valid_price": 1.35701,
        },
        {
            "timestamp": "2026-06-25T12:04:40Z",
            "signal_valid_time_utc": "2026-06-25T12:04:40Z",
            "symbol": "USDCAD",
            "raw_direction": "BUY",
            "signal_family": "SIGNAL_THROTTLE_PRESSURE",
            "status": "NO_TRADE_REASONED",
            "signal_valid_price": 1.35704,
        },
        {
            "timestamp": "2026-06-25T12:05:00Z",
            "signal_valid_time_utc": "2026-06-25T12:05:00Z",
            "symbol": "USDCAD",
            "raw_direction": "BUY",
            "signal_family": "SIGNAL_THROTTLE_PRESSURE",
            "status": "NO_TRADE_REASONED",
            "signal_valid_price": 1.35705,
        },
        {
            "timestamp": "2026-06-25T12:16:01Z",
            "signal_valid_time_utc": "2026-06-25T12:16:01Z",
            "symbol": "USDCAD",
            "raw_direction": "BUY",
            "signal_family": "SIGNAL_THROTTLE_PRESSURE",
            "status": "NO_TRADE_REASONED",
            "signal_valid_price": 1.35701,
        },
    ]

    clusters = dedupe_pressure_clusters(events)
    summary = summarize_pressure_clusters(events)

    assert cluster_key(events[0]) == cluster_key(events[1])
    assert len(clusters) == 2
    assert summary["raw_event_count"] == 4
    assert summary["deduped_cluster_count"] == 2
    assert summary["by_symbol_direction"]["USDCAD:BUY"]["raw_event_count"] == 4
    assert summary["by_symbol_direction"]["USDCAD:BUY"]["deduped_cluster_count"] == 2
