"""Engine opt-in shutdown refuses to close pools used by live tasks."""

import asyncio

import pytest

from startup.graceful_shutdown import GracefulShutdown, ShutdownCleanupTimeoutError, ShutdownDrainTimeoutError


async def resistant_worker(started, release, events):
    started.set()
    while not release.is_set():
        try:
            await release.wait()
        except asyncio.CancelledError:
            events.append("cancel-received")
    events.append("writer-stopped")


@pytest.mark.parametrize("strict", [False, True])
def test_strict_drain_timeout_never_calls_pool_cleanup(strict):
    async def run():
        events = []
        started, release = asyncio.Event(), asyncio.Event()
        writer = asyncio.create_task(resistant_worker(started, release, events))
        await started.wait()
        gs = GracefulShutdown(drain_timeout=0.01, require_quiescent=strict)

        async def pool_close():
            events.append("pool-close")

        gs.register_cleanup("pool", pool_close)
        try:
            expected = ShutdownDrainTimeoutError if strict else RuntimeError
            with pytest.raises(expected):
                await gs.shutdown([writer])
            assert not writer.done()
            assert "pool-close" not in events
        finally:
            release.set()
            await asyncio.wait_for(writer, timeout=1)
        assert events[-1] == "writer-stopped"

    asyncio.run(run())


def test_cooperative_writer_stops_before_ordered_pool_cleanups():
    async def run():
        events = []
        started = asyncio.Event()

        async def writer():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                events.append("writer-stopped")

        async def redis_close():
            events.append("redis-close")

        async def postgres_close():
            events.append("postgres-close")

        task = asyncio.create_task(writer())
        await started.wait()
        gs = GracefulShutdown(drain_timeout=0.1, require_quiescent=True)
        gs.register_cleanup("redis", redis_close)
        gs.register_cleanup("postgres", postgres_close)
        await gs.shutdown([task])
        assert task.done()
        assert events == ["writer-stopped", "redis-close", "postgres-close"]

    asyncio.run(run())


@pytest.mark.parametrize("resist_cancellation", [False, True])
def test_cleanup_timeout_propagates_without_waiting_for_resistant_cleanup(resist_cancellation):
    async def run():
        events = []
        release = asyncio.Event()
        gs = GracefulShutdown(drain_timeout=0.01, require_quiescent=True)

        async def slow_cleanup():
            while not release.is_set():
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    if not resist_cancellation:
                        raise
            events.append("cleanup-stopped")

        async def next_cleanup():
            events.append("next-cleanup")

        gs.register_cleanup("slow", slow_cleanup)
        gs.register_cleanup("next", next_cleanup)
        owned = []
        try:
            with pytest.raises(ShutdownCleanupTimeoutError, match="CLEANUP_TIMEOUT"):
                await asyncio.wait_for(gs.shutdown([]), timeout=0.5)
            owned = list(gs._cleanup_tasks)
            assert "next-cleanup" not in events
        finally:
            owned.extend(task for task in gs._cleanup_tasks if task not in owned)
            release.set()
            if owned:
                await asyncio.wait_for(asyncio.gather(*owned, return_exceptions=True), timeout=1)
        assert not gs._cleanup_tasks

    asyncio.run(run())


def test_strict_cleanup_failure_propagates_and_stops_later_cleanup():
    async def run():
        events = []
        gs = GracefulShutdown(drain_timeout=0.1, require_quiescent=True)

        async def broken():
            raise RuntimeError("fixture-cleanup-error")

        async def later():
            events.append("later")

        gs.register_cleanup("broken", broken)
        gs.register_cleanup("later", later)
        with pytest.raises(RuntimeError, match="fixture-cleanup-error"):
            await gs.shutdown([])
        assert events == []

    asyncio.run(run())


def test_default_cleanup_error_preserves_legacy_continue_behavior():
    async def run():
        events = []
        gs = GracefulShutdown(drain_timeout=0.1)

        async def broken():
            raise RuntimeError("legacy fixture")

        async def later():
            events.append("later")

        gs.register_cleanup("broken", broken)
        gs.register_cleanup("later", later)
        await gs.shutdown([])
        assert events == ["later"]

    asyncio.run(run())


@pytest.mark.parametrize("strict", [False, True])
def test_strict_inflight_drain_reports_remaining_writer(strict):
    async def run():
        events = []
        started, release = asyncio.Event(), asyncio.Event()
        writer = asyncio.create_task(resistant_worker(started, release, events))
        await started.wait()
        gs = GracefulShutdown(drain_timeout=0.01, require_quiescent=strict)
        try:
            with pytest.raises(ShutdownDrainTimeoutError if strict else RuntimeError):
                await gs.drain_worker_tasks([writer])
            assert not writer.done()
        finally:
            release.set()
            await asyncio.wait_for(writer, timeout=1)

    asyncio.run(run())


@pytest.mark.parametrize("bound", [0, -1, float("inf"), float("nan")])
def test_strict_shutdown_requires_a_finite_positive_existing_bound(bound):
    with pytest.raises(ValueError, match="SHUTDOWN_DRAIN_BOUND_INVALID"):
        GracefulShutdown(drain_timeout=bound, require_quiescent=True)
