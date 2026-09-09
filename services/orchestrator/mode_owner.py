"""Redis-atomic mode writer lease; no verdict, risk or broker authority.

Every protected write and renewal compares the process token on the Redis server.
A lost/expired owner never silently reacquires. Redis ACL/admin/restore and old
unpatched writers require separate rollout isolation; this is cooperative fencing.
"""

from __future__ import annotations

from uuid import uuid4

import redis as redis_library
from redis.backoff import NoBackoff
from redis.retry import Retry

SCRIPT = """
-- wolf15-mode-owner-v1
local action, token = ARGV[1], ARGV[2]
if action == 'acquire' then
  if redis.call('GET', KEYS[1]) then return 0 end
  redis.call('SET', KEYS[1], token, 'PX', ARGV[3], 'NX')
  return 1
end
if redis.call('GET', KEYS[1]) ~= token then return 0 end
if action == 'check' then return 1 end
if action == 'renew' then return redis.call('PEXPIRE', KEYS[1], ARGV[3]) end
if action == 'release' then return redis.call('DEL', KEYS[1]) end
if action ~= 'write' then return redis.error_reply('MODE_OWNER_ACTION_INVALID') end
for i = 2, #KEYS do redis.call('SET', KEYS[i], ARGV[i+4]) end
if ARGV[4] ~= '' then redis.call('PUBLISH', ARGV[4], ARGV[5]) end
return 1
"""


class ModeOwnerUnavailableError(RuntimeError):
    pass


class ModeOwnerLease:
    def __init__(self, redis, *, key: str, ttl_ms: int = 30000):
        if not key or type(ttl_ms) is not int or ttl_ms < 100:
            raise ValueError("MODE_OWNER_LEASE_CONFIG_INVALID")
        self.redis, self.key, self.ttl_ms = redis, key, ttl_ms
        self.token = uuid4().hex
        self.attempted = False
        self.closed = False
        self._probe_redis = redis
        if isinstance(redis, redis_library.Redis):
            # Separate bounded socket: a stalled mode loop cannot stall health.
            kwargs = dict(redis.connection_pool.connection_kwargs)
            kwargs.update(
                socket_timeout=0.5, socket_connect_timeout=0.5, retry=Retry(NoBackoff(), 0), retry_on_timeout=False
            )
            pool = redis_library.ConnectionPool(
                connection_class=redis.connection_pool.connection_class, max_connections=1, **kwargs
            )
            self._probe_redis = redis_library.Redis(connection_pool=pool)

    def _execute(self, action, writes=(), channel="", event=""):
        keys = [self.key, *(key for key, _ in writes)]
        args = [action, self.token, self.ttl_ms, channel, event, *(value for _, value in writes)]
        try:
            result = self.redis.eval(SCRIPT, len(keys), *keys, *args)
        except Exception:
            raise ModeOwnerUnavailableError("MODE_OWNER_STORE_UNAVAILABLE") from None
        if result != 1:
            raise ModeOwnerUnavailableError("MODE_OWNER_STALE_OR_UNBOUND")

    def acquire(self):
        if self.attempted:
            raise ModeOwnerUnavailableError("MODE_OWNER_REACQUIRE_FORBIDDEN")
        self.attempted = True
        self._execute("acquire")

    def renew(self):
        self._execute("renew")

    def write(self, writes, *, channel="", event=""):
        self._execute("write", writes, channel, event)

    def is_current(self) -> bool:
        if not self.attempted or self.closed:
            return False
        try:
            return self._probe_redis.eval(SCRIPT, 1, self.key, "check", self.token, self.ttl_ms, "", "") == 1
        except Exception:
            return False

    def release(self):
        try:
            self._execute("release")
        finally:
            self.closed = True
            if self._probe_redis is not self.redis:
                self._probe_redis.connection_pool.disconnect()
