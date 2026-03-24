"""Direction normalization utility.

Single source of truth for converting internal direction/verdict values
to the execution direction required by the signal contract boundary.

Signal contract allows only: "BUY", "SELL", or None.
Internal pipeline may use "HOLD", "NEUTRAL", "NO_TRADE", etc.
This module ensures those never leak to execution boundaries.
"""

from __future__ import annotations

__all__ = ["normalize_direction"]

_VALID_DIRECTIONS = frozenset({"BUY", "SELL"})


def normalize_direction(
    raw_direction: str | None,
    raw_verdict: str | None = None,
) -> str | None:
    """Normalize a direction value for signal contract boundaries.

    Args:
        raw_direction: Raw direction string (may be BUY, SELL, HOLD, NEUTRAL, etc.)
        raw_verdict: Optional verdict string to infer direction from
            (e.g. EXECUTE_BUY, EXECUTE_SELL).

    Returns:
        "BUY", "SELL", or None. Non-executable values always become None.
    """
    d = (raw_direction or "").strip().upper()
    if d in _VALID_DIRECTIONS:
        return d

    v = (raw_verdict or "").strip().upper()
    if "EXECUTE_BUY" in v or "EXECUTE_REDUCED_RISK_BUY" in v:
        return "BUY"
    if "EXECUTE_SELL" in v or "EXECUTE_REDUCED_RISK_SELL" in v:
        return "SELL"

    # HOLD / NO_TRADE / NEUTRAL / ABORT / empty → no execution direction
    return None
