"""Standalone ingest service for multi-container deployments."""

import asyncio
import contextlib
import os
import signal
import sys
import types
from datetime import datetime
from importlib import import_module
from time import time
from typing import Any, Protocol

import orjson  # noqa: I001  — needed before analysis imports for _seed_redis_candle_history
from loguru import logger

from analysis.macro.macro_regime_engine import MacroRegimeEngine
from config_loader import get_enabled_symbols
from context.system_state import SystemState, SystemStateManager
from core.health_probe import HealthProbe
from core.metrics import (
    INGEST_CACHE_MODE,
    INGEST_FRESH_PAIRS,
    INGEST_HEARTBEAT_AGE_SECONDS,
    INGEST_WS_CONNECTED,
)
from infrastructure.circuit_breaker import CircuitBreaker
from ingest.calendar_news import CalendarNewsIngestor
from ingest.candle_builder import CandleBuilder, Timeframe
from ingest.dependencies import create_finnhub_ws
from ingest.finnhub_candles import FinnhubCandleFetcher
from ingest.finnhub_market_news import FinnhubMarketNews
from ingest.h1_refresh_scheduler import H1RefreshScheduler
from ingest.htf_refresh_scheduler import HTFRefreshScheduler
from ingest.macro_monthly_scheduler import MacroMonthlyScheduler
from ingest.rest_poll_fallback import RestPollFallback
from state.redis_keys import HEARTBEAT_INGEST
from storage.candle_persistence import enqueue_candle_dict
from storage.startup import init_persistent_storage, shutdown_persistent_storage

_shutdown_event: asyncio.Event | None = None
MAX_RETRIES = 10
BASE_DELAY = 1.0

# ── Health probe for container orchestration ──────────────────────
# Railway injects PORT for its proxy/healthcheck. Prefer INGEST_HEALTH_PORT,
# then fall back to PORT (Railway-injected), then default 8082.
_INGEST_HEALTH_PORT = int(os.getenv("INGEST_HEALTH_PORT") or os.getenv("PORT", "8082"))
_health_probe: HealthProbe = HealthProbe(port=_INGEST_HEALTH_PORT, service_name="ingest")
_ingest_ready = False
# Degraded mode: warmup failed but stale Redis cache is available.
# The service stays alive and serves cached data rather than crashing.
_ingest_degraded = False
_producer_present = False
_producer_last_heartbeat_ts = 0.0
_pair_last_tick_ts: dict[str, float] = {}
_pair_last_tick_fingerprint: dict[str, tuple[float, float]] = {}

_PRODUCER_HEARTBEAT_KEY = HEARTBEAT_INGEST
_PRODUCER_HEARTBEAT_INTERVAL_SEC = max(1.0, float(os.getenv("INGEST_PRODUCER_HEARTBEAT_INTERVAL_SEC", "5")))
_PRODUCER_FRESHNESS_SEC = max(5.0, float(os.getenv("INGEST_PRODUCER_FRESHNESS_SEC", "20")))
_CACHE_MODES = ("unknown", "warmup", "stale_cache", "failed_no_cache")

# Circuit breaker for the warmup / provider chain.
# Configurable via WOLF15_INGEST_CB_* env vars (ingest-specific overrides).
# Falls back to WOLF15_CB_* generic defaults when WOLF15_INGEST_CB_* are absent.
_warmup_circuit = CircuitBreaker(
    name="ingest_warmup",
    failure_threshold=int(os.getenv("WOLF15_INGEST_CB_FAILURE_THRESHOLD", "10")),
    recovery_timeout=float(os.getenv("WOLF15_INGEST_CB_RECOVERY_TIMEOUT", "90")),
    half_open_success_threshold=int(os.getenv("WOLF15_INGEST_CB_HALF_OPEN_ATTEMPTS", "1")),
)


def _fresh_pair_count() -> int:
    now_ts = time()
    fresh = 0
    for last_tick_ts in _pair_last_tick_ts.values():
        if last_tick_ts > 0 and (now_ts - last_tick_ts) <= _PRODUCER_FRESHNESS_SEC:
            fresh += 1
    return fresh


def _mark_pair_tick(symbol: str, ts: float | None = None) -> None:
    pair = str(symbol).strip().upper()
    if not pair:
        return
    _pair_last_tick_ts[pair] = time() if ts is None else float(ts)


def _set_cache_mode(mode: str) -> None:
    selected = str(mode).strip().lower() or "unknown"
    for cache_mode in _CACHE_MODES:
        INGEST_CACHE_MODE.labels(mode=cache_mode).set(1.0 if cache_mode == selected else 0.0)
    _health_probe.set_detail("cache_mode", selected)


def _emit_ingest_runtime_metrics(connected: bool) -> None:
    heartbeat_age = max(0.0, time() - _producer_last_heartbeat_ts) if _producer_last_heartbeat_ts > 0 else float("inf")
    fresh_pairs = _fresh_pair_count()

    INGEST_WS_CONNECTED.set(1.0 if connected else 0.0)
    INGEST_FRESH_PAIRS.set(float(fresh_pairs))
    INGEST_HEARTBEAT_AGE_SECONDS.set(heartbeat_age if heartbeat_age != float("inf") else 9.99e8)

    _health_probe.set_detail("producer_present", "1" if connected else "0")
    _health_probe.set_detail("producer_fresh", "1" if _producer_fresh() else "0")
    _health_probe.set_detail(
        "producer_heartbeat_age_sec", f"{heartbeat_age if heartbeat_age != float('inf') else 0.0:.2f}"
    )
    _health_probe.set_detail("fresh_pairs", str(fresh_pairs))


def _is_duplicate_pair_tick(symbol: str, price: float, ts: float) -> bool:
    """Return True when tick fingerprint matches the last accepted tick.

    This protects M15 candle builders from duplicate events that can still slip
    through upstream filters during reconnect bursts.
    """
    pair = str(symbol).strip().upper()
    if not pair:
        return False
    fingerprint = (float(ts), float(price))
    if _pair_last_tick_fingerprint.get(pair) == fingerprint:
        return True
    _pair_last_tick_fingerprint[pair] = fingerprint
    return False


_WS_CONNECT_GRACE_SEC = float(os.getenv("INGEST_WS_CONNECT_GRACE_SEC", "45"))


def _ingest_readiness() -> bool:
    """Readiness gate with grace period for freshly-connected WS.

    Returns ``True`` when:
    - (a) startup state is ready/degraded;
    - (b) producer heartbeat is fresh;
    - (c) at least one tracked pair has a fresh tick **OR** WS just
      connected and is still within the grace window (waiting for
      first tick — avoids DEGRADED-STALE loop).
    """
    base_ready = _ingest_ready or _ingest_degraded
    if not base_ready:
        return False

    producer_ready = _producer_present and _producer_fresh()
    if not producer_ready:
        return False

    pairs_ready = _fresh_pair_count() > 0
    if pairs_ready:
        return True

    # ── Grace period: WS baru connect, tunggu tick pertama ────────
    if _producer_last_heartbeat_ts > 0:
        ws_age = time() - _producer_last_heartbeat_ts
        if ws_age <= _WS_CONNECT_GRACE_SEC:
            logger.debug(
                "[Readiness] WS fresh (age=%.1fs) — grace window active, " "menunggu tick pertama masuk",
                ws_age,
            )
            return True

    return False


_health_probe.set_readiness_check(_ingest_readiness)


class RedisClient(Protocol):
    """Async Redis client contract used by ingest service."""

    async def ping(self) -> Any: ...
    async def aclose(self) -> None: ...
    async def delete(self, name: str) -> int: ...
    async def rename(self, src: str, dst: str) -> bool: ...
    async def scan(self, cursor: int, *, match: str, count: int) -> tuple[int, list[str]]: ...
    async def llen(self, name: str) -> int: ...
    async def rpush(self, name: str, *values: str) -> int: ...
    async def ltrim(self, name: str, start: int, end: int) -> Any: ...
    async def publish(self, channel: str, message: str) -> int: ...
    async def set(self, name: str, value: str, ex: int | None = None) -> Any: ...


def _producer_fresh() -> bool:
    if _producer_last_heartbeat_ts <= 0:
        return False
    return (time() - _producer_last_heartbeat_ts) <= _PRODUCER_FRESHNESS_SEC


def _update_producer_health(connected: bool) -> None:
    global _producer_present, _producer_last_heartbeat_ts
    _producer_present = connected
    if connected:
        _producer_last_heartbeat_ts = time()


async def _producer_heartbeat_loop(ws_feed: Any, redis: RedisClient) -> None:
    while not (_shutdown_event and _shutdown_event.is_set()):
        connected = bool(getattr(ws_feed, "is_connected", False))
        _update_producer_health(connected)
        _health_probe.set_detail("producer_present", "1" if connected else "0")
        _health_probe.set_detail("producer_fresh", "1" if _producer_fresh() else "0")
        _health_probe.set_detail(
            "producer_heartbeat_age_sec",
            f"{max(0.0, time() - _producer_last_heartbeat_ts):.2f}",
        )
        _health_probe.set_detail("fresh_pairs", str(_fresh_pair_count()))
        _emit_ingest_runtime_metrics(connected)

        if connected:
            payload = {"producer": "finnhub_ws", "ts": time()}
            with contextlib.suppress(Exception):
                await redis.set(_PRODUCER_HEARTBEAT_KEY, orjson.dumps(payload).decode("utf-8"))

        await asyncio.sleep(_PRODUCER_HEARTBEAT_INTERVAL_SEC)


def _validate_api_key() -> bool:
    from ingest.finnhub_key_manager import finnhub_keys  # noqa: PLC0415

    if not finnhub_keys.available:
        logger.warning("WARNING: FINNHUB_API_KEY not configured; ingest running in DRY RUN mode.")
        return False
    logger.info("FINNHUB_API_KEY validated ({} key(s) loaded)", finnhub_keys.key_count)
    return True


async def _has_stale_cache(redis: RedisClient) -> bool:
    """Return ``True`` if Redis holds any previously seeded candle history.

    Scans for keys matching ``wolf15:candle_history:*`` using ``SCAN`` to avoid
    blocking the server.  A single key with at least one entry is sufficient to
    declare stale-cache availability.
    """
    try:
        cursor = 0
        pattern = "wolf15:candle_history:*"
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


# Symbol resolution delegated to config_loader.get_enabled_symbols()


def _build_redis_client() -> RedisClient:
    try:
        redis_asyncio = import_module("redis.asyncio")
    except ModuleNotFoundError as exc:
        raise RuntimeError("Missing dependency 'redis'. Install it with: pip install redis") from exc

    redis_cls = redis_asyncio.Redis
    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        logger.info("Using REDIS_URL for ingest service")
        return redis_cls.from_url(redis_url, encoding="utf-8", decode_responses=True)

    redis_host = os.getenv("REDIS_HOST", "localhost")
    redis_port = int(os.getenv("REDIS_PORT", "6379"))
    redis_password = os.getenv("REDIS_PASSWORD", "")
    redis_db = int(os.getenv("REDIS_DB", "0"))
    logger.info(f"Using Redis: {redis_host}:{redis_port}/{redis_db}")
    return redis_cls(
        host=redis_host,
        port=redis_port,
        password=redis_password if redis_password else None,
        db=redis_db,
        encoding="utf-8",
        decode_responses=True,
    )


async def _connect_redis() -> RedisClient:
    redis = _build_redis_client()
    try:
        await redis.ping()
    except Exception:
        await redis.aclose()
        raise
    logger.info("Redis connection validated")
    return redis


async def _connect_redis_with_retry() -> RedisClient:
    """Connect to Redis with bounded retry/backoff during startup.

    This keeps ingest process alive during transient Redis unavailability,
    allowing platform liveness probes to pass while startup dependencies settle.
    """
    max_retries = int(os.getenv("INGEST_REDIS_CONNECT_MAX_RETRIES", "15"))
    base_delay = float(os.getenv("INGEST_REDIS_CONNECT_DELAY_SEC", "2"))
    max_delay = float(os.getenv("INGEST_REDIS_CONNECT_MAX_DELAY_SEC", "10"))

    attempt = 0
    while True:
        if _shutdown_event and _shutdown_event.is_set():
            raise RuntimeError("shutdown_requested")

        attempt += 1
        try:
            client = await _connect_redis()
            _health_probe.set_detail("redis", "connected")
            _health_probe.set_detail("redis_retry", str(attempt))
            return client
        except Exception as exc:
            _health_probe.set_detail("redis", "connecting")
            _health_probe.set_detail("redis_retry", str(attempt))

            if max_retries > 0 and attempt >= max_retries:
                logger.error(
                    "Redis connection failed after %d attempt(s): %s",
                    attempt,
                    exc,
                )
                raise

            delay = min(max_delay, base_delay * (2 ** max(0, attempt - 1)))
            logger.warning(
                "Redis not ready yet (attempt %d): %s — retrying in %.1fs",
                attempt,
                exc,
                delay,
            )
            await asyncio.sleep(delay)


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


async def _run_warmup(
    system_state: SystemStateManager, enabled_symbols: list[str]
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Fetch historical candles with retry before falling back to DEGRADED.

    Returns the warmup results dict (symbol -> timeframe -> candles) so the
    caller can seed Redis for cross-container consumption.

    When the circuit breaker is OPEN (repeated failures) the warmup is skipped
    entirely to avoid hammering a 403-returning provider.  The caller should
    check the circuit state and use the stale cache instead.
    """
    if _warmup_circuit.is_open():
        logger.warning(
            "[Warmup] Circuit breaker OPEN (failure_count={}) — skipping warmup, will use stale cache fallback",
            _warmup_circuit.failure_count,
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
            _warmup_circuit.record_success()
            return warmup_results  # success — relay results for Redis seeding
        except Exception as exc:
            last_exc = exc
            _warmup_circuit.record_failure()
            delay = BASE_DELAY * (2 ** (attempt - 1))
            logger.warning(
                "[Warmup] Attempt {}/{} failed (circuit={}): {}  retrying in {:.1f}s",
                attempt,
                MAX_RETRIES,
                _warmup_circuit.state.value,
                exc,
                delay,
            )
            _health_probe.set_detail("warmup_retry", f"{attempt}/{MAX_RETRIES}")
            _health_probe.set_detail("circuit_state", _warmup_circuit.state.value)
            if _warmup_circuit.is_open():
                logger.warning(
                    "[Warmup] Circuit OPEN after {} failure(s) — aborting retry loop",
                    _warmup_circuit.failure_count,
                )
                break
            await asyncio.sleep(delay)

    logger.error("[Warmup] Failed after {} attempts (non-fatal): {}", MAX_RETRIES, last_exc)
    system_state.set_state(SystemState.DEGRADED)
    return {}  # empty — no candles to seed


async def _bootstrap_cache_and_warmup(
    redis: RedisClient,
    system_state: SystemStateManager,
    enabled_symbols: list[str],
) -> tuple[dict[str, dict[str, list[dict[str, Any]]]], bool, str]:
    """Run deterministic startup phases and return warmup/cache outcome."""
    redis_has_data = await _has_stale_cache(redis)
    warmup_results: dict[str, dict[str, list[dict[str, Any]]]] = {}

    if redis_has_data:
        logger.info(
            "[Ingest] Redis candle cache detected — skipping Finnhub REST warmup. "
            "M15 will build from real-time WebSocket ticks."
        )
        system_state.set_state(SystemState.DEGRADED)
        return warmup_results, True, "stale_cache"

    logger.info("[Ingest] Redis empty — running Finnhub REST warmup")
    warmup_results = await _run_warmup(system_state, enabled_symbols)
    logger.info(
        "[Warmup] results count=%d symbols_with_data=%s",
        len(warmup_results),
        list(warmup_results.keys())[:10],
    )
    await _seed_redis_candle_history(redis, warmup_results)

    if warmup_results:
        return warmup_results, False, "warmup"
    return warmup_results, False, "failed_no_cache"


def _set_startup_mode(
    *,
    mode: str,
    warmup_results: dict[str, dict[str, list[dict[str, Any]]]],
    redis_has_data: bool,
) -> None:
    global _ingest_ready, _ingest_degraded

    _set_cache_mode(mode)

    if mode == "warmup":
        _ingest_ready = True
        _ingest_degraded = False
        _health_probe.set_detail("warmup", "complete")
        return

    if mode == "stale_cache":
        _ingest_ready = False
        _ingest_degraded = True
        _health_probe.set_detail("warmup", "skipped_redis_cache")
        return

    if not warmup_results and not redis_has_data:
        _ingest_ready = False
        _ingest_degraded = False
        _health_probe.set_detail("warmup", "failed_no_cache")
        logger.error(
            "[Ingest] Warmup failed and no stale cache available — service will remain NOT READY (circuit={})",
            _warmup_circuit.state.value,
        )


class Stoppable(Protocol):
    """Any object that exposes an async stop() method."""

    async def stop(self) -> None: ...


async def _run_supervised(name: str, runner: Any, restart_delay: float = 5.0) -> None:
    """Run a long-lived task with restart isolation for scheduled/background services."""
    while not (_shutdown_event and _shutdown_event.is_set()):
        try:
            await runner.run()
            return
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("[%s] crashed - restarting in %.1fs", name, restart_delay)
            await asyncio.sleep(restart_delay)


# ── Redis candle history — shared helpers ─────────────────────────
# Matches the key format used by RedisContextBridge.write_candle().
# Data is persistent in Redis volume — no TTL needed.
_SEED_HISTORY_MAXLEN = 300
_SEED_RPUSH_CHUNK_SIZE = 50


async def _push_candle_to_redis(
    redis: RedisClient,
    candle_dict: dict[str, Any],
) -> None:
    """Append a single completed candle to Redis history list + PUBLISH.

    Called fire-and-forget from CandleBuilder on_complete callbacks and
    from the REST refresh schedulers.  Keeps the Redis Lists that the
    engine's RedisConsumer reads in sync with live candle production.

    Also PUBLISHes the candle to ``candle:{symbol}:{timeframe}`` so the
    engine-side RedisConsumer.pub/sub loop receives the update in real-time
    instead of only seeing it on the next LRANGE warmup.
    """
    symbol = candle_dict.get("symbol")
    timeframe = candle_dict.get("timeframe")
    if not symbol or not timeframe:
        return
    key = f"wolf15:candle_history:{symbol}:{timeframe}"
    try:
        candle_json = orjson.dumps(candle_dict).decode("utf-8")
        await redis.rpush(key, candle_json)
        await redis.ltrim(key, -_SEED_HISTORY_MAXLEN, -1)

        # Persist for restart/redeploy recovery via PostgreSQL writer loop.
        enqueue_candle_dict(candle_dict)

        # Notify engine-side RedisConsumer via Pub/Sub (matches its psubscribe patterns)
        pub_channel = f"candle:{symbol}:{timeframe}"
        await redis.publish(pub_channel, candle_json)
    except Exception as exc:
        logger.warning("[CandleBridge] RPUSH/PUBLISH failed %s: %s", key, exc)


async def _seed_redis_candle_history(
    redis: RedisClient,
    warmup_results: dict[str, dict[str, list[dict[str, Any]]]],
) -> None:
    """Write REST-warmup candles into Redis Lists.

    This bridges the gap between FinnhubCandleFetcher (which populates the
    in-process LiveContextBus) and RedisConsumer on the engine side (which
    reads from Redis Lists for cross-container warmup).

    Key format: ``wolf15:candle_history:{SYMBOL}:{TF}``
    Serialisation: orjson, matching RedisContextBridge.write_candle().
    """
    if not warmup_results:
        logger.info("[Seed] No warmup results to seed into Redis")
        return

    seeded = 0
    total_dirty = 0
    for symbol, tf_data in warmup_results.items():
        for timeframe, candles in tf_data.items():
            if not candles:
                continue

            # ── FIX DATA-NEG1: reject candles with sentinel -1 / invalid OHLC ──
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

            key = f"wolf15:candle_history:{symbol}:{timeframe}"
            # ── FIX RC-1: Non-destructive atomic swap ─────────────
            # Write new data to a temp key, then RENAME atomically.
            # If the new seed fails, old data survives in Redis.
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
                        # Use explicit ISO-8601 to keep payload stable across clients.
                        normalized["timestamp"] = ts.isoformat()
                    serialized.append(orjson.dumps(normalized).decode("utf-8"))

                # Write in small chunks to temp key
                for i in range(0, len(serialized), _SEED_RPUSH_CHUNK_SIZE):
                    chunk = serialized[i : i + _SEED_RPUSH_CHUNK_SIZE]
                    await redis.rpush(temp_key, *chunk)

                # Atomic swap: only replace if new data was written
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
                # Cleanup temp key on failure; old data preserved in `key`
                with contextlib.suppress(Exception):
                    await redis.delete(temp_key)
                logger.error("[Seed] Failed to seed {}: {} — old data preserved", key, exc)

    if total_dirty:
        logger.warning("[Seed] Total dirty candles rejected across all pairs: %d", total_dirty)
    logger.info("[Seed] Completed: {} symbol/tf combos seeded to Redis", seeded)


async def _safe_stop(name: str, obj: Any, cleanup_errors: list[tuple[str, Exception]]) -> None:
    stop = getattr(obj, "stop", None)
    if stop is None:
        return
    try:
        await stop()
    except Exception as exc:
        logger.error(f"Error stopping {name}: {exc}")
        cleanup_errors.append((f"{name}.stop()", exc))


async def run_ingest_services(has_api_key: bool) -> None:
    """Run ingest loops for WS, calendar, market news, and schedulers."""
    global _producer_present, _producer_last_heartbeat_ts
    _producer_present = False
    _producer_last_heartbeat_ts = 0.0
    _pair_last_tick_ts.clear()
    _pair_last_tick_fingerprint.clear()
    _set_cache_mode("unknown")

    if not has_api_key:
        logger.info("Skipping ingest services - no API key configured")
        while not (_shutdown_event and _shutdown_event.is_set()):  # noqa: ASYNC110
            await asyncio.sleep(1)
        return

    enabled_symbols = get_enabled_symbols()
    logger.info(
        "[Ingest] enabled symbols count=%d symbols=%s",
        len(enabled_symbols),
        enabled_symbols[:10],
    )
    redis: RedisClient | None = None
    ws_feed = None
    rest_poll = None
    news_feed = None
    market_news = None
    producer_heartbeat_task: asyncio.Task[None] | None = None
    candle_builders: dict[str, CandleBuilder] = {}

    try:
        redis = await _connect_redis_with_retry()
        system_state = SystemStateManager()
        # P0-1: Reset state at entry so retries are idempotent even when
        # main()'s reset() call was suppressed by contextlib.suppress.
        system_state.reset()
        system_state.set_state(SystemState.WARMING_UP)

        warmup_results, redis_has_data, startup_mode = await _bootstrap_cache_and_warmup(
            redis=redis,
            system_state=system_state,
            enabled_symbols=enabled_symbols,
        )
        _set_startup_mode(
            mode=startup_mode,
            warmup_results=warmup_results,
            redis_has_data=redis_has_data,
        )

        # ── Build M15 → H1 candle chain with Redis RPUSH callbacks ────
        # Every completed M15 and H1 candle is written to Redis so the
        # engine container (separate process) sees fresh data.
        loop = asyncio.get_running_loop()
        h1_builders: dict[str, CandleBuilder] = {}

        def _h1_on_complete(candle: Any) -> None:
            """H1 complete → RPUSH to Redis."""
            loop.create_task(_push_candle_to_redis(redis, candle.to_dict()))

        for _sym in enabled_symbols:
            h1_builders[_sym] = CandleBuilder(
                symbol=_sym,
                timeframe=Timeframe.H1,
                on_complete=_h1_on_complete,
            )

        def _make_m15_callback(sym: str) -> Any:
            """Factory — avoids closure-in-loop pitfall."""

            def _cb(candle: Any) -> None:
                loop.create_task(_push_candle_to_redis(redis, candle.to_dict()))
                h1b = h1_builders.get(sym)
                if h1b is not None:
                    h1b.on_candle(candle)

            return _cb

        candle_builders = {
            symbol: CandleBuilder(
                symbol=symbol,
                timeframe=Timeframe.M15,
                on_complete=_make_m15_callback(symbol),
            )
            for symbol in enabled_symbols
        }
        logger.info(
            "[CandleBridge] M15→H1 chain wired for %d symbols — completed candles will RPUSH to Redis",
            len(enabled_symbols),
        )

        # Tick callback: route to CandleBuilder per symbol
        def _on_tick(symbol: str, price: float, ts: datetime, volume: float) -> None:
            _mark_pair_tick(symbol, ts.timestamp())
            tick_ts = ts.timestamp()
            if _is_duplicate_pair_tick(symbol, price, tick_ts):
                return
            _mark_pair_tick(symbol, tick_ts)
            cb = candle_builders.get(symbol)
            if cb is not None:
                cb.on_tick(price, ts, volume)

        # Create HTF refresh scheduler early so we can wire its force_refresh_now
        # as the on_connect callback for the WS feed. This ensures HTF candles are
        # refreshed immediately after WS reconnects, shortening the stale window.
        htf_refresh = HTFRefreshScheduler(redis_client=redis)

        ws_feed = await create_finnhub_ws(
            redis=redis,  # pyright: ignore[reportArgumentType]
            candle_callback=_on_tick,
            on_connect=htf_refresh.force_refresh_now,
        )
        producer_heartbeat_task = asyncio.create_task(
            _producer_heartbeat_loop(ws_feed=ws_feed, redis=redis),
            name="IngestProducerHeartbeat",
        )

        # REST poll fallback: automatically polls M15/H1 from REST when WS is down
        def _ws_connected_fn() -> bool:
            with contextlib.suppress(Exception):
                return bool(getattr(ws_feed, "is_connected", False))
            return False

        rest_poll = RestPollFallback(
            ws_connected_fn=_ws_connected_fn,
            symbols=enabled_symbols,
            redis_client=redis,
        )
        news_feed = CalendarNewsIngestor(redis_client=redis)
        market_news = FinnhubMarketNews()
        h1_refresh = H1RefreshScheduler(redis_client=redis)

        _health_probe.set_detail("redis", "connected")
        _health_probe.set_detail("system_state", system_state.get_state().value)
        logger.info(
            "Ingest startup mode: %s | ready=%s degraded=%s",
            startup_mode,
            _ingest_ready,
            _ingest_degraded,
        )

        macro_monthly = MacroMonthlyScheduler(enabled_symbols, redis_client=redis)
        logger.info("Starting ingest services: WebSocket + supervised background refresh/poll/news tasks")
        await asyncio.gather(
            _run_supervised("finnhub_ws", ws_feed),
            _run_supervised("rest_poll_fallback", rest_poll),
            _run_supervised("calendar_news", news_feed),
            _run_supervised("market_news", market_news),
            _run_supervised("h1_refresh", h1_refresh),
            _run_supervised("htf_refresh", htf_refresh),
            _run_supervised("macro_monthly_refresh", macro_monthly),
        )
    except asyncio.CancelledError:
        logger.info("Ingest services cancelled - shutting down")
        raise
    finally:
        cleanup_errors: list[tuple[str, Exception]] = []
        if producer_heartbeat_task is not None:
            producer_heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await producer_heartbeat_task
        await _safe_stop("ws_feed", ws_feed, cleanup_errors)
        await _safe_stop("rest_poll", rest_poll, cleanup_errors)
        await _safe_stop("news_feed", news_feed, cleanup_errors)
        await _safe_stop("market_news", market_news, cleanup_errors)
        if candle_builders:
            for name, cb in candle_builders.items():
                await _safe_stop(f"candle_builder[{name}]", cb, cleanup_errors)

        if redis is not None:
            try:
                await redis.aclose()
            except Exception as exc:
                logger.error(f"Error closing redis: {exc}")
                cleanup_errors.append(("redis.aclose()", exc))

        if cleanup_errors:
            logger.warning(f"Cleanup completed with {len(cleanup_errors)} error(s)")
        logger.info("Ingest service cleanup complete")


def _handle_signal(signum: int, frame: types.FrameType | None) -> None:
    signal_name = signal.Signals(signum).name
    logger.info(f"Received {signal_name} - initiating graceful shutdown...")
    if _shutdown_event:
        _shutdown_event.set()


async def main(
    *,
    _bootstrap_probe: HealthProbe | None = None,
) -> None:
    """Ingest service entry point.

    Parameters
    ----------
    _bootstrap_probe:
        If provided, an already-started :class:`HealthProbe` created by
        ``ingest_worker.py``.  ``main()`` reuses it so Railway's prober
        never sees a gap while the port is re-bound.
    """
    global _shutdown_event, _health_probe
    _shutdown_event = asyncio.Event()

    # Configure logging — split streams for Railway compatibility
    # ── Probe ownership ──────────────────────────────────────────
    owns_probe: bool
    health_task: asyncio.Task[None] | None
    if _bootstrap_probe is not None:
        _health_probe = _bootstrap_probe
        _health_probe.set_readiness_check(_ingest_readiness)
        owns_probe = False
        health_task = None  # already running in caller
    else:
        owns_probe = True
        health_task = None  # assigned below

    logger.remove()

    # INFO/WARNING → stdout (Railway classifies as "info")
    logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan> - "
        "<level>{message}</level>",
        level="INFO",
        filter=lambda record: record["level"].no < 40,  # Below ERROR
    )

    # ERROR/CRITICAL → stderr (Railway classifies as "error")
    logger.add(
        sys.stderr,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>"
        ),
        level="ERROR",
    )

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    if owns_probe:
        # Start health probe FIRST so Railway sees liveness immediately
        # while the rest of initialization proceeds.
        health_task = asyncio.create_task(_health_probe.start(), name="IngestHealthProbe")
        # Yield to event loop so the health probe can bind its port
        # before any potentially slow/failing initialization runs.
        await asyncio.sleep(0.1)

    try:
        has_api_key = _validate_api_key()
        _health_probe.set_detail("startup_stage", "initializing_storage")
        await init_persistent_storage()
        _health_probe.set_detail("startup_stage", "running")

        restart_attempt = 0
        while not _shutdown_event.is_set():
            try:
                await run_ingest_services(has_api_key)
                break
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                restart_attempt += 1
                backoff = min(30.0, float(2 ** min(restart_attempt, 5)))
                _health_probe.set_detail("runtime_restart", str(restart_attempt))
                _health_probe.set_detail("runtime_error", str(exc)[:120])
                logger.exception(
                    "Ingest runtime failed (attempt {}), restarting in {:.1f}s: {}",
                    restart_attempt,
                    backoff,
                    exc,
                )
                with contextlib.suppress(Exception):
                    SystemStateManager().reset()
                await asyncio.sleep(backoff)
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received")
    except Exception as exc:
        _health_probe.set_detail("fatal_error", str(exc)[:120])
        logger.exception(f"Ingest bootstrap failed: {exc}")
        # Stay alive so the health probe keeps responding to Railway.
        # (When launched via ingest_worker, the caller owns the probe and
        #  will hold the process open; in standalone mode we wait here.)
        if owns_probe and _shutdown_event:
            with contextlib.suppress(asyncio.CancelledError):
                await _shutdown_event.wait()
    finally:
        if health_task is not None:
            health_task.cancel()
        if owns_probe:
            await _health_probe.stop()
        await shutdown_persistent_storage()
        logger.info("Ingest service shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
