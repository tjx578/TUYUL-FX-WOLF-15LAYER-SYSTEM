"""
Redis Stream consumer with XACK, reconnect recovery, and PEL reprocessing.

Zone: infrastructure/ — message transport only. No market direction,
no execution authority, no Layer-12 override.

Design decisions:
- Uses redis.asyncio natively (no run_in_executor).
- XREADGROUP + XACK: messages acknowledged only after successful processing.
- On startup/reconnect: reprocesses pending entries (PEL) before reading new.
- Dynamic consumer name per instance.
- Pub/Sub used ONLY for ephemeral notifications (heartbeat, invalidation).
  Critical data (candles, signals, news) goes through Streams.

Message flow:
  Producer → XADD(stream) → Consumer Group → XREADGROUP → process → XACK
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

import redis.asyncio as aioredis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import ResponseError
from redis.exceptions import TimeoutError as RedisTimeoutError

from infrastructure.consumer_identity import generate_consumer_name
from infrastructure.redis_client import get_client

logger = logging.getLogger(__name__)


class StreamPriority(Enum):
    """Stream criticality — determines retry and recovery behavior."""
    CRITICAL = "critical"    # Signals, trades — must not lose
    IMPORTANT = "important"  # Candles, news — recover on reconnect
    EPHEMERAL = "ephemeral"  # Heartbeat, status — fire and forget


@dataclass(frozen=True)
class StreamBinding:
    """Binds a stream to its consumer group and processing callback."""
    stream: str
    group: str
    callback: Callable[[str, str, dict[str, str]], Awaitable[None]]
    priority: StreamPriority = StreamPriority.IMPORTANT
    max_pending_age_ms: int = 300_000  # Auto-claim messages older than 5 min


@dataclass
class ConsumerConfig:
    """Configuration for the stream consumer."""
    consumer_name: str | None = None
    consumer_prefix: str = "engine"
    block_ms: int = 2000
    batch_size: int = 10
    reconnect_delay_initial: float = 1.0
    reconnect_delay_max: float = 30.0
    reconnect_delay_factor: float = 2.0
    pending_check_interval: float = 30.0  # Seconds between PEL reprocessing sweeps
    max_retries_per_message: int = 5


@dataclass
class _ConsumerStats:
    """Internal tracking for observability."""
    messages_processed: int = 0
    messages_acked: int = 0
    messages_failed: int = 0
    pending_recovered: int = 0
    reconnects: int = 0
    last_message_at: float = 0.0


class StreamConsumer:
    """
    Async Redis Stream consumer with:
    - Native async Redis (no run_in_executor).
    - XACK after successful processing.
    - PEL recovery on startup and periodic sweeps.
    - Exponential backoff reconnect.
    - Dynamic consumer identity.
    """

    def __init__(
        self,
        bindings: list[StreamBinding],
        config: ConsumerConfig | None = None,
        redis_client: aioredis.Redis | None = None,
    ) -> None:
        if not bindings:
            raise ValueError("At least one StreamBinding is required")

        self._bindings = bindings
        self._config = config or ConsumerConfig()
        self._redis: aioredis.Redis | None = redis_client
        self._consumer_name = generate_consumer_name(
            prefix=self._config.consumer_prefix,
            override=self._config.consumer_name,
        )
        self._stats = _ConsumerStats()
        self._running = False
        self._tasks: list[asyncio.Task[None]] = []

        logger.info("StreamConsumer initialized: consumer=%s, streams=%s",
                     self._consumer_name,
                     [b.stream for b in self._bindings])

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "consumer_name": self._consumer_name,
            "messages_processed": self._stats.messages_processed,
            "messages_acked": self._stats.messages_acked,
            "messages_failed": self._stats.messages_failed,
            "pending_recovered": self._stats.pending_recovered,
            "reconnects": self._stats.reconnects,
            "last_message_at": self._stats.last_message_at,
            "running": self._running,
        }

    async def _ensure_redis(self) -> aioredis.Redis:
        """Get or create the Redis client."""
        if self._redis is None:
            self._redis = await get_client()
        return self._redis

    async def _ensure_groups(self) -> None:
        """Create consumer groups if they don't exist."""
        client = await self._ensure_redis()
        for binding in self._bindings:
            try:
                await client.xgroup_create(
                    name=binding.stream,
                    groupname=binding.group,
                    id="0",
                    mkstream=True,
                )
                logger.info("Created consumer group: stream=%s group=%s",
                            binding.stream, binding.group)
            except ResponseError as e:
                if "BUSYGROUP" in str(e):
                    logger.debug("Consumer group already exists: stream=%s group=%s",
                                 binding.stream, binding.group)
                else:
                    raise

    async def _process_message(
        self,
        binding: StreamBinding,
        message_id: str,
        fields: dict[str, str],
    ) -> bool:
        """
        Process a single message. Returns True if successfully processed.
        On success, ACKs the message. On failure, leaves in PEL for retry.
        """
        try:
            await binding.callback(binding.stream, message_id, fields)
            self._stats.messages_processed += 1
            self._stats.last_message_at = time.time()

            # ACK the message — this is the critical fix for the XACK issue
            client = await self._ensure_redis()
            await client.xack(binding.stream, binding.group, message_id)
            self._stats.messages_acked += 1

            logger.debug("ACK: stream=%s group=%s id=%s",
                         binding.stream, binding.group, message_id)
            return True

        except Exception:
            self._stats.messages_failed += 1
            logger.exception(
                "Failed to process message: stream=%s id=%s — left in PEL for retry",
                binding.stream, message_id,
            )
            return False

    async def _recover_pending(self, binding: StreamBinding) -> int:
        """
        Recover unacknowledged messages from the Pending Entries List (PEL).
        Called on startup and periodically.

        This fixes the Pub/Sub message loss issue — Streams retain messages
        until ACK'd, so reconnect recovery is automatic.

        Returns number of messages recovered.
        """
        client = await self._ensure_redis()
        recovered = 0

        try:
            # Read pending messages for THIS consumer (id="0" means start from oldest pending)
            response = await client.xreadgroup(
                groupname=binding.group,
                consumername=self._consumer_name,
                streams={binding.stream: "0"},
                count=self._config.batch_size,
            )

            if not response:
                return 0

            for _stream_name, messages in response:
                for message_id, fields in messages:
                    if not fields:
                        # Empty fields means the message was already fully delivered
                        # before — just ACK it
                        await client.xack(binding.stream, binding.group, message_id)
                        continue

                    success = await self._process_message(binding, message_id, fields)
                    if success:
                        recovered += 1

            if recovered > 0:
                self._stats.pending_recovered += recovered
                logger.info("Recovered %d pending messages: stream=%s",
                            recovered, binding.stream)

        except (RedisConnectionError, RedisTimeoutError):
            logger.warning("Connection lost during PEL recovery: stream=%s",
                           binding.stream)
            raise
        except Exception:
            logger.exception("Unexpected error during PEL recovery: stream=%s",
                             binding.stream)

        return recovered

    async def _autoclaim_stale(self, binding: StreamBinding) -> int:
        """
        Claim and reprocess messages stuck in other consumers' PEL
        (e.g., consumer crashed before ACK).

        Uses XAUTOCLAIM (Redis 6.2+).
        """
        client = await self._ensure_redis()
        claimed = 0

        try:
            # XAUTOCLAIM: claim messages idle for > max_pending_age_ms
            result = await client.xautoclaim(
                name=binding.stream,
                groupname=binding.group,
                consumername=self._consumer_name,
                min_idle_time=binding.max_pending_age_ms,
                start_id="0-0",
                count=self._config.batch_size,
            )

            # result format: [next_start_id, [(id, fields), ...], [deleted_ids]]
            if result and len(result) >= 2:
                messages = result[1]
                for message_id, fields in messages:
                    if fields:
                        success = await self._process_message(binding, message_id, fields)
                        if success:
                            claimed += 1

            if claimed > 0:
                logger.info("Auto-claimed %d stale messages: stream=%s",
                            claimed, binding.stream)

        except ResponseError as e:
            if "unknown command" in str(e).lower():
                logger.debug("XAUTOCLAIM not supported (Redis < 6.2), skipping")
            else:
                raise
        except (RedisConnectionError, RedisTimeoutError):
            raise
        except Exception:
            logger.exception("Error during autoclaim: stream=%s", binding.stream)

        return claimed

    async def _read_loop(self, binding: StreamBinding) -> None:
        """
        Main read loop for a single stream binding.
        Reads new messages with XREADGROUP and processes them.
        """
        client = await self._ensure_redis()

        while self._running:
            try:
                # ">" means read only NEW messages (not pending)
                response = await client.xreadgroup(
                    groupname=binding.group,
                    consumername=self._consumer_name,
                    streams={binding.stream: ">"},
                    count=self._config.batch_size,
                    block=self._config.block_ms,
                )

                if not response:
                    continue

                for _stream_name, messages in response:
                    for message_id, fields in messages:
                        await self._process_message(binding, message_id, fields)

            except (RedisConnectionError, RedisTimeoutError):
                if self._running:
                    raise  # Let the outer reconnect loop handle it
                break
            except asyncio.CancelledError:
                logger.info("Read loop cancelled: stream=%s", binding.stream)
                break
            except Exception:
                logger.exception("Unexpected error in read loop: stream=%s",
                                 binding.stream)
                await asyncio.sleep(1.0)

    async def _pending_sweep_loop(self) -> None:
        """
        Periodic sweep for pending messages and stale claims.
        Runs alongside read loops.
        """
        while self._running:
            try:
                await asyncio.sleep(self._config.pending_check_interval)
                if not self._running:
                    break

                for binding in self._bindings:
                    if binding.priority == StreamPriority.EPHEMERAL:
                        continue
                    await self._recover_pending(binding)
                    await self._autoclaim_stale(binding)

            except (RedisConnectionError, RedisTimeoutError):
                if self._running:
                    logger.warning("Connection lost during pending sweep")
                    break
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in pending sweep loop")

    async def _run_with_reconnect(self) -> None:
        """
        Outer loop: runs all read loops + pending sweep, with reconnect on failure.
        Exponential backoff on connection failures.
        """
        delay = self._config.reconnect_delay_initial

        while self._running:
            try:
                self._redis = None  # Force fresh connection
                await self._ensure_redis()
                await self._ensure_groups()

                # Recover pending messages BEFORE reading new ones
                for binding in self._bindings:
                    if binding.priority != StreamPriority.EPHEMERAL:
                        await self._recover_pending(binding)

                logger.info("StreamConsumer connected: consumer=%s", self._consumer_name)
                delay = self._config.reconnect_delay_initial  # Reset backoff

                # Launch parallel tasks: one read loop per binding + pending sweep
                tasks: list[asyncio.Task[None]] = []
                for binding in self._bindings:
                    task = asyncio.create_task(
                        self._read_loop(binding),
                        name=f"read_{binding.stream}",
                    )
                    tasks.append(task)

                sweep_task = asyncio.create_task(
                    self._pending_sweep_loop(),
                    name="pending_sweep",
                )
                tasks.append(sweep_task)

                self._tasks = tasks

                # Wait for any task to fail (connection loss)
                done, pending = await asyncio.wait(
                    tasks, return_when=asyncio.FIRST_EXCEPTION,
                )

                # Cancel remaining tasks
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)

                # Check if any task raised
                for task in done:
                    if task.exception() and not isinstance(task.exception(), asyncio.CancelledError):
                        raise task.exception()  # type: ignore[misc]

            except asyncio.CancelledError:
                logger.info("StreamConsumer cancelled")
                break

            except (RedisConnectionError, RedisTimeoutError, OSError) as e:
                if not self._running:
                    break
                self._stats.reconnects += 1
                logger.warning(
                    "Redis connection lost (%s). Reconnecting in %.1fs... (attempt #%d)",
                    type(e).__name__, delay, self._stats.reconnects,
                )
                await asyncio.sleep(delay)
                delay = min(delay * self._config.reconnect_delay_factor,
                            self._config.reconnect_delay_max)

            except Exception:
                if not self._running:
                    break
                self._stats.reconnects += 1
                logger.exception("Unexpected error in consumer. Reconnecting in %.1fs...", delay)
                await asyncio.sleep(delay)
                delay = min(delay * self._config.reconnect_delay_factor,
                            self._config.reconnect_delay_max)

    async def start(self) -> None:
        """Start the consumer. Call from your async main."""
        if self._running:
            logger.warning("StreamConsumer already running")
            return
        self._running = True
        logger.info("StreamConsumer starting: consumer=%s", self._consumer_name)
        await self._run_with_reconnect()

    async def stop(self) -> None:
        """Graceful shutdown."""
        logger.info("StreamConsumer stopping: consumer=%s", self._consumer_name)
        self._running = False

        for task in self._tasks:
            task.cancel()

        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()

        logger.info("StreamConsumer stopped: consumer=%s", self._consumer_name)
