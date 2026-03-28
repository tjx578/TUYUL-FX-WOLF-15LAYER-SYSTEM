"""Cross-service heartbeat validation.

Provides a unified way for any service to validate that its upstream
dependencies are alive by reading their Redis heartbeat keys.

Zone: state/ — read-only health check, no execution side-effects.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from loguru import logger

from state.heartbeat_classifier import (
    SERVICE_HEARTBEAT_CONFIG,
    HeartbeatState,
    HeartbeatStatus,
    read_heartbeat,
)

__all__ = [
    "PeerHealth",
    "PeerHealthSummary",
    "validate_peer_health",
    "validate_peer_health_sync",
    "check_orchestrator_freshness",
]

# Orchestrator state staleness: beyond this, consider orchestrator dead.
_ORCHESTRATOR_STATE_MAX_AGE_SEC = float(
    os.getenv("ORCHESTRATOR_STATE_MAX_AGE_SEC", "120")
)


class PeerHealth(StrEnum):
    """Overall cross-service health classification."""

    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"


@dataclass(frozen=True, slots=True)
class PeerHealthSummary:
    """Summary of cross-service heartbeat validation."""

    health: PeerHealth
    peers: dict[str, HeartbeatStatus]
    stale_peers: tuple[str, ...]
    missing_peers: tuple[str, ...]

    @property
    def all_alive(self) -> bool:
        return self.health == PeerHealth.HEALTHY

    def to_dict(self) -> dict[str, Any]:
        return {
            "health": self.health.value,
            "stale_peers": list(self.stale_peers),
            "missing_peers": list(self.missing_peers),
            "peers": {
                name: {
                    "state": status.state.value,
                    "age_seconds": status.age_seconds,
                }
                for name, status in self.peers.items()
            },
        }


async def validate_peer_health(
    redis: Any,
    required_peers: tuple[str, ...],
) -> PeerHealthSummary:
    """Validate that all required peer services have alive heartbeats.

    Args:
        redis: Async Redis client.
        required_peers: Service names from SERVICE_HEARTBEAT_CONFIG to check.

    Returns:
        PeerHealthSummary with per-peer status and overall health.
    """
    peers: dict[str, HeartbeatStatus] = {}
    stale: list[str] = []
    missing: list[str] = []

    for peer_name in required_peers:
        config = SERVICE_HEARTBEAT_CONFIG.get(peer_name)
        if config is None:
            logger.warning(
                "[CrossServiceValidator] Unknown peer '{}' — skipping", peer_name
            )
            continue
        key, max_age = config
        status = await read_heartbeat(redis, key, max_age, service=peer_name)
        peers[peer_name] = status

        if status.state == HeartbeatState.STALE:
            stale.append(peer_name)
        elif status.state == HeartbeatState.MISSING:
            missing.append(peer_name)

    if missing:
        health = PeerHealth.UNHEALTHY
    elif stale:
        health = PeerHealth.DEGRADED
    else:
        health = PeerHealth.HEALTHY

    return PeerHealthSummary(
        health=health,
        peers=peers,
        stale_peers=tuple(stale),
        missing_peers=tuple(missing),
    )


def validate_peer_health_sync(
    redis_client: Any,
    required_peers: tuple[str, ...],
    *,
    now_ts: float | None = None,
) -> PeerHealthSummary:
    """Synchronous variant for services with sync Redis clients.

    Args:
        redis_client: Sync Redis client (must support ``.get(key)``).
        required_peers: Service names from SERVICE_HEARTBEAT_CONFIG to check.
        now_ts: Override wall-clock for testing.

    Returns:
        PeerHealthSummary with per-peer status and overall health.
    """
    from state.heartbeat_classifier import classify_heartbeat  # noqa: PLC0415

    peers: dict[str, HeartbeatStatus] = {}
    stale: list[str] = []
    missing: list[str] = []

    for peer_name in required_peers:
        config = SERVICE_HEARTBEAT_CONFIG.get(peer_name)
        if config is None:
            continue
        key, max_age = config
        try:
            raw = redis_client.get(key)
        except Exception as exc:
            logger.debug(
                "[CrossServiceValidator] Redis read failed for {}: {}", peer_name, exc
            )
            raw = None

        status = classify_heartbeat(raw, max_age, service=peer_name, now_ts=now_ts)
        peers[peer_name] = status

        if status.state == HeartbeatState.STALE:
            stale.append(peer_name)
        elif status.state == HeartbeatState.MISSING:
            missing.append(peer_name)

    if missing:
        health = PeerHealth.UNHEALTHY
    elif stale:
        health = PeerHealth.DEGRADED
    else:
        health = PeerHealth.HEALTHY

    return PeerHealthSummary(
        health=health,
        peers=peers,
        stale_peers=tuple(stale),
        missing_peers=tuple(missing),
    )


def check_orchestrator_freshness(
    redis_client: Any,
    *,
    max_age_sec: float | None = None,
) -> tuple[bool, float | None]:
    """Check orchestrator state freshness from its ORCHESTRATOR_STATE key.

    This reads the combined state key (not a dedicated heartbeat) and
    checks the ``timestamp`` field age. Used by workers that depend on
    orchestrator compliance state.

    Args:
        redis_client: Sync Redis client.
        max_age_sec: Override max age threshold. Defaults to env/120s.

    Returns:
        Tuple of (is_fresh, age_seconds). age_seconds is None if key missing.
    """
    import orjson  # noqa: PLC0415

    from core.redis_keys import ORCHESTRATOR_STATE  # noqa: PLC0415

    threshold = max_age_sec or _ORCHESTRATOR_STATE_MAX_AGE_SEC

    try:
        raw = redis_client.get(ORCHESTRATOR_STATE)
    except Exception as exc:
        logger.debug("[CrossServiceValidator] Failed to read orchestrator state: {}", exc)
        return False, None

    if not raw:
        return False, None

    try:
        data = orjson.loads(raw)
    except (orjson.JSONDecodeError, TypeError, ValueError):
        return False, None

    ts_raw = data.get("timestamp")
    if ts_raw is None:
        return False, None

    try:
        ts = float(ts_raw)
    except (TypeError, ValueError):
        return False, None

    age = max(0.0, time.time() - ts)
    return age <= threshold, round(age, 2)
