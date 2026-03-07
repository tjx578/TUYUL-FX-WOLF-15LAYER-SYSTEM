"""Tests for Finnhub WS Prometheus reconnect metrics."""

from __future__ import annotations

from ingest.finnhub_ws import (
    finnhub_ws_connected,
    finnhub_ws_connections_total,
    finnhub_ws_reconnect_attempts,
    finnhub_ws_reconnect_current,
)


class TestFinnhubWSMetrics:
    """Verify Prometheus metric objects are properly defined."""

    def test_reconnect_attempts_counter_exists(self) -> None:
        """Counter for total reconnect attempts should exist with expected labels."""
        assert finnhub_ws_reconnect_attempts is not None
        # Verify label names
        assert "replica_id" in finnhub_ws_reconnect_attempts._labelnames
        assert "error_type" in finnhub_ws_reconnect_attempts._labelnames

    def test_reconnect_current_gauge_exists(self) -> None:
        """Gauge for current consecutive attempt should exist."""
        assert finnhub_ws_reconnect_current is not None
        assert "replica_id" in finnhub_ws_reconnect_current._labelnames

    def test_connections_total_counter_exists(self) -> None:
        """Counter for successful connections should exist."""
        assert finnhub_ws_connections_total is not None
        assert "replica_id" in finnhub_ws_connections_total._labelnames

    def test_connected_gauge_exists(self) -> None:
        """Gauge for current connection state should exist."""
        assert finnhub_ws_connected is not None
        assert "replica_id" in finnhub_ws_connected._labelnames

    def test_reconnect_attempts_can_increment(self) -> None:
        """Counter should accept increments with labels."""
        before = finnhub_ws_reconnect_attempts.labels(
            replica_id="test", error_type="ConnectionError"
        )._value.get()
        finnhub_ws_reconnect_attempts.labels(
            replica_id="test", error_type="ConnectionError"
        ).inc()
        after = finnhub_ws_reconnect_attempts.labels(
            replica_id="test", error_type="ConnectionError"
        )._value.get()
        assert after == before + 1

    def test_reconnect_current_gauge_can_set(self) -> None:
        """Gauge should accept set() with labels."""
        finnhub_ws_reconnect_current.labels(replica_id="test").set(5)
        val = finnhub_ws_reconnect_current.labels(replica_id="test")._value.get()
        assert val == 5.0

    def test_connected_gauge_can_toggle(self) -> None:
        """Connected gauge should toggle between 0 and 1."""
        finnhub_ws_connected.labels(replica_id="test").set(1)
        assert finnhub_ws_connected.labels(replica_id="test")._value.get() == 1.0
        finnhub_ws_connected.labels(replica_id="test").set(0)
        assert finnhub_ws_connected.labels(replica_id="test")._value.get() == 0.0
