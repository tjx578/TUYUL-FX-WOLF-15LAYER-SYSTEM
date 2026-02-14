"""Async PostgreSQL client wrapper used for durable backup writes."""

from __future__ import annotations

import os

from typing import Any
from importlib import import_module

from loguru import logger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


class PostgresConnectionError(Exception):
    """Raised when PostgreSQL connection initialization fails."""


class PostgresClient:
    """Singleton async PostgreSQL client with retry-enabled query helpers."""

    _instance: PostgresClient | None = None

    def __new__(cls) -> PostgresClient:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._pool = None
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
            self._pool = await asyncpg.create_pool(
                dsn=dsn,
                min_size=1,
                max_size=10,
                command_timeout=30,
            )
            logger.info("PostgreSQL connection pool initialized")
        except Exception as exc:
            raise PostgresConnectionError(str(exc)) from exc

    @property
    def is_available(self) -> bool:
        """Return True if PostgreSQL pool is available."""
        return self._pool is not None

    async def close(self) -> None:
        """Close asyncpg pool."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            logger.info("PostgreSQL connection pool closed")

    @retry(
        retry=retry_if_exception_type((OSError, RuntimeError)),
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
        retry=retry_if_exception_type((OSError, RuntimeError)),
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
        retry=retry_if_exception_type((OSError, RuntimeError)),
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


pg_client = PostgresClient()


def _load_asyncpg_module() -> Any:
    try:
        return import_module("asyncpg")
    except ModuleNotFoundError as exc:
        raise PostgresConnectionError(
            "Missing dependency asyncpg. Install requirements before enabling PostgreSQL backup."
        ) from exc
