from __future__ import annotations

import time

from api.orchestrator_routes import _parse_orchestrator_health


def test_parse_orchestrator_health_marks_recent_payload_ready(monkeypatch) -> None:
    monkeypatch.setenv("ORCHESTRATOR_HEARTBEAT_INTERVAL_SEC", "30")
    now = time.time()
    age, ready = _parse_orchestrator_health({"timestamp": now - 10})
    assert age is not None
    assert age >= 0
    assert ready is True


def test_parse_orchestrator_health_marks_stale_payload_not_ready(monkeypatch) -> None:
    monkeypatch.setenv("ORCHESTRATOR_HEARTBEAT_INTERVAL_SEC", "10")
    now = time.time()
    age, ready = _parse_orchestrator_health({"timestamp": now - 120})
    assert age is not None
    assert age >= 100
    assert ready is False


def test_parse_orchestrator_health_invalid_timestamp_not_ready() -> None:
    age, ready = _parse_orchestrator_health({"timestamp": "not-a-number"})
    assert age is None
    assert ready is False
