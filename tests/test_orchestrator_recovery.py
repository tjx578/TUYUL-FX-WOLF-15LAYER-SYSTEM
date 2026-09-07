from __future__ import annotations

import json
from typing import Any

import pytest

from services.orchestrator.execution_mode import ExecutionMode
from services.orchestrator.ownership import LeaseIdentity, OwnershipLostError
from services.orchestrator.state_manager import StateHydrationError, StateManager


class _Redis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.published: list[tuple[str, str]] = []

    def get(self, key: str) -> str | None:
        return self.values.get(key)


class _Ownership:
    def __init__(self, redis: _Redis, *, generation: int) -> None:
        self.redis = redis
        self.identity = LeaseIdentity(owner_id=f"owner-{generation}", generation=generation)
        self.held = True
        self.fail_next_write = False

    def fenced_state_write(
        self,
        *,
        state_key: str,
        state_payload: str,
        heartbeat_key: str,
        heartbeat_payload: str,
        channel: str,
    ) -> None:
        if self.fail_next_write:
            self.fail_next_write = False
            raise OwnershipLostError("simulated interrupted write")
        self.redis.values[state_key] = state_payload
        self.redis.values[heartbeat_key] = heartbeat_payload
        self.redis.published.append((channel, state_payload))

    def fenced_value_write(self, *, key: str, value: str) -> None:
        self.redis.values[key] = value


def _manager(redis: _Redis, *, generation: int) -> StateManager:
    return StateManager(
        redis_client=redis,  # type: ignore[arg-type]
        ownership=_Ownership(redis, generation=generation),  # type: ignore[arg-type]
    )


def _committed_payload(*, generation: int = 1, revision: int = 7, **changes: Any) -> str:
    payload: dict[str, Any] = {
        "schema": "wolf15.orchestrator.state/v2",
        "commit_marker": "COMMITTED",
        "state_revision": revision,
        "source": "wolf15-orchestrator",
        "event": "MODE_CHANGED",
        "channel": "wolf15:orchestrator:commands",
        "mode": "SAFE",
        "reason": "compliance:DAILY_DD_NEAR_LIMIT",
        "compliance_code": "DAILY_DD_NEAR_LIMIT",
        "updated_at": "2026-09-06T01:02:03+00:00",
        "timestamp": 1,
        "owner_id": "prior-owner",
        "fence_generation": generation,
    }
    payload.update(changes)
    return json.dumps(payload)


def test_hydrates_prior_committed_state_and_watermark_before_boot() -> None:
    redis = _Redis()
    manager = _manager(redis, generation=2)
    redis.values[manager._state_key] = _committed_payload()  # noqa: SLF001

    assert manager.hydrate_committed_state() is True
    assert manager.snapshot().mode == ExecutionMode.SAFE
    assert manager.snapshot().compliance_code == "DAILY_DD_NEAR_LIMIT"
    assert manager._state_revision == 7  # noqa: SLF001

    manager.publish_state("BOOT", {"hydrated": True, "prior_state_revision": 7})

    boot = json.loads(redis.values[manager._state_key])  # noqa: SLF001
    assert boot["mode"] == "SAFE"
    assert boot["state_revision"] == 8
    assert boot["details"]["prior_state_revision"] == 7
    assert boot["commit_marker"] == "COMMITTED"


def test_restart_hydration_is_idempotent_and_recovery_progress_is_process_local() -> None:
    redis = _Redis()
    first = _manager(redis, generation=2)
    redis.values[first._state_key] = _committed_payload(revision=11)  # noqa: SLF001
    first._recovery_count = 2  # noqa: SLF001
    assert first.hydrate_committed_state() is True
    assert first._recovery_count == 0  # noqa: SLF001
    first.publish_state("HEARTBEAT")

    second = _manager(redis, generation=3)
    second._recovery_count = 2  # noqa: SLF001
    assert second.hydrate_committed_state() is True

    assert second.snapshot() == first.snapshot()
    assert second._state_revision == 12  # noqa: SLF001
    assert second._recovery_count == 0  # noqa: SLF001
    assert "recovery_count" not in json.loads(redis.values[second._state_key])  # noqa: SLF001


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"commit_marker": "INFLIGHT"}, "not committed"),
        ({"source": "other-service"}, "authority mismatch"),
        ({"channel": "other-channel"}, "authority mismatch"),
        ({"fence_generation": 2}, "stale or mismatched"),
        ({"fence_generation": 3}, "stale or mismatched"),
        ({"fence_generation": True}, "watermark is invalid"),
        ({"state_revision": 0}, "revision is invalid"),
        ({"state_revision": 1.5}, "watermark is invalid"),
        ({"owner_id": "owner-2"}, "owner identity is stale or mismatched"),
        ({"mode": "UNKNOWN"}, "mode is invalid"),
    ],
)
def test_hydration_rejects_uncommitted_stale_or_mismatched_state(changes: dict[str, Any], message: str) -> None:
    redis = _Redis()
    manager = _manager(redis, generation=2)
    redis.values[manager._state_key] = _committed_payload(**changes)  # noqa: SLF001

    with pytest.raises(StateHydrationError, match=message):
        manager.hydrate_committed_state()


def test_missing_state_is_clean_first_start() -> None:
    manager = _manager(_Redis(), generation=1)

    assert manager.hydrate_committed_state() is False
    assert manager._state_revision == 0  # noqa: SLF001
    assert manager._recovery_count == 0  # noqa: SLF001


def test_interrupted_write_does_not_advance_committed_watermark_or_replace_state() -> None:
    redis = _Redis()
    manager = _manager(redis, generation=2)
    redis.values[manager._state_key] = _committed_payload(revision=4)  # noqa: SLF001
    manager.hydrate_committed_state()
    original = redis.values[manager._state_key]  # noqa: SLF001
    ownership = manager._ownership  # noqa: SLF001
    ownership.fail_next_write = True  # type: ignore[attr-defined]

    with pytest.raises(OwnershipLostError, match="interrupted write"):
        manager.publish_state("SHUTDOWN")

    assert manager._state_revision == 4  # noqa: SLF001
    assert redis.values[manager._state_key] == original  # noqa: SLF001


def test_shutdown_is_a_committed_settlement_boundary() -> None:
    redis = _Redis()
    manager = _manager(redis, generation=2)
    redis.values[manager._state_key] = _committed_payload(revision=4)  # noqa: SLF001
    manager.hydrate_committed_state()

    manager.publish_state("SHUTDOWN")

    settled = json.loads(redis.values[manager._state_key])  # noqa: SLF001
    assert settled["event"] == "SHUTDOWN"
    assert settled["commit_marker"] == "COMMITTED"
    assert settled["state_revision"] == 5
    assert manager._state_revision == 5  # noqa: SLF001


class _RunOwnership(_Ownership):
    """In-memory lease lifecycle for exercising the real foreground loop."""

    def __init__(self, redis: _Redis, *, generation: int) -> None:
        super().__init__(redis, generation=generation)
        self.held = False
        self._next_generation = generation
        self.acquisitions = 0
        self.releases = 0

    def acquire(self) -> bool:
        self.identity = LeaseIdentity(owner_id=f"owner-{self._next_generation}", generation=self._next_generation)
        self._next_generation += 1
        self.acquisitions += 1
        self.held = True
        return True

    def release(self) -> bool:
        self.releases += 1
        self.held = False
        return True


def _run_manager(redis: _Redis) -> tuple[StateManager, _RunOwnership]:
    ownership = _RunOwnership(redis, generation=2)
    return (
        StateManager(
            redis_client=redis,  # type: ignore[arg-type]
            ownership=ownership,  # type: ignore[arg-type]
        ),
        ownership,
    )


def _legacy_payload() -> str:
    return json.dumps(
        {
            "source": "wolf15-orchestrator",
            "channel": "wolf15:orchestrator:commands",
            "mode": "KILL_SWITCH",
            "reason": "synthetic-account-state-missing",
            "compliance_code": "ACCOUNT_STATE_MISSING",
            "updated_at": "2026-09-05T13:48:10+00:00",
            "timestamp": 1,
            "event": "HEARTBEAT",
        }
    )


@pytest.mark.parametrize(
    "payload",
    [_legacy_payload(), "{malformed", _committed_payload(commit_marker="INFLIGHT")],
    ids=["legacy", "malformed", "uncommitted-v2"],
)
def test_run_forever_hydration_failure_preserves_storage(payload: str) -> None:
    redis = _Redis()
    manager, ownership = _run_manager(redis)
    redis.values.update(
        {
            manager._state_key: payload,  # noqa: SLF001
            "wolf15:heartbeat:orchestrator": "existing-heartbeat-bytes",
            "wolf15:system:kill_switch": '{"active":true}',
        }
    )
    before = dict(redis.values)
    started: list[bool] = []

    with pytest.raises(StateHydrationError):
        manager.run_forever(on_started=lambda: started.append(True))

    assert redis.values == before
    assert redis.published == []
    assert started == []
    assert ownership.acquisitions == ownership.releases == 1
    assert ownership.held is False
    assert manager._state_revision == 0  # noqa: SLF001
    assert manager._supervisor.state == "FATAL"  # noqa: SLF001
    assert manager._supervisor.is_ready() is False  # noqa: SLF001


def test_run_forever_reacquisition_failure_cannot_settle_prior_process_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _Redis()
    manager, ownership = _run_manager(redis)
    redis.values[manager._state_key] = _committed_payload()  # noqa: SLF001
    monkeypatch.setattr(manager, "start_listener", lambda: None)
    expected_after_loss: dict[str, str] = {}

    def lose_lease_to_legacy_writer() -> None:
        ownership.held = False
        redis.values[manager._state_key] = _legacy_payload()  # noqa: SLF001
        redis.values["wolf15:heartbeat:orchestrator"] = "replacement-heartbeat"
        expected_after_loss.update(redis.values)
        raise OwnershipLostError("synthetic lease loss")

    monkeypatch.setattr(manager, "process_once", lose_lease_to_legacy_writer)
    with pytest.raises(StateHydrationError):
        manager.run_forever()

    assert redis.values == expected_after_loss
    assert [json.loads(payload)["event"] for _, payload in redis.published] == ["BOOT"]
    assert ownership.acquisitions == 2
    assert ownership.releases == 1
    assert ownership.held is False
    assert manager._supervisor.state == "FATAL"  # noqa: SLF001


@pytest.mark.parametrize("prior_payload", [None, _committed_payload()], ids=["first-start", "recovery"])
def test_run_forever_initialized_state_still_commits_shutdown(
    prior_payload: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    redis = _Redis()
    manager, ownership = _run_manager(redis)
    if prior_payload is not None:
        redis.values[manager._state_key] = prior_payload  # noqa: SLF001
    monkeypatch.setattr(manager, "start_listener", lambda: None)

    def stop_after_boot() -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        manager.run_forever(on_started=stop_after_boot)

    published = [json.loads(payload) for _, payload in redis.published]
    assert [payload["event"] for payload in published] == ["BOOT", "SHUTDOWN"]
    expected_revision = 2 if prior_payload is None else 9
    assert published[-1]["state_revision"] == expected_revision
    assert published[-1]["commit_marker"] == "COMMITTED"
    assert published[-1]["mode"] == ("NORMAL" if prior_payload is None else "SAFE")
    assert published[-1]["compliance_code"] == ("INIT" if prior_payload is None else "DAILY_DD_NEAR_LIMIT")
    assert ownership.acquisitions == ownership.releases == 1
    assert manager._supervisor.state == "STOPPED"  # noqa: SLF001
