"""
Redis high-availability configuration — Sentinel and Cluster support.

Zone: infrastructure/ — shared utility, no business logic.

Provides ``get_ha_client()`` which returns an async Redis client configured
for the deployment topology:

  1. **Sentinel**: Automatic primary discovery and failover.
     Set ``REDIS_SENTINEL_HOSTS=host1:26379,host2:26379,host3:26379``
     and optionally ``REDIS_SENTINEL_MASTER=mymaster``.

  2. **Cluster**: Redis Cluster mode with automatic slot routing.
     Set ``REDIS_CLUSTER_HOSTS=host1:6379,host2:6379,host3:6379``.

  3. **Standalone**: Falls back to the standard ``RedisClientManager``
     when no Sentinel/Cluster env vars are set.

Priority: REDIS_SENTINEL_HOSTS > REDIS_CLUSTER_HOSTS > standalone.

Environment variables
---------------------
REDIS_SENTINEL_HOSTS        — comma-separated host:port pairs for Sentinel
REDIS_SENTINEL_MASTER       — Sentinel master name (default: ``mymaster``)
REDIS_SENTINEL_PASSWORD     — Sentinel auth password (optional)
REDIS_SENTINEL_DB           — database index (default: 0)
REDIS_CLUSTER_HOSTS         — comma-separated host:port pairs for Cluster
REDIS_CLUSTER_PASSWORD      — Cluster auth password (optional)
"""

from __future__ import annotations

import logging
import os

import redis.asyncio as aioredis
from redis.asyncio.cluster import ClusterNode

logger = logging.getLogger(__name__)


def _parse_host_list(raw: str) -> list[tuple[str, int]]:
    """Parse ``host1:port1,host2:port2`` into list of (host, port) tuples."""
    hosts: list[tuple[str, int]] = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" in entry:
            host, port_str = entry.rsplit(":", 1)
            hosts.append((host.strip(), int(port_str)))
        else:
            hosts.append((entry, 6379))
    return hosts


class SentinelClientManager:
    """
    Async Redis client via Sentinel for automatic failover.

    On primary failure, Sentinel transparently promotes a replica and
    this manager's next ``get_client()`` call discovers the new primary.
    """

    def __init__(self) -> None:
        self._sentinel: aioredis.Sentinel | None = None

    def _get_config(self) -> tuple[list[tuple[str, int]], str, str | None, int]:
        raw = os.environ.get("REDIS_SENTINEL_HOSTS", "")
        hosts = _parse_host_list(raw)
        master_name = os.environ.get("REDIS_SENTINEL_MASTER", "mymaster")
        password = os.environ.get("REDIS_SENTINEL_PASSWORD") or os.environ.get("REDIS_PASSWORD") or None
        db = int(os.environ.get("REDIS_SENTINEL_DB", "0"))
        return hosts, master_name, password, db

    async def get_client(self) -> aioredis.Redis:
        """Return an async Redis client connected to the Sentinel-managed primary."""
        if self._sentinel is None:
            hosts, master_name, password, db = self._get_config()
            sentinel_kwargs = {}
            if os.environ.get("REDIS_SENTINEL_PASSWORD"):
                sentinel_kwargs["password"] = os.environ["REDIS_SENTINEL_PASSWORD"]

            self._sentinel = aioredis.Sentinel(
                sentinels=hosts,
                socket_timeout=5.0,
                socket_connect_timeout=5.0,
                sentinel_kwargs=sentinel_kwargs,
            )
            logger.info(
                "Redis Sentinel initialized: %d nodes, master=%s",
                len(hosts),
                master_name,
            )

        _, master_name, password, db = self._get_config()
        return self._sentinel.master_for(
            master_name,
            redis_class=aioredis.Redis,
            password=password,
            db=db,
            decode_responses=True,
        )

    async def get_replica_client(self) -> aioredis.Redis:
        """Return an async Redis client connected to a Sentinel-managed replica.

        Use this for read-only dashboard queries to offload the primary.
        """
        if self._sentinel is None:
            await self.get_client()  # ensure sentinel is initialized

        _, master_name, password, db = self._get_config()
        return self._sentinel.slave_for(  # type: ignore[union-attr]
            master_name,
            redis_class=aioredis.Redis,
            password=password,
            db=db,
            decode_responses=True,
        )

    async def close(self) -> None:
        # Sentinel object doesn't hold a pool directly; clients do.
        self._sentinel = None


class ClusterClientManager:
    """
    Async Redis Cluster client with automatic slot routing.
    """

    def __init__(self) -> None:
        self._client: aioredis.RedisCluster | None = None

    async def get_client(self) -> aioredis.RedisCluster:
        if self._client is None:
            raw = os.environ.get("REDIS_CLUSTER_HOSTS", "")
            hosts = _parse_host_list(raw)
            password = os.environ.get("REDIS_CLUSTER_PASSWORD") or os.environ.get("REDIS_PASSWORD") or None

            startup_nodes = [ClusterNode(host=h, port=p) for h, p in hosts]  # noqa: F821

            self._client = aioredis.RedisCluster(
                startup_nodes=startup_nodes,
                password=password,
                decode_responses=True,
                socket_timeout=5.0,
                socket_connect_timeout=5.0,
            )
            logger.info("Redis Cluster initialized: %d startup nodes", len(hosts))

        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


# ── Module-level factory ──────────────────────────────────────────────────────

_sentinel_mgr: SentinelClientManager | None = None
_cluster_mgr: ClusterClientManager | None = None


def get_ha_mode() -> str:
    """Detect Redis HA mode from environment.

    Returns ``"sentinel"``, ``"cluster"``, or ``"standalone"``.
    """
    if os.environ.get("REDIS_SENTINEL_HOSTS"):
        return "sentinel"
    if os.environ.get("REDIS_CLUSTER_HOSTS"):
        return "cluster"
    return "standalone"


async def get_ha_client() -> aioredis.Redis | aioredis.RedisCluster:
    """Return an async Redis client appropriate for the deployment topology.

    Priority:
      1. Sentinel (if ``REDIS_SENTINEL_HOSTS`` is set)
      2. Cluster  (if ``REDIS_CLUSTER_HOSTS`` is set)
      3. Standalone (standard ``RedisClientManager``)
    """
    global _sentinel_mgr, _cluster_mgr

    mode = get_ha_mode()

    if mode == "sentinel":
        if _sentinel_mgr is None:
            _sentinel_mgr = SentinelClientManager()
        return await _sentinel_mgr.get_client()

    if mode == "cluster":
        if _cluster_mgr is None:
            _cluster_mgr = ClusterClientManager()
        return await _cluster_mgr.get_client()

    # Fallback: standalone
    from infrastructure.redis_client import get_client

    return await get_client()


async def get_replica_client() -> aioredis.Redis:
    """Return a read-replica client for Sentinel deployments.

    For non-Sentinel topologies, returns the regular client.
    Useful for offloading dashboard read queries from the primary.
    """
    global _sentinel_mgr

    if get_ha_mode() == "sentinel":
        if _sentinel_mgr is None:
            _sentinel_mgr = SentinelClientManager()
        return await _sentinel_mgr.get_replica_client()

    # Non-sentinel: return standard client
    from infrastructure.redis_client import get_client

    return await get_client()


async def close_ha() -> None:
    """Close all HA managers. Call during app shutdown."""
    global _sentinel_mgr, _cluster_mgr

    if _sentinel_mgr is not None:
        await _sentinel_mgr.close()
        _sentinel_mgr = None
    if _cluster_mgr is not None:
        await _cluster_mgr.close()
        _cluster_mgr = None
