import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from api import app_factory
from api.middleware.machine_auth import verify_observability_machine_auth
from startup.required_tasks import RequiredTaskSupervisor


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["exception", "returned", "cancelled"])
async def test_required_task_loss_is_fatal_with_causal_reason(outcome):
    supervisor = RequiredTaskSupervisor({"worker": True, "optional": False})
    assert not supervisor.snapshot()["ready"]

    async def worker():
        if outcome == "exception":
            raise RuntimeError("private DSN must not appear in health")
        if outcome == "cancelled":
            await asyncio.Event().wait()

    task = supervisor.start("worker", worker())
    if outcome == "cancelled":
        task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    snapshot = supervisor.snapshot()
    assert snapshot["reasons"] == [f"required_task_worker_{outcome}"]
    assert snapshot["states"]["optional"] == "DISABLED"
    assert supervisor.fatal.is_set()
    await supervisor.stop()


@pytest.mark.asyncio
async def test_intentional_stop_is_not_fatal_and_drains_in_flight_cleanup():
    supervisor = RequiredTaskSupervisor({"worker": True})
    started, drained = asyncio.Event(), asyncio.Event()

    async def worker():
        try:
            started.set()
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            drained.set()

    supervisor.start("worker", worker())
    await started.wait()
    assert supervisor.snapshot()["ready"]
    await supervisor.stop()
    assert drained.is_set()
    assert not supervisor.fatal.is_set()
    assert supervisor.snapshot()["states"]["worker"] == "STOPPED"


@pytest.mark.asyncio
async def test_resistant_writer_drain_timeout_is_not_reported_stopped():
    supervisor = RequiredTaskSupervisor({"worker": True})
    started, release = asyncio.Event(), asyncio.Event()

    async def worker():
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await release.wait()

    task = supervisor.start("worker", worker())
    await started.wait()
    try:
        with pytest.raises(TimeoutError, match="REQUIRED_TASK_DRAIN_TIMEOUT"):
            await supervisor.stop(timeout=0.01)
        assert not task.done()
        assert supervisor.fatal.is_set()
    finally:
        release.set()
        await task


@pytest.fixture
def api_dependencies(monkeypatch):
    from api import ws_routes
    from infrastructure import redis_client

    monkeypatch.setenv("WOLF15_API_READ_ONLY_STARTUP", "false")
    monkeypatch.setenv("WOLF15_EMBED_ORCHESTRATOR", "false")
    monkeypatch.setenv("ENABLE_WS_RELAY", "false")
    monkeypatch.setenv("ENABLE_PEER_HEALTH", "false")
    monkeypatch.setattr(
        redis_client, "get_client", AsyncMock(return_value=SimpleNamespace(ping=AsyncMock(return_value=True)))
    )
    monkeypatch.setattr(redis_client, "close_pool", AsyncMock())
    monkeypatch.setattr(app_factory, "pg_client", SimpleNamespace(initialize=AsyncMock(), close=AsyncMock()))
    monkeypatch.setattr(ws_routes, "_candle_agg", SimpleNamespace(start=AsyncMock(), stop=AsyncMock()))
    return redis_client


@pytest.mark.asyncio
async def test_actual_api_lifespan_503_on_late_worker_loss_and_drain_before_pool(monkeypatch, api_dependencies):
    from storage import trade_outbox_worker

    entered, fail = asyncio.Event(), asyncio.Event()
    events = []

    class Worker:
        def __init__(self, **_):
            pass

        async def run(self):
            try:
                entered.set()
                await fail.wait()
                raise RuntimeError("private-worker-error")
            finally:
                events.append("worker_drained")

        async def stop(self):
            pass

    async def close_pool():
        assert "worker_drained" in events
        events.append("pool_closed")

    monkeypatch.setattr(trade_outbox_worker, "TradeOutboxWorker", Worker)
    app_factory.pg_client.close.side_effect = close_pool
    app = FastAPI()
    app.state.router_boot_errors = []
    app.dependency_overrides[verify_observability_machine_auth] = lambda: None
    app_factory._register_health_routes(app)
    async with app_factory.lifespan(app):
        await entered.wait()
        fail.set()
        await asyncio.gather(app.state.trade_outbox_task, return_exceptions=True)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/readyz")
        assert response.status_code == 503
        assert response.json()["reasons"] == ["required_task_trade_outbox_exception"]
        assert "private" not in response.text
    assert events == ["worker_drained", "pool_closed"]


@pytest.mark.asyncio
async def test_actual_api_worker_constructor_failure_is_fatal(monkeypatch, api_dependencies):
    from storage import trade_outbox_worker

    def failed(**_):
        raise RuntimeError("private bootstrap error")

    monkeypatch.setattr(trade_outbox_worker, "TradeOutboxWorker", failed)
    app = FastAPI()
    with pytest.raises(RuntimeError, match="REQUIRED_TRADE_OUTBOX_BOOTSTRAP_FAILED"):
        async with app_factory.lifespan(app):
            pytest.fail("startup must fail")
    app_factory.pg_client.close.assert_awaited_once()
    api_dependencies.close_pool.assert_awaited_once()
