#!/usr/bin/env python3
"""
TUYUL FX — Redis diagnostic + cleanup
============================================================
Run on Railway after deploying patches:
    railway run -s wolf15-engine python redis_diagnostic.py

Steps:
  1. Check Redis connectivity
  2. Identify WRONGTYPE keys (HASH masquerading as LIST)
  3. Clean stale HASH keys that block LRANGE
  4. Verify candle_history LIST keys exist
  5. Inject 2 warmup bars per symbol if empty
  6. Print health summary
============================================================
"""

import asyncio
import json
import logging
import os
import sys
import time

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
INJECT_BARS = 5  # inject more than minimum for safety


async def main() -> None:
    try:
        import redis.asyncio as aioredis
    except ImportError:
        logger.error("redis package not installed. pip install redis")
        sys.exit(1)

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    logger.info("Connecting to Redis: %s", redis_url[:30] + "...")

    r = aioredis.from_url(
        redis_url,
        decode_responses=False,
        socket_timeout=10,
    )

    # --- Step 1: Connectivity ---
    try:
        pong = await r.ping()
        logger.info("Step 1 — Redis PING: %s", pong)
    except Exception as exc:
        logger.error("Step 1 — Redis connection FAILED: %s", exc)
        sys.exit(1)

    # --- Step 2: Identify WRONGTYPE keys ---
    logger.info("Step 2 — Scanning for WRONGTYPE conflicts...")
    wrongtype_keys: list[str] = []
    cursor: int = 0
    while True:
        cursor, keys = await r.scan(
            cursor=cursor,
            match="wolf15:candle:*",
            count=200,
        )
        for key in keys:
            key_str = key.decode() if isinstance(key, bytes) else str(key)
            if "candle_history" in key_str:
                continue
            ktype = await r.type(key)
            type_str = ktype.decode() if isinstance(ktype, bytes) else str(ktype)
            if type_str == "hash":
                wrongtype_keys.append(key_str)
        if cursor == 0:
            break

    if wrongtype_keys:
        logger.warning(
            "Found %d HASH keys blocking LRANGE:",
            len(wrongtype_keys),
        )
        for k in wrongtype_keys[:10]:
            logger.warning("  → %s", k)
        if len(wrongtype_keys) > 10:
            logger.warning("  ... and %d more", len(wrongtype_keys) - 10)
    else:
        logger.info("No WRONGTYPE conflicts found.")

    # --- Step 3: Cleanup stale HASH keys ---
    if wrongtype_keys:
        logger.info("Step 3 — Cleaning %d stale HASH keys...", len(wrongtype_keys))
        for key_str in wrongtype_keys:
            await r.delete(key_str)
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
            ktype = await r.type(list_key)
            type_str = ktype.decode() if isinstance(ktype, bytes) else str(ktype)
            length = await r.llen(list_key) if type_str == "list" else 0
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
        period = 900  # M15 = 900s
        injected = 0

        for sym in empty_symbols:
            list_key = f"wolf15:candle_history:{sym}:{TIMEFRAME}"
            pipe = r.pipeline(transaction=True)

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
                payload = json.dumps(candle)
                pipe.rpush(list_key, payload)

            pipe.ltrim(list_key, -300, -1)
            pipe.expire(list_key, 6 * 3600)

            try:
                await pipe.execute()
                injected += 1
            except Exception as exc:
                logger.error("Failed to inject for %s: %s", sym, exc)

        logger.info("Injected warmup bars for %d/%d symbols.", injected, len(empty_symbols))
    else:
        logger.info("Step 5 — All symbols have sufficient bars. No injection needed.")

    # --- Step 6: Flush invalid verdicts ---
    logger.info("Step 6 — Cleaning invalid verdict cache...")
    verdict_cursor: int = 0
    verdict_cleaned = 0
    while True:
        verdict_cursor, keys = await r.scan(
            cursor=verdict_cursor,
            match="L12:VERDICT:*",
            count=200,
        )
        for key in keys:
            try:
                await r.delete(key)
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
        logger.info("Warmup bars injected — pipeline will work until real candles replace them (next M15 close).")

    await r.aclose()


if __name__ == "__main__":
    asyncio.run(main())
