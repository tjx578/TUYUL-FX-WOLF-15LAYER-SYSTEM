"""Tests for CircuitBreaker metric integration.

Verifies that CIRCUIT_BREAKER_STATE and CIRCUIT_BREAKER_TRIPS are updated
when the breaker changes state.
"""

from __future__ import annotations

import pytest

from core.metrics import CIRCUIT_BREAKER_STATE, CIRCUIT_BREAKER_TRIPS
from infrastructure.circuit_breaker import CircuitBreaker, CircuitState


@pytest.fixture(autouse=True)
def _reset_cb_metrics():
    """Clear CB metric children between tests."""
    with CIRCUIT_BREAKER_STATE._lock:
        CIRCUIT_BREAKER_STATE._children.clear()
    with CIRCUIT_BREAKER_TRIPS._lock:
        CIRCUIT_BREAKER_TRIPS._children.clear()
    yield


def _get_state_gauge(name: str) -> float:
    key = ((("name", name),))
    child = CIRCUIT_BREAKER_STATE._children.get(key)
    return child.value if child else -1.0


def _get_trip_count(name: str) -> float:
    key = ((("name", name),))
    child = CIRCUIT_BREAKER_TRIPS._children.get(key)
    return child.value if child else 0.0


class TestCBMetrics:
    def test_trip_to_open_sets_gauge_2(self):
        cb = CircuitBreaker("test_svc", failure_threshold=2)
        cb.record_failure()
        cb.record_failure()
        assert cb.state is CircuitState.OPEN
        assert _get_state_gauge("test_svc") == 2.0

    def test_trip_increments_trips_counter(self):
        cb = CircuitBreaker("trip_svc", failure_threshold=1)
        cb.record_failure()
        assert _get_trip_count("trip_svc") == 1.0

    def test_half_open_to_closed_sets_gauge_0(self):
        cb = CircuitBreaker("ho_svc", failure_threshold=1, recovery_timeout=0.0, half_open_success_threshold=1)
        cb.record_failure()  # → OPEN  (gauge=2)
        assert _get_state_gauge("ho_svc") == 2.0

        # Force OPEN→HALF_OPEN by reading state (recovery_timeout=0)
        _ = cb.state
        assert cb.state is CircuitState.HALF_OPEN
        assert _get_state_gauge("ho_svc") == 1.0

        cb.record_success()  # → CLOSED (gauge=0)
        assert cb.state is CircuitState.CLOSED
        assert _get_state_gauge("ho_svc") == 0.0

    def test_open_to_half_open_sets_gauge_1(self):
        cb = CircuitBreaker("half_svc", failure_threshold=1, recovery_timeout=0.0)
        cb.record_failure()  # → OPEN
        _ = cb.state         # triggers OPEN → HALF_OPEN
        assert _get_state_gauge("half_svc") == 1.0

    def test_multiple_trips_counted(self):
        cb = CircuitBreaker("multi", failure_threshold=1, recovery_timeout=0.0, half_open_success_threshold=1)
        # First trip
        cb.record_failure()
        assert _get_trip_count("multi") == 1.0
        # Recover
        _ = cb.state
        cb.record_success()
        assert cb.state is CircuitState.CLOSED
        # Second trip
        cb.record_failure()
        assert _get_trip_count("multi") == 2.0
