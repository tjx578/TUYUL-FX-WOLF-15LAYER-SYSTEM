import asyncio
from types import SimpleNamespace

import pytest

from core.health_probe import HealthProbe
from services.engine import runner
from services.engine.runtime_state import EngineRuntimeState


class Deadline:
    def __init__(self, seconds, callback):
        assert seconds == 45
        self.callback = callback
        self.started = self.cancelled = False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True


@pytest.fixture(autouse=True)
def bounded_test_deadline(monkeypatch):
    monkeypatch.setattr("services.engine.runtime_state.threading.Timer", Deadline)


def test_bootstrap_cycle_restart_and_stale_generation_readiness():
    state = EngineRuntimeState()
    assert not state.ready()
    state.task_state("AnalysisLoop", "STARTING")
    first = state.begin_analysis()
    state.analysis_cycle(first)
    assert not state.ready()
    state.bootstrap_complete()
    assert state.ready()
    state.end_analysis(first)
    assert not state.ready()
    state.task_state("AnalysisLoop", "RESTARTING")
    state.task_state("AnalysisLoop", "STARTING")
    second = state.begin_analysis()
    state.analysis_cycle(first)
    assert not state.ready()
    state.analysis_cycle(second)
    assert state.ready()
    state.task_state("RedisConsumer", "RESTARTING")
    assert not state.ready()
    state.task_state("RedisConsumer", "STARTING")
    assert not state.ready()
    state.analysis_cycle(second)
    assert state.ready()
    state.begin_shutdown()
    state.analysis_cycle(second)
    assert not state.ready()
    assert state._deadline.started
    state.cancel_process_deadline()
    assert state._deadline.cancelled


def test_probe_launcher_returns_same_probe_and_starts_unready(monkeypatch):
    state = EngineRuntimeState()
    returned = HealthProbe(readiness_check=state.ready)
    calls = []

    def launch(**kwargs):
        calls.append(kwargs)
        assert kwargs["readiness_check"]() is False
        return returned

    monkeypatch.setenv("ENGINE_HEALTH_PORT", "18081")
    monkeypatch.setattr("services.shared.health_probe_launcher.start_probe_in_thread", launch)
    assert runner._start_health_probe_in_thread(state) is returned
    assert len(calls) == 1 and calls[0]["port"] == 18081


def test_preflight_and_main_share_probe_state_and_event_loop(monkeypatch):
    state = EngineRuntimeState()
    probe = HealthProbe(readiness_check=state.ready)
    loops = []

    async def preflight():
        loops.append(asyncio.get_running_loop())
        assert not state.ready()

    async def main(**kwargs):
        loops.append(asyncio.get_running_loop())
        assert kwargs == {"health_probe": probe, "runtime_state": state}

    monkeypatch.setattr(runner, "_preflight_checks", preflight)
    monkeypatch.setattr(runner, "_import_main", lambda: main)
    asyncio.run(runner._run_engine(probe, state))
    assert len(loops) == 2 and loops[0] is loops[1]


@pytest.mark.parametrize("failure", [False, True])
def test_process_owner_fatal_exit_and_graceful_return(monkeypatch, failure):
    observed = SimpleNamespace(probe=None, state=None, hold=0)

    def start(state):
        observed.state = state
        observed.probe = HealthProbe(readiness_check=state.ready)
        return observed.probe

    async def main(probe, state):
        assert probe is observed.probe and state is observed.state
        if failure:
            raise RuntimeError("controlled bootstrap failure")
        state.begin_shutdown()

    def hold(**_):
        observed.hold += 1
        assert observed.state._deadline.cancelled
        assert not observed.state.ready() and not observed.probe._alive

    monkeypatch.setattr(runner, "_start_health_probe_in_thread", start)
    monkeypatch.setattr(runner, "_run_engine", main)
    monkeypatch.setattr("services.shared.diagnostics.hold_alive_sync", hold)
    if failure:
        with pytest.raises(SystemExit) as exc:
            runner.run()
        assert exc.value.code == 1 and observed.hold == 1
    else:
        assert runner.run() is None and observed.hold == 0
    assert observed.state._deadline.cancelled
