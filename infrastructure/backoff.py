"""
Exponential backoff with jitter.

Zone: infrastructure/ — shared utility, no business logic.
"""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass
class BackoffConfig:
    """Exponential backoff configuration."""

    initial: float = 1.0  # First delay in seconds
    maximum: float = 60.0  # Cap
    factor: float = 2.0  # Multiplier per attempt
    jitter: float = 0.25  # ±25% randomization to prevent thundering herd

    def __post_init__(self) -> None:
        if self.initial <= 0:
            raise ValueError(f"initial must be positive, got {self.initial}")
        if self.maximum < self.initial:
            raise ValueError(f"maximum ({self.maximum}) must be >= initial ({self.initial})")
        if self.factor < 1.0:
            raise ValueError(f"factor must be >= 1.0, got {self.factor}")
        if not (0.0 <= self.jitter <= 1.0):
            raise ValueError(f"jitter must be in [0.0, 1.0], got {self.jitter}")


class ExponentialBackoff:
    """
    Stateful exponential backoff calculator with jitter.

    Usage:
        backoff = ExponentialBackoff()
        delay = backoff.next_delay()   # 1.0 ± jitter
        delay = backoff.next_delay()   # 2.0 ± jitter
        delay = backoff.next_delay()   # 4.0 ± jitter
        backoff.reset()                # back to initial
    """

    def __init__(self, config: BackoffConfig | None = None) -> None:
        self._config = config or BackoffConfig()
        self._attempt: int = 0

    @property
    def attempt(self) -> int:
        return self._attempt

    def next_delay(self) -> float:
        """Calculate next backoff delay and advance attempt counter."""
        base = min(
            self._config.initial * (self._config.factor**self._attempt),
            self._config.maximum,
        )
        self._attempt += 1

        if self._config.jitter > 0:
            jitter_range = base * self._config.jitter
            base += random.uniform(-jitter_range, jitter_range)
            base = max(0.1, base)  # Never sleep < 0.1s

        return min(base, self._config.maximum)

    def reset(self) -> None:
        """Reset attempt counter (call after successful connection)."""
        self._attempt = 0  # noqa: W292
