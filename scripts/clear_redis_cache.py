#!/usr/bin/env python3
"""
Clear Redis candle cache to reset duplicate detection.

This script deletes all candle_history (LIST) and candle hash (HASH) keys
from Redis, allowing fresh candles to be fetched and written without being
rejected as duplicates.

Key patterns cleared:
    wolf15:candle_history:*   — per-symbol/timeframe candle history lists
    candle_history:*          — legacy candle history lists
    wolf15:candle:*           — per-symbol/timeframe latest-candle hashes
    candles:*                 — legacy latest-candle hashes

Usage:
    python scripts/clear_redis_cache.py
"""

from __future__ import annotations

import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Protocol, cast

# Ensure repository root is importable when executed as
# `python scripts/clear_redis_cache.py`.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import redis  # noqa: E402

from core.redis_keys import CANDLE_HASH_SCAN, CANDLE_HISTORY_SCAN  # noqa: E402
from infrastructure.redis_url import get_redis_url, get_safe_redis_url  # noqa: E402


class SyncRedisClient(Protocol):
    def ping(self) -> object: ...
    def scan_iter(self, match: str, count: int) -> Iterable[str | bytes]: ...
    def delete(self, *names: str) -> int: ...
    def close(self) -> object: ...


_DELETE_BATCH_SIZE = 250

_HISTORY_PATTERNS: tuple[str, ...] = (
    CANDLE_HISTORY_SCAN,
    "candle_history:*",
)
_HASH_PATTERNS: tuple[str, ...] = (
    CANDLE_HASH_SCAN,
    "candles:*",
)


def _delete_batch(client: SyncRedisClient, keys: list[str]) -> int:
    """Delete a non-empty key batch.

    Redis rejects bare ``DEL`` with no keys.  Keep this guard local so future
    edits cannot accidentally recreate the empty-argument failure seen in ops
    logs.
    """
    if not keys:
        return 0
    return client.delete(*keys)


def _delete_scan_pattern(client: SyncRedisClient, pattern: str, *, batch_size: int = _DELETE_BATCH_SIZE) -> int:
    """Scan and delete keys for one pattern without ever sending empty DEL."""
    deleted = 0
    batch: list[str] = []
    for key in client.scan_iter(match=pattern, count=batch_size):
        batch.append(str(key))
        if len(batch) >= batch_size:
            deleted += _delete_batch(client, batch)
            batch = []
    deleted += _delete_batch(client, batch)
    return deleted


def clear_redis_cache() -> tuple[int, int]:
    """Clear Redis candle cache keys.

    Returns:
        Tuple of (candle_history_keys_deleted, candle_hash_keys_deleted).
    """
    url = get_redis_url()
    client = cast(SyncRedisClient, redis.from_url(url, decode_responses=True))

    print(f"🔄 Connecting to Redis: {get_safe_redis_url()}")
    client.ping()
    print("✅ Redis connection OK\n")

    # ── Clear candle_history LIST keys ────────────────────────────────────────
    history_deleted = 0
    for pattern in _HISTORY_PATTERNS:
        print(f"🔍 Scanning for candle history keys ({pattern})...")
        deleted = _delete_scan_pattern(client, pattern)
        history_deleted += deleted
        print(f"   Deleted {deleted} key(s) for {pattern}")

    print(f"✨ Candle history clear complete — {history_deleted} key(s) deleted\n")

    # ── Clear candle HASH keys (latest_candle snapshots) ─────────────────────
    hash_deleted = 0
    for pattern in _HASH_PATTERNS:
        print(f"🔍 Scanning for candle hash keys ({pattern})...")
        deleted = _delete_scan_pattern(client, pattern)
        hash_deleted += deleted
        print(f"   Deleted {deleted} key(s) for {pattern}")

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
