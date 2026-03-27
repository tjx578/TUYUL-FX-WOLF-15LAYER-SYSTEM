"""Finnhub WebSocket client with exponential backoff and distributed locking."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import random
import time
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, cast

import websockets
import websockets.asyncio.client
from prometheus_client import Counter, Gauge
from redis.asyncio import Redis
from websockets.asyncio.client import connect as _ws_connect

from core.redis_keys import WS_CONNECTED_AT

logger = logging.getLogger(__name__)

# ── Prometheus metrics for WS reconnect observability ─────────────
finnhub_ws_reconnect_attempts = Counter(
    "finnhub_ws_reconnect_attempts_total",
    "Total Finnhub WS reconnect attempts",
    ["replica_id", "error_type"],
)
finnhub_ws_reconnect_current = Gauge(
    "finnhub_ws_reconnect_current_attempt",
    "Current consecutive reconnect attempt number (resets on success)",
    ["replica_id"],
)
finnhub_ws_connections_total = Counter(
    "finnhub_ws_connections_total",
    "Total successful Finnhub WS connections",
    ["replica_id"],
)
finnhub_ws_connected = Gauge(
    "finnhub_ws_connected",
    "Whether Finnhub WS is currently connected (1=yes, 0=no)",
    ["replica_id"],
)

# Backoff configuration
INITIAL_BACKOFF_S: float = 1.0
MAX_BACKOFF_S: float = 300.0  # 5 minutes ceiling
BACKOFF_MULTIPLIER: float = 2.0
JITTER_RANGE: float = 0.5  # ±50% jitter

# Rate limit specific
RATE_LIMIT_BASE_BACKOFF_S: float = 30.0
RATE_LIMIT_STATUS: int = 429

# Connection
FINNHUB_WS_URL: str = "wss://ws.finnhub.io?token={token}"
PING_INTERVAL_S: float = 20.0
PING_TIMEOUT_S: float = 10.0
LEADER_LOCK_KEY: str = "finnhub:ws:leader"
LEADER_LOCK_TTL_S: int = 30
LEADER_LOCK_RENEWAL_S: float = 20.0  # Renew every 20s (must be < TTL)

# Market hours: Forex open Sun 22:00 UTC → Fri 22:00 UTC
WEEKEND_POLL_INTERVAL_S: float = 300.0  # Check every 5 min during weekend

# Re-export from shared utility for backward compatibility.
from utils.market_hours import is_forex_market_open  # noqa: E402, F401


class FinnhubSymbolMapper:
    """Map internal symbols to Finnhub symbols and back."""

    def __init__(self, prefix: str) -> None:
        super().__init__()
        self._prefix = prefix
        self._external_to_internal: dict[str, str] = {}

    def register(self, symbol: str) -> str:
        """Register and return the Finnhub-formatted symbol."""
        external_symbol = f"{self._prefix}:{symbol[:3]}_{symbol[3:]}" if len(symbol) == 6 else symbol

        self._external_to_internal[external_symbol] = symbol
        return external_symbol

    def to_internal(self, external_symbol: str) -> str:
        """Convert Finnhub symbol back to internal format."""
        registered = self._external_to_internal.get(external_symbol)
        if registered is not None:
            return registered

        prefix = f"{self._prefix}:"
        if external_symbol.startswith(prefix):
            return external_symbol[len(prefix) :].replace("_", "")
        return external_symbol


class FinnhubConnectionError(Exception):
    """Raised when Finnhub WS connection fails."""


class FinnhubRateLimitError(FinnhubConnectionError):
    """Raised specifically on HTTP 429 from Finnhub."""

    def __init__(self, retry_after: float = RATE_LIMIT_BASE_BACKOFF_S):
        self.retry_after = retry_after
        super().__init__(f"Finnhub rate limited - retry after {retry_after:.1f}s")


def _calculate_backoff(
    attempt: int,
    *,
    base: float = INITIAL_BACKOFF_S,
    multiplier: float = BACKOFF_MULTIPLIER,
    maximum: float = MAX_BACKOFF_S,
) -> float:
    """Calculate exponential backoff with jitter.

    Args:
        attempt: Zero-based retry attempt number.
        base: Initial backoff duration in seconds.
        multiplier: Exponential multiplier per attempt.
        maximum: Hard ceiling for backoff duration.

    Returns:
        Backoff duration in seconds with jitter applied.
    """
    exp_backoff = base * (multiplier**attempt)
    clamped = min(exp_backoff, maximum)
    jitter = clamped * random.uniform(-JITTER_RANGE, JITTER_RANGE)
    return max(0.1, clamped + jitter)


class FinnhubWebSocket:
    """Resilient Finnhub WebSocket client.

    Features:
        - Exponential backoff with jitter on reconnect
        - Aggressive backoff on HTTP 429
        - Distributed leader election via Redis (single connection)
        - Structured logging with context
    """

    def __init__(
        self,
        redis: Redis,
        on_message: Callable[[dict[str, Any]], Awaitable[None]],
        symbols: list[str],
        *,
        replica_id: str | None = None,
        on_connect: Callable[[], Coroutine[Any, Any, None]] | None = None,
    ) -> None:
        super().__init__()
        self._redis = redis
        self._on_message: Callable[[dict[str, Any]], Awaitable[None]] = on_message
        self._symbols = symbols
        self._replica_id = replica_id or os.environ.get("RAILWAY_REPLICA_ID", "unknown")
        self._on_connect = on_connect
        from ingest.finnhub_key_manager import finnhub_keys  # noqa: PLC0415

        self._key_manager = finnhub_keys
        self._token = self._key_manager.current_key()
        if not self._token:
            raise RuntimeError("No FINNHUB_API_KEY configured — cannot start WebSocket client.")
        self._attempt: int = 0
        self._running: bool = False
        self._connected: bool = False
        self._ws: websockets.asyncio.client.ClientConnection | None = None
        self._lock_renewal_task: asyncio.Task[None] | None = None

    @property
    def is_connected(self) -> bool:
        """Whether the WebSocket is currently connected and receiving data."""
        return self._connected

    @is_connected.setter
    def is_connected(self, value: bool) -> None:
        self._connected = value

    async def _acquire_leader_lock(self) -> bool:
        """Attempt to acquire distributed leader lock.

        Only one replica should maintain the WS connection to avoid
        multiplying connection attempts against Finnhub's rate limit.

        Idempotent: if this replica already holds the lock, it is
        renewed and True is returned (prevents self-deadlock after
        a WS crash within the same process).

        Returns:
            True if this replica acquired (or already holds) the lock.
        """
        # Fast path: try to claim an empty slot.
        acquired = await self._redis.set(
            LEADER_LOCK_KEY,
            self._replica_id,
            nx=True,
            ex=LEADER_LOCK_TTL_S,
        )
        if acquired:
            logger.info(
                "Acquired Finnhub WS leader lock",
                extra={"replica_id": self._replica_id},
            )
            return True

        # Lock exists — check if *we* already own it (idempotent re-acquire).
        current = await self._redis.get(LEADER_LOCK_KEY)
        if current == self._replica_id:
            await self._redis.expire(LEADER_LOCK_KEY, LEADER_LOCK_TTL_S)
            logger.debug(
                "Re-acquired own leader lock (idempotent)",
                extra={"replica_id": self._replica_id},
            )
            return True

        return False

    async def _release_leader_lock(self) -> None:
        """Release leader lock if held by this replica.

        Safe to call unconditionally — only deletes the key when its
        value matches our replica_id (compare-and-delete).
        """
        try:
            current = await self._redis.get(LEADER_LOCK_KEY)
            if current == self._replica_id:
                await self._redis.delete(LEADER_LOCK_KEY)
                logger.info(
                    "Released Finnhub WS leader lock",
                    extra={"replica_id": self._replica_id},
                )
        except Exception as exc:
            logger.warning(
                "Failed to release leader lock: %s",
                exc,
                extra={"replica_id": self._replica_id},
            )

    async def _renew_leader_lock(self) -> bool:
        """Renew leader lock if still held by this replica."""
        current = await self._redis.get(LEADER_LOCK_KEY)
        if current == self._replica_id:
            await self._redis.expire(LEADER_LOCK_KEY, LEADER_LOCK_TTL_S)
            return True
        return False

    async def _lock_renewal_loop(self) -> None:
        """Continuously renew leader lock while WS is connected.

        Runs as a background task. If renewal fails (lock stolen or
        expired), force-disconnect the WS so the main loop can
        re-acquire or yield to another replica.
        """
        while self._running and self._connected:
            try:
                renewed = await self._renew_leader_lock()
                if not renewed:
                    logger.warning(
                        "[LeaderLock] Lost lock — triggering reconnect",
                        extra={"replica_id": self._replica_id},
                    )
                    self._connected = False
                    if self._ws is not None:
                        with contextlib.suppress(Exception):
                            await self._ws.close()
                    return
            except Exception as exc:
                logger.warning(
                    "[LeaderLock] Renewal error: %s",
                    exc,
                    extra={"replica_id": self._replica_id},
                )
            await asyncio.sleep(LEADER_LOCK_RENEWAL_S)

    def _cancel_lock_renewal(self) -> None:
        """Cancel the background lock renewal task if running."""
        if self._lock_renewal_task is not None and not self._lock_renewal_task.done():
            self._lock_renewal_task.cancel()
        self._lock_renewal_task = None

    async def _subscribe(
        self,
        ws: websockets.asyncio.client.ClientConnection,
    ) -> None:
        """Subscribe to configured symbols."""
        for symbol in self._symbols:
            payload = json.dumps({"type": "subscribe", "symbol": symbol})
            await ws.send(payload)
            logger.debug(
                "Subscribed to symbol",
                extra={"symbol": symbol},
            )

    async def _connect(self) -> websockets.asyncio.client.ClientConnection:
        """Establish WebSocket connection to Finnhub.

        Raises:
            FinnhubRateLimitError: On HTTP 429 response.
            FinnhubConnectionError: On other connection failures.
        """
        # Refresh token from key manager in case of prior rotation
        refreshed = self._key_manager.current_key()
        if refreshed:
            self._token = refreshed
        url = FINNHUB_WS_URL.format(token=self._token)
        try:
            ws = await asyncio.wait_for(
                _ws_connect(
                    url,
                    ping_interval=PING_INTERVAL_S,
                    ping_timeout=PING_TIMEOUT_S,
                    close_timeout=10,
                ),
                timeout=30.0,
            )
            logger.info(
                "Finnhub WS connected",
                extra={
                    "replica_id": self._replica_id,
                    "attempt": self._attempt,
                },
            )
            self._attempt = 0  # Reset on success
            self._connected = True
            # Record WS connect timestamp for pipeline warmup grace period
            with contextlib.suppress(Exception):
                await self._redis.set(
                    WS_CONNECTED_AT,
                    str(time.time()),
                    ex=3600,  # expire after 1 hour
                )
            # Fire on_connect callback (e.g. HTF refresh) — best effort
            if self._on_connect is not None:
                with contextlib.suppress(Exception):
                    asyncio.create_task(self._on_connect(), name="WsOnConnectCallback")
            # Start background lock renewal so TTL doesn't expire mid-session
            self._lock_renewal_task = asyncio.create_task(
                self._lock_renewal_loop(),
                name="LeaderLockRenewal",
            )
            finnhub_ws_reconnect_current.labels(replica_id=self._replica_id).set(0)
            finnhub_ws_connections_total.labels(replica_id=self._replica_id).inc()
            finnhub_ws_connected.labels(replica_id=self._replica_id).set(1)
            return ws
        except Exception as exc:
            # websockets raises InvalidStatusCode on HTTP error responses
            status_code: int | None = getattr(exc, "status_code", None)
            if status_code is not None:
                if status_code == RATE_LIMIT_STATUS:
                    self._key_manager.report_failure(self._token, status_code)
                    backoff = _calculate_backoff(
                        self._attempt,
                        base=RATE_LIMIT_BASE_BACKOFF_S,
                        maximum=MAX_BACKOFF_S,
                    )
                    raise FinnhubRateLimitError(retry_after=backoff) from exc
                if status_code in (401, 403):
                    self._key_manager.report_failure(self._token, status_code)
                raise FinnhubConnectionError(f"WS connection rejected: HTTP {status_code}") from exc
            raise FinnhubConnectionError(str(exc)) from exc

    async def _listen(self, ws):
        """Listen to WebSocket messages with proper error handling."""
        try:
            async for raw_msg in ws:
                try:
                    msg = json.loads(raw_msg)

                    # Process tick
                    if msg.get("type") == "trade":
                        await self._on_message(msg)

                except json.JSONDecodeError:
                    logger.warning(f"[WS] Invalid JSON: {raw_msg}")
                    continue
                except Exception as e:
                    logger.error(f"[WS] Error processing message: {e}")
                    continue

        except asyncio.CancelledError:
            logger.info("[WS] Listen task cancelled")
            raise
        except websockets.exceptions.ConnectionClosedError as e:
            logger.warning(f"[WS] Connection closed: {e}")
            raise
        except Exception as e:
            logger.error(f"[WS] Unexpected error: {e}", exc_info=True)
            raise

    async def run(self):
        """Run WebSocket with exponential backoff reconnection."""
        self._running = True
        attempt = 0
        max_attempts = 10

        while attempt < max_attempts:
            try:
                # Acquire leader lock
                if not await self._acquire_leader_lock():
                    logger.info("[WS] Not leader - waiting")
                    await asyncio.sleep(10)
                    continue

                logger.info(f"[WS] Connection attempt {attempt + 1}/{max_attempts}")

                # Build URL correctly
                url = FINNHUB_WS_URL.format(token=self._token)

                # Connect
                async with websockets.connect(
                    url,
                    ping_interval=PING_INTERVAL_S,
                    ping_timeout=PING_TIMEOUT_S,
                    close_timeout=10,
                    max_size=10_000_000,
                ) as ws_raw:
                    ws = cast(websockets.asyncio.client.ClientConnection, ws_raw)
                    self._ws = ws
                    self._connected = True
                    attempt = 0  # Reset on success

                    logger.info("[WS] Connected successfully")

                    # Subscribe to symbols
                    await self._subscribe(ws)

                    # Listen
                    await self._listen(ws)

            except asyncio.CancelledError:
                logger.info("[WS] Task cancelled")
                break

            except websockets.exceptions.ConnectionClosedError:
                attempt += 1
                delay = min(2 * (2**attempt), 300)
                logger.warning(f"[WS] Connection closed. Retry in {delay}s (attempt {attempt}/{max_attempts})")
                self._connected = False
                await asyncio.sleep(delay)

            except Exception as e:
                attempt += 1
                delay = min(2 * (2**attempt), 300)
                logger.error(f"[WS] Error: {e}. Retry in {delay}s (attempt {attempt}/{max_attempts})")
                self._connected = False
                await asyncio.sleep(delay)

            finally:
                self._cancel_lock_renewal()
                if self._ws is not None:
                    with contextlib.suppress(Exception):
                        await self._ws.close()

        logger.error(f"[WS] Max reconnection attempts ({max_attempts}) reached. Giving up.")
        self._connected = False
        await self._release_leader_lock()

    async def stop(self) -> None:
        """Gracefully shutdown the WebSocket client."""
        self._running = False
        self._connected = False
        self._cancel_lock_renewal()
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.close()
        finnhub_ws_connected.labels(replica_id=self._replica_id).set(0)
        # Force-release lock regardless of holder — this replica is shutting
        # down, so if *we* held the lock it must go immediately.
        with contextlib.suppress(Exception):
            await self._redis.delete(LEADER_LOCK_KEY)
        logger.info(
            "Finnhub WS client stopped + lock released",
            extra={"replica_id": self._replica_id},
        )
