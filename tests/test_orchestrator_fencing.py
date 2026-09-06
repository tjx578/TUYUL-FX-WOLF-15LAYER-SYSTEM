from __future__ import annotations

import json
from typing import Any

import pytest

from services.orchestrator.ownership import OwnershipLostError, RedisFencedOwnership


class _ScriptRedis:
    """Minimal deterministic emulator for the ownership Lua contracts."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.generations: dict[str, int] = {}
        self.published: list[tuple[str, str]] = []

    def expire(self, key: str) -> None:
        self.values.pop(key, None)

    def eval(self, script: str, numkeys: int, *items: Any) -> Any:
        keys = [str(item) for item in items[:numkeys]]
        args = [str(item) for item in items[numkeys:]]
        if "lease:acquire:v1" in script:
            lease_key, counter_key = keys
            current = self.values.get(lease_key)
            if current:
                return current if current.rpartition("|")[0] == args[0] else ""
            generation = self.generations.get(counter_key, 0) + 1
            self.generations[counter_key] = generation
            value = f"{args[0]}|{generation}"
            self.values[lease_key] = value
            return value
        if "lease:renew:v1" in script:
            return int(self.values.get(keys[0]) == args[0])
        if "lease:release:v1" in script:
            if self.values.get(keys[0]) != args[0]:
                return 0
            del self.values[keys[0]]
            return 1
        if "fenced-state-write:v1" in script:
            if self.values.get(keys[0]) != args[0]:
                return 0
            self.values[keys[1]] = args[1]
            self.values[keys[2]] = args[2]
            self.published.append((keys[3], args[1]))
            return 1
        if "fenced-value-write:v1" in script:
            if self.values.get(keys[0]) != args[0]:
                return 0
            self.values[keys[1]] = args[1]
            return 1
        raise AssertionError("unexpected script")


def _owner(redis: _ScriptRedis, name: str) -> RedisFencedOwnership:
    return RedisFencedOwnership(
        redis,
        owner_id=name,
        lease_key="lease",
        generation_key="generation",
        ttl_seconds=15,
    )


def test_two_instances_have_at_most_one_owner() -> None:
    redis = _ScriptRedis()
    first = _owner(redis, "first")
    second = _owner(redis, "second")

    assert first.acquire() is True
    assert second.acquire() is False
    assert first.identity is not None
    assert first.identity.generation == 1


def test_expired_owner_is_fenced_after_takeover() -> None:
    redis = _ScriptRedis()
    old = _owner(redis, "old")
    new = _owner(redis, "new")
    assert old.acquire()
    redis.expire("lease")
    assert new.acquire()
    assert new.identity is not None and new.identity.generation == 2

    with pytest.raises(OwnershipLostError, match="stale orchestrator owner"):
        old.fenced_state_write(
            state_key="state",
            state_payload=json.dumps({"owner": "old"}),
            heartbeat_key="heartbeat",
            heartbeat_payload="old",
            channel="channel",
        )

    new.fenced_state_write(
        state_key="state",
        state_payload=json.dumps({"owner": "new"}),
        heartbeat_key="heartbeat",
        heartbeat_payload="new",
        channel="channel",
    )
    assert json.loads(redis.values["state"])["owner"] == "new"
    assert redis.values["heartbeat"] == "new"


def test_stale_owner_cannot_clear_new_owner_or_write_kill_switch() -> None:
    redis = _ScriptRedis()
    old = _owner(redis, "old")
    new = _owner(redis, "new")
    assert old.acquire()
    redis.expire("lease")
    assert new.acquire()

    with pytest.raises(OwnershipLostError):
        old.fenced_value_write(key="kill-switch", value="stale")
    assert old.release() is False

    new.fenced_value_write(key="kill-switch", value="current")
    assert redis.values["kill-switch"] == "current"


def test_wrong_generation_cannot_renew() -> None:
    redis = _ScriptRedis()
    owner = _owner(redis, "owner")
    assert owner.acquire()
    redis.values["lease"] = "owner|999"

    assert owner.renew() is False
    assert owner.held is False
