"""Execute the source entrypoint bodies without import-time trading bootstrap.

Built engine acceptance separately exercises the full module in its image.
These tests isolate early resource failure and the synchronous shutdown owner.
"""

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from services.engine.runtime_state import EngineRuntimeState
from startup.graceful_shutdown import GracefulShutdown


@pytest.fixture
def entrypoint(monkeypatch):
    source = Path(__file__).resolve().parents[1] / "main.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    selected = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in {"main", "_run_main", "run"}
    ]
    assert len(selected) == 3
    namespace = {
        "asyncio": asyncio,
        "os": SimpleNamespace(getenv=lambda name, default=None: default),
        "EngineRuntimeState": EngineRuntimeState,
        "GracefulShutdown": GracefulShutdown,
        "logger": Mock(),
        "_engine_readiness": lambda: False,
        "configure_stdlib_logging": Mock(),
        "configure_loguru_logging": Mock(),
        "install_signal_handlers": Mock(),
        "validate_engine_startup_async": AsyncMock(return_value=SimpleNamespace(ok=True)),
        "_validate_api_key": lambda: False,
        "RUN_MODE": "engine-only",
    }
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(source), "exec"), namespace)
    monkeypatch.setattr("infrastructure.redis_url.get_safe_redis_url", lambda: "fixture-local")
    monkeypatch.setattr("services.engine.runtime_state.threading.Timer", lambda *args: Mock())
    return namespace


@pytest.mark.parametrize("external_probe", [False, True])
def test_partial_storage_startup_failure_closes_owned_resources(entrypoint, monkeypatch, external_probe):
    events = []
    probe = Mock()

    async def probe_start():
        try:
            events.append("probe_started")
            await asyncio.Event().wait()
        finally:
            events.append("probe_drained")

    async def probe_stop():
        assert "probe_drained" in events
        events.append("probe_closed")

    async def initialize():
        events.append("storage_acquired")
        await asyncio.sleep(0)
        raise RuntimeError("controlled partial initialization")

    async def storage_close():
        events.append("storage_closed")

    async def redis_close():
        events.append("redis_closed")

    probe.start, probe.stop = probe_start, probe_stop
    entrypoint.update(
        _health_probe=probe, init_persistent_storage=initialize, shutdown_persistent_storage=storage_close
    )
    monkeypatch.setattr("infrastructure.redis_client.close_pool", redis_close)
    state = EngineRuntimeState()
    with pytest.raises(RuntimeError, match="controlled partial initialization"):
        asyncio.run(entrypoint["main"](health_probe=probe if external_probe else None, runtime_state=state))
    assert events[-2:] == ["storage_closed", "redis_closed"]
    assert ("probe_closed" in events) is not external_probe
    assert state._fatal and not state.ready()
    assert entrypoint["_health_probe"] is probe
    state.cancel_process_deadline()


def test_rejected_bootstrap_does_not_acquire_storage(entrypoint):
    probe = Mock()
    acquire = AsyncMock()
    entrypoint.update(_health_probe=probe, init_persistent_storage=acquire)
    entrypoint["validate_engine_startup_async"].return_value = SimpleNamespace(ok=False)
    state = EngineRuntimeState()
    with pytest.raises(RuntimeError, match="ENGINE_REQUIRED_BOOTSTRAP_FAILED"):
        asyncio.run(entrypoint["main"](health_probe=probe, runtime_state=state))
    acquire.assert_not_awaited()
    assert state._fatal
    state.cancel_process_deadline()


@pytest.mark.parametrize("failure", [False, True])
def test_direct_process_owner_cancels_deadline_after_asyncio_cleanup(entrypoint, failure):
    state = EngineRuntimeState()
    events = []
    entrypoint["EngineRuntimeState"] = lambda: state

    async def main(*, runtime_state):
        assert runtime_state is state
        started = asyncio.Event()

        async def pending_cleanup():
            try:
                started.set()
                await asyncio.Event().wait()
            finally:
                state._deadline.cancel.assert_not_called()
                events.append("asyncio_cleanup")

        asyncio.create_task(pending_cleanup())
        await started.wait()
        state.begin_shutdown(fatal=failure)
        if failure:
            raise RuntimeError("controlled failure")

    entrypoint["main"] = main
    assert entrypoint["run"]() == (1 if failure else 0)
    assert events == ["asyncio_cleanup"]
    state._deadline.cancel.assert_called_once()


@pytest.mark.parametrize("external_state", [False, True])
@pytest.mark.parametrize("cleanup_failed", [False, True])
def test_async_main_releases_only_local_deadline_after_quiescent_cleanup(entrypoint, external_state, cleanup_failed):
    state = EngineRuntimeState()
    entrypoint["EngineRuntimeState"] = lambda: state
    events = []

    async def run_main(probe, tasks, coordinator):
        async def cleanup():
            state._deadline.cancel.assert_not_called()
            events.append("cleanup")
            if cleanup_failed:
                raise RuntimeError("controlled cleanup failure")

        coordinator.register_cleanup("fixture resource", cleanup)

    entrypoint["_run_main"] = run_main
    kwargs = {"health_probe": Mock()}
    if external_state:
        kwargs["runtime_state"] = state
    if cleanup_failed:
        with pytest.raises(RuntimeError, match="controlled cleanup failure"):
            asyncio.run(entrypoint["main"](**kwargs))
    else:
        asyncio.run(entrypoint["main"](**kwargs))
    assert events == ["cleanup"]
    if not external_state and not cleanup_failed:
        state._deadline.cancel.assert_called_once()
    else:
        state._deadline.cancel.assert_not_called()
    # Fixture cleanup only; failed production cleanup must retain the deadline.
    state.cancel_process_deadline()
