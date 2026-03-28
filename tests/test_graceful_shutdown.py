"""Tests for startup/graceful_shutdown.py — GracefulShutdown coordinator.

Verifies:
- Task cancellation + drain with timeout
- Registered cleanup execution order
- Cleanup error isolation (one failure doesn't block others)
- drain_worker_tasks for in-flight message processing
- Orchestrator SHUTDOWN state publication on exit
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from startup.graceful_shutdown import GracefulShutdown

# ── Helpers ────────────────────────────────────────────────────────

async def _slow_task(seconds: float = 60.0) -> None:
    """Simulates a long-running task that can be cancelled."""
    await asyncio.sleep(seconds)


async def _fast_task() -> None:
    """Completes immediately."""
    await asyncio.sleep(0)


async def _cancel_aware_task() -> None:
    """Task that does cleanup work when cancelled."""
    try:
        await asyncio.sleep(60)
    except asyncio.CancelledError:
        await asyncio.sleep(0.01)  # simulate cleanup
        raise


# ── GracefulShutdown.shutdown() ───────────────────────────────────

class TestShutdownSequence:
    async def test_shutdown_cancels_running_tasks(self) -> None:
        gs = GracefulShutdown(drain_timeout=2.0)
        task = asyncio.create_task(_slow_task())
        await asyncio.sleep(0)  # let task start

        await gs.shutdown([task])
        assert task.cancelled() or task.done()

    async def test_shutdown_handles_already_done_tasks(self) -> None:
        gs = GracefulShutdown(drain_timeout=1.0)
        task = asyncio.create_task(_fast_task())
        await task  # let it finish

        await gs.shutdown([task])
        assert task.done()

    async def test_shutdown_runs_cleanups_in_order(self) -> None:
        gs = GracefulShutdown(drain_timeout=1.0)
        call_order: list[str] = []

        async def cleanup_a() -> None:
            call_order.append("a")

        async def cleanup_b() -> None:
            call_order.append("b")

        gs.register_cleanup("first", cleanup_a)
        gs.register_cleanup("second", cleanup_b)

        await gs.shutdown([])
        assert call_order == ["a", "b"]

    async def test_cleanup_error_does_not_block_others(self) -> None:
        gs = GracefulShutdown(drain_timeout=1.0)
        call_order: list[str] = []

        async def failing_cleanup() -> None:
            call_order.append("fail")
            raise RuntimeError("intentional")

        async def ok_cleanup() -> None:
            call_order.append("ok")

        gs.register_cleanup("broken", failing_cleanup)
        gs.register_cleanup("healthy", ok_cleanup)

        await gs.shutdown([])
        assert call_order == ["fail", "ok"]

    async def test_shutdown_with_empty_task_list(self) -> None:
        gs = GracefulShutdown(drain_timeout=1.0)
        cleanup = AsyncMock()
        gs.register_cleanup("pool", cleanup)

        await gs.shutdown([])
        cleanup.assert_awaited_once()

    async def test_shutdown_respects_drain_timeout(self) -> None:
        """Tasks that exceed drain timeout get force-cancelled."""
        gs = GracefulShutdown(drain_timeout=0.1)
        task = asyncio.create_task(_cancel_aware_task())
        await asyncio.sleep(0)

        await gs.shutdown([task])
        assert task.done()


# ── GracefulShutdown.drain_worker_tasks() ─────────────────────────

class TestDrainWorkerTasks:
    async def test_drain_completes_finished_tasks(self) -> None:
        gs = GracefulShutdown(drain_timeout=2.0)
        task = asyncio.create_task(_fast_task())
        await task

        await gs.drain_worker_tasks([task], label="test")
        assert task.done()

    async def test_drain_waits_for_active_tasks(self) -> None:
        gs = GracefulShutdown(drain_timeout=2.0)
        result: list[str] = []

        async def worker() -> None:
            await asyncio.sleep(0.05)
            result.append("done")

        task = asyncio.create_task(worker())
        await gs.drain_worker_tasks([task], label="test")
        assert result == ["done"]

    async def test_drain_cancels_on_timeout(self) -> None:
        gs = GracefulShutdown(drain_timeout=0.1)
        task = asyncio.create_task(_slow_task())
        await asyncio.sleep(0)

        await gs.drain_worker_tasks([task], label="test")
        assert task.cancelled() or task.done()

    async def test_drain_noop_on_empty_list(self) -> None:
        gs = GracefulShutdown(drain_timeout=1.0)
        await gs.drain_worker_tasks([], label="test")  # should not raise

    async def test_drain_filters_done_tasks(self) -> None:
        gs = GracefulShutdown(drain_timeout=1.0)
        done_task = asyncio.create_task(_fast_task())
        await done_task

        active_result: list[str] = []

        async def active_worker() -> None:
            await asyncio.sleep(0.05)
            active_result.append("completed")

        active_task = asyncio.create_task(active_worker())
        await gs.drain_worker_tasks([done_task, active_task], label="test")
        assert active_result == ["completed"]


# ── Orchestrator SHUTDOWN state publication ───────────────────────

class TestOrchestratorShutdownState:
    def test_run_forever_publishes_shutdown_on_exit(self) -> None:
        """StateManager.run_forever() should publish SHUTDOWN event before closing."""
        from services.orchestrator.state_manager import StateManager

        mock_redis = MagicMock()
        mock_pubsub = MagicMock()
        mock_redis.pubsub.return_value = mock_pubsub
        mock_pubsub.get_message.return_value = None
        mock_redis.mget.return_value = [None, None]
        mock_pipe = MagicMock()
        mock_redis.pipeline.return_value = mock_pipe

        sm = StateManager(redis_client=mock_redis)
        sm.configure_intervals(compliance_interval_sec=999, heartbeat_interval_sec=999)

        call_count = 0
        original_process = sm.process_once

        def limited_process(now: float | None = None) -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise KeyboardInterrupt("test exit")
            original_process(now)

        sm.process_once = limited_process

        with pytest.raises(KeyboardInterrupt):
            sm.run_forever()

        # Verify SHUTDOWN was published (last pipeline call before close)
        publish_calls = [
            c for c in mock_redis.pipeline.return_value.publish.call_args_list
        ]
        # At least one publish should contain "SHUTDOWN"
        shutdown_published = any(
            "SHUTDOWN" in str(args) for args in publish_calls
        )
        assert shutdown_published, f"Expected SHUTDOWN publish, got: {publish_calls}"

    def test_run_forever_closes_pubsub_after_shutdown(self) -> None:
        """Pubsub should be closed even if SHUTDOWN publish fails."""
        from services.orchestrator.state_manager import StateManager

        mock_redis = MagicMock()
        mock_pubsub = MagicMock()
        mock_redis.pubsub.return_value = mock_pubsub
        mock_pubsub.get_message.return_value = None
        mock_redis.mget.return_value = [None, None]
        mock_pipe = MagicMock()
        mock_redis.pipeline.return_value = mock_pipe

        sm = StateManager(redis_client=mock_redis)
        sm.configure_intervals(compliance_interval_sec=999, heartbeat_interval_sec=999)

        call_count = 0

        def limited_process(now: float | None = None) -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                # NOW make pipeline fail — after BOOT publish succeeded
                mock_pipe.execute.side_effect = ConnectionError("redis down")
                raise KeyboardInterrupt("test exit")

        sm.process_once = limited_process

        with pytest.raises(KeyboardInterrupt):
            sm.run_forever()

        # Pubsub must be closed even when publish_state("SHUTDOWN") fails
        mock_pubsub.close.assert_called_once()
