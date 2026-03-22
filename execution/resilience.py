from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from typing import TypeVar

T = TypeVar("T")


class CircuitBreakerOpenError(RuntimeError):
    pass


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 4
    base_delay_sec: float = 0.25
    max_delay_sec: float = 8.0
    jitter_ratio: float = 0.25


class SimpleCircuitBreaker:
    """Minimal circuit breaker for external API calls."""

    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        recovery_timeout_sec: float = 30.0,
    ) -> None:
        super().__init__()
        self._failure_threshold = max(1, int(failure_threshold))
        self._recovery_timeout_sec = max(1.0, float(recovery_timeout_sec))
        self._failures = 0
        self._opened_at = 0.0
        self._lock = Lock()

    def before_call(self) -> None:
        with self._lock:
            if self._opened_at <= 0:
                return
            elapsed = time.time() - self._opened_at
            if elapsed >= self._recovery_timeout_sec:
                self._opened_at = 0.0
                self._failures = 0
                return
            raise CircuitBreakerOpenError(f"Circuit breaker OPEN for {self._recovery_timeout_sec - elapsed:.1f}s")

    def on_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = 0.0

    def on_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self._failure_threshold:
                self._opened_at = time.time()


def call_with_retry(
    operation: Callable[[], T],
    *,
    policy: RetryPolicy,
    breaker: SimpleCircuitBreaker | None = None,
    is_retryable: Callable[[Exception], bool] | None = None,
) -> T:
    """Execute operation with exponential backoff + jitter and optional breaker."""
    attempts = max(1, int(policy.max_attempts))
    last_exc: Exception | None = None

    for attempt in range(1, attempts + 1):
        if breaker is not None:
            breaker.before_call()

        try:
            result = operation()
            if breaker is not None:
                breaker.on_success()
            return result
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if breaker is not None:
                breaker.on_failure()

            retryable = is_retryable(exc) if is_retryable is not None else True
            if attempt >= attempts or not retryable:
                raise

            exp_delay = min(
                policy.max_delay_sec,
                policy.base_delay_sec * (2 ** (attempt - 1)),
            )
            jitter = exp_delay * policy.jitter_ratio * random.random()
            time.sleep(exp_delay + jitter)

    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Retry wrapper exited unexpectedly")
