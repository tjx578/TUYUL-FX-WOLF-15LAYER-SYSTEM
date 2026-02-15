"""
Signal expiry enforcement.
Every L12 verdict gets a TTL. Execution must check before placing order.
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger("tuyul.constitution.expiry")

# Default TTL per timeframe (seconds)
TIMEFRAME_TTL = {
    "M1": 60,
    "M5": 180,
    "M15": 300,      # 5 minutes
    "M30": 600,
    "H1": 1800,      # 30 minutes
    "H4": 3600,      # 1 hour
    "D1": 14400,     # 4 hours
    "W1": 43200,     # 12 hours
}

DEFAULT_TTL = 300  # 5 minutes fallback


def assign_expiry(signal: dict, primary_timeframe: str = "H1") -> dict:
    """
    Attach expires_at to an L12 signal based on primary timeframe.
    Called by verdict_engine BEFORE emitting signal.
    """
    ttl = TIMEFRAME_TTL.get(primary_timeframe, DEFAULT_TTL)
    signal["expires_at"] = time.time() + ttl
    signal["ttl_seconds"] = ttl
    return signal


def is_signal_valid(signal: dict) -> tuple[bool, str]:
    """
    Check if signal is still within its expiry window.
    Called by execution/dashboard BEFORE placing order.
    """
    expires_at = signal.get("expires_at")
    if expires_at is None:
        return False, "Signal has no expiry timestamp — reject as unsafe"

    now = time.time()
    if now > expires_at:
        elapsed = now - expires_at
        return False, f"Signal expired {elapsed:.1f}s ago"

    remaining = expires_at - now
    if remaining < 10:
        logger.warning(f"Signal {signal.get('signal_id', '?')} expires in {remaining:.0f}s — urgent")

    return True, f"Valid — {remaining:.0f}s remaining"
