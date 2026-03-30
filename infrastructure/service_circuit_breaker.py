"""
Service Circuit Breaker — ARCH-GAP-10
========================================
Redis-persisted circuit breaker scoped per service name.

Extends the in-memory ``infrastructure.circuit_breaker.CircuitBreaker``
concept with Redis persistence so circuit state is visible across all
services and survives restarts.

This is for **inter-service** calls (e.g. API → Engine, Orchestrator →
Execution) — *not* for trading risk (use ``risk/circuit_breaker.py``).

Redis layout::

    wolf15:service_cb:{service}   STRING  JSON payload

Payload::

    {
        "state": "CLOSED" | "OPEN" | "HALF_OPEN",
        "failure_count": int,
        "success_count": int,
        "last_failure_at": ISO | null,
        "opened_at": ISO | null,
        "reason": str,
        "updated_at": ISO
    }

Zone: infrastructure/ — shared utility, no business logic.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from threading import Lock
from typing import Any

from loguru import logger

from core.metrics import CIRCUIT_BREAKER_STATE as CB_GAUGE
from core.metrics import CIRCUIT_BREAKER_TRIPS as CB_TRIPS


class ServiceCBState(StrEnum):
    """Circuit breaker states for inter-service calls."""

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


@dataclass(slots=True)
class ServiceCBSnapshot:
    """Serializable snapshot of a service circuit breaker."""

    service: str
    state: str = "CLOSED"
    failure_count: int = 0
    success_count: int = 0
    last_failure_at: str | None = None
    opened_at: str | None = None
    reason: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ServiceCircuitBreaker:
    """Redis-persisted per-service circuit breaker.

    Parameters
    ----------
    service:
        Service name (e.g. "engine", "ingest").
    redis_client:
        Sync Redis client with ``.get()``, ``.set()`` methods.
    failure_threshold:
        Consecutive failures before OPEN. Default: 5.
    recovery_timeout_sec:
        Seconds in OPEN before probing HALF_OPEN. Default: 60.
    half_open_successes:
        Successes in HALF_OPEN needed to CLOSE. Default: 2.
    key_prefix:
        Redis key prefix. Default: ``wolf15:service_cb``.
    """

    def __init__(
        self,
        service: str,
        redis_client: Any,
        *,
        failure_threshold: int = 5,
        recovery_timeout_sec: float = 60.0,
        half_open_successes: int = 2,
        key_prefix: str = "wolf15:service_cb",
    ) -> None:
        self.service = service
        self._redis = redis_client
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout_sec
        self._half_open_successes = half_open_successes
        self._key = f"{key_prefix}:{service}"

        # In-memory fast path (Redis is source of truth for cross-service)
        self._state = ServiceCBState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._opened_at: float | None = None
        self._last_failure_at: float | None = None
        self._reason = ""
        self._lock = Lock()

        # Hydrate from Redis on init
        self._hydrate()

    # ── Read ──────────────────────────────────────────────────────────────────

    @property
    def state(self) -> ServiceCBState:
        """Current state, auto-transitioning OPEN→HALF_OPEN on timeout."""
        with self._lock:
            self._maybe_half_open()
            return self._state

    def is_open(self) -> bool:
        """True when calls should be blocked."""
        return self.state == ServiceCBState.OPEN

    def is_closed(self) -> bool:
        """True when calls are allowed normally."""
        return self.state == ServiceCBState.CLOSED

    def snapshot(self) -> ServiceCBSnapshot:
        """Read-only snapshot of current state."""
        with self._lock:
            self._maybe_half_open()
            return self._snapshot_locked()

    def _snapshot_locked(self) -> ServiceCBSnapshot:
        """Build snapshot while lock is already held."""
        return ServiceCBSnapshot(
            service=self.service,
            state=self._state.value,
            failure_count=self._failure_count,
            success_count=self._success_count,
            last_failure_at=datetime.fromtimestamp(self._last_failure_at, tz=UTC).isoformat()
            if self._last_failure_at
            else None,
            opened_at=datetime.fromtimestamp(self._opened_at, tz=UTC).isoformat()
            if self._opened_at
            else None,
            reason=self._reason,
            updated_at=datetime.now(UTC).isoformat(),
        )

    # ── Write ─────────────────────────────────────────────────────────────────

    def record_success(self) -> None:
        """Record a successful service call."""
        with self._lock:
            self._maybe_half_open()
            if self._state == ServiceCBState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self._half_open_successes:
                    self._transition(ServiceCBState.CLOSED, "Recovery complete")
                    self._failure_count = 0
                    self._success_count = 0
            elif self._state == ServiceCBState.CLOSED:
                self._failure_count = 0
            self._persist()

    def record_failure(self, reason: str = "") -> None:
        """Record a failed service call, potentially tripping OPEN."""
        with self._lock:
            self._maybe_half_open()
            self._failure_count += 1
            self._last_failure_at = time.monotonic()
            self._reason = reason or f"failure #{self._failure_count}"

            if self._state in (ServiceCBState.CLOSED, ServiceCBState.HALF_OPEN):  # noqa: SIM102
                if self._failure_count >= self._failure_threshold:
                    self._transition(ServiceCBState.OPEN, self._reason)
                    self._opened_at = time.monotonic()
            self._persist()

    def force_open(self, reason: str = "manual") -> None:
        """Force the circuit OPEN (operator intervention)."""
        with self._lock:
            self._transition(ServiceCBState.OPEN, reason)
            self._opened_at = time.monotonic()
            self._persist()

    def force_close(self, reason: str = "manual") -> None:
        """Force the circuit CLOSED (operator intervention)."""
        with self._lock:
            self._transition(ServiceCBState.CLOSED, reason)
            self._failure_count = 0
            self._success_count = 0
            self._persist()

    def reset(self) -> None:
        """Full reset to CLOSED with zero counters."""
        self.force_close(reason="reset")

    # ── Internal ──────────────────────────────────────────────────────────────

    def _maybe_half_open(self) -> None:
        """Auto-transition OPEN → HALF_OPEN after recovery timeout."""
        if (
            self._state == ServiceCBState.OPEN
            and self._opened_at is not None
            and time.monotonic() - self._opened_at >= self._recovery_timeout
        ):
            self._state = ServiceCBState.HALF_OPEN
            self._success_count = 0
            self._reason = "auto-recovery probe"
            logger.info(
                "[ServiceCB:{}] OPEN → HALF_OPEN after {:.0f}s",
                self.service,
                self._recovery_timeout,
            )

    def _transition(self, new_state: ServiceCBState, reason: str) -> None:
        """State transition with logging and metrics."""
        prev = self._state
        self._state = new_state
        self._reason = reason
        logger.info("[ServiceCB:{}] {} → {} reason={}", self.service, prev, new_state, reason)
        try:
            CB_GAUGE.labels(name=f"svc_{self.service}").set(
                {"CLOSED": 0, "HALF_OPEN": 1, "OPEN": 2}.get(new_state.value, -1)
            )
            if new_state == ServiceCBState.OPEN:
                CB_TRIPS.labels(name=f"svc_{self.service}").inc()
        except Exception:
            pass  # Metrics best-effort

    def _persist(self) -> None:
        """Persist current state to Redis (best-effort). Must be called while lock is held."""
        try:
            snap = self._snapshot_locked()
            self._redis.set(self._key, json.dumps(snap.to_dict()))
        except Exception:
            logger.debug("[ServiceCB:{}] Redis persist failed", self.service)

    def _hydrate(self) -> None:
        """Load state from Redis on startup."""
        try:
            raw = self._redis.get(self._key)
            if raw is None:
                return
            data = json.loads(raw if isinstance(raw, str) else raw.decode())
            state_str = data.get("state", "CLOSED")
            self._state = ServiceCBState(state_str) if state_str in ServiceCBState.__members__ else ServiceCBState.CLOSED
            self._failure_count = data.get("failure_count", 0)
            self._success_count = data.get("success_count", 0)
            self._reason = data.get("reason", "")
            logger.info(
                "[ServiceCB:{}] Hydrated from Redis: state={} failures={}",
                self.service,
                self._state,
                self._failure_count,
            )
        except Exception:
            logger.debug("[ServiceCB:{}] Redis hydrate failed, starting CLOSED", self.service)
