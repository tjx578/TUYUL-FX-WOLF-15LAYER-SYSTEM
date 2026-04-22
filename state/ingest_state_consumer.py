from __future__ import annotations

import logging
import os
import time
from dataclasses import asdict, dataclass
from typing import Any, Protocol

from state.heartbeat_classifier import (
    SERVICE_HEARTBEAT_CONFIG,
    IngestHealthState,
    classify_heartbeat,
    classify_ingest_health,
)
from storage.redis_client import redis_client as default_redis_client

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestHealthSnapshot:
    state: str
    process_state: str
    provider_state: str
    process_age: float | None
    provider_age: float | None
    checked_at: float
    audit_id: str


@dataclass(frozen=True)
class IngestGateDecision:
    blocking: bool
    reason: str
    state: str
    process_age: float | None
    provider_age: float | None
    audit_id: str


class SupportsIngestGateDecision(Protocol):
    def is_blocking(self) -> IngestGateDecision: ...


class IngestStateConsumer:
    CACHE_TTL_SEC = 5.0
    BLOCKING_STATES = {IngestHealthState.NO_PRODUCER}
    DEGRADED_TOLERATED_MAX_AGE = 60.0

    def __init__(
        self,
        redis_client: Any | None = None,
        *,
        cache_ttl_sec: float | None = None,
        now_fn: Any | None = None,
    ) -> None:
        self._redis = redis_client if redis_client is not None else default_redis_client
        self._cache_ttl_sec = float(cache_ttl_sec or self.CACHE_TTL_SEC)
        self._now_fn = now_fn or time.time
        self._cached_snapshot: IngestHealthSnapshot | None = None
        self._cache_expires_at = 0.0
        self.last_audit_id: str | None = None
        self._last_logged_state: str | None = None

    def get_state(self, *, force_refresh: bool = False) -> IngestHealthSnapshot:
        now_ts = float(self._now_fn())
        if not force_refresh and self._cached_snapshot is not None and now_ts < self._cache_expires_at:
            return self._cached_snapshot

        process_key, process_max_age = SERVICE_HEARTBEAT_CONFIG["ingest_process"]
        provider_key, provider_max_age = SERVICE_HEARTBEAT_CONFIG["ingest_provider"]
        process_status = classify_heartbeat(
            self._safe_get(process_key),
            process_max_age,
            service="ingest_process",
            now_ts=now_ts,
        )
        provider_status = classify_heartbeat(
            self._safe_get(provider_key),
            provider_max_age,
            service="ingest_provider",
            now_ts=now_ts,
        )
        ingest_health = classify_ingest_health(process_status, provider_status)
        audit_id = f"ingest-state:{int(now_ts * 1000)}:{ingest_health.state.value.lower()}"
        snapshot = IngestHealthSnapshot(
            state=ingest_health.state.value,
            process_state=process_status.state.value,
            provider_state=provider_status.state.value,
            process_age=process_status.age_seconds,
            provider_age=provider_status.age_seconds,
            checked_at=now_ts,
            audit_id=audit_id,
        )

        self.last_audit_id = audit_id
        self._cached_snapshot = snapshot
        self._cache_expires_at = now_ts + self._cache_ttl_sec
        self._log_transition(snapshot)
        return snapshot

    def is_blocking(self, *, force_refresh: bool = False) -> IngestGateDecision:
        snapshot = self.get_state(force_refresh=force_refresh)
        if snapshot.state in {state.value for state in self.BLOCKING_STATES}:
            reason = self._format_age_reason("ingest_no_producer", snapshot.process_age)
            return IngestGateDecision(
                True, reason, snapshot.state, snapshot.process_age, snapshot.provider_age, snapshot.audit_id
            )

        if snapshot.state == IngestHealthState.DEGRADED.value:
            if snapshot.provider_age is not None and snapshot.provider_age > self.DEGRADED_TOLERATED_MAX_AGE:
                reason = self._format_age_reason("ingest_degraded_too_long", snapshot.provider_age)
                return IngestGateDecision(
                    True,
                    reason,
                    snapshot.state,
                    snapshot.process_age,
                    snapshot.provider_age,
                    snapshot.audit_id,
                )
            return IngestGateDecision(
                False,
                "ingest_degraded_within_grace",
                snapshot.state,
                snapshot.process_age,
                snapshot.provider_age,
                snapshot.audit_id,
            )

        return IngestGateDecision(
            False,
            "ingest_ok",
            snapshot.state,
            snapshot.process_age,
            snapshot.provider_age,
            snapshot.audit_id,
        )

    def _safe_get(self, key: str) -> str | bytes | None:
        try:
            redis_reader = getattr(self._redis, "client", self._redis)
            return redis_reader.get(key)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[IngestStateConsumer] Redis read failed for %s: %s", key, exc)
            return None

    def _log_transition(self, snapshot: IngestHealthSnapshot) -> None:
        if snapshot.state != self._last_logged_state:
            logger.info("[IngestStateConsumer] state=%s detail=%s", snapshot.state, asdict(snapshot))
            self._last_logged_state = snapshot.state

    @staticmethod
    def _format_age_reason(prefix: str, age_seconds: float | None) -> str:
        if age_seconds is None:
            return prefix
        return f"{prefix}:age={age_seconds:.1f}s"


_default_consumer: IngestStateConsumer | None = None


def ingest_gate_enabled_by_default() -> bool:
    return (os.getenv("WOLF15_ENABLE_INGEST_GATE") or "").strip().lower() in {"1", "true", "yes", "on"}


def get_ingest_state_consumer() -> IngestStateConsumer:
    global _default_consumer
    if _default_consumer is None:
        _default_consumer = IngestStateConsumer()
    return _default_consumer


__all__ = [
    "IngestGateDecision",
    "IngestHealthSnapshot",
    "IngestStateConsumer",
    "SupportsIngestGateDecision",
    "get_ingest_state_consumer",
    "ingest_gate_enabled_by_default",
]
