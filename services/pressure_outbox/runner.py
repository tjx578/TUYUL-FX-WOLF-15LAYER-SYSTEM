"""Railway entry point for the dedicated pressure outbox dispatcher."""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal

from loguru import logger

from core.health_probe import HealthProbe
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
from services.pressure_outbox.preflight import rollout_flags
from services.pressure_outbox.shadow_evidence_v2_worker import (
    ShadowEvidenceV2RuntimeConfig,
    build_shadow_evidence_v2_worker,
)
from startup.graceful_shutdown import GracefulShutdown
from startup.required_tasks import RequiredTaskSupervisor
from startup.task_supervisor import supervised_task
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
    shadow_evidence_v2_config = ShadowEvidenceV2RuntimeConfig.from_env()
    shadow_evidence_v2_worker = (
        build_shadow_evidence_v2_worker(pg=pg_client, config=shadow_evidence_v2_config)
        if shadow_evidence_v2_config.enabled
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
        if shadow_evidence_v2_worker is not None:
            await shadow_evidence_v2_worker.stop()

    shutdown_event = asyncio.Event()
    stop_tasks: list[asyncio.Task] = []

    def request_stop() -> None:
        shutdown_event.set()
        stop_tasks.append(asyncio.create_task(_stop_workers(), name="pressure-outbox-stop"))

    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError, RuntimeError):
            loop.add_signal_handler(signal_name, request_stop)
    tasks: list[asyncio.Task] = []
    primary_enabled = rollout_flags().master and rollout_flags().dispatch
    requirements = {
        "pressure-outbox": primary_enabled,
        "evidence_worker": evidence_worker is not None,
        "outcome_worker": outcome_worker is not None,
        "lifecycle_v2_worker": lifecycle_v2_worker is not None,
        "shadow_evidence_v2_worker": shadow_evidence_v2_worker is not None,
        "health-probe": True,
    }
    supervisor = RequiredTaskSupervisor(requirements)
    probe = HealthProbe(
        port=int(os.getenv("PORT", "8085")),
        service_name="pressure-outbox",
        readiness_check=lambda: bool(
            primary_enabled
            and supervisor.snapshot()["ready"]
            and worker.runtime_ready()
            and not shutdown_event.is_set()
        ),
    )
    probe.set_detail(
        "workers", ",".join(f"{name}:{'REQUIRED' if enabled else 'DISABLED'}" for name, enabled in requirements.items())
    )

    async def monitor():
        while not shutdown_event.is_set():
            supervisor.snapshot()
            if primary_enabled and getattr(worker, "_consecutive_poll_failures", 0):
                supervisor.fail("pressure-outbox", "poll_failed")
            if supervisor.fatal.is_set():
                await asyncio.sleep(1)
                raise RuntimeError("REQUIRED_PRESSURE_OUTBOX_TASK_FAILED")
            await asyncio.sleep(0.05)

    def start_worker(name, instance):
        tasks.append(
            supervisor.start(name, supervised_task(name, instance.run, shutdown_event, max_restarts=0, required=True))
        )

    try:
        tasks.append(supervisor.start("health-probe", probe.start()))
        if primary_enabled:
            start_worker("pressure-outbox", worker)
        if evidence_worker is not None:
            logger.info(
                "Starting Strategy 5S-CR evidence worker mode={} provider={} execution_enabled={}",
                evidence_config.mode,
                evidence_config.provider,
                evidence_config.execution_enabled,
            )
            start_worker("evidence_worker", evidence_worker)
        if outcome_worker is not None:
            logger.info(
                "Starting Strategy 5S-CR M1 outcome worker horizon_minutes={}",
                outcome_config.horizon_minutes,
            )
            start_worker("outcome_worker", outcome_worker)
        if lifecycle_v2_worker is not None:
            logger.info(
                "Starting Strategy 5S-CR lifecycle V2 shadow worker shadow_only={} dual_write={} continuity_gap={}s",
                lifecycle_v2_config.shadow_only,
                lifecycle_v2_config.dual_write_enabled,
                lifecycle_v2_config.max_continuity_gap_seconds,
            )
            start_worker("lifecycle_v2_worker", lifecycle_v2_worker)
        if shadow_evidence_v2_worker is not None:
            logger.info(
                "Starting Strategy 5S-CR Lifecycle V2 evidence owner shadow_only={}",
                shadow_evidence_v2_config.shadow_only,
            )
            start_worker("shadow_evidence_v2_worker", shadow_evidence_v2_worker)
        tasks.append(asyncio.create_task(monitor(), name="pressure-role-monitor"))
        stopper = asyncio.create_task(shutdown_event.wait(), name="pressure-stop-wait")
        tasks.append(stopper)
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        if not shutdown_event.is_set():
            supervisor.snapshot()
            # A completed required worker or probe must not hide behind other tasks.
            for task in done:
                task.result()
            raise RuntimeError("REQUIRED_PRESSURE_OUTBOX_TASK_RETURNED")
    finally:
        shutdown_event.set()
        supervisor.stopping = True
        shutdown = GracefulShutdown(drain_timeout=float(os.getenv("SHUTDOWN_DRAIN_SEC", "15")))
        shutdown.register_cleanup("pressure outbox health probe", probe.stop)
        shutdown.register_cleanup("pressure outbox PostgreSQL pool", pg_client.close)
        await shutdown.shutdown([*tasks, *stop_tasks])
        # Failure racing a signal must retain its nonzero result after draining.
        for task in tasks:
            if task.done() and not task.cancelled() and task.exception() is not None:
                task.result()


def run() -> None:
    logger.info("Starting Strategy 5S-CR durable pressure outbox worker")
    asyncio.run(_main())


if __name__ == "__main__":
    run()
