"""Heartbeat state classification for cross-service health detection.

Reads heartbeat keys from Redis and classifies them into one of three states:
    ALIVE   — heartbeat was written within the max-age threshold.
    STALE   — heartbeat key exists but the timestamp is older than threshold.
    MISSING — no heartbeat key found in Redis (producer never started or crashed).

For the ingest service, two independent heartbeat keys exist:
    * ``ingest:process``  — always written while the ingest process is alive.
    * ``ingest:provider`` — only written when the WS provider is connected.

This allows correct classification during weekends / market-closed periods
(process ALIVE + provider STALE → DEGRADED, not NO_PRODUCER).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import orjson
from loguru import logger

from state.redis_keys import (
    HEARTBEAT_ENGINE,
    HEARTBEAT_INGEST,
    HEARTBEAT_INGEST_PROCESS,
    HEARTBEAT_INGEST_PROVIDER,
)

__all__ = [
    "HeartbeatState",
    "HeartbeatStatus",
    "IngestHealthState",
    "IngestHealthStatus",
    "classify_heartbeat",
    "classify_ingest_health",
    "read_heartbeat",
    "read_all_heartbeats",
    "read_ingest_health",
]

# ── Configurable thresholds ───────────────────────────────────────────────────
_INGEST_MAX_AGE_SEC = float(os.getenv("HEARTBEAT_INGEST_MAX_AGE_SEC", "30"))
_ENGINE_MAX_AGE_SEC = float(os.getenv("HEARTBEAT_ENGINE_MAX_AGE_SEC", "60"))
_INGEST_PROCESS_MAX_AGE_SEC = float(os.getenv("HEARTBEAT_INGEST_PROCESS_MAX_AGE_SEC", "30"))
_INGEST_PROVIDER_MAX_AGE_SEC = float(os.getenv("HEARTBEAT_INGEST_PROVIDER_MAX_AGE_SEC", "30"))

# Map service name → (redis_key, max_age)
SERVICE_HEARTBEAT_CONFIG: dict[str, tuple[str, float]] = {
    "ingest": (HEARTBEAT_INGEST, _INGEST_MAX_AGE_SEC),
    "ingest_process": (HEARTBEAT_INGEST_PROCESS, _INGEST_PROCESS_MAX_AGE_SEC),
    "ingest_provider": (HEARTBEAT_INGEST_PROVIDER, _INGEST_PROVIDER_MAX_AGE_SEC),
    "engine": (HEARTBEAT_ENGINE, _ENGINE_MAX_AGE_SEC),
}


class HeartbeatState(StrEnum):
    """Classification of a producer heartbeat."""

    ALIVE = "ALIVE"
    STALE = "STALE"
    MISSING = "MISSING"


@dataclass(frozen=True, slots=True)
class HeartbeatStatus:
    """Immutable snapshot of a single heartbeat classification."""

    service: str
    state: HeartbeatState
    age_seconds: float | None
    producer: str | None
    last_ts: float | None


def classify_heartbeat(
    payload_raw: str | bytes | None,
    max_age_sec: float,
    *,
    service: str = "unknown",
    now_ts: float | None = None,
) -> HeartbeatStatus:
    """Classify a heartbeat from its raw Redis value.

    Args:
        payload_raw: Raw JSON bytes/string from Redis GET, or None if key missing.
        max_age_sec: Maximum acceptable age in seconds before STALE.
        service: Human-readable service name for the status record.
        now_ts: Override wall-clock for testing. Defaults to ``time.time()``.

    Returns:
        HeartbeatStatus with classification.
    """
    if now_ts is None:
        now_ts = time.time()

    if payload_raw is None:
        return HeartbeatStatus(
            service=service,
            state=HeartbeatState.MISSING,
            age_seconds=None,
            producer=None,
            last_ts=None,
        )

    try:
        data: dict[str, Any] = orjson.loads(payload_raw)
    except (orjson.JSONDecodeError, TypeError, ValueError):
        logger.warning("[HeartbeatClassifier] Malformed payload for {}: {!r}", service, payload_raw)
        return HeartbeatStatus(
            service=service,
            state=HeartbeatState.MISSING,
            age_seconds=None,
            producer=None,
            last_ts=None,
        )

    ts_raw = data.get("ts")
    if ts_raw is None:
        return HeartbeatStatus(
            service=service,
            state=HeartbeatState.MISSING,
            age_seconds=None,
            producer=data.get("producer"),
            last_ts=None,
        )

    try:
        ts = float(ts_raw)
    except (TypeError, ValueError):
        return HeartbeatStatus(
            service=service,
            state=HeartbeatState.MISSING,
            age_seconds=None,
            producer=data.get("producer"),
            last_ts=None,
        )

    age = max(0.0, now_ts - ts)
    state = HeartbeatState.ALIVE if age <= max_age_sec else HeartbeatState.STALE

    return HeartbeatStatus(
        service=service,
        state=state,
        age_seconds=round(age, 2),
        producer=data.get("producer"),
        last_ts=ts,
    )


async def read_heartbeat(
    redis: Any,
    key: str,
    max_age_sec: float,
    *,
    service: str = "unknown",
) -> HeartbeatStatus:
    """Read a heartbeat key from Redis and classify it.

    Args:
        redis: Async Redis client (must support ``await redis.get(key)``).
        key: Redis key name.
        max_age_sec: Maximum acceptable age in seconds.
        service: Human-readable service name.

    Returns:
        HeartbeatStatus with classification.
    """
    try:
        raw = await redis.get(key)
    except Exception as exc:
        logger.debug("[HeartbeatClassifier] Redis read failed for {}: {}", service, exc)
        return HeartbeatStatus(
            service=service,
            state=HeartbeatState.MISSING,
            age_seconds=None,
            producer=None,
            last_ts=None,
        )

    return classify_heartbeat(raw, max_age_sec, service=service)


async def read_all_heartbeats(redis: Any) -> dict[str, HeartbeatStatus]:
    """Read and classify all known service heartbeats.

    Returns:
        Dict mapping service name → HeartbeatStatus.
    """
    results: dict[str, HeartbeatStatus] = {}
    for svc_name, (key, max_age) in SERVICE_HEARTBEAT_CONFIG.items():
        results[svc_name] = await read_heartbeat(redis, key, max_age, service=svc_name)
    return results


# ══════════════════════════════════════════════════════════
#  Split ingest health: process vs provider
# ══════════════════════════════════════════════════════════


class IngestHealthState(StrEnum):
    """Tri-state classification of the ingest service."""

    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    NO_PRODUCER = "NO_PRODUCER"


@dataclass(frozen=True, slots=True)
class IngestHealthStatus:
    """Composite ingest health from process + provider heartbeats."""

    state: IngestHealthState
    process: HeartbeatStatus
    provider: HeartbeatStatus


def classify_ingest_health(
    process_status: HeartbeatStatus,
    provider_status: HeartbeatStatus,
) -> IngestHealthStatus:
    """Derive ingest health from two independent heartbeat signals.

    | process  | provider | → state       |
    |----------|----------|---------------|
    | ALIVE    | ALIVE    | HEALTHY       |
    | ALIVE    | STALE    | DEGRADED      |
    | ALIVE    | MISSING  | DEGRADED      |
    | STALE    | *        | NO_PRODUCER   |
    | MISSING  | *        | NO_PRODUCER   |
    """
    if process_status.state == HeartbeatState.ALIVE:
        if provider_status.state == HeartbeatState.ALIVE:
            state = IngestHealthState.HEALTHY
        else:
            state = IngestHealthState.DEGRADED
    else:
        state = IngestHealthState.NO_PRODUCER

    return IngestHealthStatus(state=state, process=process_status, provider=provider_status)


async def read_ingest_health(redis: Any) -> IngestHealthStatus:
    """Read both ingest heartbeat keys and classify composite health."""
    process = await read_heartbeat(
        redis, HEARTBEAT_INGEST_PROCESS, _INGEST_PROCESS_MAX_AGE_SEC, service="ingest_process"
    )
    provider = await read_heartbeat(
        redis, HEARTBEAT_INGEST_PROVIDER, _INGEST_PROVIDER_MAX_AGE_SEC, service="ingest_provider"
    )
    return classify_ingest_health(process, provider)
