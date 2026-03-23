#!/usr/bin/env python3
"""
TUYUL FX — Redis diagnostic + cleanup
============================================================
Run on Railway:
    railway run -s wolf15-engine python redis_diagnostic.py
============================================================
"""

import json
import logging
import os
import sys
import time
from typing import Any, cast

import redis

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
)
logger = logging.getLogger("redis_diagnostic")

SYMBOLS = [
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "USDCHF",
    "USDCAD",
    "AUDUSD",
    "NZDUSD",
    "EURGBP",
    "EURJPY",
    "EURCHF",
    "EURAUD",
    "EURCAD",
    "EURNZD",
    "GBPJPY",
    "GBPCHF",
    "GBPAUD",
    "GBPCAD",
    "GBPNZD",
    "AUDJPY",
    "AUDNZD",
    "AUDCAD",
    "AUDCHF",
    "NZDJPY",
    "NZDCHF",
    "NZDCAD",
    "CADJPY",
    "CADCHF",
    "CHFJPY",
    "XAUUSD",
    "XAGUSD",
]

TIMEFRAME = "M15"
REQUIRED_BARS = 2
INJECT_BARS = 5


def main() -> None:
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    logger.info("Connecting to Redis: %s", redis_url[:30] + "...")

    r = cast(Any, redis.from_url(redis_url, decode_responses=True, socket_timeout=10))

    # --- Step 1: Connectivity ---
    try:
        r.ping()
        logger.info("Step 1 — Redis PING: OK")
    except Exception as exc:
        logger.error("Step 1 — Redis connection FAILED: %s", exc)
        sys.exit(1)

    # --- Step 2: Identify WRONGTYPE keys ---
    logger.info("Step 2 — Scanning for WRONGTYPE conflicts...")
    wrongtype_keys: list[str] = []
    cursor = 0
    while True:
        scan_result = r.scan(cursor=cursor, match="wolf15:candle:*", count=200)
        cursor, keys = scan_result
        for key in keys:
            if "candle_history" in key:
                continue
            if r.type(key) == "hash":
                wrongtype_keys.append(key)
        if cursor == 0:
            break

    if wrongtype_keys:
        logger.warning("Found %d HASH keys blocking LRANGE:", len(wrongtype_keys))
        for k in wrongtype_keys[:10]:
            logger.warning("  → %s", k)
        if len(wrongtype_keys) > 10:
            logger.warning("  ... and %d more", len(wrongtype_keys) - 10)
    else:
        logger.info("No WRONGTYPE conflicts found.")

    # --- Step 3: Cleanup stale HASH keys ---
    if wrongtype_keys:
        logger.info("Step 3 — Cleaning %d stale HASH keys...", len(wrongtype_keys))
        for key in wrongtype_keys:
            r.delete(key)
        logger.info("Cleaned %d keys.", len(wrongtype_keys))
    else:
        logger.info("Step 3 — No cleanup needed.")

    # --- Step 4: Check candle_history LIST keys ---
    logger.info("Step 4 — Checking candle_history LIST keys...")
    empty_symbols: list[str] = []
    ok_symbols: list[str] = []

    for sym in SYMBOLS:
        list_key = f"wolf15:candle_history:{sym}:{TIMEFRAME}"
        try:
            ktype = r.type(list_key)
            length = r.llen(list_key) if ktype == "list" else 0
        except Exception:
            length = 0

        if length >= REQUIRED_BARS:
            ok_symbols.append(f"{sym}={length}")
        else:
            empty_symbols.append(sym)

    if ok_symbols:
        logger.info("  OK (%d symbols): %s", len(ok_symbols), ", ".join(ok_symbols[:10]))
    if empty_symbols:
        logger.warning(
            "  EMPTY (%d symbols): %s",
            len(empty_symbols),
            ", ".join(empty_symbols[:10]),
        )
        if len(empty_symbols) > 10:
            logger.warning("  ... and %d more", len(empty_symbols) - 10)

    # --- Step 5: Inject warmup bars for empty symbols ---
    if empty_symbols:
        logger.info(
            "Step 5 — Injecting %d warmup bars for %d empty symbols...",
            INJECT_BARS,
            len(empty_symbols),
        )
        now = time.time()
        period = 900
        injected = 0

        for sym in empty_symbols:
            list_key = f"wolf15:candle_history:{sym}:{TIMEFRAME}"
            pipe = cast(Any, r.pipeline(transaction=True))

            for i in range(INJECT_BARS):
                ts = now - (INJECT_BARS - i) * period
                candle = {
                    "symbol": sym,
                    "timeframe": TIMEFRAME,
                    "open": 1.0,
                    "high": 1.0,
                    "low": 1.0,
                    "close": 1.0,
                    "volume": 100,
                    "timestamp": ts,
                    "ts_open": ts,
                    "ts_close": ts + period,
                    "status": "closed",
                    "tick_count": 1,
                }
                pipe.rpush(list_key, json.dumps(candle))

            pipe.ltrim(list_key, -300, -1)
            pipe.expire(list_key, 6 * 3600)

            try:
                pipe.execute()
                injected += 1
            except Exception as exc:
                logger.error("Failed to inject for %s: %s", sym, exc)

        logger.info("Injected warmup bars for %d/%d symbols.", injected, len(empty_symbols))
    else:
        logger.info("Step 5 — All symbols have sufficient bars.")

    # --- Step 6: Flush invalid verdicts ---
    logger.info("Step 6 — Cleaning invalid verdict cache...")
    verdict_cursor = 0
    verdict_cleaned = 0
    while True:
        scan_result = r.scan(cursor=verdict_cursor, match="L12:VERDICT:*", count=200)
        verdict_cursor, keys = scan_result
        for key in keys:
            try:
                r.delete(key)
                verdict_cleaned += 1
            except Exception:
                pass
        if verdict_cursor == 0:
            break

    logger.info("Cleaned %d invalid verdict keys.", verdict_cleaned)

    # --- Summary ---
    logger.info("=" * 60)
    logger.info("DIAGNOSTIC SUMMARY")
    logger.info("=" * 60)
    logger.info("  WRONGTYPE keys cleaned: %d", len(wrongtype_keys))
    logger.info("  Symbols with data:      %d/%d", len(ok_symbols), len(SYMBOLS))
    logger.info("  Symbols injected:       %d", len(empty_symbols))
    logger.info("  Invalid verdicts purged: %d", verdict_cleaned)
    logger.info("=" * 60)

    if not empty_symbols and not wrongtype_keys:
        logger.info("All clear — pipeline should produce valid verdicts.")
    else:
        logger.info("Warmup bars injected — pipeline will work until real candles arrive.")

    r.close()


if __name__ == "__main__":
    main()
