"""Canonical pipeline candle minimums, shared with read-only API reporting.

These are analysis-gate minimums, not ingestion fetch targets or permission to
issue a trade. M15 is excluded; W1/MN provide the long-term regime context.
"""

WARMUP_MIN_BARS: dict[str, int] = {"H1": 30, "H4": 10, "D1": 5, "W1": 5, "MN": 2}
