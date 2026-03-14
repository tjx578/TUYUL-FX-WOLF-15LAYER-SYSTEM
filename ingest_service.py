"""Standalone ingest service for multi-container deployments."""

import asyncio
import contextlib
import os
import signal
import sys
import types
from datetime import datetime
from importlib import import_module
from typing import Any, Protocol

import orjson  # noqa: I001  — needed before analysis imports for _seed_redis_candle_history
from loguru import logger

from analysis.macro.macro_regime_engine import MacroRegimeEngine
from config_loader import CONFIG
from context.system_state import SystemState, SystemStateManager
from core.health_probe import HealthProbe
from infrastructure.circuit_breaker import CircuitBreaker
from ingest.calendar_news import CalendarNewsIngestor
from ingest.candle_builder import CandleBuilder, Timeframe
from ingest.dependencies import create_finnhub_ws
from ingest.finnhub_candles import FinnhubCandleFetcher
from ingest.finnhub_market_news import FinnhubMarketNews
from ingest.h1_refresh_scheduler import H1RefreshScheduler
from ingest.macro_monthly_scheduler import MacroMonthlyScheduler
from ingest.rest_poll_fallback import RestPollFallback
from storage.startup import init_persistent_storage, shutdown_persistent_storage

_shutdown_event: asyncio.Event | None = None
MAX_RETRIES = 10
BASE_DELAY = 1.0

# ── Health probe for container orchestration ──────────────────────
# Railway injects PORT for its proxy/healthcheck. Prefer INGEST_HEALTH_PORT,
# then fall back to PORT (Railway-injected), then default 8082.
_INGEST_HEALTH_PORT = int(os.getenv("INGEST_HEALTH_PORT") or os.getenv("PORT", "8082"))
_health_probe = HealthProbe(port=_INGEST_HEALTH_PORT, service_name="ingest")
_ingest_ready = False
# Degraded mode: warmup failed but stale Redis cache is available.
# The service stays alive and serves cached data rather than crashing.
_ingest_degraded = False

# Circuit breaker for the warmup / provider chain.
# Configurable via WOLF15_CB_* env vars; defaults are conservative for ingest.
_warmup_circuit = CircuitBreaker(
    name="ingest_warmup",
    failure_threshold=int(os.getenv("WOLF15_INGEST_CB_FAILURE_THRESHOLD", "3")),
    recovery_timeout=float(os.getenv("WOLF15_INGEST_CB_RECOVERY_TIMEOUT", "120")),
    half_open_success_threshold=int(os.getenv("WOLF15_INGEST_CB_HALF_OPEN_ATTEMPTS", "1")),
)


def _ingest_readiness() -> bool:
    """Readiness gate.

    Returns ``True`` when:
    - (a) Normal operation: Redis connected + warmup complete (``_ingest_ready``), OR
    - (b) Degraded mode: warmup failed but stale Redis cache is available
          (``_ingest_degraded``), keeping the healthcheck passing so the
          container is not killed and can serve cached data.
    """
    return _ingest_ready or _ingest_degraded


_health_probe.set_readiness_check(_ingest_readiness)


class RedisClient(Protocol):
    """Minimal async Redis client contract used by ingest service."""

    async def ping(self) -> Any: ...
    async def aclose(self) -> None: ...


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
            cursor, keys = await redis.scan(cursor, match=pattern, count=20)  # type: ignore[attr-defined]
            for key in keys:
                length: int = await redis.llen(key)  # type: ignore[attr-defined]
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


def _get_enabled_symbols() -> list[str]:
    from typing import cast

    raw: Any = CONFIG.get("pairs", {}).get("pairs", [])
    if not isinstance(raw, list):
        return []
    pairs: list[dict[str, Any]] = cast(list[dict[str, Any]], raw)
    return [p["symbol"] for p in pairs if isinstance(p, dict) and p.get("enabled")]


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
    max_retries = int(os.getenv("INGEST_REDIS_CONNECT_MAX_RETRIES", "60"))
    base_delay = float(os.getenv("INGEST_REDIS_CONNECT_DELAY_SEC", "2"))
    max_delay = float(os.getenv("INGEST_REDIS_CONNECT_MAX_DELAY_SEC", "30"))

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
            "[Warmup] Circuit breaker OPEN (failure_count={}) — skipping warmup, "
            "will use stale cache fallback",
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


class Stoppable(Protocol):
    """Any object that exposes an async stop() method."""

    async def stop(self) -> None: ...


# ── Redis candle history seeding ──────────────────────────────────
# Matches the key format used by RedisContextBridge.write_candle().
# Data is persistent in Redis volume — no TTL needed.
_SEED_HISTORY_MAXLEN = 300


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
    for symbol, tf_data in warmup_results.items():
        for timeframe, candles in tf_data.items():
            if not candles:
                continue

            key = f"wolf15:candle_history:{symbol}:{timeframe}"

            with contextlib.suppress(Exception):
                existing: int = await redis.llen(key)  # type: ignore[attr-defined]
                if existing >= len(candles):
                    logger.debug("[Seed] %s already has %d bars, skip", key, existing)
                    continue

            try:
                pipe = redis.pipeline()  # type: ignore[attr-defined]
                for candle in candles:
                    candle_json = orjson.dumps(candle).decode("utf-8")
                    pipe.rpush(key, candle_json)
                await pipe.execute()
                seeded += 1
                logger.info("[Seed] {}: {} bars written", key, len(candles))
            except Exception as exc:
                logger.error("[Seed] Failed to seed {}: {}", key, exc)

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
    if not has_api_key:
        logger.info("Skipping ingest services - no API key configured")
        while not (_shutdown_event and _shutdown_event.is_set()):  # noqa: ASYNC110
            await asyncio.sleep(1)
        return

    enabled_symbols = _get_enabled_symbols()
    redis: RedisClient | None = None
    ws_feed = None
    rest_poll = None
    news_feed = None
    market_news = None
    candle_builders: dict[str, CandleBuilder] = {}

    try:
        redis = await _connect_redis_with_retry()
        system_state = SystemStateManager()
        system_state.set_state(SystemState.WARMING_UP)
        warmup_results = await _run_warmup(system_state, enabled_symbols)

        # Seed Redis Lists so the engine's RedisConsumer can warm up
        # without waiting for live candle completion (fixes race condition).
        await _seed_redis_candle_history(redis, warmup_results)

        # ── Degraded-mode stale cache gate ────────────────────────────────
        # When warmup produced no results (Finnhub/providers all 403 or timed
        # out), check whether Redis already holds candle data from a prior run.
        # If it does, mark the service as "degraded-ready" so the healthcheck
        # passes and the container stays alive to serve cached data.
        global _ingest_ready, _ingest_degraded
        if not warmup_results:
            if await _has_stale_cache(redis):
                _ingest_degraded = True
                _health_probe.set_detail("warmup", "degraded_stale_cache")
                _health_probe.set_detail("circuit_state", _warmup_circuit.state.value)
                logger.warning(
                    "[Ingest] Warmup failed but stale cache found in Redis — "
                    "service running in DEGRADED mode (readiness=True, circuit={})",
                    _warmup_circuit.state.value,
                )
            else:
                _health_probe.set_detail("warmup", "failed_no_cache")
                logger.error(
                    "[Ingest] Warmup failed and no stale cache available — "
                    "service will remain NOT READY (circuit={})",
                    _warmup_circuit.state.value,
                )
        # ── End degraded-mode gate ────────────────────────────────────────

        # Build candle builders as dict for O(1) lookup
        candle_builders = {symbol: CandleBuilder(symbol=symbol, timeframe=Timeframe.M15) for symbol in enabled_symbols}

        # Tick callback: route to CandleBuilder per symbol
        def _on_tick(symbol: str, price: float, ts: datetime, volume: float) -> None:
            cb = candle_builders.get(symbol)
            if cb is not None:
                cb.on_tick(price, ts, volume)

        ws_feed = await create_finnhub_ws(
            redis=redis,  # pyright: ignore[reportArgumentType]
            candle_callback=_on_tick,
        )
        # REST poll fallback: automatically polls M15/H1 from REST when WS is down
        rest_poll = RestPollFallback(
            ws_connected_fn=lambda: ws_feed.is_connected if ws_feed else False,
            symbols=enabled_symbols,
        )
        news_feed = CalendarNewsIngestor(redis_client=redis)
        market_news = FinnhubMarketNews()
        h1_refresh = H1RefreshScheduler()

        # Mark ingest as ready after warmup + connection
        _ingest_ready = True
        _health_probe.set_detail("warmup", "complete")
        _health_probe.set_detail("redis", "connected")
        _health_probe.set_detail("system_state", system_state.get_state().value)
        logger.info("Ingest readiness: READY")

        logger.info(
            "Starting ingest services: WebSocket, RestPollFallback, CalendarNews, MarketNews, CandleBuilder (M15 via tick callback), H1Refresh"
        )
        await asyncio.gather(
            ws_feed.run(),
            rest_poll.run(),
            news_feed.run(),
            market_news.run(),
            h1_refresh.run(),
            MacroMonthlyScheduler(enabled_symbols).run(),
        )
    except asyncio.CancelledError:
        logger.info("Ingest services cancelled - shutting down")
        raise
    finally:
        cleanup_errors: list[tuple[str, Exception]] = []
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


async def main() -> None:
    global _shutdown_event
    _shutdown_event = asyncio.Event()

    logger.remove()
    logger.add(
        sys.stdout,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>"
        ),
        level="INFO",
        filter=lambda record: record["level"].no < 40,
    )
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
                await asyncio.sleep(backoff)
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received")
    except Exception as exc:
        _health_probe.set_detail("fatal_error", str(exc)[:120])
        logger.exception(f"Ingest bootstrap failed: {exc}")
        raise
    finally:
        health_task.cancel()
        await _health_probe.stop()
        await shutdown_persistent_storage()
        logger.info("Ingest service shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
