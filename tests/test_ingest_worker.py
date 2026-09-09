"""Tests for services/ingest/ingest_worker.py (SVC-BUG-07).

Validates that ingest_service is imported in the main event-loop thread,
not in a thread-pool executor which risks import-lock deadlocks and
async resource creation on the wrong thread.
"""

from __future__ import annotations

import ast
import asyncio
import sys
import textwrap
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


def _parse_bootstrap_function() -> ast.AsyncFunctionDef:
    """Parse the _bootstrap_and_run function from ingest_worker.py."""
    import services.ingest.ingest_worker as mod

    source = textwrap.dedent(open(mod.__file__, encoding="utf-8").read())  # noqa: SIM115
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_bootstrap_and_run":
            return node
    pytest.fail("_bootstrap_and_run not found in ingest_worker.py")


class TestIngestWorkerImportSafety:
    def test_no_run_in_executor_for_import(self):
        """ingest_service must NOT be imported via run_in_executor."""
        func = _parse_bootstrap_function()
        for node in ast.walk(func):
            if isinstance(node, ast.Attribute) and node.attr == "run_in_executor":
                pytest.fail(
                    "run_in_executor found in _bootstrap_and_run — "
                    "ingest_service must be imported in the main thread "
                    "to avoid import-lock deadlocks and wrong-thread "
                    "async resource creation"
                )

    def test_no_importlib_import_module(self):
        """importlib.import_module should not be used for ingest_service."""
        func = _parse_bootstrap_function()
        for node in ast.walk(func):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "import_module"
            ):
                pytest.fail(
                    "importlib.import_module found in _bootstrap_and_run — "
                    "use a direct `import ingest_service` statement instead"
                )

    def test_ingest_service_imported_directly(self):
        """Verify ingest_service is imported with a direct import statement."""
        func = _parse_bootstrap_function()
        found = False
        for node in ast.walk(func):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "ingest_service":
                        found = True
        assert found, (
            "Expected `import ingest_service` in _bootstrap_and_run — "
            "direct import keeps it on the main event-loop thread"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["crash", "early_return", "shutdown", "probe_loss"])
async def test_bootstrap_required_service_and_probe_are_supervised(monkeypatch, outcome):
    from services.ingest import ingest_worker
    from services.shared import health_probe_launcher

    state = {"alive": True}
    probe = SimpleNamespace(
        set_detail=lambda *args: None,
        set_alive=lambda alive: state.update(alive=alive),
        stop=AsyncMock(),
    )
    shutdown = asyncio.Event()
    drained = asyncio.Event()

    async def start_probe(**kwargs):
        assert kwargs["readiness_check"]() is False

        async def probe_loop():
            if outcome != "probe_loss":
                await asyncio.Event().wait()

        return probe, asyncio.create_task(probe_loop())

    async def run_main(**kwargs):
        assert kwargs["_bootstrap_probe"] is probe
        try:
            if outcome == "crash":
                raise RuntimeError("test_ingest_crash")
            if outcome == "probe_loss":
                await asyncio.Event().wait()
            if outcome == "shutdown":
                shutdown.set()
        finally:
            drained.set()

    monkeypatch.setattr(health_probe_launcher, "start_probe_as_task", start_probe)
    monkeypatch.setitem(sys.modules, "ingest_service", SimpleNamespace(main=run_main, _shutdown_event=shutdown))
    if outcome == "shutdown":
        await ingest_worker._bootstrap_and_run()
    else:
        with pytest.raises(RuntimeError):
            await ingest_worker._bootstrap_and_run()
    assert drained.is_set()
    assert state["alive"] is False
    probe.stop.assert_awaited_once()
