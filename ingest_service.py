"""Standalone ingest service for multi-container deployments.

This is the slim entrypoint. Business logic lives in:
  - ingest/service_metrics.py  — health, readiness, metrics, tick dedup
  - ingest/redis_setup.py      — Redis client construction + retry
  - ingest/warmup_bootstrap.py — warmup, stale-cache, HTF fetch, seeding
  - ingest/service_runner.py   — run_ingest_services() orchestration loop
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import types
from datetime import datetime

import orjson
from dotenv import load_dotenv


def _is_railway_runtime() -> bool:
    return bool(
        os.environ.get("RAILWAY_ENVIRONMENT")
        or os.environ.get("RAILWAY_ENVIRONMENT_ID")
        or os.environ.get("RAILWAY_PROJECT_ID")
        or os.environ.get("RAILWAY_SERVICE_ID")
        or os.environ.get("RAILWAY_DEPLOYMENT_ID")
        or os.environ.get("RAILWAY_REPLICA_ID")
    )


def _env_true(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


# Load .env only for local/dev workflows. On Railway, rely on platform env vars
# unless explicitly forced via WOLF15_LOAD_DOTENV=true.
if _env_true(os.getenv("WOLF15_LOAD_DOTENV")) or not _is_railway_runtime():
    load_dotenv(override=False)

from loguru import logger  # noqa: E402

from config.logging_bootstrap import configure_loguru_logging  # noqa: E402
from context.system_state import SystemState, SystemStateManager  # noqa: E402
from core.health_probe import HealthProbe  # noqa: E402
from core.redis_keys import candle_history  # noqa: E402
from ingest import service_metrics as _service_metrics  # noqa: E402
from ingest.finnhub_candles import FinnhubCandleFetcher  # noqa: E402
from ingest.redis_setup import connect_redis_with_retry as _connect_redis_with_retry  # noqa: E402
from ingest.service_metrics import ingest_readiness  # noqa: E402
from storage.startup import init_persistent_storage, shutdown_persistent_storage  # noqa: E402

_shutdown_event: asyncio.Event | None = None
_health_probe = _service_metrics.health_probe
_ingest_ready = _service_metrics.ingest_ready
_ingest_degraded = _service_metrics.ingest_degraded
_SEED_RPUSH_CHUNK_SIZE = 50
_SUPP_HTF_MIN_BARS = {"H1": 20, "H4": 10, "D1": 5}
_SUPP_FETCH_BARS = 50


class _WarmupCircuitFacade:
    def is_open(self) -> bool:
        try:
            from ingest.warmup_bootstrap import warmup_circuit  # noqa: PLC0415

            return bool(warmup_circuit.is_open())
        except Exception:
            return False


_warmup_circuit = _WarmupCircuitFacade()


async def _has_stale_cache(redis):
    try:
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor, match="wolf15:candle_history:*", count=20)
            for key in keys:
                if await redis.llen(key) > 0:
                    return True
            if cursor == 0:
                break
    except Exception as exc:
        logger.warning("[StaleCache] Cache scan failed: {}", exc)
    return False


async def _run_warmup(system_state: SystemStateManager, enabled_symbols: list[str]):
    from ingest.warmup_bootstrap import run_warmup  # noqa: PLC0415

    return await run_warmup(system_state, enabled_symbols)


async def _seed_redis_candle_history(redis, warmup_results):
    if not warmup_results:
        return

    for symbol, tf_data in warmup_results.items():
        for timeframe, candles in tf_data.items():
            if not candles:
                continue

            clean_candles = []
            for candle in candles:
                ohlc = [candle.get(k) for k in ("open", "high", "low", "close")]
                if all(value is not None for value in ohlc) and (
                    any(value <= 0 for value in ohlc) or candle["high"] < candle["low"]
                ):
                    continue
                normalized = dict(candle)
                ts = normalized.get("timestamp")
                if isinstance(ts, datetime):
                    normalized["timestamp"] = ts.isoformat()
                clean_candles.append(orjson.dumps(normalized).decode("utf-8"))

            if not clean_candles:
                continue

            key = candle_history(symbol, timeframe)
            temp_key = f"{key}:_seed_tmp"
            try:
                await redis.delete(temp_key)
            except Exception as exc:
                logger.warning("[Seed] DELETE temp key failed for %s (will attempt RPUSH anyway): %s", temp_key, exc)

            try:
                for index in range(0, len(clean_candles), _SEED_RPUSH_CHUNK_SIZE):
                    chunk = clean_candles[index : index + _SEED_RPUSH_CHUNK_SIZE]
                    await redis.rpush(temp_key, *chunk)
                if await redis.llen(temp_key) > 0:
                    await redis.rename(temp_key, key)
                else:
                    await redis.delete(temp_key)
            except Exception as exc:
                with contextlib.suppress(Exception):
                    await redis.delete(temp_key)
                logger.error("[Seed] Failed to seed {}: {}", key, exc)


async def _supplemental_htf_fetch(redis, enabled_symbols: list[str]):
    """Compatibility wrapper for the old ingest_service helper surface."""
    if _warmup_circuit.is_open():
        return {}

    deficit_map: dict[str, list[str]] = {}
    for symbol in enabled_symbols:
        missing = []
        for timeframe, required in _SUPP_HTF_MIN_BARS.items():
            try:
                have = await redis.llen(candle_history(symbol, timeframe))
            except Exception:
                have = 0
            if have < required:
                missing.append(timeframe)
        if missing:
            deficit_map[symbol] = missing

    if not deficit_map:
        return {}

    fetcher = FinnhubCandleFetcher()
    results: dict[str, dict[str, list[dict]]] = {}
    for symbol, timeframes in deficit_map.items():
        for timeframe in timeframes:
            try:
                candles = await fetcher.fetch(symbol, timeframe, _SUPP_FETCH_BARS)
            except Exception as exc:
                logger.error("[SuppHTF] {}/{} fetch failed: {}", symbol, timeframe, exc)
                continue
            if not candles:
                continue
            results.setdefault(symbol, {})[timeframe] = candles
            for candle in candles:
                with contextlib.suppress(Exception):
                    fetcher.context_bus.update_candle(candle)
    return results


async def _bootstrap_cache_and_warmup(
    redis,
    system_state: SystemStateManager,
    enabled_symbols: list[str],
):
    warmup_results = {}
    redis_has_data = await _has_stale_cache(redis)

    if redis_has_data:
        logger.info(
            "[Ingest] Redis candle cache detected - checking H1/H4 bar counts "
            "before deciding whether to skip REST warmup."
        )
        supp_results = await _supplemental_htf_fetch(redis, enabled_symbols)
        if supp_results:
            await _seed_redis_candle_history(redis, supp_results)
            warmup_results = supp_results

        system_state.set_state(SystemState.DEGRADED)
        return warmup_results, True, "stale_cache"

    logger.info("[Ingest] Redis empty - running Finnhub REST warmup")
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


def _sync_ingest_flags() -> None:
    global _ingest_ready, _ingest_degraded
    _ingest_ready = _service_metrics.ingest_ready
    _ingest_degraded = _service_metrics.ingest_degraded


def _set_startup_mode(*, mode: str, warmup_results, redis_has_data: bool) -> None:
    _service_metrics.set_startup_mode(
        mode=mode,
        warmup_results=warmup_results,
        redis_has_data=redis_has_data,
    )
    _sync_ingest_flags()


_DEFAULT_CONNECT = _connect_redis_with_retry
_DEFAULT_BOOTSTRAP = _bootstrap_cache_and_warmup


async def run_ingest_services(
    has_api_key: bool,
    shutdown_event: asyncio.Event | None = None,
) -> None:
    """Facade kept for tests and older imports; implementation lives in service_runner."""
    event = shutdown_event or _shutdown_event
    if not has_api_key:
        logger.info("Skipping ingest services - no API key configured")
        while not (event and event.is_set()):  # noqa: ASYNC110
            await asyncio.sleep(1)
        return

    if _connect_redis_with_retry is not _DEFAULT_CONNECT or _bootstrap_cache_and_warmup is not _DEFAULT_BOOTSTRAP:
        redis = None
        system_state = SystemStateManager()
        system_state.reset()
        system_state.set_state(SystemState.WARMING_UP)
        try:
            from config_loader import get_enabled_symbols  # noqa: PLC0415

            redis = await _connect_redis_with_retry(event)
            await _bootstrap_cache_and_warmup(
                redis=redis,
                system_state=system_state,
                enabled_symbols=get_enabled_symbols(),
            )
            return
        finally:
            if redis is not None:
                with contextlib.suppress(Exception):
                    await redis.aclose()

    from ingest import service_runner as _service_runner  # noqa: PLC0415

    original_connect = _service_runner.connect_redis_with_retry
    original_bootstrap = _service_runner.bootstrap_cache_and_warmup
    original_startup_mode = _service_runner.set_startup_mode
    _service_runner.connect_redis_with_retry = _connect_redis_with_retry
    _service_runner.bootstrap_cache_and_warmup = _bootstrap_cache_and_warmup
    _service_runner.set_startup_mode = _set_startup_mode
    try:
        await _service_runner.run_ingest_services(has_api_key, shutdown_event=event)
    finally:
        _service_runner.connect_redis_with_retry = original_connect
        _service_runner.bootstrap_cache_and_warmup = original_bootstrap
        _service_runner.set_startup_mode = original_startup_mode
        _sync_ingest_flags()


async def _preflight_redis_check() -> bool:
    """Fast ping to verify Redis is reachable before heavy init."""
    try:
        from ingest.redis_setup import build_redis_client  # noqa: PLC0415

        client = build_redis_client()
        try:
            await client.ping()
            return True
        except Exception:
            return False
        finally:
            with contextlib.suppress(Exception):
                await client.aclose()
    except Exception:
        return False


def _validate_api_key() -> bool:
    from ingest.finnhub_key_manager import finnhub_keys  # noqa: PLC0415

    if not finnhub_keys.available:
        logger.warning("WARNING: FINNHUB_API_KEY not configured; ingest running in DRY RUN mode.")
        return False
    logger.info("FINNHUB_API_KEY validated ({} key(s) loaded)", finnhub_keys.key_count)
    return True


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
    global _shutdown_event
    _shutdown_event = asyncio.Event()

    # ── Probe ownership ──────────────────────────────────────────
    from ingest import service_metrics as sm

    owns_probe: bool
    health_task: asyncio.Task[None] | None
    if _bootstrap_probe is not None:
        sm.health_probe = _bootstrap_probe
        sm.health_probe.set_readiness_check(ingest_readiness)
        owns_probe = False
        health_task = None
    else:
        owns_probe = True
        health_task = None

    hp = sm.health_probe

    # Shared Railway-safe routing and rate limiting.
    configure_loguru_logging(level=os.getenv("WOLF15_LOG_LEVEL"))

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    if owns_probe:
        health_task = asyncio.create_task(hp.start(), name="IngestHealthProbe")
        await asyncio.sleep(0.1)

    try:
        has_api_key = _validate_api_key()
        hp.set_detail("startup_stage", "initializing_storage")
        await init_persistent_storage()
        hp.set_detail("startup_stage", "running")

        restart_attempt = 0
        while not _shutdown_event.is_set():
            # ── Preflight: fast Redis connectivity check ─────────────
            # If Redis is unreachable, skip the heavy init inside
            # run_ingest_services() and wait here instead — avoids
            # rebuilding candle builders, WS feeds, etc. each attempt.
            if restart_attempt > 0:
                redis_ok = await _preflight_redis_check()
                if not redis_ok:
                    backoff = min(30.0, float(2 ** min(restart_attempt, 5)))
                    hp.set_detail("runtime_restart", str(restart_attempt))
                    hp.set_detail("runtime_error", "redis_preflight_failed")
                    logger.warning(
                        "Redis preflight failed (attempt %d) — retrying in %.1fs",
                        restart_attempt,
                        backoff,
                    )
                    restart_attempt += 1
                    await asyncio.sleep(backoff)
                    continue

            try:
                await run_ingest_services(has_api_key)
                break
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                restart_attempt += 1
                backoff = min(30.0, float(2 ** min(restart_attempt, 5)))
                hp.set_detail("runtime_restart", str(restart_attempt))
                hp.set_detail("runtime_error", str(exc)[:120])
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
        hp.set_detail("fatal_error", str(exc)[:120])
        logger.exception(f"Ingest bootstrap failed: {exc}")
        if owns_probe and _shutdown_event:
            with contextlib.suppress(asyncio.CancelledError):
                await _shutdown_event.wait()
    finally:
        if health_task is not None:
            health_task.cancel()
        if owns_probe:
            await hp.stop()
        await shutdown_persistent_storage()
        logger.info("Ingest service shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
