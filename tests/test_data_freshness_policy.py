from __future__ import annotations

from state.data_freshness import classify_feed_freshness


def test_classify_fresh() -> None:
    snap = classify_feed_freshness(
        transport_ok=True,
        has_producer_signal=True,
        staleness_seconds=5.0,
        threshold_seconds=30.0,
    )
    assert snap.state == "fresh"


def test_classify_stale_preserved() -> None:
    snap = classify_feed_freshness(
        transport_ok=True,
        has_producer_signal=True,
        staleness_seconds=65.0,
        threshold_seconds=30.0,
    )
    assert snap.state == "stale_preserved"


def test_classify_no_producer() -> None:
    snap = classify_feed_freshness(
        transport_ok=True,
        has_producer_signal=False,
        staleness_seconds=float("inf"),
        threshold_seconds=30.0,
    )
    assert snap.state == "no_producer"


def test_classify_no_transport() -> None:
    snap = classify_feed_freshness(
        transport_ok=False,
        has_producer_signal=False,
        staleness_seconds=float("inf"),
        threshold_seconds=30.0,
    )
    assert snap.state == "no_transport"


def test_classify_from_last_seen_ts() -> None:
    snap = classify_feed_freshness(
        transport_ok=True,
        has_producer_signal=False,
        last_seen_ts=95.0,
        now_ts=100.0,
        threshold_seconds=30.0,
    )
    assert snap.state == "fresh"
    assert snap.staleness_seconds == 5.0
    assert snap.last_seen_ts == 95.0


def test_classify_config_error() -> None:
    snap = classify_feed_freshness(
        transport_ok=True,
        has_producer_signal=True,
        staleness_seconds=1.0,
        threshold_seconds=30.0,
        config_ok=False,
    )
    assert snap.state == "config_error"
