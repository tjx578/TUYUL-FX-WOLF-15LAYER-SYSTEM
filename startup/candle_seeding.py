"""Candle seeding (warmup) on engine startup.

Zone: startup/ — one-shot initialisation, no execution side-effects.

Strategy depends on CONTEXT_MODE env var:
  - redis : load candle history from Redis Lists (populated by ingest container)
  - local : fetch historical candles directly from Finnhub REST API
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from context.live_context_bus import LiveContextBus

__all__ = ["seed_candles_on_startup"]


def _synthesize_d1_from_h1(bus: LiveContextBus, pairs: list[str]) -> None:
    """Synthesize D1 candles from H1 data for pairs missing daily bars.

    Finnhub free tier often returns no_data for daily resolution on OANDA forex.
    This mirrors the H4-from-H1 aggregation pattern.
    """
    from collections import defaultdict
    from datetime import datetime

    for pair in pairs:
        d1_candles = bus.get_candles(pair, "D1")
        if d1_candles:
            continue
        h1_candles = bus.get_candles(pair, "H1")
        if not h1_candles:
            continue

        daily_groups: dict[tuple[int, int, int], list[dict]] = defaultdict(list)
        for h1 in h1_candles:
            ts = h1.get("timestamp")
            if ts is None:
                continue
            if isinstance(ts, str):
                try:
                    dt = datetime.fromisoformat(ts)
                except (ValueError, TypeError):
                    continue
            elif isinstance(ts, datetime):
                dt = ts
            elif isinstance(ts, (int, float)):
                dt = datetime.fromtimestamp(ts, tz=UTC)
            else:
                continue
            ohlc = [h1.get(k, -1) for k in ("open", "high", "low", "close")]
            if any(v <= 0 for v in ohlc):
                continue
            daily_groups[(dt.year, dt.month, dt.day)].append(h1)

        if not daily_groups:
            continue

        synthesized = []
        for (_y, _m, _d), group in sorted(daily_groups.items()):
            last_ts = group[-1].get("timestamp")
            synthesized.append(
                {
                    "symbol": pair,
                    "timeframe": "D1",
                    "open": group[0]["open"],
                    "high": max(c["high"] for c in group),
                    "low": min(c["low"] for c in group),
                    "close": group[-1]["close"],
                    "volume": sum(c.get("volume", 0) for c in group),
                    "timestamp": last_ts,
                    "source": "h1_aggregated",
                }
            )

        bus.set_candle_history(pair, "D1", synthesized)
        logger.info(
            "[SEED] {} D1: synthesized {} bars from {} H1 bars (no daily data)",
            pair,
            len(synthesized),
            len(h1_candles),
        )


def _synthesize_w1_from_d1(bus: LiveContextBus, pairs: list[str]) -> None:
    """Synthesize W1 candles from D1 data for pairs missing weekly bars.

    Finnhub free tier often returns no_data for weekly resolution on OANDA forex.
    """
    from collections import defaultdict
    from datetime import datetime

    for pair in pairs:
        w1_candles = bus.get_candles(pair, "W1")
        if w1_candles:
            continue
        d1_candles = bus.get_candles(pair, "D1")
        if not d1_candles:
            continue

        weekly_groups: dict[tuple[int, int], list[dict]] = defaultdict(list)
        for d1 in d1_candles:
            ts = d1.get("timestamp")
            if ts is None:
                continue
            if isinstance(ts, str):
                try:
                    dt = datetime.fromisoformat(ts)
                except (ValueError, TypeError):
                    continue
            elif isinstance(ts, datetime):
                dt = ts
            elif isinstance(ts, (int, float)):
                dt = datetime.fromtimestamp(ts, tz=UTC)
            else:
                continue
            ohlc = [d1.get(k, -1) for k in ("open", "high", "low", "close")]
            if any(v <= 0 for v in ohlc):
                continue
            iso_year, iso_week, _ = dt.isocalendar()
            weekly_groups[(iso_year, iso_week)].append(d1)

        if not weekly_groups:
            continue

        synthesized = []
        for (_y, _w), group in sorted(weekly_groups.items()):
            last_ts = group[-1].get("timestamp")
            synthesized.append(
                {
                    "symbol": pair,
                    "timeframe": "W1",
                    "open": group[0]["open"],
                    "high": max(c["high"] for c in group),
                    "low": min(c["low"] for c in group),
                    "close": group[-1]["close"],
                    "volume": sum(c.get("volume", 0) for c in group),
                    "timestamp": last_ts,
                    "source": "d1_aggregated",
                }
            )

        bus.set_candle_history(pair, "W1", synthesized)
        logger.info(
            "[SEED] {} W1: synthesized {} bars from {} D1 bars (no weekly data)",
            pair,
            len(synthesized),
            len(d1_candles),
        )


def _synthesize_mn_from_d1(bus: LiveContextBus, pairs: list[str]) -> None:
    """Synthesize MN candles from D1 data for pairs missing monthly bars.

    Finnhub often returns no_data for monthly resolution on many forex pairs.
    This mirrors the H4-from-H1 aggregation pattern already used in the fetcher.
    """
    from collections import defaultdict
    from datetime import datetime

    for pair in pairs:
        mn_candles = bus.get_candles(pair, "MN")
        if mn_candles:
            continue
        d1_candles = bus.get_candles(pair, "D1")
        if not d1_candles:
            continue

        # Group D1 bars by (year, month)
        monthly_groups: dict[tuple[int, int], list[dict]] = defaultdict(list)
        for d1 in d1_candles:
            ts = d1.get("timestamp")
            if ts is None:
                continue
            if isinstance(ts, str):
                try:
                    dt = datetime.fromisoformat(ts)
                except (ValueError, TypeError):
                    continue
            elif isinstance(ts, datetime):
                dt = ts
            elif isinstance(ts, (int, float)):
                dt = datetime.fromtimestamp(ts, tz=UTC)
            else:
                continue
            ohlc = [d1.get(k, -1) for k in ("open", "high", "low", "close")]
            if any(v <= 0 for v in ohlc):
                continue
            monthly_groups[(dt.year, dt.month)].append(d1)

        if not monthly_groups:
            continue

        synthesized = []
        for (_y, _m), group in sorted(monthly_groups.items()):
            last_ts = group[-1].get("timestamp")
            synthesized.append(
                {
                    "symbol": pair,
                    "timeframe": "MN",
                    "open": group[0]["open"],
                    "high": max(c["high"] for c in group),
                    "low": min(c["low"] for c in group),
                    "close": group[-1]["close"],
                    "volume": sum(c.get("volume", 0) for c in group),
                    "timestamp": last_ts,
                    "source": "d1_aggregated",
                }
            )

        bus.set_candle_history(pair, "MN", synthesized)
        logger.info(
            "[SEED] {} MN: synthesized {} bars from {} D1 bars (REST returned no monthly data)",
            pair,
            len(synthesized),
            len(d1_candles),
        )


async def seed_candles_on_startup(pairs: list[str], warmup_min_bars: dict[str, int]) -> None:
    """Seed candle history into LiveContextBus BEFORE the analysis loop starts."""
    context_mode = os.getenv("CONTEXT_MODE", "local").lower()
    logger.info(f"[SEED] Seeding candles on startup (mode={context_mode}, pairs={len(pairs)})")

    hydration_report: dict[str, object]
    if context_mode == "redis":
        hydration_report = await _seed_from_redis(pairs)
    else:
        hydration_report = await _seed_from_finnhub(pairs)

    # Verify warmup status
    from context.live_context_bus import LiveContextBus  # noqa: PLC0415

    bus = LiveContextBus()
    ready_count = 0
    degraded_pairs: list[str] = []
    for pair in pairs:
        status = bus.check_warmup(pair, warmup_min_bars)
        if status.get("ready"):
            ready_count += 1
        else:
            missing = status.get("missing", {})
            degraded_pairs.append(pair)
            logger.warning(
                "[SEED] {} warmup insufficient after seeding: missing={} | bars_have={} | bars_need={}",
                pair,
                missing,
                status.get("bars", {}),
                status.get("required", {}),
            )

    if degraded_pairs:
        logger.warning(
            "[SEED] {}/{} pairs degraded after seeding: {} — "
            "pipeline will gate these until ingest delivers sufficient data. "
            "This is expected on cold-start; ingest will fill gaps.",
            len(degraded_pairs),
            len(pairs),
            degraded_pairs,
        )
    logger.info("[SEED] Warmup ready: {}/{} pairs", ready_count, len(pairs))
    logger.info(
        "[SEED] Hydration report: source={} seeded_pairs={} attempts={} status={}",
        hydration_report.get("source", "unknown"),
        hydration_report.get("seeded_pairs", 0),
        hydration_report.get("attempts", 0),
        hydration_report.get("status", "unknown"),
    )


async def _seed_from_redis(pairs: list[str]) -> dict[str, object]:
    """Load candle history from Redis Lists into LiveContextBus.

    Retries with backoff when Redis has no data yet (race condition: engine
    starts before ingest finishes seeding).
    """
    # Defaults target cross-service race in Railway: ingest warmup for 30x5 TF
    # can take several minutes before the first Redis history is available.
    max_retries = int(os.getenv("ENGINE_WARMUP_MAX_RETRIES", "60"))
    retry_delay = float(os.getenv("ENGINE_WARMUP_RETRY_DELAY_SEC", "5"))

    try:
        from context.live_context_bus import LiveContextBus  # noqa: PLC0415
        from context.redis_consumer import RedisConsumer  # noqa: PLC0415
        from infrastructure.redis_client import get_client  # noqa: PLC0415

        redis_client = await get_client()
        try:
            # Sanitise conflicting key types BEFORE warmup reads
            from core.redis_consumer_fix import sanitize_redis_keys  # noqa: PLC0415

            await sanitize_redis_keys(redis_client)

            consumer = RedisConsumer(symbols=pairs, redis_client=redis_client)
            bus = LiveContextBus()

            _h4_warmup = {"H1": 1, "H4": 5}
            _htf_verify = {"D1": 1, "W1": 1, "MN": 1}

            for attempt in range(1, max_retries + 1):
                await consumer.load_candle_history()

                h1_count = sum(1 for pair in pairs if bus.check_warmup(pair, _h4_warmup).get("ready"))

                if h1_count > 0:
                    logger.info(
                        "[SEED] Redis candle history loaded into LiveContextBus "
                        "({}/{} pairs with H1 data, attempt {}). "
                        "M15 will arrive from tick stream after ~15 min.",
                        h1_count,
                        len(pairs),
                        attempt,
                    )

                    # Synthesize D1 from H1, W1 from D1, MN from D1
                    # when ingest didn't provide those timeframes
                    _synthesize_d1_from_h1(bus, pairs)
                    _synthesize_w1_from_d1(bus, pairs)
                    _synthesize_mn_from_d1(bus, pairs)

                    for pair in pairs:
                        htf_status = bus.check_warmup(pair, _htf_verify)
                        if htf_status.get("missing"):
                            missing_tfs = list(htf_status["missing"].keys())
                            logger.warning(
                                "[SEED] {} missing higher-TF data: {} — "
                                "L1 context/regime analysis may be degraded "
                                "until ingest delivers these timeframes.",
                                pair,
                                missing_tfs,
                            )
                    return {"source": "redis", "seeded_pairs": h1_count, "attempts": attempt, "status": "ok"}

                if attempt < max_retries:
                    logger.warning(
                        "[SEED] No candle data in Redis yet (H1={}, attempt {}/{}) — waiting {:.0f}s",
                        h1_count,
                        attempt,
                        max_retries,
                        retry_delay,
                    )
                    await asyncio.sleep(retry_delay)

            logger.critical(
                "[SEED] Redis still empty after {} retries ({:.0f}s total wait). "
                "Attempting PostgreSQL candle recovery before degraded mode.",
                max_retries,
                max_retries * retry_delay,
            )
            # Fallback: recover candle history from PostgreSQL snapshots
            pg_recovered = await _try_restore_from_postgres(pairs, bus)
            if pg_recovered > 0:
                logger.info("[SEED] PostgreSQL recovery seeded {} pairs into LiveContextBus", pg_recovered)
                return {
                    "source": "postgres_fallback",
                    "seeded_pairs": pg_recovered,
                    "attempts": max_retries,
                    "status": "recovered",
                }
            return {"source": "redis", "seeded_pairs": 0, "attempts": max_retries, "status": "degraded"}
        finally:
            pass  # Pooled client — don't close; pool is managed by RedisClientManager
    except Exception as exc:
        logger.error(f"[SEED] Failed to seed from Redis: {exc}")
        return {"source": "redis", "seeded_pairs": 0, "attempts": 1, "status": "failed"}


async def _seed_from_finnhub(pairs: list[str]) -> dict[str, object]:
    """Fetch historical candles from Finnhub REST API into LiveContextBus."""
    from ingest.finnhub_key_manager import finnhub_keys  # noqa: PLC0415

    if not finnhub_keys.available:
        logger.warning("[SEED] No Finnhub API key — skipping REST warmup")
        return {"source": "finnhub", "seeded_pairs": 0, "attempts": 1, "status": "skipped"}

    del pairs  # symbols are sourced from fetcher warmup config
    try:
        from ingest.finnhub_candles import FinnhubCandleFetcher  # noqa: PLC0415

        fetcher = FinnhubCandleFetcher()
        results = await fetcher.warmup_all()
        total = sum(len(candles) for tfs in results.values() for candles in tfs.values())
        logger.info(f"[SEED] Finnhub warmup complete: {len(results)} symbols, {total} total bars")

        m15_seeded = await fetcher.cold_start_m15(bars=100)
        m15_total = sum(m15_seeded.values())
        logger.info(f"[SEED] M15 cold-start: {len(m15_seeded)} symbols, {m15_total} total bars")
        return {"source": "finnhub", "seeded_pairs": len(results), "attempts": 1, "status": "ok"}
    except Exception as exc:
        logger.error(f"[SEED] Failed to seed from Finnhub: {exc}")
        return {"source": "finnhub", "seeded_pairs": 0, "attempts": 1, "status": "failed"}


async def _try_restore_from_postgres(
    pairs: list[str],
    bus: LiveContextBus | None = None,
) -> int:
    """Attempt to recover candle history from PostgreSQL ohlc_candles table.

    This is a last-resort fallback when Redis is empty or unresponsive.
    Loads recent candles per symbol/tf directly into LiveContextBus.
    Data recovered this way is marked STALE_PRESERVED (not live).

    Returns:
        Number of symbol/tf combos successfully recovered.
    """
    try:
        from storage.postgres_client import pg_client  # noqa: PLC0415

        if not pg_client.is_available:
            await pg_client.initialize()
        if not pg_client.is_available:
            logger.warning("[SEED] PostgreSQL not available for candle recovery")
            return 0

        pool = pg_client._pool  # noqa: SLF001
        if pool is None:
            return 0

        from context.live_context_bus import LiveContextBus  # noqa: PLC0415

        ctx_bus = bus if bus is not None else LiveContextBus()
        timeframes = ["M15", "H1", "H4", "D1", "W1", "MN"]
        recovered = 0

        async with pool.acquire() as conn:
            for symbol in pairs:
                for tf in timeframes:
                    try:
                        rows = await conn.fetch(
                            """
                            SELECT open_time, close_time, open, high, low, close, volume, tick_count
                            FROM ohlc_candles
                            WHERE symbol = $1 AND timeframe = $2
                            ORDER BY open_time DESC
                            LIMIT 250
                            """,
                            symbol,
                            tf,
                        )
                        if not rows:
                            continue
                        candles = [
                            {
                                "symbol": symbol,
                                "timeframe": tf,
                                "open_time": r["open_time"],
                                "close_time": r["close_time"],
                                "open": float(r["open"]),
                                "high": float(r["high"]),
                                "low": float(r["low"]),
                                "close": float(r["close"]),
                                "volume": float(r["volume"]) if r["volume"] else 0.0,
                                "tick_count": int(r["tick_count"]) if r["tick_count"] else 0,
                                "_source": "postgres_recovery",
                            }
                            for r in reversed(rows)  # oldest first
                        ]
                        ctx_bus.set_candle_history(symbol, tf, candles)
                        recovered += 1
                        logger.info("[SEED] PG recovery: {}:{} — {} candles", symbol, tf, len(candles))
                    except Exception as row_exc:
                        logger.warning("[SEED] PG recovery failed for {}:{}: {}", symbol, tf, row_exc)

        logger.info("[SEED] PostgreSQL candle recovery complete: {} symbol/tf combos", recovered)
        return recovered

    except Exception as exc:
        logger.error("[SEED] PostgreSQL candle recovery failed: {}", exc)
        return 0
