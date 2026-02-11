"""One-shot fix: set TTL on all existing Wolf15 hash keys missing expiry.

Run once: python scripts/fix_redis_ttl_existing.py
"""

import os
import redis # pyright: ignore[reportMissingImports]

LATEST_TICK_TTL = 60
CANDLE_HASH_TTL = 14400  # 4h


def main() -> None:
    url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    r = redis.from_url(url, decode_responses=True)
    r.ping()
    print("✅ Connected to Redis")

    fixed = 0

    # Fix latest_tick hashes
    for key in r.scan_iter(match="wolf15:latest_tick:*", count=100):
        if r.ttl(key) == -1:
            r.expire(key, LATEST_TICK_TTL)
            fixed += 1
            print(f"  🔧 {key} → TTL {LATEST_TICK_TTL}s")

    # Fix candle hashes
    for key in r.scan_iter(match="wolf15:candle:*", count=100):
        if r.ttl(key) == -1:
            r.expire(key, CANDLE_HASH_TTL)
            fixed += 1
            print(f"  🔧 {key} → TTL {CANDLE_HASH_TTL}s")

    print(f"\n🐺 Done. Fixed {fixed} keys.")
    r.close()


if __name__ == "__main__":
    main()
