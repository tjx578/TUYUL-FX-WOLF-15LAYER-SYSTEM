from __future__ import annotations

import asyncio
import json

import pytest

from core.health_probe import HealthProbe
from startup.graceful_shutdown import GracefulShutdown
from startup.task_supervisor import supervised_task


@pytest.mark.asyncio
@pytest.mark.parametrize("returns", [True, False])
async def test_required_exit_fails_closed_and_propagates(returns):
    probe = HealthProbe(readiness_check=lambda: True)

    async def worker():
        if not returns:
            raise ValueError("private-connection-details")

    with pytest.raises(RuntimeError, match="crash_limit"):
        await supervised_task("worker", worker, health_probe=probe, max_restarts=0, required=True)
    response = probe._readiness_response()
    assert "503 Service Unavailable" in response
    assert "private" not in response
    assert json.loads(response.split("\r\n\r\n")[1])["status"] == "not_ready"


@pytest.mark.asyncio
async def test_optional_completion_and_requested_stop_are_not_fatal():
    probe = HealthProbe()

    async def worker():
        return

    await supervised_task("optional", worker, health_probe=probe)
    stop = asyncio.Event()
    stop.set()
    await supervised_task("required", worker, stop, probe, required=True)
    assert "200 OK" in probe._readiness_response()


@pytest.mark.asyncio
async def test_shutdown_drains_worker_before_pool_close():
    order = []
    started = asyncio.Event()

    async def worker():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            order.append("drained")

    async def close_pool():
        order.append("pool_closed")

    task = asyncio.create_task(worker())
    await started.wait()
    shutdown = GracefulShutdown(drain_timeout=1)
    shutdown.register_cleanup("pool", close_pool)
    await shutdown.shutdown([task])
    assert order == ["drained", "pool_closed"]


@pytest.mark.asyncio
async def test_readiness_cannot_outlive_liveness():
    probe = HealthProbe(readiness_check=lambda: True)
    probe.set_alive(False)
    assert "503 Service Unavailable" in probe._readiness_response()
    assert '"ready": false' in probe._status_response()


@pytest.mark.asyncio
async def test_undrained_task_blocks_pool_cleanup(monkeypatch):
    closed = []
    pending = asyncio.create_task(asyncio.Event().wait())

    async def still_pending(tasks, **kwargs):
        return set(), set(tasks)

    async def close_pool():
        closed.append(True)

    monkeypatch.setattr(asyncio, "wait", still_pending)
    shutdown = GracefulShutdown(drain_timeout=0)
    shutdown.register_cleanup("pool", close_pool)
    with pytest.raises(RuntimeError, match="shutdown_tasks_not_drained"):
        await shutdown.shutdown([pending])
    assert not closed
    with pytest.raises(asyncio.CancelledError):
        await pending


@pytest.mark.asyncio
@pytest.mark.parametrize("requested", [False, True])
async def test_required_cancellation_distinguishes_shutdown(requested):
    stop = asyncio.Event()
    started = asyncio.Event()
    probe = HealthProbe()

    async def worker():
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(supervised_task("worker", worker, stop, probe, required=True))
    await started.wait()
    if requested:
        stop.set()
    task.cancel()
    if requested:
        await task
        assert "200 OK" in probe._readiness_response()
    else:
        with pytest.raises(RuntimeError, match="unexpected_cancellation"):
            await task
        assert "503 Service Unavailable" in probe._readiness_response()
