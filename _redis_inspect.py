"""Temporary script to inspect Redis keys for conflicts."""
from __future__ import annotations

from typing import Any, cast

import redis

r: redis.Redis[str] = redis.Redis.from_url(  # type: ignore[assignment]
    "redis://localhost:6379/0", decode_responses=True
)

try:
    r.ping()  # type: ignore[reportUnknownMemberType]
    print("=== PING: OK ===")
except Exception as e:
    print(f"=== PING FAILED: {e} ===")
    exit(1)

# 1) All keys
keys: list[str] = cast(list[str], r.keys("*"))  # type: ignore[reportUnknownMemberType]
print(f"\n=== ALL KEYS ({len(keys)}) ===")
for k in sorted(keys):
    print(f"  {k}")

# 2) Type + TTL + size of every key
print("\n=== KEY DETAILS ===")
for k in sorted(keys):
    t: str = cast(str, r.type(k))
    ttl: int = cast(int, r.ttl(k))
    size: Any
    try:
        if t == "list":
            size = r.llen(k)
        elif t == "set":
            size = r.scard(k)
        elif t == "hash":
            size = r.hlen(k)
        elif t == "zset":
            size = r.zcard(k)
        elif t == "stream":
            size = r.xlen(k)
        elif t == "string":
            size = len(cast(str, r.get(k)) or "")
        else:
            size = "?"
    except Exception:
        size = "?"
    print(f"  {k:<50s}  type={t:<8s}  ttl={ttl:>8}  size={size}")

# 3) Specifically check requested keys
print("\n=== SPECIFIC KEY CHECK ===")
check_keys: list[str] = ["candles:EURUSD:M15", "wolf:pipeline:EURUSD", "consumer:group:wolf15"]
for k in check_keys:
    if r.exists(k):
        t = cast(str, r.type(k))
        print(f"  {k}: type={t}")
        if t == "stream":
            info: dict[str, Any] = cast(dict[str, Any], r.xinfo_stream(k))
            groups: list[dict[str, Any]] = cast(list[dict[str, Any]], r.xinfo_groups(k))
            print(f"    stream length={info['length']}, groups={len(groups)}")
            for g in groups:
                print(f"    group: {g['name']}, pending={g['pending']}, "
                      f"consumers={g['consumers']}, last-delivered={g['last-delivered-id']}")
        elif t == "string":
            val: str | None = cast(str | None, r.get(k))
            print(f"    value (first 200 chars): {str(val)[:200]}")
        elif t == "hash":
            fields: dict[str, str] = cast(dict[str, str], r.hgetall(k))  # type: ignore[reportUnknownMemberType]
            print(f"    fields: {list(fields.keys())[:20]}")
        elif t == "list":
            print(f"    length: {r.llen(k)}, first 3: {cast(list[str], r.lrange(k, 0, 2))}")  # type: ignore[reportUnknownMemberType]
        elif t == "set":
            print(f"    members (first 10): {list(cast(set[str], r.smembers(k)))[:10]}")  # type: ignore[reportUnknownMemberType]
        elif t == "zset":
            print(f"    count: {r.zcard(k)}, first 3: {cast(list[Any], r.zrange(k, 0, 2, withscores=True))}")  # type: ignore[reportUnknownMemberType]
    else:
        print(f"  {k}: DOES NOT EXIST")
