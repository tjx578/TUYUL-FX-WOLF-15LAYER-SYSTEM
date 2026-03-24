#!/usr/bin/env python3
"""
TUYUL FX Wolf-15 — Warmup Injector v2 (Dual-Zone).

Seeds M15/H1/H4 bars from Finnhub REST API into Redis candle_history.
Bypasses stale_cache logic for cold-start and post-flush recovery.

v2 changes from v1:
  - Added M15 seeding (TRQ engine needs >=30 bars)
  - Added M5 seeding (TRQ Quad coupling needs >=10 bars)
  - Skips M1 (builds from ticks within 1-2 minutes)
  - Added --force flag to overwrite existing data
  - Added --verify-only mode for health checks
  - Deterministic candle format matching MicroCandleChain output

Usage:
    railway run -s wolf15-ingest python warmup_inject.py
    railway run -s wolf15-ingest python warmup_inject.py --force
    railway run -s wolf15-ingest python warmup_inject.py --verify-only

Requires env vars:
    REDIS_URL       — Railway Redis URL
    FINNHUB_API_KEY — Finnhub API key
"""
from __future__ import annotations

import argparse
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

# Timeframes: {name: (finnhub_resolution, bars_to_fetch, min_required, consumer)}
TIMEFRAMES = {
    "M5": ("5", 60, 10, "TRQ Quad coupling"),
    "M15": ("15", 100, 30, "TRQ engine (Zone A)"),
    "H1": ("60", 50, 20, "Pipeline gate (Zone B)"),
    "H4": ("240", 30, 10, "Pipeline gate (Zone B)"),
}

# Expand calendar lookback beyond pure bar math, especially for HTF where
# weekends and broker feed gaps can reduce returned bars.
LOOKBACK_MULTIPLIER = {
    "M5": 2.0,
    "M15": 2.5,
    "H1": 6.0,
    "H4": 12.0,
}

MAX_FETCH_RETRIES = 3


def to_redis_symbol(finnhub_sym: str) -> str:
    """OANDA:EUR_USD → EURUSD"""
    return finnhub_sym.replace("OANDA:", "").replace("_", "")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TUYUL FX Warmup Injector v2 (Dual-Zone)")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing data even if sufficient",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only check warmup status, do not seed",
    )
    parser.add_argument(
        "--timeframes",
        nargs="+",
        choices=list(TIMEFRAMES.keys()),
        default=list(TIMEFRAMES.keys()),
        help="Timeframes to seed (default: all)",
    )
    return parser.parse_args()


def verify_warmup(r: redis.Redis, selected_tfs: list[str]) -> dict:
    """Check warmup status for all pairs and timeframes."""
    status = {}
    for tf in selected_tfs:
        _, _, min_required, consumer = TIMEFRAMES[tf]
        counts = []
        insufficient = []
        for pair in PAIRS:
            sym = to_redis_symbol(pair)
            key = f"wolf15:candle_history:{sym}:{tf}"
            try:
                c = cast(int, r.llen(key))
            except Exception:
                c = 0
            counts.append(c)
            if c < min_required:
                insufficient.append(f"{sym}({c})")

        status[tf] = {
            "min": min(counts) if counts else 0,
            "max": max(counts) if counts else 0,
            "sufficient": sum(1 for c in counts if c >= min_required),
            "total": len(PAIRS),
            "min_required": min_required,
            "consumer": consumer,
            "insufficient": insufficient[:5],
        }
    return status


def seed_timeframe(
    r: redis.Redis,
    pair: str,
    tf: str,
    force: bool = False,
) -> tuple[int, str | None]:
    """Seed one pair/timeframe. Returns (bars_seeded, error_or_None)."""
    resolution, bars_to_fetch, min_required, _ = TIMEFRAMES[tf]
    redis_sym = to_redis_symbol(pair)
    key = f"wolf15:candle_history:{redis_sym}:{tf}"

    # Check existing
    try:
        existing = cast(int, r.llen(key))
    except Exception:
        existing = 0

    if existing >= min_required and not force:
        return 0, None  # sufficient, skip

    # Fetch from Finnhub
    now = int(time.time())
    lookback_seconds = int(bars_to_fetch * int(resolution) * 60 * LOOKBACK_MULTIPLIER.get(tf, 2.0))
    since = now - lookback_seconds

    try:
        resp = None
        data = None
        last_http_error = None

        for attempt in range(1, MAX_FETCH_RETRIES + 1):
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
                break
            except requests.exceptions.RequestException as exc:
                last_http_error = exc
                if attempt == MAX_FETCH_RETRIES:
                    raise
                time.sleep(0.5 * attempt)

        if resp is None or data is None:
            if last_http_error:
                raise last_http_error
            return 0, "Finnhub: no response"

        if resp.status_code != 200:
            detail = data.get("error") or data.get("s") or resp.reason
            return 0, f"Finnhub HTTP {resp.status_code}: {detail}"

        if data.get("s") != "ok" or "t" not in data:
            detail = data.get("error") or data.get("s") or "error"
            return 0, f"Finnhub: {detail}"

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
                        "ts_open": data["t"][i],
                    }
                )
            )

        if not candles:
            return 0, "0 candles returned"

        # Atomic write
        pipe = r.pipeline(transaction=True)
        if force:
            pipe.delete(key)
        for c in candles:
            pipe.rpush(key, c)
        pipe.ltrim(key, -500, -1)
        pipe.expire(key, 8 * 3600)
        pipe.execute()

        return len(candles), None

    except requests.exceptions.RequestException as e:
        return 0, f"HTTP: {e}"
    except Exception as e:
        return 0, str(e)


def main() -> None:
    args = parse_args()

    if not FINNHUB_KEY.strip():
        print("❌ FINNHUB_API_KEY is not set. Aborting warmup.")
        print("   Set FINNHUB_API_KEY in the same shell before running this script.")
        sys.exit(1)

    print("=" * 60)
    print("🐺 TUYUL FX — Warmup Injector v2 (Dual-Zone)")
    print("=" * 60)
    print(f"Redis:      {REDIS_URL[:40]}...")
    print(f"Pairs:      {len(PAIRS)}")
    print(f"Timeframes: {args.timeframes}")
    print(f"Mode:       {'VERIFY ONLY' if args.verify_only else 'FORCE' if args.force else 'NORMAL'}")
    print()

    # Connect Redis
    r = redis.from_url(REDIS_URL, decode_responses=False)
    try:
        r.ping()
        print("✅ Redis connected\n")
    except Exception as e:
        print(f"❌ Redis failed: {e}")
        sys.exit(1)

    # ── Verify current status ────────────────────────────────
    print("📋 CURRENT WARMUP STATUS:")
    status = verify_warmup(r, args.timeframes)
    all_ready = True
    for tf, st in status.items():
        icon = "✅" if st["sufficient"] == st["total"] else "⚠️"
        if st["sufficient"] < st["total"]:
            all_ready = False
        print(
            f"  {icon} {tf:4s}: {st['sufficient']}/{st['total']} pairs "
            f"ready (min={st['min']}, max={st['max']}, "
            f"need≥{st['min_required']}) → {st['consumer']}"
        )
        if st["insufficient"]:
            print(f"        Missing: {', '.join(st['insufficient'])}")

    if args.verify_only:
        print(f"\n{'✅ All ready' if all_ready else '⚠️  Warmup needed'}")
        r.close()
        return

    if all_ready and not args.force:
        print("\n✅ All timeframes sufficiently seeded. Use --force to override.")
        r.close()
        return

    # ── Seed ─────────────────────────────────────────────────
    print(f"\n{'🔄 SEEDING (force mode)' if args.force else '🔄 SEEDING'}...")
    total_seeded = 0
    total_skipped = 0
    errors = []

    for tf in args.timeframes:
        print(f"\n  ── {tf} ({TIMEFRAMES[tf][3]}) ──")
        for pair in PAIRS:
            sym = to_redis_symbol(pair)
            seeded, err = seed_timeframe(r, pair, tf, args.force)

            if err:
                print(f"    ❌ {sym}: {err}")
                errors.append(f"{sym}/{tf}: {err}")
            elif seeded > 0:
                print(f"    ✅ {sym}: +{seeded} bars")
                total_seeded += seeded
            else:
                total_skipped += 1

            time.sleep(0.1)  # Finnhub rate limit

    # ── Final verification ───────────────────────────────────
    print(f"\n{'=' * 60}")
    print(f"📊 RESULT: {total_seeded} bars seeded, {total_skipped} skipped")
    if errors:
        print(f"\n⚠️  {len(errors)} errors:")
        for e in errors[:10]:
            print(f"    • {e}")

    print("\n📋 POST-SEED WARMUP STATUS:")
    status = verify_warmup(r, args.timeframes)
    for tf, st in status.items():
        icon = "✅" if st["sufficient"] == st["total"] else "⚠️"
        print(
            f"  {icon} {tf:4s}: {st['sufficient']}/{st['total']} pairs "
            f"ready (min={st['min']}, max={st['max']}, "
            f"need≥{st['min_required']}) → {st['consumer']}"
        )

    r.close()
    print("\n✅ Done.")


if __name__ == "__main__":
    main()
