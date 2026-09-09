from types import SimpleNamespace

import pytest

from storage.pressure_outbox_worker import PressureOutboxWorker


@pytest.mark.asyncio
async def test_readiness_requires_successful_poll_and_rejects_failed_or_stale_poll(monkeypatch):
    import storage.pressure_outbox_worker as mod

    now = [10.0]
    monkeypatch.setattr(mod.time, "monotonic", lambda: now[0])
    worker = PressureOutboxWorker(
        repository=SimpleNamespace(),
        consumer=SimpleNamespace(),
        master_enabled=True,
        dispatch_enabled=True,
        consumer_enabled=False,
    )
    assert not worker.runtime_ready()
    observed = []

    async def process():
        return 0

    async def wait(timeout):
        observed.append(worker.runtime_ready())
        await worker.stop()

    monkeypatch.setattr(worker, "process_once", process)
    monkeypatch.setattr(worker, "_wait_or_stop", wait)
    await worker.run()
    assert observed == [True]
    worker._consecutive_poll_failures = 1
    assert not worker.runtime_ready()
    worker._consecutive_poll_failures = 0
    now[0] += 31
    assert not worker.runtime_ready()


@pytest.mark.parametrize("master,dispatch", [(False, False), (True, False), (False, True)])
def test_disabled_dispatcher_cannot_report_ready(master, dispatch):
    import time

    worker = PressureOutboxWorker(
        repository=SimpleNamespace(),
        consumer=SimpleNamespace(),
        master_enabled=master,
        dispatch_enabled=dispatch,
        consumer_enabled=False,
    )
    worker._last_successful_poll = time.monotonic()
    assert not worker.runtime_ready()
