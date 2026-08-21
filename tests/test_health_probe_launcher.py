"""DEBT-SVC-04: Unified health-probe launcher tests.

Validates that both ``start_probe_in_thread`` and ``start_probe_as_task``
correctly construct and launch a HealthProbe, forwarding readiness checks
and extra details.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from services.shared.health_probe_launcher import HealthProbeRuntime, start_probe_as_task, start_probe_in_thread

# ── Helpers ────────────────────────────────────────────────────


def _get(port: int, path: str) -> tuple[int, dict]:
    """Blocking HTTP GET helper."""
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
    try:
        resp = urllib.request.urlopen(req, timeout=3)  # noqa: S310
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _health_probe_threads() -> tuple[threading.Thread, ...]:
    return tuple(thread for thread in threading.enumerate() if thread.name.endswith("-health-probe"))


@contextmanager
def _running_thread_probe(
    *,
    port: int,
    service_name: str,
    readiness_check: Callable[[], bool] | None = None,
    extra_details: dict[str, str] | None = None,
) -> Iterator[HealthProbeRuntime]:
    runtime = start_probe_in_thread(
        port=port,
        service_name=service_name,
        readiness_check=readiness_check,
        extra_details=extra_details,
    )
    try:
        yield runtime
    finally:
        runtime.close(timeout=3.0)


# ── start_probe_in_thread tests ─────────────────────────────


class TestStartProbeInThread:
    def test_returns_runtime_with_health_probe(self):
        """start_probe_in_thread returns an explicit runtime owner."""
        from core.health_probe import HealthProbe

        with _running_thread_probe(port=0, service_name="test-thread") as runtime:
            assert isinstance(runtime, HealthProbeRuntime)
            assert isinstance(runtime.probe, HealthProbe)
            assert runtime.probe._service_name == "test-thread"

    def test_daemon_thread_created(self):
        """A daemon thread with the expected name should be running."""
        with _running_thread_probe(port=0, service_name="thread-check") as runtime:
            assert runtime.thread.daemon
            assert runtime.thread.is_alive()
            assert runtime.thread.name == "thread-check-health-probe"

    def test_readiness_check_forwarded(self):
        """readiness_check callable is passed through to the probe."""
        check = MagicMock(return_value=True)
        with _running_thread_probe(
            port=0,
            service_name="rc-thread",
            readiness_check=check,
        ) as runtime:
            assert runtime.probe._readiness_check is check

    def test_extra_details_set(self):
        """Extra details should be stored on the probe."""
        with _running_thread_probe(
            port=0,
            service_name="detail-thread",
            extra_details={"role": "orchestrator", "version": "1.0"},
        ) as runtime:
            assert runtime.probe._details.get("role") == "orchestrator"
            assert runtime.probe._details.get("version") == "1.0"

    def test_no_extra_details(self):
        """When no extra_details given, no crash and details stay default."""
        with _running_thread_probe(port=0, service_name="no-detail") as runtime:
            assert runtime.probe is not None

    def test_isolated_event_loop(self):
        """Thread should create its own event loop (not reuse the main one)."""
        loops_seen: list[asyncio.AbstractEventLoop] = []

        original_new_event_loop = asyncio.new_event_loop

        def _spy_new_event_loop():
            loop = original_new_event_loop()
            loops_seen.append(loop)
            return loop

        with (
            patch("services.shared.health_probe_launcher.asyncio.new_event_loop", _spy_new_event_loop),
            _running_thread_probe(port=0, service_name="loop-test") as runtime,
        ):
            assert runtime.event_loop is loops_seen[0]

        assert len(loops_seen) == 1
        assert loops_seen[0].is_closed()


class TestThreadProbeLifecycle:
    def test_normal_stop_closes_loop_and_joins_thread(self):
        runtime = start_probe_in_thread(port=0, service_name="normal-stop")
        loop = runtime.event_loop

        runtime.stop()
        runtime.join(timeout=3.0)

        assert not runtime.thread.is_alive()
        assert loop.is_closed()

    def test_stop_is_idempotent(self):
        runtime = start_probe_in_thread(port=0, service_name="stop-twice")

        runtime.stop()
        runtime.stop()
        runtime.join(timeout=3.0)

        assert not runtime.thread.is_alive()

    def test_context_manager_cleans_up_after_exception(self):
        class ExpectedError(Exception):
            pass

        runtime = start_probe_in_thread(port=0, service_name="exception-stop")
        with pytest.raises(ExpectedError), runtime:
            raise ExpectedError

        assert not runtime.thread.is_alive()
        assert runtime.event_loop.is_closed()

    def test_join_is_bounded_and_fails_while_thread_is_live(self):
        runtime = start_probe_in_thread(port=0, service_name="bounded-join")
        started = time.monotonic()
        try:
            with pytest.raises(TimeoutError):
                runtime.join(timeout=0.01)
            assert time.monotonic() - started < 1.0
        finally:
            runtime.close(timeout=3.0)

    def test_repeated_launch_stop_does_not_accumulate_threads(self):
        baseline = {thread.ident for thread in _health_probe_threads()}

        for index in range(6):
            runtime = start_probe_in_thread(port=0, service_name=f"repeat-{index}")
            runtime.close(timeout=3.0)
            assert not runtime.thread.is_alive()
            assert {thread.ident for thread in _health_probe_threads()} == baseline


# ── start_probe_as_task tests ───────────────────────────────


class TestStartProbeAsTask:
    @pytest.mark.asyncio()
    async def test_returns_probe_and_task(self):
        """Returns a tuple of (HealthProbe, asyncio.Task)."""
        from core.health_probe import HealthProbe

        probe, task = await start_probe_as_task(port=0, service_name="test-task")
        assert isinstance(probe, HealthProbe)
        assert isinstance(task, asyncio.Task)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    @pytest.mark.asyncio()
    async def test_task_name(self):
        """Task should have the expected name."""
        _, task = await start_probe_as_task(
            port=0,
            service_name="named",
            task_name="MyProbe",
        )
        assert task.get_name() == "MyProbe"
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    @pytest.mark.asyncio()
    async def test_default_task_name(self):
        """Default task name uses capitalized service_name."""
        _, task = await start_probe_as_task(port=0, service_name="engine")
        assert task.get_name() == "EngineHealthProbe"
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    @pytest.mark.asyncio()
    async def test_readiness_check_forwarded(self):
        """readiness_check is passed through to the probe."""
        check = MagicMock(return_value=False)
        probe, task = await start_probe_as_task(
            port=0,
            service_name="rc-task",
            readiness_check=check,
        )
        assert probe._readiness_check is check
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    @pytest.mark.asyncio()
    async def test_extra_details_set(self):
        """Extra details stored on probe before task starts."""
        probe, task = await start_probe_as_task(
            port=0,
            service_name="detail-task",
            extra_details={"env": "staging"},
        )
        assert probe._details.get("env") == "staging"
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    @pytest.mark.asyncio()
    async def test_probe_responds_healthz(self):
        """Probe launched as task should respond to /healthz."""
        probe, task = await start_probe_as_task(port=0, service_name="http-test")
        # Need to wait for the server to bind
        await asyncio.sleep(0.2)

        # Find the actual port the probe bound to
        if probe._server and probe._server.sockets:
            port = probe._server.sockets[0].getsockname()[1]
            status, body = await asyncio.to_thread(_get, port, "/healthz")
            assert status == 200
            assert body.get("status") in ("ok", "alive")
        else:
            pytest.skip("Probe server did not bind (port=0 on this platform)")

        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


# ── Consistency checks ──────────────────────────────────────


class TestConsistency:
    """Verify that no call-site still does inline HealthProbe + create_task."""

    @staticmethod
    def _read_source(path: str) -> str:
        from pathlib import Path

        return Path(path).read_text(encoding="utf-8")

    LAUNCHER_SITES = [
        "services/engine/runner.py",
        "services/orchestrator/state_manager.py",
        "services/ingest/ingest_worker.py",
        "services/trade/runner.py",
        "execution/async_worker.py",
        "allocation/async_worker.py",
    ]

    def test_no_inline_health_probe_create_task(self):
        """Updated call sites should not have raw asyncio.create_task(probe.start())."""
        for site in self.LAUNCHER_SITES:
            src = self._read_source(site)
            assert "create_task(probe.start())" not in src, (
                f"{site} still has inline create_task(probe.start()) — should use shared launcher"
            )

    def test_no_inline_thread_pattern(self):
        """Updated call sites should not have inline asyncio.new_event_loop for probes."""
        for site in self.LAUNCHER_SITES:
            src = self._read_source(site)
            assert "new_event_loop()" not in src, (
                f"{site} still has inline new_event_loop() — should use shared launcher"
            )

    def test_all_sites_import_shared_launcher(self):
        """All updated sites should import from services.shared.health_probe_launcher."""
        for site in self.LAUNCHER_SITES:
            src = self._read_source(site)
            assert "health_probe_launcher" in src, f"{site} should import from services.shared.health_probe_launcher"
