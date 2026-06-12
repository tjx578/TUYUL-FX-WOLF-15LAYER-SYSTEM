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

import os
import sys
import threading
import time
from collections import defaultdict, deque

from schemas.direction import normalize_direction

__all__ = ["SignalThrottle"]

# Defaults: max 3 EXECUTE signals per 5 minutes per symbol.
# Raw "[SignalThrottle] ... THROTTLED" lines write straight to stderr (not via the
# loguru limiter) and emit at most once per throttle window (window_seconds) per
# symbol so a sustained clamp does not flood platform logs; suppressed repeats fold
# into "suppressed=N". This caps only the LOG line — every throttled event is still
# recorded into SignalThrottleLiveAnalyzer, so log suppression never starves the
# pressure-block builder. Lower SIGNAL_THROTTLE_ERROR_LOG_MIN_INTERVAL_SECONDS only
# for debugging raw radar.
_DEFAULT_MAX_SIGNALS = 3
_DEFAULT_WINDOW_SECONDS = 300.0


def _emit_throttle_error(message: str) -> None:
    """Emit throttle-limit events as plain stderr lines for platform severity."""
    sys.stderr.write(f"{message}\n")
    sys.stderr.flush()


def _emit_throttle_info(message: str) -> None:
    """Emit allowed throttle events as plain stdout lines for info severity."""
    sys.stdout.write(f"{message}\n")
    sys.stdout.flush()


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
        throttle_error_log_min_interval_seconds: float | None = None,
    ) -> None:
        self.max_signals = max_signals
        self.window_seconds = window_seconds
        self.throttle_error_log_min_interval_seconds = _coerce_non_negative_float(
            throttle_error_log_min_interval_seconds,
            env_name="SIGNAL_THROTTLE_ERROR_LOG_MIN_INTERVAL_SECONDS",
            default=self.window_seconds,
        )
        # symbol -> deque of Unix timestamps (ascending)
        self._windows: dict[str, deque[float]] = defaultdict(deque)
        self._last_throttle_error_log_at: dict[str, float] = {}
        self._suppressed_throttle_error_logs: dict[str, int] = defaultdict(int)
        self._allowed_streak_symbol: str | None = None
        self._allowed_streak_direction: str | None = None
        self._allowed_streak_count: int = 0
        self._lock = threading.Lock()

    # ── public API ───────────────────────────────────────

    def is_throttled(self, symbol: str) -> bool:
        """Return True if ``symbol`` has reached the signal rate limit.

        Does NOT mutate state — call :meth:`record` separately after a
        signal is actually emitted.
        """
        normalized_symbol = _normalize_symbol(symbol)
        with self._lock:
            self._purge(normalized_symbol)
            count = len(self._windows[normalized_symbol])
            throttled = count >= self.max_signals
            if throttled:
                self._emit_throttled_log_if_due(normalized_symbol, count, time.time())
            return throttled

    def record(self, symbol: str) -> None:
        """Record an emitted EXECUTE signal for ``symbol``."""
        normalized_symbol = _normalize_symbol(symbol)
        with self._lock:
            self._purge(normalized_symbol)
            self._windows[normalized_symbol].append(time.time())

    def emit_allowed(self, symbol: str, verdict: str) -> None:
        """Emit a plain info event after an EXECUTE signal passes throttle."""
        _emit_throttle_info(f"[SignalThrottle] {symbol} allowed — verdict {verdict}")

    def record_allowed_streak(self, symbol: str, verdict: str) -> int:
        """Track consecutive allowed events by symbol and direction.

        Only allowed events call this method, so stderr throttle/error lines do
        not break the streak.  A different allowed symbol or direction resets it.
        """
        direction = normalize_direction(None, verdict)
        normalized_symbol = _normalize_symbol(symbol)
        with self._lock:
            if (
                direction
                and self._allowed_streak_symbol == normalized_symbol
                and self._allowed_streak_direction == direction
            ):
                self._allowed_streak_count += 1
            else:
                self._allowed_streak_symbol = normalized_symbol if direction else None
                self._allowed_streak_direction = direction
                self._allowed_streak_count = 1 if direction else 0
            return self._allowed_streak_count

    def get_count(self, symbol: str) -> int:
        """Return the current signal count in the active window."""
        normalized_symbol = _normalize_symbol(symbol)
        with self._lock:
            self._purge(normalized_symbol)
            return len(self._windows[normalized_symbol])

    def get_remaining(self, symbol: str) -> int:
        """Return how many signals can still fire before throttling."""
        normalized_symbol = _normalize_symbol(symbol)
        with self._lock:
            self._purge(normalized_symbol)
            return max(0, self.max_signals - len(self._windows[normalized_symbol]))

    def reset(self, symbol: str | None = None) -> None:
        """Clear history.  If *symbol* is None, clear everything."""
        with self._lock:
            if symbol is None:
                self._windows.clear()
                self._last_throttle_error_log_at.clear()
                self._suppressed_throttle_error_logs.clear()
                self._allowed_streak_symbol = None
                self._allowed_streak_direction = None
                self._allowed_streak_count = 0
            else:
                normalized_symbol = _normalize_symbol(symbol)
                self._windows.pop(normalized_symbol, None)
                self._last_throttle_error_log_at.pop(normalized_symbol, None)
                self._suppressed_throttle_error_logs.pop(normalized_symbol, None)
                if self._allowed_streak_symbol == normalized_symbol:
                    self._allowed_streak_symbol = None
                    self._allowed_streak_direction = None
                    self._allowed_streak_count = 0

    # ── internals ────────────────────────────────────────

    def _emit_throttled_log_if_due(self, symbol: str, count: int, now: float) -> None:
        normalized_symbol = _normalize_symbol(symbol)
        last_logged_at = self._last_throttle_error_log_at.get(normalized_symbol)
        min_interval = self.throttle_error_log_min_interval_seconds
        if last_logged_at is not None and min_interval > 0 and (now - last_logged_at) < min_interval:
            self._suppressed_throttle_error_logs[normalized_symbol] += 1
            return

        suppressed = self._suppressed_throttle_error_logs.pop(normalized_symbol, 0)
        suffix = f" suppressed={suppressed}" if suppressed else ""
        _emit_throttle_error(
            f"[SignalThrottle] {normalized_symbol} THROTTLED — {count} signals in last "
            f"{self.window_seconds:.0f}s (max {self.max_signals}){suffix}"
        )
        self._last_throttle_error_log_at[normalized_symbol] = now

    def _purge(self, symbol: str) -> None:
        """Remove entries older than the window.  Caller must hold lock."""
        cutoff = time.time() - self.window_seconds
        q = self._windows[symbol]
        while q and q[0] < cutoff:
            q.popleft()


def _coerce_non_negative_float(value: float | None, *, env_name: str, default: float) -> float:
    raw: str | float = os.getenv(env_name, str(default)) if value is None else value
    try:
        number = float(raw)
    except (TypeError, ValueError):
        number = default
    return max(0.0, number)


def _normalize_symbol(symbol: str) -> str:
    return str(symbol or "").strip().upper()
