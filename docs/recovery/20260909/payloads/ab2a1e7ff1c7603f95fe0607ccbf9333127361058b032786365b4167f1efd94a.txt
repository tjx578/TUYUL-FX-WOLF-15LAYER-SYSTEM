from __future__ import annotations

import pytest

from services.orchestrator.state_manager import RuntimeSupervisor


def test_standby_is_live_but_not_writer_ready() -> None:
    supervisor = RuntimeSupervisor(stall_timeout_sec=30)
    supervisor.mark_standby()

    assert supervisor.state == "STANDBY"
    assert supervisor.is_alive() is True
    assert supervisor.is_ready() is False


def test_current_owner_is_live_and_ready() -> None:
    supervisor = RuntimeSupervisor(stall_timeout_sec=30)
    supervisor.mark_owner()

    assert supervisor.state == "OWNER"
    assert supervisor.is_alive() is True
    assert supervisor.is_ready() is True


def test_fatal_evaluator_is_neither_live_nor_ready() -> None:
    supervisor = RuntimeSupervisor(stall_timeout_sec=30)
    supervisor.mark_owner()
    supervisor.mark_fatal(RuntimeError("sensitive details must not escape"))

    assert supervisor.state == "FATAL"
    assert supervisor.is_alive() is False
    assert supervisor.is_ready() is False
    assert supervisor.details()["fatal_error"] == "RuntimeError"


def test_stagnant_owner_fails_liveness_and_readiness(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = 100.0
    monkeypatch.setattr("services.orchestrator.state_manager.time.monotonic", lambda: clock)
    supervisor = RuntimeSupervisor(stall_timeout_sec=10)
    supervisor.mark_owner()

    clock = 111.0
    assert supervisor.is_alive() is False
    assert supervisor.is_ready() is False


def test_progress_refreshes_stagnation_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = 100.0
    monkeypatch.setattr("services.orchestrator.state_manager.time.monotonic", lambda: clock)
    supervisor = RuntimeSupervisor(stall_timeout_sec=10)
    supervisor.mark_owner()

    clock = 109.0
    supervisor.mark_progress()
    clock = 118.0
    assert supervisor.is_alive() is True
    assert supervisor.is_ready() is True
