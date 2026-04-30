#!/usr/bin/env python3
"""
Clear Redis candle cache to reset duplicate detection.

This script deletes all candle_history (LIST) and candle hash (HASH) keys
from Redis, allowing fresh candles to be fetched and written without being
rejected as duplicates.

Key patterns cleared:
    wolf15:candle_history:*   — per-symbol/timeframe candle history lists
    wolf15:candle:*           — per-symbol/timeframe latest-candle hashes

Usage:
    python scripts/clear_redis_cache.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure repository root is importable when executed as
# `python scripts/clear_redis_cache.py`.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import redis  # noqa: E402

from core.redis_keys import CANDLE_HASH_SCAN, CANDLE_HISTORY_SCAN  # noqa: E402
from infrastructure.redis_url import get_redis_url, get_safe_redis_url  # noqa: E402


def clear_redis_cache() -> tuple[int, int]:
    """Clear Redis candle cache keys.

    Returns:
        Tuple of (candle_history_keys_deleted, candle_hash_keys_deleted).
    """
    url = get_redis_url()
    client = redis.from_url(url, decode_responses=True)

    print(f"🔄 Connecting to Redis: {get_safe_redis_url()}")
    client.ping()
    print("✅ Redis connection OK\n")

    # ── Clear candle_history LIST keys ────────────────────────────────────────
    print(f"🔍 Scanning for candle history keys ({CANDLE_HISTORY_SCAN})...")
    history_deleted = 0

    for key in client.scan_iter(match=CANDLE_HISTORY_SCAN, count=100):
        client.delete(key)
        history_deleted += 1
        if history_deleted % 10 == 0:
            print(f"   Deleted {history_deleted} candle_history keys...")

    print(f"✨ Candle history clear complete — {history_deleted} key(s) deleted\n")

    # ── Clear candle HASH keys (latest_candle snapshots) ─────────────────────
    print(f"🔍 Scanning for candle hash keys ({CANDLE_HASH_SCAN})...")
    hash_deleted = 0

    for key in client.scan_iter(match=CANDLE_HASH_SCAN, count=100):
        client.delete(key)
        hash_deleted += 1
        if hash_deleted % 10 == 0:
            print(f"   Deleted {hash_deleted} candle hash keys...")

    print(f"✨ Candle hash clear complete — {hash_deleted} key(s) deleted\n")

    # ── Summary ───────────────────────────────────────────────────────────────
    total = history_deleted + hash_deleted
    print("📈 SUMMARY")
    print(f"   candle_history keys deleted : {history_deleted}")
    print(f"   candle hash keys deleted    : {hash_deleted}")
    print(f"   total keys deleted          : {total}")

    client.close()
    return history_deleted, hash_deleted


if __name__ == "__main__":
    try:
        clear_redis_cache()
        print("\n✅ Redis candle cache cleared successfully.")
        print("   Restart the ingest service (or wait for the next REST poll)")
        print("   to repopulate with fresh candles.")
    except Exception as exc:
        print(f"\n❌ Error clearing Redis cache: {exc}")
        sys.exit(1)
