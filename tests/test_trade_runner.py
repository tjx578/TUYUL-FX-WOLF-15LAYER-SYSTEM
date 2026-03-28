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


@pytest.mark.asyncio
async def test_probe_task_reference_stored() -> None:
    """Health probe task must be stored to prevent GC collection."""
    probe = _make_probe_mock()
    tasks_created: list[asyncio.Task[None]] = []
    original_create_task = asyncio.create_task

    def _tracking_create_task(*args: Any, **kwargs: Any) -> asyncio.Task[None]:
        t = original_create_task(*args, **kwargs)
        tasks_created.append(t)
        return t

    async def _instant_worker() -> None:
        return

    with (
        patch("services.trade.runner.HealthProbe", return_value=probe),
        patch("asyncio.create_task", side_effect=_tracking_create_task),
        patch("allocation.async_worker._main", new=_instant_worker),
        patch("execution.async_worker._main", new=_instant_worker),
    ):
        from services.trade.runner import _main

        await _main()

    # At least 3 tasks: probe + alloc + exec — all stored as local vars.
    assert len(tasks_created) >= 3
    probe_task = tasks_created[0]
    assert probe_task.get_name() == "TradeHealthProbe"


@pytest.mark.asyncio
async def test_worker_crash_marks_unhealthy() -> None:
    """When a worker crashes, readiness_check must return False."""
    probe = _make_probe_mock()
    captured_readiness = None

    def _capture_probe(**kwargs: Any) -> AsyncMock:
        nonlocal captured_readiness
        captured_readiness = kwargs.get("readiness_check")
        return probe

    async def _crash_worker() -> None:
        raise RuntimeError("boom")

    async def _ok_worker() -> None:
        await asyncio.sleep(10)

    with (
        patch("services.trade.runner.HealthProbe", side_effect=_capture_probe),
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

    probe = _make_probe_mock()
    env_at_import: dict[str, str | None] = {}

    async def _checking_worker() -> None:
        env_at_import["ALLOC_HEALTH_PORT"] = os.environ.get("ALLOC_HEALTH_PORT")
        env_at_import["EXEC_HEALTH_PORT"] = os.environ.get("EXEC_HEALTH_PORT")

    with (
        patch("services.trade.runner.HealthProbe", return_value=probe),
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
    probe = _make_probe_mock()

    async def _instant_worker() -> None:
        return

    with (
        patch("services.trade.runner.HealthProbe", return_value=probe),
        patch("allocation.async_worker._main", new=_instant_worker),
        patch("execution.async_worker._main", new=_instant_worker),
    ):
        from services.trade.runner import _main

        await _main()

    probe.stop.assert_awaited_once()
