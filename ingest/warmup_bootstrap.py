"""Warmup, stale-cache detection, HTF supplemental fetch, and Redis candle seeding.

Extracted from ingest_service.py for maintainability.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from datetime import datetime
from typing import Any

import orjson
from loguru import logger

from analysis.macro.macro_regime_engine import MacroRegimeEngine
from context.system_state import SystemState, SystemStateManager
from core.redis_keys import CANDLE_HISTORY_SCAN, candle_history, channel_candle
from infrastructure.circuit_breaker import CircuitBreaker
from ingest.finnhub_candles import FinnhubCandleFetcher
from ingest.redis_setup import RedisClient
from ingest.service_metrics import health_probe
from storage.candle_persistence import enqueue_candle_dict

MAX_RETRIES = 10
BASE_DELAY = 1.0

# Circuit breaker for the warmup / provider chain.
warmup_circuit = CircuitBreaker(
    name="ingest_warmup",
    failure_threshold=int(os.getenv("WOLF15_INGEST_CB_FAILURE_THRESHOLD", "10")),
    recovery_timeout=float(os.getenv("WOLF15_INGEST_CB_RECOVERY_TIMEOUT", "90")),
    half_open_success_threshold=int(os.getenv("WOLF15_INGEST_CB_HALF_OPEN_ATTEMPTS", "1")),
)


async def has_stale_cache(redis: RedisClient) -> bool:
    """Return ``True`` if Redis holds any previously seeded candle history."""
    try:
        cursor = 0
        pattern = CANDLE_HISTORY_SCAN
        while True:
            cursor, keys = await redis.scan(cursor, match=pattern, count=20)
            for key in keys:
                length: int = await redis.llen(key)
                if length > 0:
                    logger.info(
                        "[StaleCache] Found stale candle cache: {} ({} bars)",
                        key,
                        length,
                    )
                    return True
            if cursor == 0:
                break
    except Exception as exc:
        logger.warning("[StaleCache] Cache scan failed: {}", exc)
    return False


def _set_state_from_warmup(system_state: SystemStateManager) -> None:
    warmup_report = system_state.get_warmup_report()
    incomplete_count = sum(1 for status in warmup_report.values() if status.status.value != "COMPLETE")
    if incomplete_count == 0:
        system_state.set_state(SystemState.READY)
        logger.info("Warmup complete - system state: READY")
        return
    system_state.set_state(SystemState.DEGRADED)
    logger.warning(f"Warmup complete with {incomplete_count} incomplete symbols - system state: DEGRADED")


def _update_macro_regime(enabled_symbols: list[str]) -> None:
    try:
        macro_engine = MacroRegimeEngine()
    except Exception:
        logger.exception("Failed to initialize MacroRegimeEngine")
        return

    for symbol in enabled_symbols:
        try:
            macro_engine.update_macro_state(symbol)
        except Exception as exc:
            logger.error(f"Macro regime failed for {symbol}: {exc}")


async def run_warmup(
    system_state: SystemStateManager, enabled_symbols: list[str]
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Fetch historical candles with retry before falling back to DEGRADED."""
    if warmup_circuit.is_open():
        logger.warning(
            "[Warmup] Circuit breaker OPEN (failure_count={}) — skipping warmup, will use stale cache fallback",
            warmup_circuit.failure_count,
        )
        system_state.set_state(SystemState.DEGRADED)
        return {}

    logger.info("Starting warmup: fetching historical candles from Finnhub REST API")
    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            fetcher = FinnhubCandleFetcher()
            warmup_results = await fetcher.warmup_all()

            system_state.validate_warmup(warmup_results)
            _update_macro_regime(enabled_symbols)
            _set_state_from_warmup(system_state)
            warmup_circuit.record_success()
            return warmup_results
        except Exception as exc:
            last_exc = exc
            warmup_circuit.record_failure()
            delay = BASE_DELAY * (2 ** (attempt - 1))
            logger.warning(
                "[Warmup] Attempt {}/{} failed (circuit={}): {}  retrying in {:.1f}s",
                attempt,
                MAX_RETRIES,
                warmup_circuit.state.value,
                exc,
                delay,
            )
            health_probe.set_detail("warmup_retry", f"{attempt}/{MAX_RETRIES}")
            health_probe.set_detail("circuit_state", warmup_circuit.state.value)
            if warmup_circuit.is_open():
                logger.warning(
                    "[Warmup] Circuit OPEN after {} failure(s) — aborting retry loop",
                    warmup_circuit.failure_count,
                )
                break
            await asyncio.sleep(delay)

    logger.error("[Warmup] Failed after {} attempts (non-fatal): {}", MAX_RETRIES, last_exc)
    system_state.set_state(SystemState.DEGRADED)
    return {}


# ── Supplemental HTF fetch for stale-cache mode ──────────────────
_SUPP_HTF_MIN_BARS: dict[str, int] = {
    "H1": 20,
    "H4": 10,
}
_SUPP_FETCH_BARS = 50


async def supplemental_htf_fetch(
    redis: RedisClient,
    enabled_symbols: list[str],
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Fetch H1/H4 bars via REST for symbols whose Redis counts are below threshold."""
    if warmup_circuit.is_open():
        logger.warning("[SuppHTF] Circuit breaker OPEN — skipping supplemental fetch")
        return {}

    deficit_map: dict[str, list[str]] = {}
    for symbol in enabled_symbols:
        missing_tfs: list[str] = []
        for tf, required in _SUPP_HTF_MIN_BARS.items():
            key = candle_history(symbol, tf)
            try:
                have = await redis.llen(key)
            except Exception:
                have = 0
            if have < required:
                missing_tfs.append(tf)
        if missing_tfs:
            deficit_map[symbol] = missing_tfs

    if not deficit_map:
        logger.info("[SuppHTF] All symbols meet H1/H4 thresholds — no supplemental fetch needed")
        return {}

    total_tasks = sum(len(tfs) for tfs in deficit_map.values())
    logger.info(
        "[SuppHTF] %d symbols need supplemental H1/H4 data (%d fetch tasks)",
        len(deficit_map),
        total_tasks,
    )

    fetcher = FinnhubCandleFetcher()
    results: dict[str, dict[str, list[dict[str, Any]]]] = {}

    async def _fetch_one(symbol: str, tf: str) -> None:
        try:
            candles = await fetcher.fetch(symbol, tf, _SUPP_FETCH_BARS)
            if candles:
                if symbol not in results:
                    results[symbol] = {}
                results[symbol][tf] = candles
                for candle in candles:
                    fetcher.context_bus.update_candle(candle)
                logger.info("[SuppHTF] %s/%s: fetched %d bars", symbol, tf, len(candles))
            else:
                logger.warning("[SuppHTF] %s/%s: REST returned 0 bars", symbol, tf)
        except Exception as exc:
            logger.error("[SuppHTF] %s/%s fetch failed: %s", symbol, tf, exc)

    tasks = [_fetch_one(sym, tf) for sym, tfs in deficit_map.items() for tf in tfs]
    await asyncio.gather(*tasks, return_exceptions=True)

    filled = sum(len(tfs) for tfs in results.values())
    logger.info("[SuppHTF] Supplemental fetch complete: %d/%d symbol/tf combos filled", filled, total_tasks)
    if filled > 0:
        warmup_circuit.record_success()
    return results


# ── Redis candle history — shared helpers ─────────────────────────
_SEED_HISTORY_MAXLEN = 300
_SEED_RPUSH_CHUNK_SIZE = 50


async def push_candle_to_redis(
    redis: RedisClient,
    candle_dict: dict[str, Any],
) -> None:
    """Append a single completed candle to Redis history list + PUBLISH."""
    symbol = candle_dict.get("symbol")
    timeframe = candle_dict.get("timeframe")
    if not symbol or not timeframe:
        return
    key = candle_history(symbol, timeframe)
    try:
        candle_json = orjson.dumps(candle_dict).decode("utf-8")
        await redis.rpush(key, candle_json)
        await redis.ltrim(key, -_SEED_HISTORY_MAXLEN, -1)

        enqueue_candle_dict(candle_dict)

        pub_channel = channel_candle(symbol, timeframe)
        await redis.publish(pub_channel, candle_json)
    except Exception as exc:
        logger.warning("[CandleBridge] RPUSH/PUBLISH failed %s: %s", key, exc)


async def seed_redis_candle_history(
    redis: RedisClient,
    warmup_results: dict[str, dict[str, list[dict[str, Any]]]],
) -> None:
    """Write REST-warmup candles into Redis Lists with atomic swap."""
    if not warmup_results:
        logger.info("[Seed] No warmup results to seed into Redis")
        return

    seeded = 0
    total_dirty = 0
    for symbol, tf_data in warmup_results.items():
        for timeframe, candles in tf_data.items():
            if not candles:
                continue

            clean_candles = [
                c
                for c in candles
                if all(c.get(k, -1) > 0 for k in ("open", "high", "low", "close")) and c["high"] >= c["low"]
            ]
            dirty = len(candles) - len(clean_candles)
            if dirty:
                total_dirty += dirty
                logger.warning(
                    "[Seed] %s/%s: dropped %d/%d dirty candles (sentinel -1 or OHLC violation)",
                    symbol,
                    timeframe,
                    dirty,
                    len(candles),
                )
            if not clean_candles:
                continue
            candles = clean_candles

            key = candle_history(symbol, timeframe)
            temp_key = f"{key}:_seed_tmp"

            try:
                await redis.delete(temp_key)
            except Exception as exc:
                logger.warning(
                    "[Seed] DELETE temp key failed for %s (will attempt RPUSH anyway): %s",
                    temp_key,
                    exc,
                )

            try:
                serialized: list[str] = []
                for candle in candles:
                    normalized = dict(candle)
                    ts = normalized.get("timestamp")
                    if isinstance(ts, datetime):
                        normalized["timestamp"] = ts.isoformat()
                    serialized.append(orjson.dumps(normalized).decode("utf-8"))

                for i in range(0, len(serialized), _SEED_RPUSH_CHUNK_SIZE):
                    chunk = serialized[i : i + _SEED_RPUSH_CHUNK_SIZE]
                    await redis.rpush(temp_key, *chunk)

                if await redis.llen(temp_key) > 0:
                    await redis.rename(temp_key, key)
                    seeded += 1
                    logger.info(
                        "[Seed] {}: {} bars written (atomic swap)",
                        key,
                        len(serialized),
                    )
                else:
                    await redis.delete(temp_key)
                    logger.warning("[Seed] %s: temp key empty after write — keeping old data", key)

            except Exception as exc:
                with contextlib.suppress(Exception):
                    await redis.delete(temp_key)
                logger.error("[Seed] Failed to seed {}: {} — old data preserved", key, exc)

    if total_dirty:
        logger.warning("[Seed] Total dirty candles rejected across all pairs: %d", total_dirty)
    logger.info("[Seed] Completed: {} symbol/tf combos seeded to Redis", seeded)


async def bootstrap_cache_and_warmup(
    redis: RedisClient,
    system_state: SystemStateManager,
    enabled_symbols: list[str],
) -> tuple[dict[str, dict[str, list[dict[str, Any]]]], bool, str]:
    """Run deterministic startup phases and return warmup/cache outcome."""
    redis_has_data = await has_stale_cache(redis)
    warmup_results: dict[str, dict[str, list[dict[str, Any]]]] = {}

    if redis_has_data:
        logger.info(
            "[Ingest] Redis candle cache detected — checking H1/H4 bar counts "
            "before deciding whether to skip REST warmup."
        )
        supp_results = await supplemental_htf_fetch(redis, enabled_symbols)
        if supp_results:
            await seed_redis_candle_history(redis, supp_results)
            warmup_results = supp_results

        system_state.set_state(SystemState.DEGRADED)
        return warmup_results, True, "stale_cache"

    logger.info("[Ingest] Redis empty — running Finnhub REST warmup")
    warmup_results = await run_warmup(system_state, enabled_symbols)
    logger.info(
        "[Warmup] results count=%d symbols_with_data=%s",
        len(warmup_results),
        list(warmup_results.keys())[:10],
    )
    await seed_redis_candle_history(redis, warmup_results)

    if warmup_results:
        return warmup_results, False, "warmup"
    return warmup_results, False, "failed_no_cache"
