"""
Async Execution Worker (Redis Streams + consumer group).

Authority boundaries:
- Executes only prepared execution plans.
- Does NOT compute direction and does NOT alter Layer-12 verdict.
"""

from __future__ import annotations

import asyncio
import os
import tracemalloc
import uuid
from dataclasses import dataclass, replace
from typing import Any, cast

import redis.asyncio as aioredis
from loguru import logger
from prometheus_client import REGISTRY, Counter, Gauge, Histogram, start_http_server
from redis.exceptions import ResponseError


def _get_or_create_metric(metric_cls: type, name: str, *args: Any, **kwargs: Any) -> Any:
    """Return existing metric or create new one (handles duplicate registration)."""
    try:
        return metric_cls(name, *args, **kwargs)
    except ValueError:
        # Already registered — return the existing collector
        return REGISTRY._names_to_collectors.get(name)


from config.logging_bootstrap import configure_loguru_logging  # noqa: E402
from contracts.execution_queue_contract import ExecutionQueuePayload  # noqa: E402
from core.health_probe import HealthProbe  # noqa: E402
from execution.broker_executor import BrokerExecutor, ExecutionRequest, OrderAction  # noqa: E402
from infrastructure.redis_client import RedisConfig, close_pool, get_client  # noqa: E402
from infrastructure.tracing import (  # noqa: E402
    extract_trace_carrier,
    extract_trace_context,
    instrument_asyncio,
    instrument_redis,
    setup_tracer,
)

EXECUTION_STREAM = "execution:queue"
EXEC_GROUP = "exec-group"

configure_loguru_logging()

execution_latency = _get_or_create_metric(Histogram, "wolf_execution_latency_seconds", "Order send latency")
orders_sent = _get_or_create_metric(Counter, "wolf_orders_total", "Orders sent")
orders_failed = _get_or_create_metric(Counter, "wolf_orders_failed_total", "Orders failed")
execution_errors_total = _get_or_create_metric(Counter, "wolf_execution_errors_total", "Execution worker errors")
redis_stream_lag = _get_or_create_metric(
    Gauge,
    "wolf_redis_stream_lag",
    "Pending Redis stream messages per consumer group",
    ["stream", "group"],
)
process_memory = _get_or_create_metric(
    Gauge,
    "wolf_process_memory_bytes",
    "Python memory tracked by tracemalloc",
    ["service"],
)

_exec_tracer = setup_tracer("wolf-execution")
instrument_asyncio()
instrument_redis()


@dataclass(frozen=True)
class WorkerConfig:
    stream: str = EXECUTION_STREAM
    group: str = EXEC_GROUP
    worker_name: str = f"exec-{uuid.uuid4().hex[:8]}"
    block_ms: int = 5000
    count: int = 20
    max_concurrency: int = 5
    metrics_port: int = int(os.getenv("EXEC_METRICS_PORT", "9103"))

    @property
    def redis_socket_timeout(self) -> float:
        # Keep socket timeout comfortably above XREADGROUP block window.
        # block_ms=5000 with socket_timeout=5.0 can produce spurious TimeoutError.
        return max((self.block_ms / 1000.0) + 2.0, 10.0)


class AsyncExecutionWorker:
    def __init__(self, config: WorkerConfig | None = None) -> None:
        super().__init__()
        self._cfg = config or WorkerConfig()
        self._sem = asyncio.Semaphore(self._cfg.max_concurrency)
        self._executor = BrokerExecutor(
            ea_url=os.getenv("EA_BRIDGE_URL", "http://localhost:8081"),
        )
        self._in_flight: list[asyncio.Task[None]] = []

    async def run(self) -> None:
        tracemalloc.start()
        logger.info(
            "Execution worker started (worker={} stream={} metrics={})",
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
                        execution_errors_total.inc()
                        logger.warning(
                            "xreadgroup connection error: {} — reconnecting",
                            type(exc).__name__,
                        )
                        await close_pool()
                        break  # Break inner loop → reconnect in outer loop

                    await self._update_runtime_metrics(redis_client)

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
                logger.info("Execution worker cancelled — draining in-flight tasks")
                await self._drain_in_flight()
                raise
            except Exception as exc:
                execution_errors_total.inc()
                logger.exception(
                    "Execution worker error: {} — retry in {:.1f}s",
                    exc,
                    backoff,
                )

            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)

    async def _drain_in_flight(self) -> None:
        """Wait for in-flight execution tasks to complete before shutdown."""
        from startup.graceful_shutdown import GracefulShutdown  # noqa: PLC0415

        gs = GracefulShutdown(
            drain_timeout=float(os.getenv("SHUTDOWN_DRAIN_SEC", "15")),
        )
        await gs.drain_worker_tasks(self._in_flight, label="execution")

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

    async def _handle_message(
        self, redis_client: aioredis.Redis, stream_name: str, msg_id: str, msg: dict[str, str]
    ) -> None:
        async with self._sem:
            parent_context = extract_trace_context(extract_trace_carrier(msg))
            with _exec_tracer.start_as_current_span("execution_send", context=parent_context) as span:
                span.set_attribute("redis.stream", stream_name)
                span.set_attribute("redis.message_id", msg_id)
                span.set_attribute("signal.id", str(msg.get("signal_id", "")))

                try:
                    request = self._build_execution_request(msg)
                except ValueError as exc:
                    execution_errors_total.inc()
                    span.record_exception(exc)
                    logger.error("Execution worker dropped malformed message id={} err={}", msg_id, exc)
                    await redis_client.xack(stream_name, self._cfg.group, msg_id)
                    return

                span.set_attribute("execution.request_id", request.request_id)
                span.set_attribute("account.id", request.account_id)
                span.set_attribute("symbol", request.symbol)

                with execution_latency.time():
                    result = await asyncio.to_thread(self._executor.execute, request)

                orders_sent.inc()
                if result.success:
                    await redis_client.xack(stream_name, self._cfg.group, msg_id)
                else:
                    orders_failed.inc()
                    logger.error(
                        "Execution failed request_id={} code={} err={}",
                        request.request_id,
                        result.error_code,
                        result.error_msg,
                    )

    @staticmethod
    def _build_execution_request(msg: dict[str, str]) -> ExecutionRequest:
        try:
            # Validate incoming stream fields through Pydantic contract
            payload = ExecutionQueuePayload(
                request_id=msg.get("request_id", uuid.uuid4().hex),
                signal_id=msg.get("signal_id", "N/A"),
                account_id=msg["account_id"],
                symbol=msg["symbol"],
                verdict=msg.get("verdict", "EXECUTE"),
                direction=msg.get("direction", "BUY"),
                entry_price=float(msg.get("entry_price", "0")),
                stop_loss=float(msg.get("stop_loss", "0")),
                take_profit_1=float(msg.get("take_profit_1", msg.get("take_profit", "0"))),
                lot_size=float(msg.get("lot_size", "0")),
                order_type=msg.get("order_type", "PENDING_ONLY"),
                execution_mode=msg.get("execution_mode", "TP1_ONLY"),
                operator=msg.get("operator", "system"),
            )
        except (KeyError, ValueError) as exc:
            raise ValueError(f"contract validation failed: {exc}") from exc

        return ExecutionRequest(
            action=OrderAction.PLACE,
            account_id=payload.account_id,
            symbol=payload.symbol,
            lot_size=payload.lot_size,
            order_type=payload.order_type,
            entry_price=payload.entry_price,
            stop_loss=payload.stop_loss,
            take_profit=payload.take_profit_1,
            request_id=payload.request_id,
            meta={
                "signal_id": payload.signal_id,
                "execution_mode": payload.execution_mode,
            },
        )

    async def _update_runtime_metrics(self, redis_client: aioredis.Redis) -> None:
        pending_count = 0
        try:
            pending_raw = await redis_client.xpending(self._cfg.stream, self._cfg.group)
            if isinstance(pending_raw, dict):
                raw_dict = cast(dict[str, object], pending_raw)
                pending_value = raw_dict.get("pending", 0)
                pending_count = int(pending_value) if pending_value is not None else 0  # type: ignore[arg-type]
            elif isinstance(pending_raw, list | tuple) and pending_raw:
                pending_count = int(str(cast(tuple[Any, ...], pending_raw)[0]))
        except Exception:
            pending_count = 0

        redis_stream_lag.labels(stream=self._cfg.stream, group=self._cfg.group).set(pending_count)

        current_mem, _peak_mem = tracemalloc.get_traced_memory()
        process_memory.labels(service="execution").set(float(current_mem))


_MAX_RESTARTS = int(os.getenv("EXEC_MAX_RESTARTS", "10"))
_RESTART_COOLDOWN = float(os.getenv("EXEC_RESTART_COOLDOWN_SEC", "5.0"))


async def _main() -> None:
    start_http_server(int(os.getenv("EXEC_METRICS_PORT", "9103")))

    health_port = int(os.getenv("PORT", os.getenv("EXEC_HEALTH_PORT", "8084")))
    probe = HealthProbe(port=health_port, service_name="execution")
    asyncio.create_task(probe.start())
    logger.info("Execution health probe started on :{}", health_port)

    restarts = 0
    try:
        while restarts <= _MAX_RESTARTS:
            try:
                logger.info(
                    "[SUPERVISOR] Starting execution worker (attempt {}/{})",
                    restarts + 1,
                    _MAX_RESTARTS + 1,
                )
                worker = AsyncExecutionWorker()
                await worker.run()
                return  # clean exit
            except asyncio.CancelledError:
                logger.info("[SUPERVISOR] Execution worker cancelled")
                return
            except Exception as exc:
                restarts += 1
                logger.error(
                    "[SUPERVISOR] Execution worker crashed: {} (restart {}/{})",
                    exc,
                    restarts,
                    _MAX_RESTARTS,
                )
                if restarts > _MAX_RESTARTS:
                    logger.critical("[SUPERVISOR] Execution worker exceeded max restarts — giving up")
                    return
                await asyncio.sleep(_RESTART_COOLDOWN)
    finally:
        await close_pool()
        await probe.stop()


if __name__ == "__main__":
    asyncio.run(_main())
