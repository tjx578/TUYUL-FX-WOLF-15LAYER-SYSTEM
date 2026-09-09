"""Redis-backed lease and fencing for the standalone orchestrator.

The lease value contains both a unique process owner id and a monotonically
increasing generation.  Every authoritative Redis write is performed by a Lua
script that compares the current lease value in the same Redis operation.  A
process that wakes after its lease expired therefore cannot overwrite the new
owner's state, heartbeat, or kill-switch projection.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class OwnershipLostError(RuntimeError):
    """Raised when a fenced write is attempted by a stale owner."""


_ACQUIRE_SCRIPT = """
-- wolf15:orchestrator:lease:acquire:v1
local current = redis.call('GET', KEYS[1])
if current then
  local separator = string.find(current, '|', 1, true)
  if separator and string.sub(current, 1, separator - 1) == ARGV[1] then
    redis.call('PEXPIRE', KEYS[1], ARGV[2])
    return current
  end
  return ''
end
local generation = redis.call('INCR', KEYS[2])
local lease_value = ARGV[1] .. '|' .. tostring(generation)
local installed = redis.call('SET', KEYS[1], lease_value, 'PX', ARGV[2], 'NX')
if installed then return lease_value end
return ''
"""

_COMPARE_PEXPIRE_SCRIPT = """
-- wolf15:orchestrator:lease:renew:v1
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('PEXPIRE', KEYS[1], ARGV[2])
end
return 0
"""

_COMPARE_DELETE_SCRIPT = """
-- wolf15:orchestrator:lease:release:v1
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""

_FENCED_STATE_WRITE_SCRIPT = """
-- wolf15:orchestrator:fenced-state-write:v1
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
redis.call('SET', KEYS[2], ARGV[2])
redis.call('SET', KEYS[3], ARGV[3])
redis.call('PUBLISH', KEYS[4], ARGV[2])
return 1
"""

_FENCED_VALUE_WRITE_SCRIPT = """
-- wolf15:orchestrator:fenced-value-write:v1
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
redis.call('SET', KEYS[2], ARGV[2])
return 1
"""


@dataclass(frozen=True, slots=True)
class LeaseIdentity:
    owner_id: str
    generation: int

    @property
    def wire_value(self) -> str:
        return f"{self.owner_id}|{self.generation}"


class RedisFencedOwnership:
    """Exclusive lease whose generation fences all orchestrator Redis writes."""

    def __init__(
        self,
        redis_client: Any,
        *,
        owner_id: str,
        lease_key: str,
        generation_key: str,
        ttl_seconds: float,
    ) -> None:
        if not owner_id or "|" in owner_id:
            raise ValueError("owner_id must be non-empty and cannot contain '|'")
        if ttl_seconds < 3:
            raise ValueError("lease ttl must be at least 3 seconds")
        self._redis = redis_client
        self._owner_id = owner_id
        self._lease_key = lease_key
        self._generation_key = generation_key
        self._ttl_ms = int(ttl_seconds * 1000)
        self._identity: LeaseIdentity | None = None

    @property
    def identity(self) -> LeaseIdentity | None:
        return self._identity

    @property
    def held(self) -> bool:
        return self._identity is not None

    def acquire(self) -> bool:
        raw = self._redis.eval(
            _ACQUIRE_SCRIPT,
            2,
            self._lease_key,
            self._generation_key,
            self._owner_id,
            self._ttl_ms,
        )
        value = raw.decode() if isinstance(raw, bytes) else str(raw or "")
        if not value:
            self._identity = None
            return False
        owner_id, separator, generation_raw = value.rpartition("|")
        if not separator or owner_id != self._owner_id:
            raise RuntimeError("lease backend returned an invalid owner identity")
        self._identity = LeaseIdentity(owner_id=owner_id, generation=int(generation_raw))
        return True

    def renew(self) -> bool:
        identity = self._identity
        if identity is None:
            return False
        renewed = int(
            self._redis.eval(
                _COMPARE_PEXPIRE_SCRIPT,
                1,
                self._lease_key,
                identity.wire_value,
                self._ttl_ms,
            )
            or 0
        )
        if renewed != 1:
            self._identity = None
            return False
        return True

    def release(self) -> bool:
        identity = self._identity
        self._identity = None
        if identity is None:
            return False
        return bool(
            self._redis.eval(
                _COMPARE_DELETE_SCRIPT,
                1,
                self._lease_key,
                identity.wire_value,
            )
        )

    def fenced_state_write(
        self,
        *,
        state_key: str,
        state_payload: str,
        heartbeat_key: str,
        heartbeat_payload: str,
        channel: str,
    ) -> None:
        identity = self._require_identity()
        written = self._redis.eval(
            _FENCED_STATE_WRITE_SCRIPT,
            4,
            self._lease_key,
            state_key,
            heartbeat_key,
            channel,
            identity.wire_value,
            state_payload,
            heartbeat_payload,
        )
        if int(written or 0) != 1:
            self._identity = None
            raise OwnershipLostError("stale orchestrator owner rejected during state write")

    def fenced_value_write(self, *, key: str, value: str) -> None:
        identity = self._require_identity()
        written = self._redis.eval(
            _FENCED_VALUE_WRITE_SCRIPT,
            2,
            self._lease_key,
            key,
            identity.wire_value,
            value,
        )
        if int(written or 0) != 1:
            self._identity = None
            raise OwnershipLostError("stale orchestrator owner rejected during value write")

    def _require_identity(self) -> LeaseIdentity:
        if self._identity is None:
            raise OwnershipLostError("orchestrator has no active ownership lease")
        return self._identity
