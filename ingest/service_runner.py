"""Ingest service main orchestration loop.

Extracted from ingest_service.py for maintainability.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime
from time import time
from typing import Any, Protocol

import orjson
from loguru import logger

from config_loader import get_enabled_symbols
from context.system_state import SystemState, SystemStateManager
from core.redis_keys import HEARTBEAT_INGEST, HEARTBEAT_INGEST_PROCESS, HEARTBEAT_INGEST_PROVIDER
from ingest.calendar_news import CalendarNewsIngestor
from ingest.candle_builder import CandleBuilder, Timeframe
from ingest.dependencies import create_finnhub_ws
from ingest.finnhub_market_news import FinnhubMarketNews
from ingest.forming_bar_publisher import FormingBarPublisher
from ingest.h1_refresh_scheduler import H1RefreshScheduler
from ingest.htf_refresh_scheduler import HTFRefreshScheduler
from ingest.macro_monthly_scheduler import MacroMonthlyScheduler
from ingest.micro_candle_chain import MicroCandleChain
from ingest.redis_setup import RedisClient, connect_redis_with_retry
from ingest.rest_poll_fallback import RestPollFallback
from ingest.service_metrics import (
    emit_ingest_runtime_metrics,
    health_probe,
    is_duplicate_pair_tick,
    mark_pair_tick,
    producer_fresh,
    set_startup_mode,
    update_producer_health,
)
from ingest.warmup_bootstrap import bootstrap_cache_and_warmup

_PRODUCER_HEARTBEAT_KEY = HEARTBEAT_INGEST
_PRODUCER_HEARTBEAT_INTERVAL_SEC = max(
    1.0, float(__import__("os").getenv("INGEST_PRODUCER_HEARTBEAT_INTERVAL_SEC", "5"))
)


class Stoppable(Protocol):
    """Any object that exposes an async stop() method."""

    async def stop(self) -> None: ...


async def _producer_heartbeat_loop(ws_feed: Any, redis: RedisClient, shutdown_event: asyncio.Event | None) -> None:
    from ingest.service_metrics import fresh_pair_count

    while not (shutdown_event and shutdown_event.is_set()):
        connected = bool(getattr(ws_feed, "is_connected", False))
        update_producer_health(connected)
        health_probe.set_detail("producer_present", "1" if connected else "0")
        health_probe.set_detail("producer_fresh", "1" if producer_fresh() else "0")
        from ingest.service_metrics import producer_last_heartbeat_ts

        health_probe.set_detail(
            "producer_heartbeat_age_sec",
            f"{max(0.0, time() - producer_last_heartbeat_ts):.2f}",
        )
        health_probe.set_detail("fresh_pairs", str(fresh_pair_count()))
        emit_ingest_runtime_metrics(connected)

        process_payload = {"producer": "ingest_service", "ts": time(), "ws_connected": connected}
        with contextlib.suppress(Exception):
            await redis.set(HEARTBEAT_INGEST_PROCESS, orjson.dumps(process_payload).decode("utf-8"))

        if connected:
            provider_payload = {"producer": "finnhub_ws", "ts": time()}
            with contextlib.suppress(Exception):
                await redis.set(HEARTBEAT_INGEST_PROVIDER, orjson.dumps(provider_payload).decode("utf-8"))

        if connected:
            legacy_payload = {"producer": "finnhub_ws", "ts": time()}
            with contextlib.suppress(Exception):
                await redis.set(_PRODUCER_HEARTBEAT_KEY, orjson.dumps(legacy_payload).decode("utf-8"))

        await asyncio.sleep(_PRODUCER_HEARTBEAT_INTERVAL_SEC)


async def _run_supervised(
    name: str,
    runner: Any,
    restart_delay: float = 5.0,
    shutdown_event: asyncio.Event | None = None,
) -> None:
    """Run a long-lived task with restart isolation."""
    while not (shutdown_event and shutdown_event.is_set()):
        try:
            await runner.run()
            return
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("[%s] crashed - restarting in %.1fs", name, restart_delay)
            await asyncio.sleep(restart_delay)


async def _safe_stop(name: str, obj: Any, cleanup_errors: list[tuple[str, Exception]]) -> None:
    stop = getattr(obj, "stop", None)
    if stop is None:
        return
    try:
        await stop()
    except Exception as exc:
        logger.error(f"Error stopping {name}: {exc}")
        cleanup_errors.append((f"{name}.stop()", exc))


async def _check_redis(redis: RedisClient | None) -> bool:
    """Best-effort Redis health probe."""
    if redis is None:
        return False
    try:
        pong = await redis.ping()
        return bool(pong)
    except Exception:
        return False


class _HealthCheckRunner:
    """Periodic health monitor for WS + Redis connectivity."""

    def __init__(self, ws_connected_fn: Any, redis: RedisClient | None) -> None:
        self._ws_connected_fn = ws_connected_fn
        self._redis = redis

    async def run(self) -> None:
        """Monitor system health and log status."""
        while True:
            try:
                ws_connected = bool(self._ws_connected_fn())
                redis_ok = await _check_redis(self._redis)

                status = "HEALTHY" if (ws_connected and redis_ok) else "DEGRADED"

                logger.info(
                    "[HealthCheck] %s | WS: %s | Redis: %s",
                    status,
                    ws_connected,
                    redis_ok,
                )

                await asyncio.sleep(60)  # Check every minute

            except Exception as e:
                logger.error(f"[HealthCheck] Error: {e}")
                await asyncio.sleep(60)

    async def stop(self) -> None:
        return None


async def run_ingest_services(
    has_api_key: bool,
    shutdown_event: asyncio.Event | None = None,
) -> None:
    """Run ingest loops for WS, calendar, market news, and schedulers."""
    from ingest import service_metrics as sm

    sm.producer_present = False
    sm.producer_last_heartbeat_ts = 0.0
    sm.pair_last_tick_ts.clear()
    sm.pair_last_tick_fingerprint.clear()
    sm.set_cache_mode("unknown")

    if not has_api_key:
        logger.info("Skipping ingest services - no API key configured")
        while not (shutdown_event and shutdown_event.is_set()):  # noqa: ASYNC110
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
    supervised_tasks: list[asyncio.Task[None]] = []
    candle_builders: dict[str, CandleBuilder] = {}
    forming_pub = None

    _phase = "init"
    try:
        _phase = "redis_connect"
        redis = await connect_redis_with_retry(shutdown_event)
        system_state = SystemStateManager()
        system_state.reset()
        system_state.set_state(SystemState.WARMING_UP)

        _phase = "warmup_bootstrap"
        warmup_results, redis_has_data, startup_mode = await bootstrap_cache_and_warmup(
            redis=redis,
            system_state=system_state,
            enabled_symbols=enabled_symbols,
        )
        set_startup_mode(
            mode=startup_mode,
            warmup_results=warmup_results,
            redis_has_data=redis_has_data,
        )

        # Inject async Redis client into tick_pipeline so its _on_candle_complete
        # callback can persist completed candles (fixes redis=None bug).
        from analysis.tick_pipeline import set_redis_client
        from core.candle_bridge_fix import publish_candle_sync

        set_redis_client(redis)

        h1_builders: dict[str, CandleBuilder] = {}

        def _h1_on_complete(candle: Any) -> None:
            publish_candle_sync(candle.to_dict(), redis=redis)

        for _sym in enabled_symbols:
            h1_builders[_sym] = CandleBuilder(
                symbol=_sym,
                timeframe=Timeframe.H1,
                on_complete=_h1_on_complete,
            )

        def _make_m15_callback(sym: str) -> Any:
            def _cb(candle: Any) -> None:
                publish_candle_sync(candle.to_dict(), redis=redis)
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

        micro_chain = MicroCandleChain(redis)
        micro_chain.init_symbols(enabled_symbols)

        forming_pub = FormingBarPublisher(redis)
        for _sym, _m15b in micro_chain.m15_builders.items():
            forming_pub.register_builder(_sym, "M15", _m15b)
        for _sym, _h1b in h1_builders.items():
            forming_pub.register_builder(_sym, "H1", _h1b)

        def _on_tick(symbol: str, price: float, ts: datetime, volume: float) -> None:
            mark_pair_tick(symbol, ts.timestamp())
            tick_ts = ts.timestamp()
            if is_duplicate_pair_tick(symbol, price, tick_ts):
                return
            mark_pair_tick(symbol, tick_ts)
            cb = candle_builders.get(symbol)
            if cb is not None:
                cb.on_tick(price, ts, volume)
            micro_chain.on_tick(symbol, price, ts, volume)

        htf_refresh = HTFRefreshScheduler(redis_client=redis)

        _phase = "ws_connect"
        ws_feed = await create_finnhub_ws(
            redis=redis,  # pyright: ignore[reportArgumentType]
            candle_callback=_on_tick,
            on_connect=htf_refresh.force_refresh_now,
        )
        producer_heartbeat_task = asyncio.create_task(
            _producer_heartbeat_loop(ws_feed=ws_feed, redis=redis, shutdown_event=shutdown_event),
            name="IngestProducerHeartbeat",
        )

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

        health_probe.set_detail("redis", "connected")
        health_probe.set_detail("system_state", system_state.get_state().value)
        logger.info(
            "Ingest startup mode: %s | ready=%s degraded=%s",
            startup_mode,
            sm.ingest_ready,
            sm.ingest_degraded,
        )

        macro_monthly = MacroMonthlyScheduler(enabled_symbols, redis_client=redis)
        logger.info("Starting ingest services: WebSocket + supervised background refresh/poll/news tasks")

        class _FormingPubRunner:
            def __init__(self, pub: FormingBarPublisher) -> None:
                self._pub = pub

            async def run(self) -> None:
                await self._pub.start()
                try:
                    while True:
                        await asyncio.sleep(3600)
                except asyncio.CancelledError:
                    await self._pub.stop()
                    raise

            async def stop(self) -> None:
                await self._pub.stop()

        _phase = "running"
        supervised_tasks = [
            asyncio.create_task(
                _run_supervised("finnhub_ws", ws_feed, shutdown_event=shutdown_event),
                name="IngestSupervisor:finnhub_ws",
            ),
            asyncio.create_task(
                _run_supervised("rest_poll_fallback", rest_poll, shutdown_event=shutdown_event),
                name="IngestSupervisor:rest_poll_fallback",
            ),
            asyncio.create_task(
                _run_supervised("calendar_news", news_feed, shutdown_event=shutdown_event),
                name="IngestSupervisor:calendar_news",
            ),
            asyncio.create_task(
                _run_supervised("market_news", market_news, shutdown_event=shutdown_event),
                name="IngestSupervisor:market_news",
            ),
            asyncio.create_task(
                _run_supervised("h1_refresh", h1_refresh, shutdown_event=shutdown_event),
                name="IngestSupervisor:h1_refresh",
            ),
            asyncio.create_task(
                _run_supervised("htf_refresh", htf_refresh, shutdown_event=shutdown_event),
                name="IngestSupervisor:htf_refresh",
            ),
            asyncio.create_task(
                _run_supervised("macro_monthly_refresh", macro_monthly, shutdown_event=shutdown_event),
                name="IngestSupervisor:macro_monthly_refresh",
            ),
            asyncio.create_task(
                _run_supervised("forming_publisher", _FormingPubRunner(forming_pub), shutdown_event=shutdown_event),
                name="IngestSupervisor:forming_publisher",
            ),
            asyncio.create_task(
                _run_supervised(
                    "health_check", _HealthCheckRunner(_ws_connected_fn, redis), shutdown_event=shutdown_event
                ),
                name="IngestSupervisor:health_check",
            ),
        ]
        await asyncio.gather(*supervised_tasks)
    except asyncio.CancelledError:
        logger.info("Ingest services cancelled during phase '%s' - shutting down", _phase)
        raise
    except Exception:
        logger.error("Ingest services failed during phase '%s'", _phase)
        raise
    finally:
        cleanup_errors: list[tuple[str, Exception]] = []
        for task in supervised_tasks:
            if not task.done():
                task.cancel()
        for task in supervised_tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        if producer_heartbeat_task is not None:
            producer_heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await producer_heartbeat_task
        await _safe_stop("ws_feed", ws_feed, cleanup_errors)
        await _safe_stop("rest_poll", rest_poll, cleanup_errors)
        await _safe_stop("news_feed", news_feed, cleanup_errors)
        await _safe_stop("market_news", market_news, cleanup_errors)
        if forming_pub is not None:
            await _safe_stop("forming_publisher", forming_pub, cleanup_errors)
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
