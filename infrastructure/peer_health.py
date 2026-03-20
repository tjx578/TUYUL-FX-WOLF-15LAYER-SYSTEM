"""Async peer health checker with circuit breaker.

Periodically probes peer services' ``/healthz`` endpoints and maintains
a cached view of the fleet's health.  Results are available via
:meth:`PeerHealthChecker.snapshot` for the aggregation endpoint.

Circuit-breaker logic:
    * After ``failure_threshold`` consecutive failures → OPEN (skip probes).
    * After ``recovery_timeout`` seconds in OPEN → HALF_OPEN (try one probe).
    * On HALF_OPEN success → CLOSED.  On failure → OPEN again.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import httpx
from loguru import logger

from infrastructure.service_registry import ServiceEndpoint, get_peer_services

# ── Circuit breaker states ────────────────────────────────────────────────────


class CBState(Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


@dataclass
class CircuitBreaker:
    failure_threshold: int = 3
    recovery_timeout: float = 120.0
    state: CBState = CBState.CLOSED
    failure_count: int = 0
    last_failure_time: float = 0.0

    def record_success(self) -> None:
        self.failure_count = 0
        self.state = CBState.CLOSED

    def record_failure(self) -> None:
        self.failure_count += 1
        self.last_failure_time = time.monotonic()
        if self.failure_count >= self.failure_threshold:
            self.state = CBState.OPEN

    def should_attempt(self) -> bool:
        if self.state == CBState.CLOSED:
            return True
        if self.state == CBState.OPEN:
            elapsed = time.monotonic() - self.last_failure_time
            if elapsed >= self.recovery_timeout:
                self.state = CBState.HALF_OPEN
                return True
            return False
        # HALF_OPEN — allow exactly one probe
        return True


# ── Peer status snapshot ──────────────────────────────────────────────────────


class PeerStatus(Enum):
    HEALTHY = "HEALTHY"
    UNHEALTHY = "UNHEALTHY"
    UNREACHABLE = "UNREACHABLE"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"
    UNKNOWN = "UNKNOWN"


@dataclass
class PeerHealthRecord:
    service: str
    status: PeerStatus = PeerStatus.UNKNOWN
    latency_ms: float | None = None
    last_checked: float = 0.0
    detail: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


# ── Main checker ──────────────────────────────────────────────────────────────

_PROBE_TIMEOUT = 5.0  # seconds per HTTP request
_DEFAULT_INTERVAL = 15.0  # seconds between check rounds


class PeerHealthChecker:
    """Background task that probes peer services and caches results.

    Usage::

        checker = PeerHealthChecker(self_name="api")
        await checker.start()          # spawns background task
        snap = checker.snapshot()       # read latest results
        await checker.stop()            # graceful shutdown
    """

    def __init__(
        self,
        self_name: str = "api",
        interval: float = _DEFAULT_INTERVAL,
    ) -> None:
        self._self_name = self_name
        self._interval = interval
        self._peers = get_peer_services(exclude_self=self_name)
        self._records: dict[str, PeerHealthRecord] = {p.name: PeerHealthRecord(service=p.name) for p in self._peers}
        self._breakers: dict[str, CircuitBreaker] = {p.name: CircuitBreaker() for p in self._peers}
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    # ── Public API ────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the background probing loop."""
        self._stop_event.clear()
        # Do one immediate round before entering the loop
        await self._check_all()
        self._task = asyncio.create_task(self._loop(), name="peer-health-checker")
        logger.info(
            "PeerHealthChecker started — monitoring {} peers every {:.0f}s",
            len(self._peers),
            self._interval,
        )

    async def stop(self) -> None:
        """Gracefully stop the background task."""
        self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        logger.info("PeerHealthChecker stopped")

    def snapshot(self) -> dict[str, Any]:
        """Return the latest cached health view (thread-safe read)."""
        records: list[dict[str, Any]] = []
        for rec in self._records.values():
            records.append(
                {
                    "service": rec.service,
                    "status": rec.status.value,
                    "latency_ms": round(rec.latency_ms, 1) if rec.latency_ms is not None else None,
                    "last_checked_ago_s": round(time.monotonic() - rec.last_checked, 1) if rec.last_checked else None,
                    "circuit_breaker": self._breakers[rec.service].state.value,
                    "error": rec.error,
                }
            )
        overall = "HEALTHY"
        if any(r.status != PeerStatus.HEALTHY for r in self._records.values()):
            if all(r.status == PeerStatus.UNKNOWN for r in self._records.values()):
                overall = "UNKNOWN"
            elif any(r.status in (PeerStatus.UNREACHABLE, PeerStatus.CIRCUIT_OPEN) for r in self._records.values()):
                overall = "DEGRADED"
            else:
                overall = "PARTIAL"
        return {"overall": overall, "self": self._self_name, "peers": records}

    # ── Internals ─────────────────────────────────────────────────────────

    async def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval)
                break  # stop_event was set
            except TimeoutError:
                pass  # interval elapsed — run checks
            await self._check_all()

    async def _check_all(self) -> None:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
            tasks = [self._probe_one(client, peer) for peer in self._peers]
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _probe_one(self, client: httpx.AsyncClient, peer: ServiceEndpoint) -> None:
        breaker = self._breakers[peer.name]
        record = self._records[peer.name]
        record.last_checked = time.monotonic()

        if not breaker.should_attempt():
            record.status = PeerStatus.CIRCUIT_OPEN
            record.error = "circuit breaker open"
            return

        url = f"{peer.base_url.rstrip('/')}{peer.health_path}"
        try:
            t0 = time.monotonic()
            resp = await client.get(url)
            latency = (time.monotonic() - t0) * 1000

            if resp.status_code == 200:
                record.status = PeerStatus.HEALTHY
                record.latency_ms = latency
                record.error = None
                try:
                    record.detail = resp.json()
                except Exception:
                    record.detail = {}
                breaker.record_success()
            else:
                record.status = PeerStatus.UNHEALTHY
                record.latency_ms = latency
                record.error = f"HTTP {resp.status_code}"
                breaker.record_failure()
        except httpx.TimeoutException:
            record.status = PeerStatus.UNREACHABLE
            record.latency_ms = None
            record.error = "timeout"
            breaker.record_failure()
        except httpx.ConnectError:
            record.status = PeerStatus.UNREACHABLE
            record.latency_ms = None
            record.error = "connection refused"
            breaker.record_failure()
        except Exception as exc:
            record.status = PeerStatus.UNREACHABLE
            record.latency_ms = None
            record.error = str(exc)[:200]
            breaker.record_failure()
            logger.debug("Peer probe {} failed: {}", peer.name, exc)
