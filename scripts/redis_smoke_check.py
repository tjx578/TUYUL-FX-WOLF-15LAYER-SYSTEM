"""
Redis Smoke Check — Python version (portable, no bash required).
Zone: infrastructure diagnostic — no authority boundary impact.
Run: python scripts/redis_smoke_check.py
"""

from __future__ import annotations

import os
import sys
from urllib.parse import urlparse, urlunparse


def _load_env():
    """Load .env if REDIS_URL not in environment."""
    if "REDIS_URL" not in os.environ:
        env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k.strip(), v.strip())


def _mask(url: str) -> str:
    p = urlparse(url)
    if p.password:
        return url.replace(p.password, "***")
    return url


def _alt_url(redis_url: str, alt_db: int) -> str:
    """Build alternate Redis URL with different DB index using urlunparse (safe for numeric hostnames/ports)."""
    parsed = urlparse(redis_url)
    alt_path = f"/{alt_db}"
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            alt_path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


def main():
    try:
        import redis
        from redis import Redis
    except ImportError:
        print("[FATAL] redis-py not installed. Run: pip install redis")
        sys.exit(1)

    _load_env()
    redis_url = os.environ.get("REDIS_URL", "")
    if not redis_url:
        print("[FATAL] REDIS_URL not set.")
        sys.exit(1)

    # Detect Railway / Render template placeholders that are never substituted
    if "${{" in redis_url or "${" in redis_url:
        print(
            f"[FATAL] REDIS_URL contains an unresolved template variable: {redis_url!r}\n"
            "        This is a Railway/Render deployment placeholder.\n"
            "        To run locally, set REDIS_URL manually:\n"
            "          $env:REDIS_URL = 'redis://:password@host:port/0'\n"
            "        Or edit .env with the real URL before running this script."
        )
        sys.exit(1)

    parsed = urlparse(redis_url)
    raw_path = parsed.path.lstrip("/") or "0"
    try:
        db_index = int(raw_path)
    except ValueError:
        db_index = 0
        print(f"[WARN] Could not parse DB index from URL path {raw_path!r}, defaulting to 0")

    print("=" * 60)
    print(" Wolf-15 Redis Smoke Check (Python)")
    print("=" * 60)
    print(f"[1] REDIS_URL (masked) = {_mask(redis_url)}")
    print(f"[1] DB index           = {db_index}")

    # ── Ping ──────────────────────────────────────────────
    try:
        r: Redis = redis.from_url(str(redis_url), decode_responses=True)  # type: ignore[attr-defined]
        bool(r.ping())  # type: ignore[arg-type]
        print("\n[2] ✅ Redis alive — PONG")
    except Exception as e:
        print(f"\n[2] ❌ Redis unreachable: {e}")
        sys.exit(1)

    # ── Key scan ──────────────────────────────────────────
    print("\n[3] Scanning keys matching *candle* and *wolf15*...")
    found_keys: set[str] = set()
    for pattern in ("*candle*", "*wolf15*"):
        for key in r.scan_iter(pattern, count=200):  # type: ignore[assignment]
            found_keys.add(key if isinstance(key, str) else str(key))  # type: ignore[arg-type]

    if not found_keys:
        print(f"    ❌ NO matching keys in DB{db_index}")
        print("    → Writer is NOT pushing to this DB.")
        print("\n    Cross-checking DB 0 and DB 1...")
        for alt_db in (0, 1):
            if alt_db == db_index:
                continue
            try:
                r_alt = redis.from_url(str(_alt_url(redis_url, alt_db)), decode_responses=True)  # type: ignore[attr-defined]
                count = sum(1 for _key in r_alt.scan_iter("*candle*", count=200))  # type: ignore[var-annotated]
                print(f"    DB{alt_db}: {count} candle keys")
                if count > 0:
                    print(f"    ⚠️  MISMATCH: Writer uses DB{alt_db}, reader uses DB{db_index}")
                    print(f"       → Fix: Set REDIS_URL=.../{alt_db} in analysis-engine .env")
            except Exception as e:
                print(f"    DB{alt_db}: unreachable ({e})")
    else:
        print(f"    Found {len(found_keys)} keys:")
        for k in sorted(found_keys)[:100]:
            print(f"      {k}")

    # ── LLEN probe ────────────────────────────────────────
    print("\n[4] Probing known namespace variants for EURUSD:M15...")
    candidates = [
        "wolf15:candle_history:EURUSD:M15",
        "candle_history:EURUSD:M15",
        "wolf15:candle:EURUSD:M15",
        "candle:EURUSD:M15",
        "ohlcv:EURUSD:M15",
        "wolf15:ohlcv:EURUSD:M15",
        "bars:EURUSD:M15",
        "wolf15:bars:EURUSD:M15",
    ]

    populated: list[str] = []
    for key in candidates:
        try:
            key_type = r.type(key)
            if key_type == "list":
                length = r.llen(key)
            elif key_type == "string":
                length = r.strlen(key)
            elif key_type == "none":
                length = 0
            else:
                length = "N/A"
            marker = "✅" if isinstance(length, int) and length > 0 else "○ "
            print(f"    {marker} {key:<45} LLEN={length}  TYPE={key_type}")
            if marker == "✅":
                populated.append(key)
        except Exception as e:
            print(f"    ✗  {key} → error: {e}")

    # ── Sample ────────────────────────────────────────────
    if populated:
        key = populated[0]
        print(f"\n[5] Sample (LRANGE 0 2) from: {key}")
        samples: list[str] = list(r.lrange(key, 0, 2))  # type: ignore[arg-type]
        for i, s in enumerate(samples):
            preview = s[:120] + "..." if len(s) > 120 else s
            print(f"    [{i}] {preview}")

        ttl = r.ttl(key)
        print(f"\n[6] TTL={ttl}  (-1=no expiry, -2=missing)")
    else:
        print("\n[5] No populated key found.")

    # ── Summary ───────────────────────────────────────────
    print("\n" + "=" * 60)
    print(" DIAGNOSIS SUMMARY")
    print("=" * 60)
    if not found_keys:
        print(f" ROOT CAUSE : Writer not pushing to DB{db_index}")
        print("  NEXT STEP  : Confirm writer's REDIS_URL db index")
    elif populated:
        prefix = populated[0].split(":")[0]
        print(f" ✅ Data found under prefix '{prefix}'")
        print(f"    → Ensure analysis-engine uses CANDLE_KEY_PREFIX={prefix!r}")
    else:
        print(" Keys exist but all empty → writer push type/expiry issue")
        print(" → Check writer uses LPUSH/RPUSH, not SET with expiry 0")
    print("=" * 60)


if __name__ == "__main__":
    main()
