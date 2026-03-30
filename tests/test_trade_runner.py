"""Tests for services.trade.runner — SVC-BUG-03 fixes."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def _env_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRADE_HEALTH_PORT", "19090")
    monkeypatch.delenv("PORT", raising=False)


def _make_probe_mock() -> AsyncMock:
    probe = AsyncMock()
    probe.start = AsyncMock(return_value=None)
    probe.stop = AsyncMock(return_value=None)
    return probe


async def _fake_start_probe_as_task(
    *,
    port: int,
    service_name: str,
    readiness_check: Any = None,
    extra_details: Any = None,
    task_name: str | None = None,
) -> tuple[AsyncMock, asyncio.Task[None]]:
    """Stand-in for start_probe_as_task that returns a mock probe + real task."""
    probe = _make_probe_mock()
    probe._readiness_check = readiness_check
    task = asyncio.create_task(asyncio.sleep(999), name=task_name or "TestProbe")
    return probe, task


@pytest.mark.asyncio
async def test_probe_task_reference_stored() -> None:
    """Health probe task must be stored to prevent GC collection."""
    tasks_created: list[asyncio.Task[None]] = []
    original_create_task = asyncio.create_task

    def _tracking_create_task(*args: Any, **kwargs: Any) -> asyncio.Task[None]:
        t = original_create_task(*args, **kwargs)
        tasks_created.append(t)
        return t

    async def _instant_worker() -> None:
        return

    with (
        patch(
            "services.shared.health_probe_launcher.start_probe_as_task",
            side_effect=_fake_start_probe_as_task,
        ),
        patch("asyncio.create_task", side_effect=_tracking_create_task),
        patch("allocation.async_worker._main", new=_instant_worker),
        patch("execution.async_worker._main", new=_instant_worker),
    ):
        from services.trade.runner import _main

        await _main()

    # At least 2 worker tasks: alloc + exec (probe is via shared launcher)
    assert len(tasks_created) >= 2


@pytest.mark.asyncio
async def test_worker_crash_marks_unhealthy() -> None:
    """When a worker crashes, readiness_check must return False."""
    captured_readiness = None

    async def _capturing_start_probe(
        *,
        port: int,
        service_name: str,
        readiness_check: Any = None,
        extra_details: Any = None,
        task_name: str | None = None,
    ) -> tuple[AsyncMock, asyncio.Task[None]]:
        nonlocal captured_readiness
        captured_readiness = readiness_check
        probe = _make_probe_mock()
        task = asyncio.create_task(asyncio.sleep(999), name=task_name or "TestProbe")
        return probe, task

    async def _crash_worker() -> None:
        raise RuntimeError("boom")

    async def _ok_worker() -> None:
        await asyncio.sleep(10)

    with (
        patch(
            "services.shared.health_probe_launcher.start_probe_as_task",
            side_effect=_capturing_start_probe,
        ),
        patch("allocation.async_worker._main", new=_crash_worker),
        patch("execution.async_worker._main", new=_ok_worker),
    ):
        from services.trade.runner import _main

        with pytest.raises(RuntimeError, match="boom"):
            await _main()

    assert captured_readiness is not None
    assert captured_readiness() is False


@pytest.mark.asyncio
async def test_env_vars_set_before_worker_import() -> None:
    """ALLOC/EXEC_HEALTH_PORT env vars must be set before workers are imported."""
    import os

    env_at_import: dict[str, str | None] = {}

    async def _checking_worker() -> None:
        env_at_import["ALLOC_HEALTH_PORT"] = os.environ.get("ALLOC_HEALTH_PORT")
        env_at_import["EXEC_HEALTH_PORT"] = os.environ.get("EXEC_HEALTH_PORT")

    with (
        patch(
            "services.shared.health_probe_launcher.start_probe_as_task",
            side_effect=_fake_start_probe_as_task,
        ),
        patch("allocation.async_worker._main", new=_checking_worker),
        patch("execution.async_worker._main", new=_checking_worker),
    ):
        from services.trade.runner import _main

        await _main()

    assert env_at_import["ALLOC_HEALTH_PORT"] == "19091"
    assert env_at_import["EXEC_HEALTH_PORT"] == "19092"


@pytest.mark.asyncio
async def test_probe_stopped_in_finally() -> None:
    """Probe.stop() must be called even on normal exit."""
    probes_created: list[AsyncMock] = []

    async def _tracking_start_probe(
        *,
        port: int,
        service_name: str,
        readiness_check: Any = None,
        extra_details: Any = None,
        task_name: str | None = None,
    ) -> tuple[AsyncMock, asyncio.Task[None]]:
        probe = _make_probe_mock()
        probes_created.append(probe)
        task = asyncio.create_task(asyncio.sleep(999), name=task_name or "TestProbe")
        return probe, task

    async def _instant_worker() -> None:
        return

    with (
        patch(
            "services.shared.health_probe_launcher.start_probe_as_task",
            side_effect=_tracking_start_probe,
        ),
        patch("allocation.async_worker._main", new=_instant_worker),
        patch("execution.async_worker._main", new=_instant_worker),
    ):
        from services.trade.runner import _main

        await _main()

    assert len(probes_created) == 1
    probes_created[0].stop.assert_awaited_once()
