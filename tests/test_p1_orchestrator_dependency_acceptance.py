"""Keep dependency-failure acceptance strict across fail-fast HTTP races."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from scripts.ci.p1_runtime_acceptance import validate_orchestrator_dependency_failure
from services.orchestrator.state_manager import RuntimeSupervisor, StateManager

_FAILURE_LOG = "Orchestrator fatal error\nredis.exceptions.ConnectionError: unavailable"


@pytest.mark.parametrize("responses", [[], [{"status": 503, "body": {"status": "not_ready"}}]])
def test_dependency_exit_accepts_only_explicit_failure_evidence(responses: list[dict]) -> None:
    receipt = validate_orchestrator_dependency_failure(1, _FAILURE_LOG, responses)
    assert receipt["exit_code"] == 1
    assert receipt["readiness_observations"] == responses
    assert receipt["http_readiness"] == ("REJECTED" if responses else "NOT_OBSERVED_BEFORE_EXIT")


@pytest.mark.parametrize(
    ("exit_code", "logs", "responses"),
    [
        (0, _FAILURE_LOG, []),
        (1, "unrelated startup exception", []),
        (1, "Orchestrator fatal error\nValueError: invalid configuration", []),
        (1, _FAILURE_LOG + "\nacquired ownership generation=1", []),
        (1, _FAILURE_LOG, [{"status": 200, "body": {"status": "ready"}}]),
        (1, _FAILURE_LOG, [{"status": 503, "body": {"status": "ready"}}]),
    ],
)
def test_dependency_exit_rejects_false_success(exit_code: int, logs: str, responses: list[dict]) -> None:
    with pytest.raises(AssertionError):
        validate_orchestrator_dependency_failure(exit_code, logs, responses)


def test_unavailable_ownership_storage_never_starts_or_publishes() -> None:
    redis = Mock()
    redis.eval.side_effect = RedisConnectionError("disposable unavailable storage")
    supervisor = RuntimeSupervisor(stall_timeout_sec=30)
    manager = StateManager(redis_client=redis, supervisor=supervisor)
    on_started = Mock()

    with pytest.raises(RedisConnectionError):
        manager.run_forever(on_started=on_started)

    assert supervisor.state == "FATAL"
    assert supervisor.is_ready() is False
    assert supervisor.is_alive() is False
    on_started.assert_not_called()
    redis.publish.assert_not_called()
    redis.set.assert_not_called()
    redis.pubsub.assert_not_called()
    assert redis.eval.call_count == 1
