"""
Redis Stream consumer — native async, XACK, PEL recovery, exponential backoff.

Zone: infrastructure/ — message transport only. No market direction,
no execution authority, no Layer-12 override.

Fixes applied:
- 🔴 run_in_executor removed: uses redis.asyncio natively.
- 🔴 XACK added: messages acknowledged only after successful processing.
- ⚠️ sleep(1) replaced: exponential backoff with jitter.
- ⚠️ Pub/Sub loss mitigated: critical data uses Streams with PEL recovery.

Message lifecycle:
  Producer → XADD → Consumer Group → XREADGROUP → callback() → XACK
  On failure: message stays in PEL → retried on next sweep / reconnect.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import redis.asyncio as aioredis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import ResponseError
from redis.exceptions import TimeoutError as RedisTimeoutError

from infrastructure.backoff import BackoffConfig, ExponentialBackoff
from infrastructure.consumer_identity import generate_consumer_name
from infrastructure.redis_client import get_client

logger = logging.getLogger(__name__)


class StreamPriority(Enum):
    """Determines retry and recovery behavior."""
    CRITICAL = "critical"    # Signals, trades — must not lose, PEL recovery
    IMPORTANT = "important"  # Candles, news — PEL recovery on reconnect
    EPHEMERAL = "ephemeral"  # Heartbeat — no PEL sweep


@dataclass(frozen=True)
class StreamBinding:
    """Binds a stream to its consumer group and processing callback."""
    stream: str
    group: str
    callback: Callable[[str, str, dict[str, str]], Awaitable[None]]
    priority: StreamPriority = StreamPriority.IMPORTANT
    max_pending_age_ms: int = 300_000  # Auto-claim idle messages > 5 min


@dataclass
class ConsumerConfig:
    """Configuration for the stream consumer."""
    consumer_name: str | None = None
    consumer_prefix: str = "engine"
    block_ms: int = 2000
    batch_size: int = 10
    pending_sweep_interval: float = 30.0
    max_retries_per_message: int = 5
    backoff: BackoffConfig = field(
        default_factory=lambda: BackoffConfig(
            initial=1.0,
            maximum=30.0,
            factor=2.0,
            jitter=0.25,
        )
    )

    def __post_init__(self) -> None:
        if isinstance(self.backoff, dict):
            object.__setattr__(self, "backoff", BackoffConfig(**self.backoff))


@dataclass
class ConsumerStats:
    """Observable consumer metrics."""
    messages_processed: int = 0
    messages_acked: int = 0
    messages_failed: int = 0
    pending_recovered: int = 0
    pending_autoclaimed: int = 0
    reconnects: int = 0
    last_message_at: float = 0.0
    last_error: str | None = None
    last_error_at: float = 0.0


class StreamConsumer:
    """
    Async Redis Stream consumer.

    Native async — no run_in_executor.
    XREADGROUP + XACK: messages acknowledged only after successful processing.
    PEL recovery on startup and periodic sweeps.
    Exponential backoff with jitter on connection failures.
    Dynamic consumer name per instance.
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
        self._stats = ConsumerStats()
        self._backoff = ExponentialBackoff(self._config.backoff)
        self._running = False
        self._tasks: list[asyncio.Task[None]] = []

        logger.info(
            "StreamConsumer init: consumer=%s streams=%s backoff=%s",
            self._consumer_name,
            [b.stream for b in self._bindings],
            f"initial={self._config.backoff.initial}s "
            f"max={self._config.backoff.maximum}s "
            f"factor={self._config.backoff.factor}x",
        )

    @property
    def consumer_name(self) -> str:
        return self._consumer_name

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "consumer_name": self._consumer_name,
            "messages_processed": self._stats.messages_processed,
            "messages_acked": self._stats.messages_acked,
            "messages_failed": self._stats.messages_failed,
            "pending_recovered": self._stats.pending_recovered,
            "pending_autoclaimed": self._stats.pending_autoclaimed,
            "reconnects": self._stats.reconnects,
            "last_message_at": self._stats.last_message_at,
            "last_error": self._stats.last_error,
            "last_error_at": self._stats.last_error_at,
            "running": self._running,
        }

    # ─── Redis / Group Setup ─────────────────────────────────

    async def _ensure_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = await get_client()
        return self._redis

    async def _ensure_groups(self) -> None:
        """Create consumer groups if they don't exist. Idempotent."""
        client = await self._ensure_redis()
        for binding in self._bindings:
            try:
                await client.xgroup_create(
                    name=binding.stream,
                    groupname=binding.group,
                    id="0",
                    mkstream=True,
                )
                logger.info(
                    "Created consumer group: stream=%s group=%s",
                    binding.stream, binding.group,
                )
            except ResponseError as e:
                if "BUSYGROUP" in str(e):
                    logger.debug(
                        "Consumer group exists: stream=%s group=%s",
                        binding.stream, binding.group,
                    )
                else:
                    raise

    # ─── Message Processing + XACK ───────────────────────────

    async def _process_and_ack(
        self,
        binding: StreamBinding,
        message_id: str,
        fields: dict[str, str],
    ) -> bool:
        """
        Process a single message via callback, then XACK on success.

        On failure: message stays in PEL for retry. Not ACK'd.
        This is the critical fix for the missing-XACK issue.

        Returns True if processed and ACK'd successfully.
        """
        try:
            # Step 1: Process via user callback
            await binding.callback(binding.stream, message_id, fields)
            self._stats.messages_processed += 1
            self._stats.last_message_at = time.time()

            # Step 2: ACK — only after successful processing
            client = await self._ensure_redis()
            await client.xack(binding.stream, binding.group, message_id)
            self._stats.messages_acked += 1

            logger.debug(
                "Processed+ACK: stream=%s id=%s",
                binding.stream, message_id,
            )
            return True

        except (RedisConnectionError, RedisTimeoutError):
            # Connection-level errors bubble up for reconnect handling
            raise

        except Exception as exc:
            # Application error — message stays in PEL for retry
            self._stats.messages_failed += 1
            self._stats.last_error = f"{type(exc).__name__}: {exc}"
            self._stats.last_error_at = time.time()
            logger.exception(
                "Processing failed (no ACK, stays in PEL): stream=%s id=%s",
                binding.stream, message_id,
            )
            return False

    # ─── PEL Recovery ────────────────────────────────────────

    async def _recover_pending(self, binding: StreamBinding) -> int:
        """
        Reprocess unacknowledged messages from this consumer's PEL.

        Called on startup and periodically. Fixes the Pub/Sub message-loss
        issue: Streams retain messages until ACK'd, so reconnect recovery
        is automatic for any data routed through Streams.

        Returns number of messages recovered and ACK'd.
        """
        client = await self._ensure_redis()
        recovered = 0

        try:
            # id="0" reads oldest pending for THIS consumer
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
                        # Empty fields = already delivered, just ACK
                        await client.xack(
                            binding.stream, binding.group, message_id,
                        )
                        continue

                    if await self._process_and_ack(binding, message_id, fields):
                        recovered += 1

            if recovered > 0:
                self._stats.pending_recovered += recovered
                logger.info(
                    "PEL recovery: %d messages from stream=%s",
                    recovered, binding.stream,
                )

        except (RedisConnectionError, RedisTimeoutError):
            raise
        except Exception:
            logger.exception(
                "PEL recovery error: stream=%s", binding.stream,
            )

        return recovered

    async def _autoclaim_stale(self, binding: StreamBinding) -> int:
        """
        Claim messages stuck in other consumers' PEL (crashed consumers).
        Uses XAUTOCLAIM (Redis 6.2+).
        """
        client = await self._ensure_redis()
        claimed = 0

        try:
            result = await client.xautoclaim(
                name=binding.stream,
                groupname=binding.group,
                consumername=self._consumer_name,
                min_idle_time=binding.max_pending_age_ms,
                start_id="0-0",
                count=self._config.batch_size,
            )

            # result: [next_start_id, [(id, fields), ...], [deleted_ids]]
            if result and len(result) >= 2:
                for message_id, fields in result[1]:
                    if fields and await self._process_and_ack(binding, message_id, fields):
                        claimed += 1

            if claimed > 0:
                self._stats.pending_autoclaimed += claimed
                logger.info(
                    "Autoclaimed %d stale messages: stream=%s",
                    claimed, binding.stream,
                )

        except ResponseError as e:
            if "unknown command" in str(e).lower():
                logger.debug("XAUTOCLAIM unsupported (Redis < 6.2)")
            else:
                raise
        except (RedisConnectionError, RedisTimeoutError):
            raise
        except Exception:
            logger.exception(
                "Autoclaim error: stream=%s", binding.stream,
            )

        return claimed

    # ─── Main Loops ──────────────────────────────────────────

    async def _read_loop(self, binding: StreamBinding) -> None:
        """Read new messages from a single stream. Runs until stopped."""
        client = await self._ensure_redis()

        while self._running:
            try:
                # ">" = only NEW messages (pending handled separately)
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
                        await self._process_and_ack(
                            binding, message_id, fields,
                        )

            except (RedisConnectionError, RedisTimeoutError):
                if self._running:
                    raise
                break
            except asyncio.CancelledError:
                logger.debug("Read loop cancelled: stream=%s", binding.stream)
                break
            except Exception:
                # Application-level error in loop — do NOT sleep(1)
                # The _process_and_ack already handles per-message errors.
                # If we get here, it's an unexpected loop-level issue.
                self._stats.last_error = "read_loop_unexpected"
                self._stats.last_error_at = time.time()
                logger.exception(
                    "Unexpected read loop error: stream=%s", binding.stream,
                )
                # Brief pause to prevent tight error loop, but not backoff
                # (backoff is for connection-level failures in the outer loop)
                await asyncio.sleep(0.5)

    async def _pending_sweep_loop(self) -> None:
        """Periodic PEL recovery + autoclaim sweep."""
        while self._running:
            try:
                await asyncio.sleep(self._config.pending_sweep_interval)
                if not self._running:
                    break

                for binding in self._bindings:
                    if binding.priority == StreamPriority.EPHEMERAL:
                        continue
                    await self._recover_pending(binding)
                    await self._autoclaim_stale(binding)

            except (RedisConnectionError, RedisTimeoutError):
                if self._running:
                    raise
                break
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Pending sweep error")

    # ─── Outer Reconnect Loop (exponential backoff) ──────────

    async def _run_with_reconnect(self) -> None:
        """
        Outer loop: connect → recover PEL → read → reconnect on failure.

        Uses exponential backoff with jitter instead of sleep(1).
        Resets backoff after successful connection.
        """
        while self._running:
            try:
                # Fresh connection on each attempt
                self._redis = None
                await self._ensure_redis()
                await self._ensure_groups()

                # Recover pending BEFORE reading new
                for binding in self._bindings:
                    if binding.priority != StreamPriority.EPHEMERAL:
                        await self._recover_pending(binding)

                logger.info(
                    "StreamConsumer connected: consumer=%s (attempt reset)",
                    self._consumer_name,
                )
                self._backoff.reset()  # Success — reset backoff

                # Launch parallel tasks
                tasks: list[asyncio.Task[None]] = []
                for binding in self._bindings:
                    tasks.append(asyncio.create_task(
                        self._read_loop(binding),
                        name=f"read:{binding.stream}",
                    ))
                tasks.append(asyncio.create_task(
                    self._pending_sweep_loop(),
                    name="pending_sweep",
                ))
                self._tasks = tasks

                # Wait for first failure
                done, pending = await asyncio.wait(
                    tasks, return_when=asyncio.FIRST_EXCEPTION,
                )

                # Cancel remaining
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)

                # Re-raise task exceptions
                for task in done:
                    exc = task.exception()
                    if exc and not isinstance(exc, asyncio.CancelledError):
                        raise exc

            except asyncio.CancelledError:
                logger.info("StreamConsumer cancelled")
                break

            except (RedisConnectionError, RedisTimeoutError, OSError) as exc:
                if not self._running:
                    break
                self._stats.reconnects += 1
                delay = self._backoff.next_delay()
                self._stats.last_error = f"{type(exc).__name__}"
                self._stats.last_error_at = time.time()
                logger.warning(
                    "Redis connection lost (%s). "
                    "Reconnecting in %.2fs (attempt #%d, backoff #%d)",
                    type(exc).__name__,
                    delay,
                    self._stats.reconnects,
                    self._backoff.attempt,
                )
                await asyncio.sleep(delay)

            except Exception as exc:
                if not self._running:
                    break
                self._stats.reconnects += 1
                delay = self._backoff.next_delay()
                self._stats.last_error = f"{type(exc).__name__}: {exc}"
                self._stats.last_error_at = time.time()
                logger.exception(
                    "Unexpected error. Reconnecting in %.2fs (attempt #%d)",
                    delay,
                    self._stats.reconnects,
                )
                await asyncio.sleep(delay)

    # ─── Public API ──────────────────────────────────────────

    async def start(self) -> None:
        """Start the consumer. Blocks until stop() is called."""
        if self._running:
            logger.warning("StreamConsumer already running: %s", self._consumer_name)
            return
        self._running = True
        logger.info("StreamConsumer starting: %s", self._consumer_name)
        await self._run_with_reconnect()

    async def stop(self) -> None:
        """Graceful shutdown. Cancels all tasks."""
        logger.info("StreamConsumer stopping: %s", self._consumer_name)
        self._running = False

        for task in self._tasks:
            task.cancel()

        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()

        logger.info(
            "StreamConsumer stopped: %s (processed=%d acked=%d failed=%d recovered=%d)",
            self._consumer_name,
            self._stats.messages_processed,
            self._stats.messages_acked,
            self._stats.messages_failed,
            self._stats.pending_recovered,
        )
