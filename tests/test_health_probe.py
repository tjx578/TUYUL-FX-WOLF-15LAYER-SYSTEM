"""Tests for core.health_probe — lightweight container health server."""

import asyncio
import contextlib
import json
import urllib.error
import urllib.request

import pytest

from core.health_probe import HealthProbe


@pytest.fixture()
async def probe_server():
    """Start a HealthProbe on a random high port and tear it down after the test."""
    probe = HealthProbe(port=0, service_name="test-service")

    # Use port 0 → OS picks a free port.  We need to start the server
    # manually so we can discover the actual port.
    server = await asyncio.start_server(probe._handle, "127.0.0.1", 0)
    probe._server = server
    port = server.sockets[0].getsockname()[1]

    task = asyncio.create_task(server.serve_forever())
    yield probe, port

    server.close()
    await server.wait_closed()
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


def _get(port: int, path: str) -> tuple[int, dict]:
    """Blocking HTTP GET — fine for tests."""
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
    try:
        resp = urllib.request.urlopen(req, timeout=3)  # noqa: S310
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


# ── Liveness ────────────────────────────────────────────────────


@pytest.mark.asyncio()
async def test_healthz_alive(probe_server):
    _probe, port = probe_server
    status, body = await asyncio.to_thread(_get, port, "/healthz")
    assert status == 200
    assert body["status"] == "alive"
    assert body["service"] == "test-service"
    assert "uptime_sec" in body


@pytest.mark.asyncio()
async def test_healthz_dead(probe_server):
    probe, port = probe_server
    probe.set_alive(False)
    status, body = await asyncio.to_thread(_get, port, "/healthz")
    assert status == 503
    assert body["status"] == "dead"


# ── Readiness ───────────────────────────────────────────────────


@pytest.mark.asyncio()
async def test_readyz_default_ready(probe_server):
    _probe, port = probe_server
    status, body = await asyncio.to_thread(_get, port, "/readyz")
    assert status == 200
    assert body["status"] == "ready"


@pytest.mark.asyncio()
async def test_readyz_not_ready(probe_server):
    probe, port = probe_server
    probe.set_readiness_check(lambda: False)
    status, body = await asyncio.to_thread(_get, port, "/readyz")
    assert status == 503
    assert body["status"] == "not_ready"


@pytest.mark.asyncio()
async def test_readyz_custom_check(probe_server):
    probe, port = probe_server
    ready_flag = False
    probe.set_readiness_check(lambda: ready_flag)

    status, _ = await asyncio.to_thread(_get, port, "/readyz")
    assert status == 503

    ready_flag = True
    status, body = await asyncio.to_thread(_get, port, "/readyz")
    assert status == 200
    assert body["status"] == "ready"


# ── Details metadata ────────────────────────────────────────────


@pytest.mark.asyncio()
async def test_set_detail_appears_in_response(probe_server):
    probe, port = probe_server
    probe.set_detail("version", "1.2.3")
    status, body = await asyncio.to_thread(_get, port, "/healthz")
    assert status == 200
    assert body["version"] == "1.2.3"


# ── 404 on unknown paths ───────────────────────────────────────


@pytest.mark.asyncio()
async def test_unknown_path_returns_404(probe_server):
    _probe, port = probe_server
    status, body = await asyncio.to_thread(_get, port, "/unknown")
    assert status == 404
    assert body["error"] == "not_found"


# ── /status endpoint ───────────────────────────────────────────


@pytest.mark.asyncio()
async def test_status_healthy(probe_server):
    """When alive and ready, /status returns 200 with combined info."""
    probe, port = probe_server
    probe.set_detail("component", "ws")
    status, body = await asyncio.to_thread(_get, port, "/status")
    assert status == 200
    assert body["alive"] is True
    assert body["ready"] is True
    assert body["service"] == "test-service"
    assert body["component"] == "ws"
    assert "uptime_sec" in body


@pytest.mark.asyncio()
async def test_status_degraded_when_not_ready(probe_server):
    """When alive but not ready, /status returns 503."""
    probe, port = probe_server
    probe.set_readiness_check(lambda: False)
    status, body = await asyncio.to_thread(_get, port, "/status")
    assert status == 503
    assert body["alive"] is True
    assert body["ready"] is False
