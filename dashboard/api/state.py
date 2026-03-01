"""
In-memory verdict cache used by the SSE stream when Redis is unavailable.

Updated by the verdict ingest worker (or the /api/v1/verdict webhook).
Keyed by symbol for O(1) upserts.

This module is **read-only from the dashboard's perspective** – only the
constitution/verdict_engine pipeline writes to it.
"""

from __future__ import annotations

from typing import Any

# symbol → latest L12 verdict dict
verdict_cache: dict[str, dict[str, Any]] = {}


def upsert_verdict(verdict: dict[str, Any]) -> None:
    """Insert or replace a verdict in the cache (keyed by symbol)."""
    symbol = verdict.get("symbol")
    if not symbol:
        raise ValueError("Verdict must include 'symbol'")
    verdict_cache[symbol] = verdict


def clear_cache() -> None:
    """Reset the cache (useful in tests)."""
    verdict_cache.clear()
