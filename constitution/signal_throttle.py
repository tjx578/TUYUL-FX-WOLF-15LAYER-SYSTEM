"""
Signal rate throttle — prevents rapid consecutive EXECUTE verdicts for the
same symbol.

This is a **constitutional safety clamp**, not a market decision.  It sits
downstream of Layer-12's verdict and downgrade-enforces HOLD when too many
actionable signals fire in a short window.

Design
------
* Sliding-window counter per symbol.
* Configurable: ``max_signals`` in ``window_seconds``.
* Thread-safe (``threading.Lock``).
* Pure in-memory — no Redis dependency (stateless restart is acceptable;
  the risk of one extra signal after restart is lower than the risk of
  Redis failure blocking all signals).

Usage::

    from constitution.signal_throttle import SignalThrottle

    throttle = SignalThrottle(max_signals=3, window_seconds=300)

    # After L12 produces an EXECUTE verdict:
    if throttle.is_throttled("EURUSD"):
        verdict = "HOLD"  # downgrade
    else:
        throttle.record("EURUSD")
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque

logger = logging.getLogger("tuyul.constitution.throttle")

# Defaults: max 3 EXECUTE signals per 5 minutes per symbol
_DEFAULT_MAX_SIGNALS = 3
_DEFAULT_WINDOW_SECONDS = 300.0


class SignalThrottle:
    """Sliding-window signal rate limiter per symbol.

    Parameters
    ----------
    max_signals : int
        Maximum EXECUTE verdicts allowed per symbol within the window.
    window_seconds : float
        Length of the sliding window in seconds.
    """

    def __init__(
        self,
        max_signals: int = _DEFAULT_MAX_SIGNALS,
        window_seconds: float = _DEFAULT_WINDOW_SECONDS,
    ) -> None:
        self.max_signals = max_signals
        self.window_seconds = window_seconds
        # symbol -> deque of Unix timestamps (ascending)
        self._windows: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    # ── public API ───────────────────────────────────────

    def is_throttled(self, symbol: str) -> bool:
        """Return True if ``symbol`` has reached the signal rate limit.

        Does NOT mutate state — call :meth:`record` separately after a
        signal is actually emitted.
        """
        with self._lock:
            self._purge(symbol)
            count = len(self._windows[symbol])
            throttled = count >= self.max_signals
            if throttled:
                logger.warning(
                    "[SignalThrottle] %s THROTTLED — %d signals in last %.0fs (max %d)",
                    symbol,
                    count,
                    self.window_seconds,
                    self.max_signals,
                )
            return throttled

    def record(self, symbol: str) -> None:
        """Record an emitted EXECUTE signal for ``symbol``."""
        with self._lock:
            self._purge(symbol)
            self._windows[symbol].append(time.time())

    def get_count(self, symbol: str) -> int:
        """Return the current signal count in the active window."""
        with self._lock:
            self._purge(symbol)
            return len(self._windows[symbol])

    def get_remaining(self, symbol: str) -> int:
        """Return how many signals can still fire before throttling."""
        with self._lock:
            self._purge(symbol)
            return max(0, self.max_signals - len(self._windows[symbol]))

    def reset(self, symbol: str | None = None) -> None:
        """Clear history.  If *symbol* is None, clear everything."""
        with self._lock:
            if symbol is None:
                self._windows.clear()
            else:
                self._windows.pop(symbol, None)

    # ── internals ────────────────────────────────────────

    def _purge(self, symbol: str) -> None:
        """Remove entries older than the window.  Caller must hold lock."""
        cutoff = time.time() - self.window_seconds
        q = self._windows[symbol]
        while q and q[0] < cutoff:
            q.popleft()
