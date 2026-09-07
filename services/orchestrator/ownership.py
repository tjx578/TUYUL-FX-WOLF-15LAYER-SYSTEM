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

_FENCED_LEGACY_IMPORT_SCRIPT = """
-- wolf15:orchestrator:fenced-legacy-import:v1
-- Every check precedes the sole mutation. State and provenance are one value.
for i = 1, 4 do
  for j = i + 1, 4 do
    if KEYS[i] == KEYS[j] then return -3 end
  end
  if redis.call('TYPE', KEYS[i]).ok ~= 'string' then return -2 end
end
if redis.call('GET', KEYS[1]) ~= ARGV[1] or redis.call('PTTL', KEYS[1]) <= 0 then
  return -1
end
local clock = redis.call('TIME')
local now_ms = tonumber(clock[1]) * 1000 + math.floor(tonumber(clock[2]) / 1000)
if now_ms >= tonumber(ARGV[8]) then return -3 end
for i = 2, 4 do
  if redis.call('PTTL', KEYS[i]) ~= -1 or redis.call('GET', KEYS[i]) ~= ARGV[i] then
    return -2
  end
end
local ok_old, old = pcall(cjson.decode, ARGV[2])
local ok_kill, kill = pcall(cjson.decode, ARGV[3])
local ok_new, new = pcall(cjson.decode, ARGV[5])
if not ok_old or not ok_kill or not ok_new then return -3 end
if type(old) ~= 'table' or type(kill) ~= 'table' or type(new) ~= 'table' then return -3 end
if old.schema ~= nil or old.mode ~= 'KILL_SWITCH' or kill.active ~= true then return -3 end
if new.schema ~= 'wolf15.orchestrator.state/v2' or new.commit_marker ~= 'COMMITTED' then return -3 end
if new.state_revision ~= 1 or new.event ~= 'IMPORT_COMMITTED' then return -3 end
if new.owner_id ~= ARGV[6] or new.fence_generation ~= tonumber(ARGV[7]) then return -3 end
if new.mode ~= old.mode or new.reason ~= old.reason or new.compliance_code ~= old.compliance_code
  or new.updated_at ~= old.updated_at or new.source ~= old.source or new.channel ~= old.channel then return -3 end
local p = new.legacy_import
if type(p) ~= 'table' or p.schema ~= 'wolf15.orchestrator.legacy-import/v1'
  or p.imported_owner_id ~= new.owner_id or p.imported_fence_generation ~= new.fence_generation then return -3 end
redis.call('SET', KEYS[2], ARGV[5])
return 1
"""


class LegacyImportConflictError(RuntimeError):
    """The compare/import operation rejected its preconditions without writing."""


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

    def fenced_legacy_import(
        self,
        *,
        state_key: str,
        kill_key: str,
        heartbeat_key: str,
        old_state: bytes,
        old_kill: bytes,
        old_heartbeat: bytes,
        new_state: bytes,
        valid_until_epoch_ms: int,
    ) -> None:
        """One SET after lease, exact bytes and type/TTL validation; no publication.

        The caller must validate the package and persist its protected raw archive
        before acquiring ownership. A transport error has an ambiguous outcome.
        """
        from services.orchestrator.legacy_import_contract import ImportHoldError, validate_import_state

        identity = self._require_identity()
        validate_import_state(new_state, old_state=old_state, owner=identity.owner_id, generation=identity.generation)
        if type(valid_until_epoch_ms) is not int or valid_until_epoch_ms < 1:
            raise ImportHoldError("INVALID_APPLY_DEADLINE")
        result = int(
            self._redis.eval(
                _FENCED_LEGACY_IMPORT_SCRIPT,
                4,
                self._lease_key,
                state_key,
                kill_key,
                heartbeat_key,
                identity.wire_value,
                old_state,
                old_kill,
                old_heartbeat,
                new_state,
                identity.owner_id,
                identity.generation,
                valid_until_epoch_ms,
            )
        )
        if result == -1:
            self._identity = None
            raise OwnershipLostError("legacy import lease no longer held")
        if result != 1:
            raise LegacyImportConflictError("LEGACY_IMPORT_CAS_REJECTED")

    def _require_identity(self) -> LeaseIdentity:
        if self._identity is None:
            raise OwnershipLostError("orchestrator has no active ownership lease")
        return self._identity
