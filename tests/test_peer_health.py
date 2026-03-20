"""Tests for infrastructure/peer_health.py — PeerHealthChecker + CircuitBreaker.

Validates:
    1. Healthy peer probe returns HEALTHY with latency.
    2. Failed peer probe returns UNREACHABLE, increments circuit breaker.
    3. Circuit breaker opens after failure_threshold consecutive failures.
    4. Circuit breaker transitions OPEN → HALF_OPEN after recovery_timeout.
    5. snapshot() returns correct overall status.
    6. Service registry excludes self.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from infrastructure.peer_health import (
    CBState,
    CircuitBreaker,
    PeerHealthChecker,
)
from infrastructure.service_registry import get_peer_services

# ── Circuit Breaker unit tests ────────────────────────────────────────────────


class TestCircuitBreaker:
    def test_starts_closed(self) -> None:
        cb = CircuitBreaker()
        assert cb.state == CBState.CLOSED
        assert cb.should_attempt() is True

    def test_opens_after_threshold(self) -> None:
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CBState.CLOSED
        cb.record_failure()
        assert cb.state == CBState.OPEN
        assert cb.should_attempt() is False

    def test_success_resets(self) -> None:
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.state == CBState.CLOSED
        assert cb.failure_count == 0

    def test_half_open_after_recovery(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure()
        assert cb.state == CBState.OPEN

        # Wait past recovery_timeout
        time.sleep(0.02)
        assert cb.should_attempt() is True
        assert cb.state == CBState.HALF_OPEN

    def test_half_open_failure_reopens(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure()
        time.sleep(0.02)
        cb.should_attempt()  # transition to HALF_OPEN
        assert cb.state == CBState.HALF_OPEN
        cb.record_failure()
        assert cb.state == CBState.OPEN


# ── Service Registry unit tests ───────────────────────────────────────────────


class TestServiceRegistry:
    def test_returns_all_services(self) -> None:
        peers = get_peer_services()
        names = {p.name for p in peers}
        assert names == {"api", "engine", "ingest", "orchestrator"}

    def test_excludes_self(self) -> None:
        peers = get_peer_services(exclude_self="api")
        names = {p.name for p in peers}
        assert "api" not in names
        assert "engine" in names
        assert "ingest" in names
        assert "orchestrator" in names


# ── PeerHealthChecker integration tests (mocked HTTP) ─────────────────────────


def _make_mock_response(status_code: int = 200, json_data: dict | None = None) -> httpx.Response:
    """Build a fake httpx.Response."""
    return httpx.Response(
        status_code=status_code,
        json=json_data or {"status": "ok"},
        request=httpx.Request("GET", "http://test/healthz"),
    )


class TestPeerHealthChecker:
    @pytest.fixture()
    def checker(self) -> PeerHealthChecker:
        return PeerHealthChecker(self_name="api", interval=60.0)  # long interval to prevent auto-run

    @pytest.mark.asyncio
    async def test_healthy_probe(self, checker: PeerHealthChecker) -> None:
        mock_get = AsyncMock(return_value=_make_mock_response(200, {"status": "ok"}))
        with patch("httpx.AsyncClient.get", mock_get):
            await checker._check_all()

        snap = checker.snapshot()
        assert snap["self"] == "api"
        assert snap["overall"] == "HEALTHY"
        for peer in snap["peers"]:
            assert peer["status"] == "HEALTHY"
            assert peer["latency_ms"] is not None

    @pytest.mark.asyncio
    async def test_unreachable_peer(self, checker: PeerHealthChecker) -> None:
        mock_get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        with patch("httpx.AsyncClient.get", mock_get):
            await checker._check_all()

        snap = checker.snapshot()
        assert snap["overall"] in ("DEGRADED", "PARTIAL")
        for peer in snap["peers"]:
            assert peer["status"] == "UNREACHABLE"
            assert peer["error"] == "connection refused"

    @pytest.mark.asyncio
    async def test_unhealthy_peer(self, checker: PeerHealthChecker) -> None:
        mock_get = AsyncMock(return_value=_make_mock_response(503))
        with patch("httpx.AsyncClient.get", mock_get):
            await checker._check_all()

        snap = checker.snapshot()
        for peer in snap["peers"]:
            assert peer["status"] == "UNHEALTHY"
            assert peer["error"] == "HTTP 503"

    @pytest.mark.asyncio
    async def test_circuit_opens_on_repeated_failures(self, checker: PeerHealthChecker) -> None:
        mock_get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        with patch("httpx.AsyncClient.get", mock_get):
            # Default threshold is 3 — run 3 rounds to trip, then 4th to observe CIRCUIT_OPEN
            await checker._check_all()
            await checker._check_all()
            await checker._check_all()
            await checker._check_all()

        snap = checker.snapshot()
        for peer in snap["peers"]:
            assert peer["circuit_breaker"] == "OPEN"
            assert peer["status"] == "CIRCUIT_OPEN"

    @pytest.mark.asyncio
    async def test_start_stop_lifecycle(self, checker: PeerHealthChecker) -> None:
        mock_get = AsyncMock(return_value=_make_mock_response(200))
        with patch("httpx.AsyncClient.get", mock_get):
            await checker.start()
            # Task should be running
            assert checker._task is not None
            assert not checker._task.done()

            await checker.stop()
            assert checker._task is None

    @pytest.mark.asyncio
    async def test_timeout_peer(self, checker: PeerHealthChecker) -> None:
        mock_get = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
        with patch("httpx.AsyncClient.get", mock_get):
            await checker._check_all()

        snap = checker.snapshot()
        for peer in snap["peers"]:
            assert peer["status"] == "UNREACHABLE"
            assert peer["error"] == "timeout"
