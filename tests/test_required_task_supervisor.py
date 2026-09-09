"""Opt-in required worker supervision, separate from optional legacy behavior."""

import asyncio

import pytest

from core.health_probe import HealthProbe
from startup.task_supervisor import RequiredTaskFailedError, supervised_task


@pytest.mark.parametrize("fault", ["exception", "returned", "cancelled", "self_cancel"])
def test_required_worker_loss_exhausts_retries_and_marks_probe_unready(fault):
    async def run():
        probe = HealthProbe(readiness_check=lambda: True)
        calls = []
        states = []

        async def worker():
            calls.append(1)
            if fault == "exception":
                raise RuntimeError("private database credential must not enter status")
            if fault == "cancelled":
                raise asyncio.CancelledError
            if fault == "self_cancel":
                asyncio.current_task().cancel()
                await asyncio.sleep(0)

        with pytest.raises(RequiredTaskFailedError) as captured:
            await supervised_task(
                "AnalysisLoop",
                worker,
                health_probe=probe,
                max_restarts=1,
                cooldown=0,
                required=True,
                state_callback=lambda name, state: states.append((name, state)),
            )
        assert len(calls) == 2
        assert captured.value.cause == ("cancelled" if fault == "self_cancel" else fault)
        assert "private" not in str(captured.value)
        assert states == [
            ("AnalysisLoop", state) for state in ["STARTING", "RESTARTING", "STARTING", "RESTARTING", "FAILED"]
        ]
        assert probe._readiness_check() is False
        assert probe._alive is False
        assert probe._details["dead_reason"] == "AnalysisLoop_crash_limit"

    asyncio.run(run())


def test_required_retry_reaches_real_worker_then_intentional_shutdown():
    async def run():
        stop = asyncio.Event()
        states = []
        calls = []

        async def worker():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("transient")
            stop.set()

        await supervised_task(
            "RedisConsumer",
            worker,
            shutdown_event=stop,
            max_restarts=1,
            cooldown=0,
            required=True,
            state_callback=lambda _, state: states.append(state),
        )
        assert len(calls) == 2
        assert states == ["STARTING", "RESTARTING", "STARTING", "STOPPED"]
        assert "RUNNING" not in states, "supervision does not attest application readiness"

    asyncio.run(run())


def test_shutdown_before_start_never_constructs_required_worker():
    async def run():
        stop = asyncio.Event()
        stop.set()
        states = []

        async def worker():
            raise AssertionError("must not start")

        await supervised_task(
            "AnalysisLoop",
            worker,
            shutdown_event=stop,
            required=True,
            state_callback=lambda _, state: states.append(state),
        )
        assert states == ["STOPPED"]

    asyncio.run(run())


def test_owner_sets_shutdown_before_cancellation_is_clean():
    async def run():
        stop = asyncio.Event()
        started = asyncio.Event()
        probe = HealthProbe()
        states = []

        async def worker():
            started.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(
            supervised_task(
                "AnalysisLoop",
                worker,
                shutdown_event=stop,
                health_probe=probe,
                required=True,
                state_callback=lambda _, state: states.append(state),
            )
        )
        await started.wait()
        stop.set()
        task.cancel()
        await task
        assert states == ["STARTING", "STOPPED"]
        assert probe._alive is True

    asyncio.run(run())


def test_shutdown_interrupts_existing_long_cooldown():
    async def run():
        stop = asyncio.Event()
        restarting = asyncio.Event()
        states = []

        def changed(_, state):
            states.append(state)
            if state == "RESTARTING":
                restarting.set()

        async def worker():
            raise RuntimeError("failure")

        task = asyncio.create_task(
            supervised_task(
                "AnalysisLoop",
                worker,
                shutdown_event=stop,
                max_restarts=2,
                cooldown=120,
                required=True,
                state_callback=changed,
            )
        )
        await restarting.wait()
        stop.set()
        await asyncio.wait_for(task, timeout=1)
        assert states == ["STARTING", "RESTARTING", "STOPPED"]

    asyncio.run(run())


def test_unsolicited_cancellation_during_cooldown_is_fatal_at_limit():
    async def run():
        restarting = asyncio.Event()

        async def worker():
            raise RuntimeError("failure")

        task = asyncio.create_task(
            supervised_task(
                "AnalysisLoop",
                worker,
                max_restarts=1,
                cooldown=120,
                required=True,
                state_callback=lambda _, state: restarting.set() if state == "RESTARTING" else None,
            )
        )
        await restarting.wait()
        task.cancel()
        with pytest.raises(RequiredTaskFailedError, match="cancelled"):
            await task

    asyncio.run(run())


@pytest.mark.parametrize("fault", ["return", "cancel", "exception"])
def test_optional_legacy_behavior_is_preserved(fault):
    async def run():
        calls = []

        async def worker():
            calls.append(1)
            if fault == "cancel":
                raise asyncio.CancelledError
            if fault == "exception":
                raise RuntimeError("legacy crash")

        await supervised_task("OptionalWorker", worker, max_restarts=1, cooldown=0)
        assert len(calls) == (2 if fault == "exception" else 1)

    asyncio.run(run())
