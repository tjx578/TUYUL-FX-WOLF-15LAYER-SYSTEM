from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


def test_orchestrator_late_fatal_clears_readiness_and_exits(monkeypatch):
    from services.orchestrator import state_manager as mod
    from services.shared import diagnostics

    observed = []

    def run_forever(on_started):
        on_started()
        assert mod._ORCHESTRATOR_READY.is_set()
        raise RuntimeError("fixture_fatal")

    monkeypatch.setattr(mod, "_start_health_probe_in_thread", lambda **kwargs: None)
    monkeypatch.setattr(mod, "StateManager", lambda: SimpleNamespace(run_forever=run_forever))
    monkeypatch.setattr(
        diagnostics, "hold_alive_sync", lambda **kwargs: observed.append(mod._ORCHESTRATOR_READY.is_set())
    )
    with pytest.raises(RuntimeError, match="fixture_fatal"):
        mod.run()
    assert observed == [False]


@pytest.mark.asyncio
@pytest.mark.parametrize("signal_stop", [False, True])
async def test_pressure_outbox_failure_drains_siblings_before_pool_close(monkeypatch, signal_stop):
    from services.pressure_outbox import runner as mod

    monkeypatch.setenv("SIGNAL_PRESSURE_OUTBOX_ENABLED", "true")
    monkeypatch.setenv("SIGNAL_PRESSURE_OUTBOX_DISPATCH_ENABLED", "true")
    monkeypatch.setenv("PORT", "0")
    order = []
    started = asyncio.Event()
    stop_started = asyncio.Event()
    callbacks = []

    async def primary():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            order.append("primary_drained")

    async def stop_worker():
        stop_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            order.append("stop_drained")

    async def fault():
        await started.wait()
        if signal_stop:
            callbacks[0]()
            await stop_started.wait()
        raise RuntimeError("required_evidence_failed")

    async def close():
        order.append("pool_closed")

    monkeypatch.setattr(mod, "pg_client", SimpleNamespace(initialize=AsyncMock(), is_available=True, close=close))
    monkeypatch.setattr(mod, "PressureOutboxRepository", lambda **kwargs: None)
    monkeypatch.setattr(mod, "Strategy5SCRInboxConsumer", lambda **kwargs: None)
    monkeypatch.setattr(mod, "PressureOutboxWorker", lambda **kwargs: SimpleNamespace(run=primary, stop=stop_worker))
    enabled = SimpleNamespace(enabled=True, mode="SHADOW", provider="fixture", execution_enabled=False)
    monkeypatch.setattr(mod.EvidenceRuntimeConfig, "from_env", lambda: enabled)
    monkeypatch.setattr(mod, "build_evidence_worker", lambda **kwargs: SimpleNamespace(run=fault, stop=AsyncMock()))
    for config in [mod.OutcomeRuntimeConfig, mod.LifecycleV2RuntimeConfig, mod.ShadowEvidenceV2RuntimeConfig]:
        monkeypatch.setattr(config, "from_env", lambda: SimpleNamespace(enabled=False))
    monkeypatch.setattr(asyncio.get_running_loop(), "add_signal_handler", lambda *args: callbacks.append(args[1]))
    with pytest.raises(RuntimeError, match="crash_limit"):
        await mod._main()
    assert order[-1] == "pool_closed"
    assert "primary_drained" in order[:-1]
    assert ("stop_drained" in order[:-1]) is signal_stop
