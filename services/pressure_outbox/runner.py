"""Railway entry point for the dedicated pressure outbox dispatcher."""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal

from loguru import logger

from storage.postgres_client import pg_client
from storage.pressure_outbox import PressureOutboxRepository
from storage.pressure_outbox_worker import PressureOutboxWorker
from storage.strategy_5scr_pressure_inbox import Strategy5SCRInboxConsumer


async def _main() -> None:
    await pg_client.initialize()
    if not pg_client.is_available:
        raise RuntimeError("DATABASE_URL is required for the pressure outbox worker")

    repository = PressureOutboxRepository(pg=pg_client)
    consumer = Strategy5SCRInboxConsumer(pg=pg_client)
    worker = PressureOutboxWorker(
        worker_id=os.getenv("PRESSURE_OUTBOX_WORKER_ID") or os.getenv("RAILWAY_REPLICA_ID") or "pressure-worker-1",
        repository=repository,
        consumer=consumer,
        poll_interval_seconds=float(os.getenv("PRESSURE_OUTBOX_POLL_SECONDS", "1")),
        batch_size=int(os.getenv("PRESSURE_OUTBOX_BATCH_SIZE", "100")),
        lease_seconds=float(os.getenv("PRESSURE_OUTBOX_LEASE_SECONDS", "30")),
        max_attempts=int(os.getenv("PRESSURE_OUTBOX_MAX_ATTEMPTS", "8")),
    )
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError, RuntimeError):
            loop.add_signal_handler(signal_name, lambda: asyncio.create_task(worker.stop()))
    try:
        await worker.run()
    finally:
        await pg_client.close()


def run() -> None:
    logger.info("Starting Strategy 5S-CR durable pressure outbox worker")
    asyncio.run(_main())


if __name__ == "__main__":
    run()
