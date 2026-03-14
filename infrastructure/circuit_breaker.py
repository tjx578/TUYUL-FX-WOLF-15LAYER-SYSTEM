"""Circuit breaker pattern for resilient external service calls.

Zone: infrastructure/ — shared utility, no business logic.

Implements the classic three-state circuit breaker:
  - CLOSED   : Normal operation; calls pass through.
  - OPEN     : Too many failures detected; calls are blocked and callers
               should use a fallback (e.g. stale cache).
  - HALF_OPEN: Recovery probe; a limited number of calls are allowed
               through to test whether the downstream service has recovered.

All thresholds are configurable via env vars so they can be tuned per
deployment without code changes:

  WOLF15_CB_FAILURE_THRESHOLD    — consecutive failures to trip CLOSED→OPEN
                                   (default: 5)
  WOLF15_CB_RECOVERY_TIMEOUT     — seconds before OPEN→HALF_OPEN probe
                                   (default: 60)
  WOLF15_CB_HALF_OPEN_ATTEMPTS   — successes in HALF_OPEN to close the
                                   circuit (default: 2)

Usage::

    from infrastructure.circuit_breaker import CircuitBreaker, CircuitState

    cb = CircuitBreaker(name="finnhub")

    try:
        result = await fetch_data()
        cb.record_success()
    except Exception as exc:
        cb.record_failure()
        if cb.is_open():
            result = get_stale_cache()
        else:
            raise

    if cb.state == CircuitState.OPEN:
        # degrade gracefully
        ...
"""

from __future__ import annotations

import os
import time
from enum import Enum
from threading import Lock

from loguru import logger


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    """Thread-safe circuit breaker for resilient external service calls.

    Parameters
    ----------
    name:
        Human-readable identifier used in log messages.
    failure_threshold:
        Number of consecutive failures before the circuit trips OPEN.
        Defaults to ``WOLF15_CB_FAILURE_THRESHOLD`` env var (5).
    recovery_timeout:
        Seconds to wait in OPEN state before transitioning to HALF_OPEN
        for a recovery probe.
        Defaults to ``WOLF15_CB_RECOVERY_TIMEOUT`` env var (60).
    half_open_success_threshold:
        Number of consecutive successes in HALF_OPEN state needed to
        transition back to CLOSED.
        Defaults to ``WOLF15_CB_HALF_OPEN_ATTEMPTS`` env var (2).
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int | None = None,
        recovery_timeout: float | None = None,
        half_open_success_threshold: int | None = None,
    ) -> None:
        self.name = name
        self._failure_threshold: int = (
            failure_threshold if failure_threshold is not None
            else int(os.getenv("WOLF15_CB_FAILURE_THRESHOLD", "5"))
        )
        self._recovery_timeout: float = (
            recovery_timeout if recovery_timeout is not None
            else float(os.getenv("WOLF15_CB_RECOVERY_TIMEOUT", "60"))
        )
        self._half_open_success_threshold: int = (
            half_open_success_threshold if half_open_success_threshold is not None
            else int(os.getenv("WOLF15_CB_HALF_OPEN_ATTEMPTS", "2"))
        )
        self._state: CircuitState = CircuitState.CLOSED
        self._failure_count: int = 0
        self._success_count: int = 0
        self._last_failure_time: float | None = None
        self._lock: Lock = Lock()

    # ── public read-only properties ───────────────────────────────────────────

    @property
    def state(self) -> CircuitState:
        """Current circuit state (auto-transitions OPEN→HALF_OPEN when due)."""
        with self._lock:
            return self._get_state_locked()

    @property
    def failure_count(self) -> int:
        """Running failure count in the current window."""
        with self._lock:
            return self._failure_count

    # ── internal helpers ──────────────────────────────────────────────────────

    def _get_state_locked(self) -> CircuitState:
        """Return current state, triggering OPEN→HALF_OPEN if timeout elapsed.

        Must be called while holding ``self._lock``.
        """
        if (
            self._state is CircuitState.OPEN
            and self._last_failure_time is not None
            and time.monotonic() - self._last_failure_time >= self._recovery_timeout
        ):
            self._state = CircuitState.HALF_OPEN
            self._success_count = 0
            logger.info(
                "[CircuitBreaker:{}] OPEN → HALF_OPEN after {:.0f}s timeout",
                self.name,
                self._recovery_timeout,
            )
        return self._state

    # ── public state mutators ─────────────────────────────────────────────────

    def is_open(self) -> bool:
        """Return ``True`` when the circuit is OPEN and calls should be blocked."""
        return self.state is CircuitState.OPEN

    def record_success(self) -> None:
        """Record a successful call, potentially closing the circuit.

        In HALF_OPEN state this counts toward closing the circuit.
        In CLOSED state it resets the failure counter.
        """
        with self._lock:
            state = self._get_state_locked()
            if state is CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self._half_open_success_threshold:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._success_count = 0
                    logger.info(
                        "[CircuitBreaker:{}] HALF_OPEN → CLOSED after {} success(es)",
                        self.name,
                        self._half_open_success_threshold,
                    )
            elif state is CircuitState.CLOSED:
                self._failure_count = 0

    def record_failure(self) -> None:
        """Record a failed call, potentially tripping the circuit OPEN.

        Also resets HALF_OPEN → OPEN if the recovery probe fails.
        """
        with self._lock:
            state = self._get_state_locked()
            self._failure_count += 1
            self._last_failure_time = time.monotonic()

            if (
                state in (CircuitState.CLOSED, CircuitState.HALF_OPEN)
                and self._failure_count >= self._failure_threshold
            ):
                prev = state.value
                self._state = CircuitState.OPEN
                logger.warning(
                    "[CircuitBreaker:{}] {} → OPEN after {} failure(s) — "
                    "will retry after {:.0f}s",
                    self.name,
                    prev,
                    self._failure_count,
                    self._recovery_timeout,
                )

    def reset(self) -> None:
        """Force the circuit back to CLOSED (e.g. after manual intervention)."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._last_failure_time = None
            logger.info(
                "[CircuitBreaker:{}] manually reset to CLOSED",
                self.name,
            )
