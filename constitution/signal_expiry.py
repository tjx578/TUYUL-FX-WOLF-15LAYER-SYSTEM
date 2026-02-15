"""
Signal expiry enforcement.
Every L12 verdict gets a TTL. Execution must check before placing order.
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger("tuyul.constitution.expiry")

TIMEFRAME_TTL: dict[str, int] = {
    "M1": 60, "M5": 180, "M15": 300, "M30": 600,
    "H1": 1800, "H4": 3600, "D1": 14400, "W1": 43200,
}

DEFAULT_TTL = 300


def assign_expiry(signal: dict, primary_timeframe: str = "H1") -> dict:
    """Attach expires_at to an L12 signal."""
    ttl = TIMEFRAME_TTL.get(primary_timeframe, DEFAULT_TTL)
    signal["expires_at"] = time.time() + ttl
    signal["ttl_seconds"] = ttl
    return signal


def is_signal_valid(signal: dict) -> tuple[bool, str]:
    """Check if signal is within expiry window. Call before execution."""
    expires_at = signal.get("expires_at")
    if expires_at is None:
        return False, "Signal has no expiry timestamp — reject as unsafe"

    now = time.time()
    if now > expires_at:
        elapsed = now - expires_at
        return False, f"Signal expired {elapsed:.1f}s ago"

    remaining = expires_at - now
    if remaining < 10:
        logger.warning(
            "Signal %s expires in %.0fs — urgent",
            signal.get("signal_id", "?"), remaining,
        )

    return True, f"Valid — {remaining:.0f}s remaining"
