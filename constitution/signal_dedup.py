"""
Signal deduplication — prevents duplicate execution from repeated pipeline runs.
Uses a hash of (symbol, direction, entry, sl, timeframe, candle_time) as key.
"""

from __future__ import annotations

import hashlib
import logging
import time

logger = logging.getLogger("tuyul.constitution.dedup")


class SignalDeduplicator:
    """
    In-memory dedup with TTL-based cleanup.
    For production persistence, back with Redis.
    """

    def __init__(self, window_seconds: float = 600.0, redis_client=None):
        self._window = window_seconds
        self._seen: dict[str, float] = {}  # hash -> timestamp
        self._redis = redis_client

    def compute_hash(self, signal: dict) -> str:
        """
        Create deterministic hash from signal core fields.
        Same market setup on same candle = same hash.
        """
        parts = [
            str(signal.get("symbol", "")),
            str(signal.get("direction", "")),
            f"{signal.get('entry_price', 0):.5f}",
            f"{signal.get('stop_loss', 0):.5f}",
            str(signal.get("primary_timeframe", "")),
        ]
        raw = "|".join(parts)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def is_duplicate(self, signal: dict) -> tuple[bool, str]:
        """
        Check if this signal was already emitted within the dedup window.
        Returns (is_dup, hash).
        """
        self._cleanup()
        sig_hash = self.compute_hash(signal)

        # Check Redis first (if available, for multi-process)
        if self._redis:
            redis_key = f"tuyul:dedup:{sig_hash}"
            if self._redis.exists(redis_key):
                logger.info(f"Duplicate signal detected (Redis): {sig_hash}")
                return True, sig_hash

        # Check in-memory
        if sig_hash in self._seen:
            logger.info(f"Duplicate signal detected (memory): {sig_hash}")
            return True, sig_hash

        return False, sig_hash

    def register(self, signal: dict) -> str:
        """Mark signal as emitted. Must be called after successful emit."""
        sig_hash = self.compute_hash(signal)
        self._seen[sig_hash] = time.time()

        if self._redis:
            redis_key = f"tuyul:dedup:{sig_hash}"
            self._redis.setex(redis_key, int(self._window), "1")

        return sig_hash

    def _cleanup(self) -> None:
        cutoff = time.time() - self._window
        self._seen = {h: t for h, t in self._seen.items() if t > cutoff}
