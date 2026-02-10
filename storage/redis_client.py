"""
Redis Client Wrapper with Connection Pooling, Pub/Sub, and Streams support.
"""

import os
from typing import Any, Optional

import redis
from loguru import logger
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)


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
        url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        socket_timeout = int(os.getenv("REDIS_SOCKET_TIMEOUT_SEC", "5"))

        # Create connection pool for reuse
        self._pool = redis.ConnectionPool.from_url(
            url,
            decode_responses=True,
            socket_timeout=socket_timeout,
            socket_connect_timeout=socket_timeout,
            max_connections=50,
        )
        self.client = redis.Redis(connection_pool=self._pool)
        logger.info(f"Redis client initialized with connection pool: {url}")

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
        return self.client.ping()

    @retry(
        retry=retry_if_exception_type(
            (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError)
        ),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def set(self, key: str, value: str, ex: Optional[int] = None) -> None:
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
    def get(self, key: str) -> Optional[str]:
        """Get value by key."""
        return self.client.get(key)

    @retry(
        retry=retry_if_exception_type(
            (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError)
        ),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def hset(
        self, name: str, key: Optional[str] = None, value: Optional[str] = None,
        mapping: Optional[dict] = None
    ) -> int:
        """Set hash field(s)."""
        return self.client.hset(name, key, value, mapping)

    @retry(
        retry=retry_if_exception_type(
            (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError)
        ),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def hget(self, name: str, key: str) -> Optional[str]:
        """Get hash field value."""
        return self.client.hget(name, key)

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
        return self.client.delete(key)

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
        return self.client.publish(channel, message)

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
        maxlen: Optional[int] = None,
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
        return self.client.xadd(
            name, fields, id=id, maxlen=maxlen, approximate=approximate
        )

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
        count: Optional[int] = None,
        block: Optional[int] = None,
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
        return self.client.xread(streams, count=count, block=block)

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
        count: Optional[int] = None,
        block: Optional[int] = None,
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
        return self.client.xreadgroup(
            groupname, consumername, streams, count=count, block=block
        )

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
            return self.client.xgroup_create(
                name, groupname, id=id, mkstream=mkstream
            )
        except redis.exceptions.ResponseError as e:
            if "BUSYGROUP" in str(e):
                # Group already exists, this is fine
                logger.debug(f"Consumer group {groupname} already exists on {name}")
                return False
            raise


# Singleton instance for imports
redis_client = RedisClient()
