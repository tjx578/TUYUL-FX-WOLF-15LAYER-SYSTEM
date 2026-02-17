"""Finnhub WebSocket client with exponential backoff and distributed locking."""

import asyncio
import contextlib
import json
import logging
import os
import random
from collections.abc import Callable, Coroutine
from typing import Any

import websockets  # pyright: ignore[reportMissingImports]
import websockets.asyncio.client  # pyright: ignore[reportMissingImports]
from redis.asyncio import Redis  # pyright: ignore[reportMissingImports]
from websockets.exceptions import (  # pyright: ignore[reportMissingImports]
    ConnectionClosed,
    ConnectionClosedError,
)

logger = logging.getLogger(__name__)

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
LEADER_LOCK_TTL_S: int = 60


class FinnhubSymbolMapper:
    """Map internal symbols to Finnhub symbols and back."""

    def __init__(self, prefix: str) -> None:
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
        on_message: Callable[[dict[str, Any]], Coroutine],
        symbols: list[str],
        *,
        replica_id: str | None = None,
    ) -> None:
        self._redis = redis
        self._on_message = on_message
        self._symbols = symbols
        self._replica_id = replica_id or os.environ.get("RAILWAY_REPLICA_ID", "unknown")
        self._token = os.environ["FINNHUB_API_KEY"]
        self._attempt: int = 0
        self._running: bool = False
        self._ws: websockets.asyncio.client.ClientConnection | None = None

    async def _acquire_leader_lock(self) -> bool:
        """Attempt to acquire distributed leader lock.

        Only one replica should maintain the WS connection to avoid
        multiplying connection attempts against Finnhub's rate limit.

        Returns:
            True if this replica acquired the lock.
        """
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
        return bool(acquired)

    async def _renew_leader_lock(self) -> bool:
        """Renew leader lock if still held by this replica."""
        current = await self._redis.get(LEADER_LOCK_KEY)
        if current == self._replica_id:
            await self._redis.expire(LEADER_LOCK_KEY, LEADER_LOCK_TTL_S)
            return True
        return False

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
        url = FINNHUB_WS_URL.format(token=self._token)
        try:
            ws = await websockets.connect(
                url,
                ping_interval=PING_INTERVAL_S,
                ping_timeout=PING_TIMEOUT_S,
                close_timeout=10,
            )
            logger.info(
                "Finnhub WS connected",
                extra={
                    "replica_id": self._replica_id,
                    "attempt": self._attempt,
                },
            )
            self._attempt = 0  # Reset on success
            return ws
        except Exception as exc:
            # websockets raises InvalidStatusCode on HTTP error responses
            status_code = getattr(exc, 'status_code', None)
            if status_code == RATE_LIMIT_STATUS:
                backoff = _calculate_backoff(
                    self._attempt,
                    base=RATE_LIMIT_BASE_BACKOFF_S,
                    maximum=MAX_BACKOFF_S,
                )
                raise FinnhubRateLimitError(retry_after=backoff) from exc
            if status_code is not None:
                raise FinnhubConnectionError(f"WS connection rejected: HTTP {status_code}") from exc
            raise FinnhubConnectionError(str(exc)) from exc

    async def _listen(
        self,
        ws: websockets.asyncio.client.ClientConnection,
    ) -> None:
        """Listen for messages and dispatch to handler."""
        import time
        _RENEW_INTERVAL_S = 15  # noqa: N806
        _last_renew = 0.0
        async for raw_msg in ws:
            data = json.loads(raw_msg)

            if data.get("type") == "ping":
                continue

            # Renew lock periodically during message processing (throttled)
            now = time.monotonic()
            if now - _last_renew >= _RENEW_INTERVAL_S:
                await self._renew_leader_lock()
                _last_renew = now
            await self._on_message(data)

    async def run(self) -> None:
        """Main loop: connect, subscribe, listen, reconnect on failure.

        Implements leader election so only one replica connects.
        Uses exponential backoff with jitter on failures, with
        aggressive backoff specifically for HTTP 429.
        """
        self._running = True
        logger.info(
            "Finnhub WS client starting",
            extra={
                "replica_id": self._replica_id,
                "symbols": self._symbols,
            },
        )

        while self._running:
            # --- Leader election ---
            if not await self._acquire_leader_lock():
                logger.debug(
                    "Not leader - waiting before retry",
                    extra={"replica_id": self._replica_id},
                )
                await asyncio.sleep(LEADER_LOCK_TTL_S / 2)
                continue

            try:
                self._ws = await self._connect()
                await self._subscribe(self._ws)
                await self._listen(self._ws)

            except (
                ConnectionClosedError,
                ConnectionError,
                OSError,
            ) as exc:
                self._attempt += 1
                backoff = _calculate_backoff(self._attempt)
                logger.warning(
                    "Finnhub WS connection error (retryable)",
                    extra={
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                        "backoff_s": backoff,
                        "attempt": self._attempt,
                        "replica_id": self._replica_id,
                    },
                    exc_info=self._attempt <= 3,  # full traceback only on first few attempts
                )
                await asyncio.sleep(backoff)

            except FinnhubRateLimitError as exc:
                self._attempt += 1
                logger.warning(
                    "Finnhub rate limited (HTTP 429)",
                    extra={
                        "retry_after_s": exc.retry_after,
                        "attempt": self._attempt,
                        "replica_id": self._replica_id,
                    },
                )
                await asyncio.sleep(exc.retry_after)

            except FinnhubConnectionError as exc:
                self._attempt += 1
                backoff = _calculate_backoff(self._attempt)
                logger.error(
                    "Finnhub WS connection error",
                    extra={
                        "error": str(exc),
                        "backoff_s": backoff,
                        "attempt": self._attempt,
                        "replica_id": self._replica_id,
                    },
                )
                await asyncio.sleep(backoff)

            except ConnectionClosed as exc:
                self._attempt += 1
                backoff = _calculate_backoff(self._attempt)
                logger.warning(
                    "Finnhub WS connection closed",
                    extra={
                        "code": exc.code,
                        "reason": exc.reason,
                        "backoff_s": backoff,
                        "attempt": self._attempt,
                    },
                )
                await asyncio.sleep(backoff)

            finally:
                if self._ws is not None:
                    with contextlib.suppress(Exception):
                        await self._ws.close()
                    self._ws = None

    async def stop(self) -> None:
        """Gracefully shutdown the WebSocket client."""
        self._running = False
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.close()
        # Release leader lock
        current = await self._redis.get(LEADER_LOCK_KEY)
        if current == self._replica_id:
            await self._redis.delete(LEADER_LOCK_KEY)
        logger.info(
            "Finnhub WS client stopped",
            extra={"replica_id": self._replica_id},
        )
