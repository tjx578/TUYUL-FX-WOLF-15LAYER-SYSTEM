"""
Async Allocation Worker (Redis Streams + consumer group).

Authority boundaries:
- Does NOT compute market direction.
- Does NOT execute trades.
- Consumes allocation requests and delegates risk sizing to AllocationService.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import tracemalloc
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any, cast

import redis.asyncio as aioredis
from loguru import logger
from prometheus_client import Counter, Gauge, Histogram, start_http_server
from redis.exceptions import ResponseError

from allocation.allocation_models import AllocationRequest
from allocation.allocation_service import AllocationService
from config.logging_bootstrap import configure_loguru_logging
from core.health_probe import HealthProbe
from infrastructure.redis_client import RedisConfig, close_pool, get_client
from infrastructure.tracing import (
    extract_trace_carrier,
    extract_trace_context,
    instrument_asyncio,
    instrument_redis,
    setup_tracer,
)

ALLOC_REQUEST_STREAM = "allocation:request"
ALLOC_GROUP = "alloc-group"
EXECUTION_STREAM = "execution:queue"

configure_loguru_logging()

alloc_latency = Histogram(
    "wolf_allocation_latency_seconds",
    "Allocation latency per request",
)
alloc_success = Counter(
    "wolf_alloc_success_total",
    "Allocation success per account",
    ["account_id"],
)
alloc_reject = Counter(
    "wolf_alloc_reject_total",
    "Allocation reject per account",
    ["account_id", "reason"],
)
alloc_requests_total = Counter(
    "wolf_alloc_requests_total",
    "Allocation requests consumed",
)
alloc_errors_total = Counter(
    "wolf_alloc_errors_total",
    "Allocation worker errors",
)
redis_stream_lag = Gauge(
    "wolf_redis_stream_lag",
    "Pending Redis stream messages per consumer group",
    ["stream", "group"],
)
process_memory = Gauge(
    "wolf_process_memory_bytes",
    "Python memory tracked by tracemalloc",
    ["service"],
)

_alloc_tracer = setup_tracer("wolf-allocation")
instrument_asyncio()
instrument_redis()


@dataclass(frozen=True)
class WorkerConfig:
    stream: str = ALLOC_REQUEST_STREAM
    group: str = ALLOC_GROUP
    worker_name: str = f"alloc-{uuid.uuid4().hex[:8]}"
    block_ms: int = 5000
    count: int = 10
    max_concurrency: int = 5
    metrics_port: int = int(os.getenv("ALLOC_METRICS_PORT", "9102"))

    @property
    def redis_socket_timeout(self) -> float:
        # Keep socket timeout comfortably above XREADGROUP block window.
        # block_ms=5000 with socket_timeout=5.0 can produce spurious TimeoutError.
        return max((self.block_ms / 1000.0) + 2.0, 10.0)


class AsyncAllocationWorker:
    def __init__(self, config: WorkerConfig | None = None) -> None:
        super().__init__()
        self._cfg = config or WorkerConfig()
        self._service = AllocationService()
        self._sem = asyncio.Semaphore(self._cfg.max_concurrency)
        self._in_flight: list[asyncio.Task[None]] = []
        self._orchestrator_alive: bool = True

    async def run(self) -> None:
        tracemalloc.start()
        logger.info(
            "Allocation worker started (worker={} stream={} metrics={})",
            self._cfg.worker_name,
            self._cfg.stream,
            self._cfg.metrics_port,
        )

        backoff = 1.0
        max_backoff = 60.0

        while True:
            try:
                base_cfg = RedisConfig.from_env()
                redis_cfg = replace(base_cfg, socket_timeout=self._cfg.redis_socket_timeout)
                redis_client = await get_client(redis_cfg)
                await self._ensure_group(redis_client)
                await self._recover_pending(redis_client)
                backoff = 1.0  # Reset on successful connect

                while True:
                    try:
                        response = await redis_client.xreadgroup(
                            groupname=self._cfg.group,
                            consumername=self._cfg.worker_name,
                            streams={self._cfg.stream: ">"},
                            count=self._cfg.count,
                            block=self._cfg.block_ms,
                        )
                    except aioredis.TimeoutError:
                        # Long-poll timeout can occur on quiet streams when socket_timeout
                        # is close to block_ms. Treat as empty poll, not a hard disconnect.
                        response = []
                    except (
                        aioredis.ConnectionError,
                        OSError,
                    ) as exc:
                        alloc_errors_total.inc()
                        logger.warning(
                            "xreadgroup connection error: {} — reconnecting",
                            type(exc).__name__,
                        )
                        await close_pool()
                        break  # Break inner loop → reconnect in outer loop

                    await self._update_runtime_metrics(redis_client)
                    await self._check_orchestrator_health(redis_client)

                    if not response:
                        continue

                    tasks: list[asyncio.Task[None]] = []
                    for stream_name, messages in response:
                        for msg_id, msg in messages:
                            tasks.append(
                                asyncio.create_task(
                                    self._handle_message(
                                        redis_client,
                                        stream_name,
                                        msg_id,
                                        msg,
                                    ),
                                ),
                            )
                    if tasks:
                        # Track in-flight for graceful drain on shutdown
                        self._in_flight = [t for t in self._in_flight if not t.done()]
                        self._in_flight.extend(tasks)
                        await asyncio.gather(*tasks, return_exceptions=False)

            except asyncio.CancelledError:
                logger.info("Allocation worker cancelled — draining in-flight tasks")
                await self._drain_in_flight()
                raise
            except Exception as exc:
                alloc_errors_total.inc()
                logger.exception(
                    "Allocation worker error: {} — retry in {:.1f}s",
                    exc,
                    backoff,
                )

            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)

    async def _drain_in_flight(self) -> None:
        """Wait for in-flight allocation tasks to complete before shutdown."""
        from startup.graceful_shutdown import GracefulShutdown  # noqa: PLC0415

        gs = GracefulShutdown(
            drain_timeout=float(os.getenv("SHUTDOWN_DRAIN_SEC", "15")),
        )
        await gs.drain_worker_tasks(self._in_flight, label="allocation")

    async def _ensure_group(self, redis_client: aioredis.Redis) -> None:
        try:
            await redis_client.xgroup_create(
                name=self._cfg.stream,
                groupname=self._cfg.group,
                id="0",
                mkstream=True,
            )
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def _recover_pending(self, redis_client: aioredis.Redis) -> int:
        """Claim and re-process orphaned PEL messages (P1-10).

        Messages idle > 60s are assumed orphaned (crashed consumer).
        Returns the number of messages recovered.
        """
        min_idle_ms = 60_000
        count = 50
        recovered = 0
        try:
            claimed = await redis_client.xautoclaim(
                name=self._cfg.stream,
                groupname=self._cfg.group,
                consumername=self._cfg.worker_name,
                min_idle_time=min_idle_ms,
                start_id="0-0",
                count=count,
            )
            # xautoclaim returns (next_start_id, messages, deleted_ids)
            if claimed and len(claimed) >= 2:
                messages = claimed[1]
                for msg_id, msg in messages:
                    if msg:
                        await self._handle_message(redis_client, self._cfg.stream, msg_id, msg)
                        recovered += 1
            if recovered > 0:
                logger.info(
                    "[PEL-Recovery] Reclaimed and processed {} orphaned messages",
                    recovered,
                )
        except Exception as exc:
            logger.warning("[PEL-Recovery] Failed: {}", exc)
        return recovered

    async def _handle_message(
        self, redis_client: aioredis.Redis, stream_name: str, msg_id: str, msg: dict[str, str]
    ) -> None:
        async with self._sem:
            parent_context = extract_trace_context(extract_trace_carrier(msg))
            with _alloc_tracer.start_as_current_span("allocation_process", context=parent_context) as span:
                alloc_requests_total.inc()
                span.set_attribute("redis.stream", stream_name)
                span.set_attribute("redis.message_id", msg_id)

                # Reject allocation if orchestrator compliance data is stale
                if not self._orchestrator_alive:
                    alloc_reject.labels(account_id="*", reason="orchestrator_heartbeat_dead").inc()
                    logger.warning(
                        "[AllocationWorker] Rejecting allocation msg_id={} — orchestrator heartbeat dead",
                        msg_id,
                    )
                    await redis_client.xack(stream_name, self._cfg.group, msg_id)
                    return

                request = self._build_request(msg)
                if request is None:
                    alloc_errors_total.inc()
                    await redis_client.xack(stream_name, self._cfg.group, msg_id)
                    return

                span.set_attribute("signal.id", request.signal_id)
                span.set_attribute("allocation.request_id", request.request_id)
                span.set_attribute("allocation.account_count", len(request.account_ids))

                try:
                    with alloc_latency.time():
                        result = await asyncio.to_thread(self._service.allocate, request)
                except Exception as exc:
                    alloc_errors_total.inc()
                    span.record_exception(exc)
                    logger.exception("Allocation worker failed request_id={} err={}", request.request_id, exc)
                    return

                for account_result in result.account_results:
                    if account_result.allowed:
                        alloc_success.labels(account_id=account_result.account_id).inc()
                    else:
                        reason = account_result.reason or "unknown"
                        alloc_reject.labels(account_id=account_result.account_id, reason=reason).inc()

                await redis_client.xack(stream_name, self._cfg.group, msg_id)

    def _build_request(self, msg: dict[str, str]) -> AllocationRequest | None:
        signal_id = str(msg.get("signal_id", "")).strip()
        if not signal_id:
            logger.error("Allocation worker dropped malformed message: missing signal_id")
            return None

        raw_accounts = msg.get("account_ids", "")
        account_ids = self._parse_accounts(raw_accounts)
        if not account_ids:
            logger.error("Allocation worker dropped malformed message: missing account_ids")
            return None

        raw_risk = msg.get("risk_percent", "1.0")
        try:
            risk_percent = float(raw_risk)
        except (TypeError, ValueError):
            risk_percent = 1.0

        return AllocationRequest(
            request_id=str(msg.get("request_id", uuid.uuid4().hex)),
            signal_id=signal_id,
            account_ids=account_ids,
            risk_percent=risk_percent,
        )

    @staticmethod
    def _parse_accounts(raw_accounts: str | Sequence[str]) -> list[str]:
        if isinstance(raw_accounts, list | tuple):
            return [str(a).strip() for a in raw_accounts if str(a).strip()]

        text = str(raw_accounts or "").strip()
        if not text:
            return []

        if text.startswith("["):
            with contextlib.suppress(Exception):
                parsed: list[Any] = json.loads(text)
                return [str(a).strip() for a in parsed if str(a).strip()]

        return [x.strip() for x in text.split(",") if x.strip()]

    async def _update_runtime_metrics(self, redis_client: aioredis.Redis) -> None:
        pending_count = 0
        try:
            pending: Any = await redis_client.xpending(self._cfg.stream, self._cfg.group)
            if isinstance(pending, dict):
                pending_count = int(str(cast(dict[str, Any], pending).get("pending", 0)))
            elif isinstance(pending, list | tuple) and pending:
                pending_count = int(str(cast(tuple[Any, ...], pending)[0]))
        except Exception:
            pending_count = 0

        redis_stream_lag.labels(stream=self._cfg.stream, group=self._cfg.group).set(pending_count)

        current_mem, _peak_mem = tracemalloc.get_traced_memory()
        process_memory.labels(service="allocation").set(float(current_mem))

    async def _check_orchestrator_health(self, redis_client: aioredis.Redis) -> None:
        """Validate orchestrator heartbeat and update internal flag + metrics."""
        from state.cross_service_validator import validate_peer_health  # noqa: PLC0415

        try:
            summary = await validate_peer_health(redis_client, ("orchestrator",))
            was_alive = self._orchestrator_alive
            self._orchestrator_alive = summary.all_alive
            if not summary.all_alive and was_alive:
                logger.warning(
                    "[AllocationWorker] Orchestrator heartbeat lost — compliance data may be stale | {}",
                    summary.stale_peers or summary.missing_peers,
                )
            elif summary.all_alive and not was_alive:
                logger.info("[AllocationWorker] Orchestrator heartbeat restored")
        except Exception:
            pass


_MAX_RESTARTS = int(os.getenv("ALLOC_MAX_RESTARTS", "10"))
_RESTART_COOLDOWN = float(os.getenv("ALLOC_RESTART_COOLDOWN_SEC", "5.0"))


async def _main() -> None:
    start_http_server(int(os.getenv("ALLOC_METRICS_PORT", "9102")))

    health_port = int(os.getenv("PORT", os.getenv("ALLOC_HEALTH_PORT", "8085")))
    probe = HealthProbe(port=health_port, service_name="allocation")
    asyncio.create_task(probe.start())
    logger.info("Allocation health probe started on :{}", health_port)

    restarts = 0
    try:
        while restarts <= _MAX_RESTARTS:
            try:
                logger.info(
                    "[SUPERVISOR] Starting allocation worker (attempt {}/{})",
                    restarts + 1,
                    _MAX_RESTARTS + 1,
                )
                worker = AsyncAllocationWorker()
                await worker.run()
                return  # clean exit
            except asyncio.CancelledError:
                logger.info("[SUPERVISOR] Allocation worker cancelled")
                return
            except Exception as exc:
                restarts += 1
                logger.error(
                    "[SUPERVISOR] Allocation worker crashed: {} (restart {}/{})",
                    exc,
                    restarts,
                    _MAX_RESTARTS,
                )
                if restarts > _MAX_RESTARTS:
                    logger.critical("[SUPERVISOR] Allocation worker exceeded max restarts — giving up")
                    return
                await asyncio.sleep(_RESTART_COOLDOWN)
    finally:
        await close_pool()
        await probe.stop()


if __name__ == "__main__":
    asyncio.run(_main())
