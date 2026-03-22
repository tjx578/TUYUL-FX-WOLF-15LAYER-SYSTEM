"""
Finnhub API Key Rotation Manager
=================================

Centralises Finnhub API key access and provides automatic rotation on
HTTP 429 (rate-limit) or 401/403 (revoked key) responses.

Environment variables
---------------------
  FINNHUB_API_KEY           Primary key (required).
  FINNHUB_API_KEY_SECONDARY Optional fallback key.
  FINNHUB_API_KEYS          Comma-separated list (overrides the above two if set).

Usage
-----
    from ingest.finnhub_key_manager import finnhub_keys

    key = finnhub_keys.current_key()          # get active key
    finnhub_keys.report_failure(key, 429)      # mark key as rate-limited
    next_key = finnhub_keys.current_key()      # automatically rotated

Design constraints:
  - Pure utility — no market logic, no execution authority.
  - Thread-safe (keys may be read from async + sync contexts).
  - Falls back gracefully to single-key mode when no secondary is set.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Final

from loguru import logger

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Cooldown before a rate-limited key is retried (seconds).
_DEFAULT_COOLDOWN_SEC: Final[int] = 65
_COOLDOWN_SEC: int = int(os.getenv("FINNHUB_KEY_COOLDOWN_SEC", str(_DEFAULT_COOLDOWN_SEC)))


@dataclass
class _KeyState:
    """Per-key health tracking."""

    key: str
    failures: int = 0
    last_failure_time: float = 0.0
    # True while the key is in cooldown (rate-limited or auth-failed).
    suspended: bool = False
    suspend_until: float = 0.0


class FinnhubKeyManager:
    """Thread-safe Finnhub API key manager with rotation on failure.

    Keys are loaded once from env vars at construction time.  If only a
    single key is configured, rotation is a no-op and `current_key()`
    always returns that key (even after failures — there is no better
    option).
    """

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._keys: list[_KeyState] = []
        self._active_index: int = 0
        self._load_keys()

    # ── Bootstrap ──────────────────────────────────────────────────

    def _load_keys(self) -> None:
        """Load keys from environment variables (priority order).

        1. ``FINNHUB_API_KEYS`` (comma-separated) — highest priority.
        2. ``FINNHUB_API_KEY`` + optional ``FINNHUB_API_KEY_SECONDARY``.
        """
        raw_keys = os.getenv("FINNHUB_API_KEYS", "").strip()

        if raw_keys:
            unique: list[str] = []
            for k in raw_keys.split(","):
                k = k.strip()
                if k and k not in unique:
                    unique.append(k)
            self._keys = [_KeyState(key=k) for k in unique]
        else:
            primary = os.getenv("FINNHUB_API_KEY", "").strip()
            secondary = os.getenv("FINNHUB_API_KEY_SECONDARY", "").strip()

            if primary and primary != "YOUR_FINNHUB_API_KEY":
                self._keys.append(_KeyState(key=primary))
            if secondary and secondary != primary:
                self._keys.append(_KeyState(key=secondary))

        if not self._keys:
            logger.warning(
                "[FINNHUB-KEY] No Finnhub API keys configured — all Finnhub features will run in dry-run / mock mode."
            )
        elif len(self._keys) == 1:
            logger.info("[FINNHUB-KEY] Single API key loaded (no rotation available).")
        else:
            logger.info(
                "[FINNHUB-KEY] %d API keys loaded — rotation enabled.",
                len(self._keys),
            )

    # ── Public API ─────────────────────────────────────────────────

    @property
    def available(self) -> bool:
        """True if at least one key is configured."""
        return len(self._keys) > 0

    def current_key(self) -> str:
        """Return the active API key.

        If the active key is in cooldown and a healthy alternative exists,
        rotation happens transparently.

        Returns:
            The API key string, or ``""`` if no keys are configured.
        """
        if not self._keys:
            return ""

        now = time.monotonic()
        with self._lock:
            state = self._keys[self._active_index]

            # If current key is suspended but cooldown has elapsed, unsuspend.
            if state.suspended and now >= state.suspend_until:
                state.suspended = False
                logger.info(
                    "[FINNHUB-KEY] Key #%d cooldown expired — re-enabling.",
                    self._active_index,
                )

            # If current key is still suspended, try to rotate.
            if state.suspended and len(self._keys) > 1:
                rotated = self._rotate_locked(now)
                if rotated:
                    return self._keys[self._active_index].key

            # Single-key mode: warn when key is in cooldown (no alternative).
            if state.suspended and len(self._keys) == 1:
                remaining = max(0.0, state.suspend_until - now)
                if remaining > 0:
                    logger.warning(
                        "[FINNHUB-KEY] Single key sedang cooldown (%.0fs sisa) — request berikutnya mungkin 429",
                        remaining,
                    )

            return state.key

    def report_failure(self, key: str, status_code: int) -> None:
        """Report an API failure for a key.

        Suspends the key on 429 / 401 / 403 and attempts rotation.

        Args:
            key: The exact key string that caused the failure.
            status_code: HTTP status code from Finnhub.
        """
        if status_code not in {401, 403, 429}:
            return

        now = time.monotonic()
        with self._lock:
            idx = self._find_key_index(key)
            if idx is None:
                return

            state = self._keys[idx]
            state.failures += 1
            state.last_failure_time = now
            state.suspended = True

            if status_code == 429:
                cooldown = _COOLDOWN_SEC
                reason = "rate-limited"
            else:
                # Auth failure — longer cooldown, key may be permanently bad.
                cooldown = _COOLDOWN_SEC * 5
                reason = f"auth-error ({status_code})"

            state.suspend_until = now + cooldown

            logger.warning(
                "[FINNHUB-KEY] Key #%d %s (total failures: %d). Suspended for %ds.",
                idx,
                reason,
                state.failures,
                cooldown,
            )

            # Attempt rotation if this was the active key.
            if idx == self._active_index and len(self._keys) > 1:
                self._rotate_locked(now)

    def report_success(self, key: str) -> None:
        """Report a successful API call — resets failure counter."""
        with self._lock:
            idx = self._find_key_index(key)
            if idx is not None:
                state = self._keys[idx]
                if state.failures > 0:
                    state.failures = 0
                    state.suspended = False
                    logger.debug(
                        "[FINNHUB-KEY] Key #%d recovered — failures reset.",
                        idx,
                    )

    def get_all_keys(self) -> list[str]:
        """Return all configured keys (order-preserved). For diagnostics only."""
        return [ks.key for ks in self._keys]

    @property
    def key_count(self) -> int:
        return len(self._keys)

    @property
    def active_index(self) -> int:
        return self._active_index

    def status(self) -> list[dict[str, Any]]:
        """Return diagnostic status for all keys (safe for logging — keys masked)."""
        now = time.monotonic()
        result: list[dict[str, Any]] = []
        with self._lock:
            for i, ks in enumerate(self._keys):
                result.append(
                    {
                        "index": i,
                        "active": i == self._active_index,
                        "masked_key": ks.key[:4] + "****" + ks.key[-4:] if len(ks.key) > 8 else "****",
                        "failures": ks.failures,
                        "suspended": ks.suspended,
                        "cooldown_remaining_sec": max(0, round(ks.suspend_until - now, 1)) if ks.suspended else 0,
                    }
                )
        return result

    # ── Internal ───────────────────────────────────────────────────

    def _find_key_index(self, key: str) -> int | None:
        for i, ks in enumerate(self._keys):
            if ks.key == key:
                return i
        return None

    def _rotate_locked(self, now: float) -> bool:
        """Try to switch to the next healthy key. Must be called under lock.

        Returns True if rotation succeeded.
        """
        n = len(self._keys)
        for offset in range(1, n):
            candidate = (self._active_index + offset) % n
            state = self._keys[candidate]

            # Unsuspend if cooldown has elapsed.
            if state.suspended and now >= state.suspend_until:
                state.suspended = False

            if not state.suspended:
                old = self._active_index
                self._active_index = candidate
                logger.info(
                    "[FINNHUB-KEY] Rotated from key #%d to key #%d.",
                    old,
                    candidate,
                )
                return True

        logger.warning("[FINNHUB-KEY] All keys are suspended — no rotation possible.")
        return False


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

finnhub_keys = FinnhubKeyManager()
