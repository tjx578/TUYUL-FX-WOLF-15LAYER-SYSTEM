"""Download Redis for Windows (if needed), start it, then inspect all keys."""
from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
import zipfile
from typing import Any  # noqa: UP035

import redis

REDIS_DIR = os.path.join(os.environ["LOCALAPPDATA"], "Redis")
REDIS_EXE = os.path.join(REDIS_DIR, "redis-server.exe")
OUTPUT     = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_redis_output.txt")
URL        = "redis://localhost:6379/0"

# ── 1. Install ──
if not os.path.isfile(REDIS_EXE):
    os.makedirs(REDIS_DIR, exist_ok=True)
    dl = "https://github.com/tporadowski/redis/releases/download/v5.0.14.1/Redis-x64-5.0.14.1.zip"
    zp = os.path.join(REDIS_DIR, "redis.zip")
    print(f"Downloading {dl} ...")
    urllib.request.urlretrieve(dl, zp)
    with zipfile.ZipFile(zp) as z:
        z.extractall(REDIS_DIR)
    os.remove(zp)
    print(f"Redis installed → {REDIS_DIR}")
else:
    print(f"Redis found at {REDIS_EXE}")

# ── 2. Start server ──


def ping() -> bool:
    try:
        client: redis.Redis[str] = redis.Redis.from_url(URL, decode_responses=True)  # type: ignore[assignment]
        return bool(client.ping())  # type: ignore[arg-type]
    except Exception:
        return False


if not ping():
    print("Starting redis-server ...")
    subprocess.Popen([REDIS_EXE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=0x08000000)          # CREATE_NO_WINDOW
    for _ in range(30):
        time.sleep(0.5)
        if ping():
            break
    else:
        sys.exit("redis-server did not become ready in 15 s")
print("PING OK\n")

# ── 3. Inspect ──
r: redis.Redis[str] = redis.Redis.from_url(URL, decode_responses=True)  # type: ignore[assignment]

lines: list[str] = []


def p(msg: str = "") -> None:
    print(msg)
    lines.append(msg)


all_keys: list[str] = sorted(r.keys("*"))  # type: ignore[arg-type]
p(f"=== ALL KEYS ({len(all_keys)}) ===")
for k in all_keys:
    p(f"  {k}")

p("\n=== KEY DETAILS ===")
for k in all_keys:
    t: str = str(r.type(k))
    key_ttl: int = int(r.ttl(k))  # type: ignore[arg-type]
    try:
        sz: Any = (
            r.llen(k)   if t == "list"   else
            r.scard(k)  if t == "set"    else
            r.hlen(k)   if t == "hash"   else
            r.zcard(k)  if t == "zset"   else
            r.xlen(k)   if t == "stream" else
            len(str(r.get(k) or "")) if t == "string" else "?"
        )
    except Exception:
        sz = "?"
    p(f"  {k:<55s}  type={t:<8s}  ttl={key_ttl:>8}  size={sz}")

p("\n=== SPECIFIC KEY CHECK ===")
for k in ["candles:EURUSD:M15", "wolf:pipeline:EURUSD", "consumer:group:wolf15"]:
    if not r.exists(k):
        p(f"  {k}: DOES NOT EXIST")
        continue
    t = str(r.type(k))
    p(f"  {k}: type={t}")
    if t == "stream":
        info: dict[str, Any] = r.xinfo_stream(k)  # type: ignore[assignment]
        grps: list[dict[str, Any]] = r.xinfo_groups(k)  # type: ignore[assignment]
        p(f"    length={info['length']}, groups={len(grps)}")
        for g in grps:
            p(f"      group={g['name']}  pending={g['pending']}  consumers={g['consumers']}  last-id={g['last-delivered-id']}")
    elif t == "string":
        p(f"    value={str(r.get(k))[:300]}")
    elif t == "hash":
        hdata: dict[str, str] = r.hgetall(k)  # type: ignore[assignment]
        p(f"    fields={list(hdata.keys())[:30]}")
    elif t == "list":
        llen_val: int = r.llen(k)  # type: ignore[assignment]
        lrange_val: list[str] = r.lrange(k, 0, 2)  # type: ignore[assignment]
        p(f"    len={llen_val} first3={lrange_val}")
    elif t == "set":
        smembers_val: list[str] = list(r.smembers(k))  # type: ignore[arg-type]
        p(f"    members={smembers_val[:15]}")
    elif t == "zset":
        zcard_val: int = r.zcard(k)  # type: ignore[assignment]
        zrange_val: list[Any] = r.zrange(k, 0, 2, withscores=True)  # type: ignore[assignment]
        p(f"    card={zcard_val} first3={zrange_val}")

with open(OUTPUT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print(f"\n>>> Output saved to {OUTPUT}")
