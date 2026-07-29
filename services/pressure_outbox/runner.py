"""Railway entry point for the dedicated pressure outbox dispatcher."""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal

from loguru import logger

from services.pressure_outbox.evidence_worker import (
    EvidenceRuntimeConfig,
    build_evidence_worker,
)
from services.pressure_outbox.lifecycle_shadow_worker import (
    LifecycleV2RuntimeConfig,
    build_lifecycle_v2_shadow_runner,
)
from services.pressure_outbox.outcome_worker import (
    OutcomeRuntimeConfig,
    build_outcome_worker,
)
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
    evidence_config = EvidenceRuntimeConfig.from_env()
    evidence_worker = build_evidence_worker(pg=pg_client, config=evidence_config) if evidence_config.enabled else None
    outcome_config = OutcomeRuntimeConfig.from_env()
    outcome_worker = build_outcome_worker(pg=pg_client, config=outcome_config) if outcome_config.enabled else None
    # Shadow episode-lifecycle observer.  A peer worker: it reads delivered
    # events and writes only its own V2 tables, so the existing path above is
    # byte-identical whether this is on or off.
    lifecycle_v2_config = LifecycleV2RuntimeConfig.from_env()
    lifecycle_v2_worker = (
        build_lifecycle_v2_shadow_runner(pg=pg_client, config=lifecycle_v2_config)
        if lifecycle_v2_config.enabled
        else None
    )

    async def _stop_workers() -> None:
        await worker.stop()
        if evidence_worker is not None:
            await evidence_worker.stop()
        if outcome_worker is not None:
            await outcome_worker.stop()
        if lifecycle_v2_worker is not None:
            await lifecycle_v2_worker.stop()

    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError, RuntimeError):
            loop.add_signal_handler(signal_name, lambda: asyncio.create_task(_stop_workers()))
    try:
        tasks = [worker.run()]
        if evidence_worker is not None:
            logger.info(
                "Starting Strategy 5S-CR evidence worker mode={} provider={} execution_enabled={}",
                evidence_config.mode,
                evidence_config.provider,
                evidence_config.execution_enabled,
            )
            tasks.append(evidence_worker.run())
        if outcome_worker is not None:
            logger.info(
                "Starting Strategy 5S-CR M1 outcome worker horizon_minutes={}",
                outcome_config.horizon_minutes,
            )
            tasks.append(outcome_worker.run())
        if lifecycle_v2_worker is not None:
            logger.info(
                "Starting Strategy 5S-CR lifecycle V2 shadow worker "
                "shadow_only={} dual_write={} continuity_gap={}s",
                lifecycle_v2_config.shadow_only,
                lifecycle_v2_config.dual_write_enabled,
                lifecycle_v2_config.max_continuity_gap_seconds,
            )
            tasks.append(lifecycle_v2_worker.run())
        await asyncio.gather(*tasks)
    finally:
        await pg_client.close()


def run() -> None:
    logger.info("Starting Strategy 5S-CR durable pressure outbox worker")
    asyncio.run(_main())


if __name__ == "__main__":
    run()
