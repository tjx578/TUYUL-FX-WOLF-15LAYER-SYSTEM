#!/usr/bin/env python3
"""
TUYUL FX Wolf-15 — Emergency Warmup Injector.

Bypasses stale_cache logic by directly seeding H1/H4 bars
from Finnhub REST API into Redis candle_history lists.

Usage:
    railway run python warmup_inject.py

Requires env vars:
    REDIS_URL       — Railway Redis URL
    FINNHUB_API_KEY — Finnhub API key
"""

import json
import os
import sys
import time
from typing import cast

import redis
import requests

# ── Config ────────────────────────────────────────────────────

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
FINNHUB_KEY = os.getenv("FINNHUB_API_KEY", "")

PAIRS = [
    "OANDA:EUR_USD",
    "OANDA:GBP_USD",
    "OANDA:USD_JPY",
    "OANDA:USD_CHF",
    "OANDA:AUD_USD",
    "OANDA:NZD_USD",
    "OANDA:USD_CAD",
    "OANDA:EUR_GBP",
    "OANDA:EUR_JPY",
    "OANDA:GBP_JPY",
    "OANDA:CHF_JPY",
    "OANDA:EUR_CHF",
    "OANDA:AUD_JPY",
    "OANDA:GBP_CHF",
    "OANDA:EUR_AUD",
    "OANDA:EUR_CAD",
    "OANDA:AUD_NZD",
    "OANDA:GBP_AUD",
    "OANDA:GBP_CAD",
    "OANDA:GBP_NZD",
    "OANDA:CAD_JPY",
    "OANDA:NZD_JPY",
    "OANDA:AUD_CAD",
    "OANDA:AUD_CHF",
    "OANDA:NZD_CAD",
    "OANDA:NZD_CHF",
    "OANDA:EUR_NZD",
    "OANDA:USD_SGD",
    "OANDA:USD_HKD",
    "OANDA:XAU_USD",
]


# Map: Finnhub symbol → Redis symbol (strip OANDA: and underscores)
def to_redis_symbol(finnhub_sym: str) -> str:
    """OANDA:EUR_USD → EURUSD"""
    return finnhub_sym.replace("OANDA:", "").replace("_", "")


# Timeframes to seed: {tf_name: (finnhub_resolution, bars_to_fetch)}
TIMEFRAMES = {
    "H1": ("60", 50),
    "H4": ("240", 30),
}

# ── Main ──────────────────────────────────────────────────────


def main():
    if not FINNHUB_KEY:
        print("❌ FINNHUB_API_KEY not set!")
        sys.exit(1)

    print("=" * 60)
    print("🐺 TUYUL FX — Emergency Warmup Injector")
    print("=" * 60)
    print(f"Redis: {REDIS_URL[:40]}...")
    print(f"Pairs: {len(PAIRS)}")
    print(f"Timeframes: {list(TIMEFRAMES.keys())}")
    print()

    # Connect Redis
    r = redis.from_url(REDIS_URL, decode_responses=False)
    try:
        r.ping()
        print("✅ Redis connected")
    except Exception as e:
        print(f"❌ Redis failed: {e}")
        sys.exit(1)

    total_seeded = 0
    total_skipped = 0
    errors = []

    for pair in PAIRS:
        redis_sym = to_redis_symbol(pair)

        for tf, (resolution, bars_needed) in TIMEFRAMES.items():
            key = f"wolf15:candle_history:{redis_sym}:{tf}"

            # Check existing count
            try:
                existing = cast(int, r.llen(key))
            except Exception:
                existing = 0

            if existing >= bars_needed:
                print(f"  ⏭  {redis_sym}/{tf}: {existing} bars (sufficient)")
                total_skipped += 1
                continue

            # Fetch from Finnhub REST
            now = int(time.time())
            since = now - (bars_needed * int(resolution) * 60)

            try:
                resp = requests.get(
                    "https://finnhub.io/api/v1/forex/candle",
                    params={
                        "symbol": pair,
                        "resolution": resolution,
                        "from": since,
                        "to": now,
                        "token": FINNHUB_KEY,
                    },
                    timeout=15,
                )
                data = resp.json()

                if data.get("s") != "ok" or "t" not in data:
                    print(f"  ⚠️  {redis_sym}/{tf}: Finnhub returned '{data.get('s', 'error')}'")
                    errors.append(f"{redis_sym}/{tf}: {data.get('s', 'no data')}")
                    continue

                # Build candle list
                candles = []
                for i in range(len(data["t"])):
                    candles.append(
                        json.dumps(
                            {
                                "symbol": redis_sym,
                                "timeframe": tf,
                                "open": data["o"][i],
                                "high": data["h"][i],
                                "low": data["l"][i],
                                "close": data["c"][i],
                                "volume": data["v"][i],
                                "timestamp": data["t"][i],
                            }
                        )
                    )

                if not candles:
                    print(f"  ⚠️  {redis_sym}/{tf}: 0 candles returned")
                    continue

                # Write to Redis (atomic pipeline)
                pipe = r.pipeline(transaction=True)
                # Delete existing (might be corrupt/stale)
                pipe.delete(key)
                # Push all candles
                for c in candles:
                    pipe.rpush(key, c)
                # Trim + TTL
                pipe.ltrim(key, -300, -1)
                pipe.expire(key, 8 * 3600)  # 8h TTL (longer than default 6h)
                pipe.execute()

                new_count = cast(int, r.llen(key))
                print(f"  ✅ {redis_sym}/{tf}: seeded {len(candles)} bars (was {existing}, now {new_count})")
                total_seeded += len(candles)

            except requests.exceptions.RequestException as e:
                print(f"  ❌ {redis_sym}/{tf}: HTTP error: {e}")
                errors.append(f"{redis_sym}/{tf}: {e}")
            except Exception as e:
                print(f"  ❌ {redis_sym}/{tf}: {e}")
                errors.append(f"{redis_sym}/{tf}: {e}")

            # Rate limit: Finnhub free tier = 30 calls/sec
            time.sleep(0.1)

    # ── Summary ───────────────────────────────────────────────
    print()
    print("=" * 60)
    print(f"📊 RESULT: {total_seeded} bars seeded, {total_skipped} skipped")

    if errors:
        print(f"\n⚠️  {len(errors)} errors:")
        for e in errors[:10]:
            print(f"  • {e}")

    # Verify warmup status
    print("\n📋 WARMUP STATUS:")
    for tf in TIMEFRAMES:
        counts = []
        for pair in PAIRS:
            sym = to_redis_symbol(pair)
            key = f"wolf15:candle_history:{sym}:{tf}"
            try:
                c = cast(int, r.llen(key))
                counts.append(c)
            except Exception:
                counts.append(0)

        min_c = min(counts) if counts else 0
        max_c = max(counts) if counts else 0
        sufficient = sum(1 for c in counts if c >= TIMEFRAMES[tf][1])
        print(f"  {tf}: min={min_c}, max={max_c}, " f"sufficient={sufficient}/{len(PAIRS)}")

    r.close()
    print("\n✅ Done.")


if __name__ == "__main__":
    main()
