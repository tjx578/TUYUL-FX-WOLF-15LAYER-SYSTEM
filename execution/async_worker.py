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
from dataclasses import dataclass

from loguru import logger
from prometheus_client import Counter, Gauge, Histogram, start_http_server
from redis.exceptions import ResponseError
from config.logging_bootstrap import configure_loguru_logging

from execution.broker_executor import BrokerExecutor, ExecutionRequest, OrderAction
from infrastructure.redis_client import get_client
from infrastructure.tracing import (
    extract_trace_carrier,
    extract_trace_context,
    instrument_asyncio,
    instrument_redis,
    setup_tracer,
)

EXECUTION_STREAM = "execution:queue"
EXEC_GROUP = "exec-group"

configure_loguru_logging()

execution_latency = Histogram(
    "wolf_execution_latency_seconds",
    "Order send latency",
)
orders_sent = Counter("wolf_orders_total", "Orders sent")
orders_failed = Counter("wolf_orders_failed_total", "Orders failed")
execution_errors_total = Counter(
    "wolf_execution_errors_total",
    "Execution worker errors",
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


class AsyncExecutionWorker:
    def __init__(self, config: WorkerConfig | None = None) -> None:
        self._cfg = config or WorkerConfig()
        self._sem = asyncio.Semaphore(self._cfg.max_concurrency)
        self._executor = BrokerExecutor(
            ea_url=os.getenv("EA_BRIDGE_URL", "http://localhost:8081"),
        )

    async def run(self) -> None:
        tracemalloc.start()
        start_http_server(self._cfg.metrics_port)
        logger.info(
            "Execution worker started (worker=%s stream=%s metrics=%s)",
            self._cfg.worker_name,
            self._cfg.stream,
            self._cfg.metrics_port,
        )

        redis_client = await get_client()
        await self._ensure_group(redis_client)

        while True:
            response = await redis_client.xreadgroup(
                groupname=self._cfg.group,
                consumername=self._cfg.worker_name,
                streams={self._cfg.stream: ">"},
                count=self._cfg.count,
                block=self._cfg.block_ms,
            )
            await self._update_runtime_metrics(redis_client)

            if not response:
                continue

            tasks: list[asyncio.Task[None]] = []
            for stream_name, messages in response:
                for msg_id, msg in messages:
                    tasks.append(
                        asyncio.create_task(
                            self._handle_message(redis_client, stream_name, msg_id, msg),
                        ),
                    )
            if tasks:
                await asyncio.gather(*tasks)

    async def _ensure_group(self, redis_client) -> None:
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

    async def _handle_message(self, redis_client, stream_name: str, msg_id: str, msg: dict[str, str]) -> None:
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
                    logger.error("Execution worker dropped malformed message id=%s err=%s", msg_id, exc)
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
                        "Execution failed request_id=%s code=%s err=%s",
                        request.request_id,
                        result.error_code,
                        result.error_msg,
                    )

    @staticmethod
    def _build_execution_request(msg: dict[str, str]) -> ExecutionRequest:
        try:
            return ExecutionRequest(
                action=OrderAction.PLACE,
                account_id=str(msg["account_id"]),
                symbol=str(msg["symbol"]),
                lot_size=float(msg.get("lot_size", "0")),
                order_type=str(msg.get("order_type", "BUY_LIMIT")),
                entry_price=float(msg.get("entry_price", "0")),
                stop_loss=float(msg.get("stop_loss", "0")),
                take_profit=float(msg.get("take_profit_1", msg.get("take_profit", "0"))),
                request_id=str(msg.get("request_id", uuid.uuid4().hex)),
                meta={
                    "signal_id": str(msg.get("signal_id", "")),
                    "execution_mode": str(msg.get("execution_mode", "TP1_ONLY")),
                },
            )
        except KeyError as exc:
            raise ValueError(f"missing field: {exc.args[0]}") from exc

    async def _update_runtime_metrics(self, redis_client) -> None:
        pending_count = 0
        try:
            pending = await redis_client.xpending(self._cfg.stream, self._cfg.group)
            if isinstance(pending, dict):
                pending_count = int(pending.get("pending", 0))
            elif isinstance(pending, tuple) and pending:
                pending_count = int(pending[0])
        except Exception:
            pending_count = 0

        redis_stream_lag.labels(stream=self._cfg.stream, group=self._cfg.group).set(pending_count)

        current_mem, _peak_mem = tracemalloc.get_traced_memory()
        process_memory.labels(service="execution").set(float(current_mem))


async def _main() -> None:
    worker = AsyncExecutionWorker()
    await worker.run()


if __name__ == "__main__":
    asyncio.run(_main())
