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
from dataclasses import dataclass

from loguru import logger
from prometheus_client import Counter, Gauge, Histogram, start_http_server
from redis.exceptions import ResponseError

from allocation.allocation_models import AllocationRequest
from allocation.allocation_service import AllocationService
from infrastructure.redis_client import get_client
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


class AsyncAllocationWorker:
    def __init__(self, config: WorkerConfig | None = None) -> None:
        self._cfg = config or WorkerConfig()
        self._service = AllocationService()
        self._sem = asyncio.Semaphore(self._cfg.max_concurrency)

    async def run(self) -> None:
        tracemalloc.start()
        start_http_server(self._cfg.metrics_port)
        logger.info(
            "Allocation worker started (worker=%s stream=%s metrics=%s)",
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
            with _alloc_tracer.start_as_current_span("allocation_process", context=parent_context) as span:
                alloc_requests_total.inc()
                span.set_attribute("redis.stream", stream_name)
                span.set_attribute("redis.message_id", msg_id)

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
                    logger.exception("Allocation worker failed request_id=%s err=%s", request.request_id, exc)
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
        if isinstance(raw_accounts, (list, tuple)):
            return [str(a).strip() for a in raw_accounts if str(a).strip()]

        text = str(raw_accounts or "").strip()
        if not text:
            return []

        if text.startswith("["):
            with contextlib.suppress(Exception):
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    return [str(a).strip() for a in parsed if str(a).strip()]

        return [x.strip() for x in text.split(",") if x.strip()]

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
        process_memory.labels(service="allocation").set(float(current_mem))


async def _main() -> None:
    worker = AsyncAllocationWorker()
    await worker.run()


if __name__ == "__main__":
    asyncio.run(_main())
