"""Tests for infrastructure.circuit_breaker."""

from __future__ import annotations

import time

import pytest

from infrastructure.circuit_breaker import CircuitBreaker, CircuitState

# ══════════════════════════════════════════════════════════════════════
#  Initial state
# ══════════════════════════════════════════════════════════════════════


class TestCircuitBreakerInitialState:
    def test_starts_closed(self) -> None:
        cb = CircuitBreaker(name="test")
        assert cb.state is CircuitState.CLOSED

    def test_starts_with_zero_failures(self) -> None:
        cb = CircuitBreaker(name="test")
        assert cb.failure_count == 0

    def test_is_not_open_initially(self) -> None:
        cb = CircuitBreaker(name="test")
        assert cb.is_open() is False


# ══════════════════════════════════════════════════════════════════════
#  CLOSED → OPEN transitions
# ══════════════════════════════════════════════════════════════════════


class TestCircuitBreakerTripping:
    def test_trips_open_at_threshold(self) -> None:
        cb = CircuitBreaker(name="test", failure_threshold=3, recovery_timeout=60)
        for _ in range(3):
            cb.record_failure()
        assert cb.state is CircuitState.OPEN
        assert cb.is_open() is True

    def test_stays_closed_below_threshold(self) -> None:
        cb = CircuitBreaker(name="test", failure_threshold=3, recovery_timeout=60)
        cb.record_failure()
        cb.record_failure()
        assert cb.state is CircuitState.CLOSED

    def test_success_resets_failure_count_in_closed(self) -> None:
        cb = CircuitBreaker(name="test", failure_threshold=3, recovery_timeout=60)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.failure_count == 0
        assert cb.state is CircuitState.CLOSED

    def test_single_failure_threshold(self) -> None:
        cb = CircuitBreaker(name="test", failure_threshold=1, recovery_timeout=60)
        cb.record_failure()
        assert cb.state is CircuitState.OPEN


# ══════════════════════════════════════════════════════════════════════
#  OPEN → HALF_OPEN transition (recovery timeout)
# ══════════════════════════════════════════════════════════════════════


class TestCircuitBreakerRecovery:
    def test_transitions_to_half_open_after_timeout(self) -> None:
        cb = CircuitBreaker(name="test", failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure()
        assert cb.state is CircuitState.OPEN
        time.sleep(0.05)
        assert cb.state is CircuitState.HALF_OPEN

    def test_stays_open_before_timeout(self) -> None:
        cb = CircuitBreaker(name="test", failure_threshold=1, recovery_timeout=9999)
        cb.record_failure()
        assert cb.state is CircuitState.OPEN

    def test_half_open_failure_reopens_circuit(self) -> None:
        cb = CircuitBreaker(name="test", failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure()
        time.sleep(0.05)
        assert cb.state is CircuitState.HALF_OPEN
        cb.record_failure()
        assert cb.state is CircuitState.OPEN


# ══════════════════════════════════════════════════════════════════════
#  HALF_OPEN → CLOSED transition (probe success)
# ══════════════════════════════════════════════════════════════════════


class TestCircuitBreakerClose:
    def test_closes_after_required_successes(self) -> None:
        cb = CircuitBreaker(
            name="test",
            failure_threshold=1,
            recovery_timeout=0.01,
            half_open_success_threshold=2,
        )
        cb.record_failure()
        time.sleep(0.05)
        assert cb.state is CircuitState.HALF_OPEN
        cb.record_success()
        assert cb.state is CircuitState.HALF_OPEN  # still needs one more
        cb.record_success()
        assert cb.state is CircuitState.CLOSED

    def test_single_success_threshold_closes_immediately(self) -> None:
        cb = CircuitBreaker(
            name="test",
            failure_threshold=1,
            recovery_timeout=0.01,
            half_open_success_threshold=1,
        )
        cb.record_failure()
        time.sleep(0.05)
        cb.record_success()
        assert cb.state is CircuitState.CLOSED

    def test_failure_count_reset_after_close(self) -> None:
        cb = CircuitBreaker(
            name="test",
            failure_threshold=1,
            recovery_timeout=0.01,
            half_open_success_threshold=1,
        )
        cb.record_failure()
        time.sleep(0.05)
        cb.record_success()
        assert cb.failure_count == 0


# ══════════════════════════════════════════════════════════════════════
#  Manual reset
# ══════════════════════════════════════════════════════════════════════


class TestCircuitBreakerReset:
    def test_reset_clears_open_state(self) -> None:
        cb = CircuitBreaker(name="test", failure_threshold=1, recovery_timeout=9999)
        cb.record_failure()
        assert cb.state is CircuitState.OPEN
        cb.reset()
        assert cb.state is CircuitState.CLOSED

    def test_reset_clears_failure_count(self) -> None:
        cb = CircuitBreaker(name="test", failure_threshold=5, recovery_timeout=9999)
        for _ in range(4):
            cb.record_failure()
        cb.reset()
        assert cb.failure_count == 0


# ══════════════════════════════════════════════════════════════════════
#  Env-var configuration
# ══════════════════════════════════════════════════════════════════════


class TestCircuitBreakerEnvConfig:
    def test_failure_threshold_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WOLF15_CB_FAILURE_THRESHOLD", "2")
        cb = CircuitBreaker(name="test", recovery_timeout=9999)
        cb.record_failure()
        assert cb.state is CircuitState.CLOSED
        cb.record_failure()
        assert cb.state is CircuitState.OPEN

    def test_explicit_param_overrides_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WOLF15_CB_FAILURE_THRESHOLD", "2")
        cb = CircuitBreaker(name="test", failure_threshold=5, recovery_timeout=9999)
        for _ in range(4):
            cb.record_failure()
        assert cb.state is CircuitState.CLOSED

    def test_zero_recovery_timeout_allowed(self) -> None:
        """recovery_timeout=0 must not be silently treated as unset (None check, not or)."""
        cb = CircuitBreaker(name="test", failure_threshold=1, recovery_timeout=0.0)
        assert cb._recovery_timeout == 0.0

    def test_zero_failure_threshold_allowed(self) -> None:
        """failure_threshold=0 must not be silently replaced by the env default."""
        cb = CircuitBreaker(name="test", failure_threshold=0, recovery_timeout=9999)
        assert cb._failure_threshold == 0
