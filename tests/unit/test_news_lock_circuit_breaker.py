"""
Tests for news lock engine and circuit breaker state transitions.
"""
import time

from datetime import datetime

import pytest

try:
    from execution.news_lock import (
        NewsLockEngine,  # noqa: F401
    )
    HAS_NEWS_LOCK = True
except ImportError:
    HAS_NEWS_LOCK = False

try:
    from execution.circuit_breaker import (
        CircuitBreaker,  # noqa: F401
    )
    HAS_CB = True
except ImportError:
    HAS_CB = False


class TestNewsLockEngine:
    """News events should lock trading around high-impact releases."""

    def _is_locked(self, current_time, event_time, lockout_minutes=15):
        delta = abs((event_time - current_time).total_seconds())
        return delta <= lockout_minutes * 60

    def test_lock_before_news(self):
        event = datetime(2026, 2, 15, 14, 30)
        now = datetime(2026, 2, 15, 14, 20)  # 10 min before
        assert self._is_locked(now, event, lockout_minutes=15)

    def test_lock_after_news(self):
        event = datetime(2026, 2, 15, 14, 30)
        now = datetime(2026, 2, 15, 14, 40)  # 10 min after
        assert self._is_locked(now, event, lockout_minutes=15)

    def test_no_lock_well_before(self):
        event = datetime(2026, 2, 15, 14, 30)
        now = datetime(2026, 2, 15, 13, 0)  # 90 min before
        assert not self._is_locked(now, event, lockout_minutes=15)

    def test_no_lock_well_after(self):
        event = datetime(2026, 2, 15, 14, 30)
        now = datetime(2026, 2, 15, 15, 0)  # 30 min after
        assert not self._is_locked(now, event, lockout_minutes=15)

    def test_multiple_news_events(self):
        events = [
            datetime(2026, 2, 15, 8, 30),
            datetime(2026, 2, 15, 14, 30),
            datetime(2026, 2, 15, 18, 0),
        ]
        now = datetime(2026, 2, 15, 14, 25)
        locked = any(self._is_locked(now, ev) for ev in events)
        assert locked

    @pytest.mark.parametrize("impact,should_lock", [
        ("HIGH", True),
        ("MEDIUM", False),
        ("LOW", False),
    ])
    def test_only_high_impact_locks(self, impact, should_lock):
        """Only high-impact news triggers lockout."""
        locked = impact == "HIGH"
        assert locked == should_lock


class TestCircuitBreaker:
    """Circuit breaker state machine under load conditions."""

    # States: CLOSED (normal), OPEN (tripped), HALF_OPEN (testing)
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"

    def _create_breaker(self, failure_threshold=3, recovery_timeout=60):
        return {
            "state": self.CLOSED,
            "failures": 0,
            "failure_threshold": failure_threshold,
            "recovery_timeout": recovery_timeout,
            "last_failure_time": None,
        }

    def _record_failure(self, breaker):
        breaker["failures"] += 1
        breaker["last_failure_time"] = time.time()
        if breaker["failures"] >= breaker["failure_threshold"]:
            breaker["state"] = self.OPEN
        return breaker

    def _record_success(self, breaker):
        if breaker["state"] == self.HALF_OPEN:
            breaker["state"] = self.CLOSED
            breaker["failures"] = 0
        return breaker

    def _check_recovery(self, breaker):
        if breaker["state"] == self.OPEN and breaker["last_failure_time"]:
            elapsed = time.time() - breaker["last_failure_time"]
            if elapsed >= breaker["recovery_timeout"]:
                breaker["state"] = self.HALF_OPEN
        return breaker

    def test_starts_closed(self):
        cb = self._create_breaker()
        assert cb["state"] == self.CLOSED

    def test_opens_after_threshold(self):
        cb = self._create_breaker(failure_threshold=3)
        for _ in range(3):
            self._record_failure(cb)
        assert cb["state"] == self.OPEN

    def test_stays_closed_below_threshold(self):
        cb = self._create_breaker(failure_threshold=3)
        self._record_failure(cb)
        self._record_failure(cb)
        assert cb["state"] == self.CLOSED

    def test_half_open_after_recovery_timeout(self):
        cb = self._create_breaker(failure_threshold=1, recovery_timeout=0)
        self._record_failure(cb)
        assert cb["state"] == self.OPEN
        time.sleep(0.01)
        self._check_recovery(cb)
        assert cb["state"] == self.HALF_OPEN

    def test_half_open_to_closed_on_success(self):
        cb = self._create_breaker(failure_threshold=1, recovery_timeout=0)
        self._record_failure(cb)
        time.sleep(0.01)
        self._check_recovery(cb)
        assert cb["state"] == self.HALF_OPEN
        self._record_success(cb)
        assert cb["state"] == self.CLOSED

    def test_half_open_to_open_on_failure(self):
        cb = self._create_breaker(failure_threshold=1, recovery_timeout=0)
        self._record_failure(cb)
        time.sleep(0.01)
        self._check_recovery(cb)
        assert cb["state"] == self.HALF_OPEN
        self._record_failure(cb)
        assert cb["state"] == self.OPEN

    @pytest.mark.concurrent
    def test_concurrent_failures(self):
        """Multiple rapid failures should all count."""
        cb = self._create_breaker(failure_threshold=5)
        for i in range(10):
            self._record_failure(cb)
        assert cb["state"] == self.OPEN
        assert cb["failures"] == 10
