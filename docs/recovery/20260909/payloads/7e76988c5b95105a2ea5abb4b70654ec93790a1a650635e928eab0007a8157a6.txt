"""Startup helpers for persistent PostgreSQL backup services."""

from __future__ import annotations

import asyncio
import contextlib
from typing import cast

from loguru import logger

from core.redis_keys import CANDLE_HISTORY_SCAN, PEAK_EQUITY
from storage.persistence_sync import PersistenceSync
from storage.postgres_client import pg_client
from storage.redis_client import RedisClient

_sync_service: PersistenceSync | None = None
_sync_task: asyncio.Task[None] | None = None


def _has_candle_data(redis: RedisClient) -> bool:
    """Return True if Redis holds any candle history keys.

    Uses ``SCAN`` to avoid blocking the server.  A single key is sufficient
    to conclude that candle data survived the restart.
    Returns False on Redis errors so callers can fall back to PostgreSQL recovery.
    """
    try:
        cursor: int = 0
        while True:
            cursor, keys = cast(
                tuple[int, list[str]],
                redis.client.scan(cursor, match=CANDLE_HISTORY_SCAN, count=20),
            )
            if keys:
                return True
            if cursor == 0:
                break
    except Exception as exc:
        logger.warning("Failed to scan Redis for candle data — assuming empty: {}", exc)
        return False
    return False


async def init_persistent_storage() -> PersistenceSync | None:
    """Initialize PostgreSQL and start sync service if configured."""
    global _sync_service, _sync_task

    try:
        await pg_client.initialize()
    except Exception as exc:
        logger.warning(f"PostgreSQL init failed; continuing without durable backup: {exc}")
        return None

    if not pg_client.is_available:
        return None

    # Bind the synchronous analysis thread to the asyncpg owner loop.  The
    # feature remains inert unless both the master and granular write flags are true.
    from storage.observer_export_outbox import ObserverExportOutboxRepository  # noqa: PLC0415
    from storage.pair_admission_evaluations import (  # noqa: PLC0415
        PairAdmissionEvaluationRepository,
        configure_pair_admission_evaluation_runtime,
        hold_pair_admission_evaluation_runtime,
    )
    from storage.pressure_outbox import configure_pressure_outbox_runtime  # noqa: PLC0415
    from storage.pressure_radar_manifest import (  # noqa: PLC0415
        PressureRadarManifestRepository,
        configure_pressure_radar_runtime,
        hold_pressure_radar_runtime,
    )

    loop = asyncio.get_running_loop()
    observer_export = ObserverExportOutboxRepository(pg=pg_client)
    pair_admission = PairAdmissionEvaluationRepository(
        pg=pg_client,
        observer_export_repository=observer_export,
    )
    pressure_radar = PressureRadarManifestRepository(
        pg=pg_client,
        observer_export_repository=observer_export,
    )
    try:
        pair_status, radar_status, observer_status = await asyncio.gather(
            pair_admission.schema_status(),
            pressure_radar.schema_status(),
            observer_export.schema_status(),
        )
    except Exception as exc:  # noqa: BLE001
        hold_pair_admission_evaluation_runtime("PAIR_ADMISSION_SCHEMA_PREFLIGHT_FAILED")
        hold_pressure_radar_runtime("PRESSURE_RADAR_SCHEMA_PREFLIGHT_FAILED")
        logger.warning("Observer-backed persistence HOLD: schema preflight failed: {}", exc)
    else:
        if pair_status.ready and observer_status.ready:
            configure_pair_admission_evaluation_runtime(loop=loop, repository=pair_admission)
            logger.info("PairAdmission persistence preflight READY")
        else:
            hold_pair_admission_evaluation_runtime("PAIR_ADMISSION_REQUIRED_SCHEMA_NOT_READY")
            logger.warning(
                "PairAdmission persistence HOLD: required schema not ready "
                "pair_admission_ready={} observer_export_ready={} "
                "pair_missing_tables={} observer_missing_tables={} "
                "observer_missing_indexes={} observer_missing_triggers={}",
                pair_status.ready,
                observer_status.ready,
                pair_status.missing_tables,
                observer_status.missing_tables,
                observer_status.missing_indexes,
                observer_status.missing_triggers,
            )
        if radar_status.ready and observer_status.ready:
            configure_pressure_radar_runtime(loop=loop, repository=pressure_radar)
            logger.info("Pressure radar persistence preflight READY")
        else:
            hold_pressure_radar_runtime("PRESSURE_RADAR_REQUIRED_SCHEMA_NOT_READY")
            logger.warning(
                "Pressure radar persistence HOLD: required schema not ready "
                "pressure_radar_ready={} observer_export_ready={} "
                "radar_missing_tables={} observer_missing_tables={}",
                radar_status.ready,
                observer_status.ready,
                radar_status.missing_tables,
                observer_status.missing_tables,
            )
    configure_pressure_outbox_runtime(loop=asyncio.get_running_loop())

    redis = RedisClient()
    try:
        has_candles = _has_candle_data(redis)
        has_risk_data = bool(redis.get(PEAK_EQUITY))

        if not has_candles and not has_risk_data:
            logger.warning("Redis truly empty (no candle history, no risk state); attempting recovery from PostgreSQL")
            recovery_service = PersistenceSync(pg=pg_client, redis=redis)
            await recovery_service.hydrate_redis_from_postgres(mode="full")
        elif not has_risk_data:
            logger.info("Redis has candle data but missing peak_equity — risk state only recovery from PostgreSQL")
            recovery_service = PersistenceSync(pg=pg_client, redis=redis)
            await recovery_service.hydrate_redis_from_postgres(mode="risk_only")
        else:
            logger.info("Redis has existing data — skipping PostgreSQL recovery")
    except Exception as exc:
        logger.warning(f"Redis unavailable during PG sync init; skipping recovery: {exc}")

    try:
        _sync_service = PersistenceSync(interval_sec=30.0, pg=pg_client, redis=redis)
        _sync_task = asyncio.create_task(_sync_service.run())
        logger.info("Persistent storage initialized")
    except Exception as exc:
        logger.warning(f"Persistence sync startup failed: {exc}")
        return None

    # Start OHLC candle persistence flush loop
    try:
        from storage.candle_persistence import start_candle_persistence

        await start_candle_persistence()
    except Exception as exc:
        logger.warning(f"Candle persistence startup failed: {exc}")

    return _sync_service


async def shutdown_persistent_storage() -> None:
    """Stop sync service and close PostgreSQL pool."""
    global _sync_service, _sync_task

    if _sync_service is not None:
        await _sync_service.stop()
        _sync_service = None

    if _sync_task is not None:
        _sync_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _sync_task
        _sync_task = None

    # Stop OHLC candle persistence
    try:
        from storage.candle_persistence import stop_candle_persistence

        await stop_candle_persistence()
    except Exception:
        pass

    from storage.pair_admission_evaluations import pair_admission_evaluation_runtime  # noqa: PLC0415
    from storage.pressure_outbox import pressure_outbox_runtime  # noqa: PLC0415
    from storage.pressure_radar_manifest import pressure_radar_runtime  # noqa: PLC0415

    pair_admission_evaluation_runtime.clear()
    pressure_outbox_runtime.clear()
    pressure_radar_runtime.clear()
    await pg_client.close()


def get_sync_service() -> PersistenceSync | None:
    """Return active sync service instance."""
    return _sync_service
