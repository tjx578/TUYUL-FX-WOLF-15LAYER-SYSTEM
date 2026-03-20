"""Async PostgreSQL client wrapper used for durable backup writes."""

from __future__ import annotations

import asyncio
import contextlib
import os
from importlib import import_module
from typing import Any

from loguru import logger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


class PostgresConnectionError(Exception):
    """Raised when PostgreSQL connection initialization fails."""


# Railway/cloud proxies typically have 300s idle timeout.
# We ping at 120s to stay well under the limit.
_POOL_KEEPALIVE_INTERVAL_SEC: int = int(os.getenv("PG_POOL_KEEPALIVE_SEC", "120"))


def _pg_retry_exceptions() -> tuple[type[Exception], ...]:
    """Build tuple of exceptions that should trigger query retry.

    Includes asyncpg-specific connection errors if the module is available.
    """
    base: list[type[Exception]] = [OSError, RuntimeError, ConnectionResetError]
    try:
        import asyncpg  # noqa: PLC0415

        base.extend(
            [
                asyncpg.PostgresConnectionError,
                asyncpg.InterfaceError,
                asyncpg.InternalClientError,
            ]
        )
    except ImportError:
        pass
    return tuple(base)


class PostgresClient:
    """Singleton async PostgreSQL client with retry-enabled query helpers.

    Includes a background keepalive task that pings idle connections
    periodically to prevent Railway TCP proxy from killing idle sockets.
    """

    _instance: PostgresClient | None = None

    def __new__(cls) -> PostgresClient:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._pool = None
            cls._instance._keepalive_task: asyncio.Task[None] | None = None  # type: ignore
        return cls._instance

    async def initialize(self) -> None:
        """Initialize asyncpg pool from DATABASE_URL if configured."""
        if self._pool is not None:
            return

        dsn = os.getenv("DATABASE_URL", "")
        if not dsn:
            logger.warning("DATABASE_URL not set; PostgreSQL backup disabled")
            return

        try:
            asyncpg = _load_asyncpg_module()
            self._pool = await asyncio.wait_for(
                asyncpg.create_pool(
                    dsn=dsn,
                    min_size=1,
                    max_size=10,
                    command_timeout=30,
                    max_inactive_connection_lifetime=300.0,
                    server_settings={
                        "tcp_keepalives_idle": "60",
                        "tcp_keepalives_interval": "10",
                        "tcp_keepalives_count": "5",
                    },
                ),
                timeout=30,
            )
            logger.info("PostgreSQL connection pool initialized")

            self._keepalive_task = asyncio.create_task(
                self._keepalive_loop(),
                name="pg-pool-keepalive",
            )
            logger.debug(f"PostgreSQL pool keepalive started " f"(interval={_POOL_KEEPALIVE_INTERVAL_SEC}s)")
        except Exception as exc:
            raise PostgresConnectionError(str(exc)) from exc

    async def _keepalive_loop(self) -> None:
        """Periodic ping to prevent Railway proxy from killing idle connections."""
        while True:
            try:
                await asyncio.sleep(_POOL_KEEPALIVE_INTERVAL_SEC)
                if self._pool is None:
                    break
                async with self._pool.acquire() as conn:
                    await conn.execute("SELECT 1")
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning(f"PostgreSQL keepalive ping failed: {exc}")
                if self._pool is not None:
                    with contextlib.suppress(Exception):
                        await self._pool.expire_connections()

    @property
    def is_available(self) -> bool:
        """Return True if PostgreSQL pool is available."""
        return self._pool is not None

    async def close(self) -> None:
        """Close asyncpg pool and stop keepalive task."""
        if self._keepalive_task is not None:
            self._keepalive_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._keepalive_task
            self._keepalive_task = None

        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            logger.info("PostgreSQL connection pool closed")

    @retry(
        retry=retry_if_exception_type(_pg_retry_exceptions()),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def execute(self, query: str, *args: Any) -> str:
        """Execute one SQL statement."""
        if self._pool is None:
            return "SKIP"
        async with self._pool.acquire() as conn:
            return await conn.execute(query, *args)

    @retry(
        retry=retry_if_exception_type(_pg_retry_exceptions()),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def fetch(self, query: str, *args: Any) -> list[Any]:
        """Fetch multiple rows."""
        if self._pool is None:
            return []
        async with self._pool.acquire() as conn:
            return await conn.fetch(query, *args)

    @retry(
        retry=retry_if_exception_type(_pg_retry_exceptions()),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def fetchrow(self, query: str, *args: Any) -> Any | None:
        """Fetch a single row."""
        if self._pool is None:
            return None
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(query, *args)

    async def health_check(self) -> dict[str, Any]:
        """Return PostgreSQL health details for API status endpoints."""
        if self._pool is None:
            return {"connected": False, "reason": "DATABASE_URL not configured"}

        try:
            row = await self.fetchrow("SELECT 1 AS ok")
            pool_size = self._pool.get_size()
            idle = self._pool.get_idle_size()
            return {
                "connected": row is not None,
                "pool_size": pool_size,
                "pool_free": idle,
                "pool_used": pool_size - idle,
            }
        except Exception as exc:
            return {"connected": False, "error": str(exc)}

    async def execute_in_transaction(
        self,
        operations: list[tuple[str, tuple[Any, ...]]],
    ) -> list[str]:
        """Execute multiple SQL statements atomically in one transaction."""
        if self._pool is None:
            return []
        results: list[str] = []
        async with self._pool.acquire() as conn, conn.transaction():
            for query, args in operations:
                result = await conn.execute(query, *args)
                results.append(result)
        return results


pg_client = PostgresClient()


def _load_asyncpg_module() -> Any:
    try:
        return import_module("asyncpg")
    except ModuleNotFoundError as exc:
        raise PostgresConnectionError(
            "Missing dependency asyncpg. Install requirements before enabling PostgreSQL backup."
        ) from exc
