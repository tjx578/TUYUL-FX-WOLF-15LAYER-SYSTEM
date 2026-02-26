"""
Redis Client Wrapper with Connection Pooling, Pub/Sub, and Streams support.
"""

import os
from typing import Any, Optional, cast  # noqa: UP035
from urllib.parse import urlsplit, urlunsplit

import redis
import redis.client
import redis.exceptions
from loguru import logger
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


def _sanitize_redis_url(url: str) -> str:
    """Mask password in Redis URL for safe logging."""
    parts = urlsplit(url)
    if not parts.netloc or "@" not in parts.netloc:
        return url

    userinfo, hostinfo = parts.netloc.rsplit("@", 1)
    if ":" not in userinfo:
        return url

    username, _password = userinfo.split(":", 1)
    safe_netloc = f"{username}:***@{hostinfo}"
    return urlunsplit((parts.scheme, safe_netloc, parts.path, parts.query, parts.fragment))


class RedisClient:
    """
    Thread-safe Redis client with connection pooling and retry logic.

    Supports:
      - Basic key-value operations
      - Pub/Sub messaging
      - Redis Streams (XADD, XREAD, consumer groups)
      - Health checks
    """

    _instance: Optional["RedisClient"] = None

    def __new__(cls) -> "RedisClient":
        if not cls._instance:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self) -> None:
        """Initialize Redis connection pool."""
        from infrastructure.redis_url import get_redis_url
        url = get_redis_url()
        socket_timeout = int(os.getenv("REDIS_SOCKET_TIMEOUT_SEC", "5"))

        # TCP_OVERWINDOW fix: enable keepalive, reduce pool size,
        # add health-check interval to prune idle connections.
        # NOTE: Only SO_KEEPALIVE is set here (socket_keepalive=True).
        # Detailed keepalive timing (idle/interval/count) is handled
        # server-side via Redis --tcp-keepalive.  Passing
        # socket_keepalive_options with TCP_KEEPIDLE etc. causes EINVAL
        # on some container runtimes (e.g. Railway Alpine).
        self._pool = redis.ConnectionPool.from_url(
            url,
            decode_responses=True,
            socket_timeout=socket_timeout,
            socket_connect_timeout=socket_timeout,
            max_connections=20,
            socket_keepalive=True,
            health_check_interval=30,
            retry_on_timeout=True,
        )
        self.client = redis.Redis(connection_pool=self._pool)
        logger.info(
            "Redis client initialized with connection pool: {}",
            _sanitize_redis_url(url),
        )

    @retry(
        retry=retry_if_exception_type(
            (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError)
        ),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def ping(self) -> bool:
        """
        Health check for Redis connection.

        Returns:
            True if Redis is reachable and responsive.

        Raises:
            redis.exceptions.ConnectionError: If connection fails after retries.
        """
        result = self.client.ping()
        return bool(result)

    @retry(
        retry=retry_if_exception_type(
            (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError)
        ),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def set(self, key: str, value: str, ex: int | None = None) -> None:
        """Set key-value with optional expiration."""
        self.client.set(key, value, ex=ex)

    @retry(
        retry=retry_if_exception_type(
            (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError)
        ),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def get(self, key: str) -> str | None:
        """Get value by key."""
        return cast(str | None, self.client.get(key))

    @retry(
        retry=retry_if_exception_type(
            (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError)
        ),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def hset(self, name: str, mapping: dict | None = None, **kwargs: Any) -> int:
        """
        Set hash field(s).

        Args:
            name: Hash name.
            mapping: Dictionary of field-value pairs.
            **kwargs: Alternative way to specify field-value pairs.

        Returns:
            Number of fields that were added.
        """
        if mapping:
            return cast(int, self.client.hset(name, mapping=mapping))
        return cast(int, self.client.hset(name, **kwargs))

    @retry(
        retry=retry_if_exception_type(
            (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError)
        ),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def hget(self, name: str, key: str) -> str | None:
        """Get hash field value."""
        return cast(str | None, self.client.hget(name, key))

    @retry(
        retry=retry_if_exception_type(
            (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError)
        ),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def delete(self, key: str) -> int:
        """Delete key."""
        return cast(int, self.client.delete(key))

    def pubsub(self) -> redis.client.PubSub:
        """
        Get a Pub/Sub instance for subscribing to channels.

        Returns:
            redis.client.PubSub instance for subscribing.
        """
        return self.client.pubsub()

    @retry(
        retry=retry_if_exception_type(
            (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError)
        ),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def publish(self, channel: str, message: str) -> int:
        """
        Publish message to a channel.

        Args:
            channel: Channel name.
            message: Message payload.

        Returns:
            Number of subscribers that received the message.
        """
        return cast(int, self.client.publish(channel, message))

    @retry(
        retry=retry_if_exception_type(
            (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError)
        ),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def xadd(
        self,
        name: str,
        fields: dict[str, Any],
        id: str = "*",
        maxlen: int | None = None,
        approximate: bool = True,
    ) -> str:
        """
        Add entry to a Redis Stream.

        Args:
            name: Stream name.
            fields: Dictionary of field-value pairs.
            id: Entry ID (default "*" for auto-generate).
            maxlen: Maximum stream length (oldest entries trimmed).
            approximate: Use approximate trimming (~) for performance.

        Returns:
            Entry ID assigned by Redis.
        """
        return cast(str, self.client.xadd(name, fields, id=id, maxlen=maxlen, approximate=approximate))  # type: ignore[arg-type]

    @retry(
        retry=retry_if_exception_type(
            (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError)
        ),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def xread(
        self,
        streams: dict[str, str],
        count: int | None = None,
        block: int | None = None,
    ) -> list:
        """
        Read from Redis Streams.

        Args:
            streams: Dict mapping stream names to last seen IDs (use "0" for all).
            count: Max number of entries to read per stream.
            block: Block for N milliseconds if no data (None = no blocking).

        Returns:
            List of [stream_name, [(entry_id, fields), ...]] tuples.
        """
        return cast(list, self.client.xread(streams, count=count, block=block)) # type: ignore

    @retry(
        retry=retry_if_exception_type(
            (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError)
        ),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def xreadgroup(
        self,
        groupname: str,
        consumername: str,
        streams: dict[str, str],
        count: int | None = None,
        block: int | None = None,
    ) -> list:
        """
        Read from Redis Streams using a consumer group.

        Args:
            groupname: Consumer group name.
            consumername: Consumer name within the group.
            streams: Dict mapping stream names to last seen IDs (use ">" for new).
            count: Max number of entries to read per stream.
            block: Block for N milliseconds if no data.

        Returns:
            List of [stream_name, [(entry_id, fields), ...]] tuples.
        """
        return cast(list, self.client.xreadgroup(groupname, consumername, streams, count=count, block=block)) # type: ignore

    @retry(
        retry=retry_if_exception_type(
            (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError)
        ),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def xgroup_create(
        self,
        name: str,
        groupname: str,
        id: str = "0",
        mkstream: bool = True,
    ) -> bool:
        """
        Create a consumer group for a stream.

        Args:
            name: Stream name.
            groupname: Consumer group name.
            id: Starting position ("0" for beginning, "$" for new entries only).
            mkstream: Create stream if it doesn't exist.

        Returns:
            True if group was created.

        Raises:
            redis.exceptions.ResponseError: If group already exists.
        """
        try:
            return cast(bool, self.client.xgroup_create(name, groupname, id=id, mkstream=mkstream))
        except redis.exceptions.ResponseError as e:
            if "BUSYGROUP" in str(e):
                # Group already exists, this is fine
                logger.debug(f"Consumer group {groupname} already exists on {name}")
                return False
            raise


# Singleton instance for imports
redis_client = RedisClient()
