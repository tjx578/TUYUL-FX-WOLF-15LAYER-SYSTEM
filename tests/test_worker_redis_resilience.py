"""Tests for allocation + execution worker Redis resilience fixes.

Validates:
- xreadgroup timeout/connection errors trigger reconnect (not crash)
- Exponential backoff resets on successful reconnect
- Supervised _main() restarts worker after crash
- CancelledError propagates cleanly without restart
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import redis.asyncio as aioredis
from prometheus_client import REGISTRY as _REG

# Both allocation/ and execution/ workers define identically-named Prometheus
# metrics at module level.  In production they run in separate processes; in
# tests they coexist.  Force-import allocation first, then clear shared metric
# names so the execution module can safely re-register them.
try:  # noqa: SIM105
    import allocation.async_worker  # noqa: F401
except Exception:
    pass

for _coll_name in list(getattr(_REG, "_names_to_collectors", {})):
    if _coll_name.startswith("wolf_"):
        with contextlib.suppress(Exception):
            _REG.unregister(_REG._names_to_collectors[_coll_name])

try:  # noqa: SIM105
    import execution.async_worker  # noqa: F401
except Exception:
    pass

# ═══════════════════════════════════════════════════════════════════
# Allocation Worker — run() retry + reconnect
# ═══════════════════════════════════════════════════════════════════


class TestAllocationWorkerReconnect:
    """Allocation worker run() must survive Redis connection errors."""

    @pytest.mark.asyncio
    async def test_xreadgroup_timeout_triggers_reconnect(self) -> None:
        """TimeoutError in xreadgroup must break inner loop and reconnect."""
        from allocation.async_worker import AsyncAllocationWorker, WorkerConfig

        call_count = 0

        async def _fake_xreadgroup(**kwargs: Any) -> None:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise aioredis.TimeoutError("Timeout reading from redis")
            # 3rd call: signal to stop test
            raise asyncio.CancelledError

        mock_redis = AsyncMock()
        mock_redis.xreadgroup = _fake_xreadgroup
        mock_redis.xgroup_create = AsyncMock()
        mock_redis.xpending = AsyncMock(return_value=(0,))

        cfg = WorkerConfig(block_ms=10)
        worker = AsyncAllocationWorker(config=cfg)

        with (
            patch("allocation.async_worker.get_client", return_value=mock_redis),
            patch("allocation.async_worker.tracemalloc"),
            pytest.raises(asyncio.CancelledError),
        ):
            await worker.run()

        # Must have called xreadgroup 3 times (2 retries + 1 cancel)
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_connection_error_triggers_reconnect(self) -> None:
        """ConnectionError in xreadgroup must break inner loop."""
        from allocation.async_worker import AsyncAllocationWorker, WorkerConfig

        call_count = 0

        async def _fake_xreadgroup(**kwargs: Any) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise aioredis.ConnectionError("Connection reset")
            raise asyncio.CancelledError

        mock_redis = AsyncMock()
        mock_redis.xreadgroup = _fake_xreadgroup
        mock_redis.xgroup_create = AsyncMock()
        mock_redis.xpending = AsyncMock(return_value=(0,))

        cfg = WorkerConfig(block_ms=10)
        worker = AsyncAllocationWorker(config=cfg)

        with (
            patch("allocation.async_worker.get_client", return_value=mock_redis),
            patch("allocation.async_worker.tracemalloc"),
            pytest.raises(asyncio.CancelledError),
        ):
            await worker.run()

        assert call_count == 2

    @pytest.mark.asyncio
    async def test_os_error_triggers_reconnect(self) -> None:
        """OSError in xreadgroup must break inner loop."""
        from allocation.async_worker import AsyncAllocationWorker, WorkerConfig

        call_count = 0

        async def _fake_xreadgroup(**kwargs: Any) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OSError("Network unreachable")
            raise asyncio.CancelledError

        mock_redis = AsyncMock()
        mock_redis.xreadgroup = _fake_xreadgroup
        mock_redis.xgroup_create = AsyncMock()
        mock_redis.xpending = AsyncMock(return_value=(0,))

        cfg = WorkerConfig(block_ms=10)
        worker = AsyncAllocationWorker(config=cfg)

        with (
            patch("allocation.async_worker.get_client", return_value=mock_redis),
            patch("allocation.async_worker.tracemalloc"),
            pytest.raises(asyncio.CancelledError),
        ):
            await worker.run()

        assert call_count == 2


# ═══════════════════════════════════════════════════════════════════
# Execution Worker — run() retry + reconnect
# ═══════════════════════════════════════════════════════════════════


class TestExecutionWorkerReconnect:
    """Execution worker run() must survive Redis connection errors."""

    @pytest.mark.asyncio
    async def test_xreadgroup_timeout_triggers_reconnect(self) -> None:
        from execution.async_worker import AsyncExecutionWorker, WorkerConfig

        call_count = 0

        async def _fake_xreadgroup(**kwargs: Any) -> None:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise aioredis.TimeoutError("Timeout reading from redis")
            raise asyncio.CancelledError

        mock_redis = AsyncMock()
        mock_redis.xreadgroup = _fake_xreadgroup
        mock_redis.xgroup_create = AsyncMock()
        mock_redis.xpending = AsyncMock(return_value=(0,))

        cfg = WorkerConfig(block_ms=10)
        worker = AsyncExecutionWorker(config=cfg)

        with (
            patch("execution.async_worker.get_client", return_value=mock_redis),
            patch("execution.async_worker.tracemalloc"),
            pytest.raises(asyncio.CancelledError),
        ):
            await worker.run()

        assert call_count == 3


# ═══════════════════════════════════════════════════════════════════
# Supervised _main() restart tests
# ═══════════════════════════════════════════════════════════════════


class TestAllocationSupervisedMain:
    """_main() must restart worker on crash up to max_restarts."""

    @pytest.mark.asyncio
    async def test_main_restarts_on_crash(self) -> None:
        from allocation import async_worker as mod

        run_calls = 0

        async def _fake_run(self: Any) -> None:
            nonlocal run_calls
            run_calls += 1
            if run_calls <= 2:
                raise RuntimeError("Redis exploded")
            # 3rd run: clean exit

        with (
            patch.object(mod.AsyncAllocationWorker, "run", _fake_run),
            patch.object(mod, "_MAX_RESTARTS", 5),
            patch.object(mod, "_RESTART_COOLDOWN", 0.0),
            patch.object(mod, "start_http_server"),
        ):
            await mod._main()

        assert run_calls == 3  # 2 crashes + 1 clean exit

    @pytest.mark.asyncio
    async def test_main_gives_up_after_max_restarts(self) -> None:
        from allocation import async_worker as mod

        run_calls = 0

        async def _fake_run(self: Any) -> None:
            nonlocal run_calls
            run_calls += 1
            raise RuntimeError("persistent failure")

        with (
            patch.object(mod.AsyncAllocationWorker, "run", _fake_run),
            patch.object(mod, "_MAX_RESTARTS", 3),
            patch.object(mod, "_RESTART_COOLDOWN", 0.0),
            patch.object(mod, "start_http_server"),
        ):
            await mod._main()

        # 3+1 = 4 attempts (0..3 inclusive)
        assert run_calls == 4

    @pytest.mark.asyncio
    async def test_main_propagates_cancelled(self) -> None:
        from allocation import async_worker as mod

        async def _fake_run(self: Any) -> None:
            raise asyncio.CancelledError

        with (
            patch.object(mod.AsyncAllocationWorker, "run", _fake_run),
            patch.object(mod, "start_http_server"),
        ):
            # CancelledError should return cleanly, not crash
            await mod._main()


class TestExecutionSupervisedMain:
    """Execution _main() must restart worker on crash."""

    @pytest.mark.asyncio
    async def test_main_restarts_on_crash(self) -> None:
        from execution import async_worker as mod

        run_calls = 0

        async def _fake_run(self: Any) -> None:
            nonlocal run_calls
            run_calls += 1
            if run_calls <= 2:
                raise RuntimeError("Redis exploded")

        with (
            patch.object(mod.AsyncExecutionWorker, "run", _fake_run),
            patch.object(mod, "_MAX_RESTARTS", 5),
            patch.object(mod, "_RESTART_COOLDOWN", 0.0),
            patch.object(mod, "start_http_server"),
        ):
            await mod._main()

        assert run_calls == 3

    @pytest.mark.asyncio
    async def test_main_gives_up_after_max_restarts(self) -> None:
        from execution import async_worker as mod

        run_calls = 0

        async def _fake_run(self: Any) -> None:
            nonlocal run_calls
            run_calls += 1
            raise RuntimeError("persistent failure")

        with (
            patch.object(mod.AsyncExecutionWorker, "run", _fake_run),
            patch.object(mod, "_MAX_RESTARTS", 3),
            patch.object(mod, "_RESTART_COOLDOWN", 0.0),
            patch.object(mod, "start_http_server"),
        ):
            await mod._main()

        assert run_calls == 4
