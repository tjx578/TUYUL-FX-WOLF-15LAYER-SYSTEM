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
import sys
import types

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

from loguru import logger

from context.system_state import SystemStateManager
from core.health_probe import HealthProbe
from ingest.service_metrics import ingest_readiness
from ingest.service_runner import run_ingest_services
from storage.startup import init_persistent_storage, shutdown_persistent_storage

_shutdown_event: asyncio.Event | None = None


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

    logger.remove()

    logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan> - "
        "<level>{message}</level>",
        level="INFO",
        filter=lambda record: record["level"].no < 40,
    )

    logger.add(
        sys.stderr,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>"
        ),
        level="ERROR",
    )

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
                await run_ingest_services(has_api_key, shutdown_event=_shutdown_event)
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
