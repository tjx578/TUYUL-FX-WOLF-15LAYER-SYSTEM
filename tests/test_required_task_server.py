import asyncio
from types import SimpleNamespace

import pytest

from startup.required_task_server import serve_required_tasks
from startup.required_tasks import RequiredTaskSupervisor


@pytest.mark.asyncio
async def test_required_task_failure_stops_effective_worker_and_reports_failure():
    supervisor = RequiredTaskSupervisor({"worker": True})
    app = SimpleNamespace(state=SimpleNamespace(required_task_supervisor=supervisor))
    server = SimpleNamespace(started=True, should_exit=False, lifespan=SimpleNamespace())

    async def serve(*, sockets):
        assert sockets == ["inherited listener"]
        supervisor.fail("worker", "exception")
        while not server.should_exit:
            await asyncio.sleep(0.01)

    server.serve = serve
    assert await asyncio.wait_for(serve_required_tasks(server, app, sockets=["inherited listener"]), 3)
    assert server.should_exit


@pytest.mark.asyncio
@pytest.mark.parametrize("shutdown_failed", [False, True])
async def test_effective_worker_lifespan_exit_status(shutdown_failed):
    app = SimpleNamespace(state=SimpleNamespace())
    server = SimpleNamespace(started=True, should_exit=False, lifespan=SimpleNamespace(shutdown_failed=shutdown_failed))

    async def serve(*, sockets):
        pass

    server.serve = serve
    assert await serve_required_tasks(server, app) is shutdown_failed


@pytest.mark.asyncio
async def test_failed_monitor_stops_server_instead_of_serving_unmonitored():
    def broken_snapshot():
        raise RuntimeError("monitor broken")

    supervisor = SimpleNamespace(snapshot=broken_snapshot, tasks={})
    app = SimpleNamespace(state=SimpleNamespace(required_task_supervisor=supervisor))
    server = SimpleNamespace(started=True, should_exit=False, lifespan=SimpleNamespace())

    async def serve(*, sockets):
        while not server.should_exit:
            await asyncio.sleep(0.01)

    server.serve = serve
    assert await asyncio.wait_for(serve_required_tasks(server, app), 2)
    assert server.should_exit


@pytest.mark.asyncio
async def test_pending_required_task_keeps_process_deadline_armed(monkeypatch):
    from startup import required_task_server

    events = []

    class Timer:
        def __init__(self, seconds, callback):
            assert seconds == 25

        def start(self):
            events.append("armed")

        def cancel(self):
            events.append("cancelled")

    monkeypatch.setattr(required_task_server.threading, "Timer", Timer)
    supervisor = RequiredTaskSupervisor({"writer": True})
    task = supervisor.start("writer", asyncio.Event().wait())
    app = SimpleNamespace(state=SimpleNamespace(required_task_supervisor=supervisor))
    server = SimpleNamespace(started=True, should_exit=True, lifespan=SimpleNamespace(shutdown_failed=True))

    async def serve(*, sockets):
        pass

    server.serve = serve
    try:
        assert await serve_required_tasks(server, app)
        assert events == ["armed"]
    finally:
        await supervisor.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RuntimeError("transport failure"), SystemExit(1)])
async def test_gunicorn_worker_maps_raised_server_failure_to_master_failure(monkeypatch, failure):
    import importlib.util
    import sys
    from pathlib import Path

    # Gunicorn requires Unix; isolate its interface for this Windows-portable
    # exception mapping test. Actual entrypoint acceptance runs separately on Linux.
    monkeypatch.setitem(sys.modules, "gunicorn.arbiter", SimpleNamespace(Arbiter=SimpleNamespace(WORKER_BOOT_ERROR=3)))
    monkeypatch.setitem(
        sys.modules, "uvicorn.workers", SimpleNamespace(UvicornWorker=type("Base", (), {"CONFIG_KWARGS": {}}))
    )
    spec = importlib.util.spec_from_file_location("c06_worker_under_test", Path("deploy/uvicorn_worker.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    worker = module.UvicornWorker()
    worker.config = SimpleNamespace()
    worker.wsgi = SimpleNamespace()
    worker.sockets = []
    worker._install_sigquit_handler = lambda: None
    monkeypatch.setattr(module, "Server", lambda **kwargs: SimpleNamespace())

    async def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(module, "serve_required_tasks", fail)
    with pytest.raises(SystemExit) as caught:
        await worker._serve()
    assert caught.value.code == 3
