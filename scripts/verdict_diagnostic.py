#!/usr/bin/env python
"""
P0 Verdict Diagnostic — runtime proof that L12 verdicts are being written.

Checks:
    1. Redis keys L12:VERDICT:<PAIR> exist
    2. Each key contains valid JSON with expected fields
    3. _cached_at timestamp is present and recent (not stale)
    4. Redis Stream stream:l12_verdict has entries
    5. All configured pairs have verdicts

Usage:
    # From repo root (requires REDIS_URL or REDIS_HOST env):
    python scripts/verdict_diagnostic.py

    # With explicit Redis URL:
    REDIS_URL=redis://:pass@host:6379/0 python scripts/verdict_diagnostic.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# ---------------------------------------------------------------------------
# Section helpers
# ---------------------------------------------------------------------------

_PASS = "\033[92m[PASS]\033[0m"
_FAIL = "\033[91m[FAIL]\033[0m"
_WARN = "\033[93m[WARN]\033[0m"
_INFO = "\033[94m[INFO]\033[0m"

STALE_THRESHOLD_SEC = 300  # 5 minutes — same as is_verdict_stale() default


def _age_str(cached_at: float) -> str:
    age = time.time() - cached_at
    if age < 60:
        return f"{age:.1f}s ago"
    if age < 3600:
        return f"{age / 60:.1f}m ago"
    return f"{age / 3600:.1f}h ago"


def main() -> int:
    # ------------------------------------------------------------------
    # 1. Connect to Redis
    # ------------------------------------------------------------------
    from storage.redis_client import redis_client  # noqa: E402

    try:
        redis_client.ping()
        print(f"{_PASS} Redis connection OK")
    except Exception as exc:
        print(f"{_FAIL} Redis connection FAILED: {exc}")
        return 1

    # Access underlying redis.Redis instance for commands not on the wrapper
    raw: Any = redis_client.client

    # ------------------------------------------------------------------
    # 2. Load configured pairs
    # ------------------------------------------------------------------
    from config_loader import load_pairs  # noqa: E402

    pairs = [str(p.get("symbol", "")).upper() for p in load_pairs() if p.get("enabled", True) and p.get("symbol")]
    print(f"{_INFO} Configured pairs ({len(pairs)}): {', '.join(pairs)}")

    # ------------------------------------------------------------------
    # 3. Scan L12:VERDICT:* keys
    # ------------------------------------------------------------------
    cursor, found_keys = 0, []
    while True:
        cursor, keys = raw.scan(cursor, match="L12:VERDICT:*", count=100)
        found_keys.extend(k.decode() if isinstance(k, bytes) else k for k in keys)
        if cursor == 0:
            break

    if not found_keys:
        print(f"{_FAIL} No L12:VERDICT:* keys found in Redis!")
        print("       Engine has not written any verdicts — or keys expired (TTL=3600s).")
        return 1

    print(f"{_PASS} Found {len(found_keys)} verdict key(s): {', '.join(sorted(found_keys))}")

    # ------------------------------------------------------------------
    # 4. Check each key: valid JSON, expected fields, _cached_at freshness
    # ------------------------------------------------------------------
    missing_pairs: list[str] = []
    stale_pairs: list[str] = []
    healthy_pairs: list[str] = []
    verdicts_summary: list[dict] = []

    for pair in pairs:
        key = f"L12:VERDICT:{pair}"
        raw = redis_client.get(key)
        if not raw:
            missing_pairs.append(pair)
            continue

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            print(f"{_FAIL} {key}: invalid JSON!")
            continue

        verdict = data.get("verdict", "?")
        confidence = data.get("confidence", "?")
        cached_at = data.get("_cached_at")

        if cached_at is None:
            print(f"{_WARN} {key}: missing _cached_at — legacy entry")
            stale_pairs.append(pair)
            continue

        age = time.time() - float(cached_at)
        fresh = age <= STALE_THRESHOLD_SEC

        if fresh:
            healthy_pairs.append(pair)
        else:
            stale_pairs.append(pair)

        status = _PASS if fresh else _WARN
        print(
            f"{status} {pair}: verdict={verdict}  confidence={confidence}  "
            f"cached_at={_age_str(float(cached_at))}  age={age:.0f}s"
        )
        verdicts_summary.append({"pair": pair, "verdict": verdict, "confidence": confidence, "age_s": round(age, 1)})

    # ------------------------------------------------------------------
    # 5. Report missing pairs
    # ------------------------------------------------------------------
    if missing_pairs:
        print(f"{_FAIL} Missing verdicts for {len(missing_pairs)} pair(s): {', '.join(missing_pairs)}")

    # ------------------------------------------------------------------
    # 6. Check Redis Stream
    # ------------------------------------------------------------------
    stream_key = "stream:l12_verdict"
    stream_len = raw.xlen(stream_key)
    if stream_len > 0:
        print(f"{_PASS} Verdict stream '{stream_key}' has {stream_len} entries")
        # Show last entry timestamp
        last = raw.xrevrange(stream_key, count=1)
        if last:
            entry_id, fields = last[0]
            entry_id_str = entry_id.decode() if isinstance(entry_id, bytes) else entry_id
            ts_ms = int(entry_id_str.split("-")[0])
            print(f"       Last stream entry: {_age_str(ts_ms / 1000)}")
    else:
        print(f"{_WARN} Verdict stream '{stream_key}' is empty (no durable events)")

    # ------------------------------------------------------------------
    # 7. Summary
    # ------------------------------------------------------------------
    print()
    print("=" * 60)
    total = len(pairs)
    print(f"  Configured pairs : {total}")
    print(f"  Healthy (fresh)  : {len(healthy_pairs)}")
    print(f"  Stale (>5min)    : {len(stale_pairs)}")
    print(f"  Missing (no key) : {len(missing_pairs)}")
    print(f"  Stream entries   : {stream_len}")
    print("=" * 60)

    if missing_pairs or (stale_pairs and not healthy_pairs):
        print(f"{_FAIL} VERDICT WRITE PATH NOT HEALTHY")
        return 1

    if stale_pairs:
        print(f"{_WARN} Some verdicts are stale — engine may be under load")
        return 0

    print(f"{_PASS} ALL VERDICTS HEALTHY — write path confirmed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
