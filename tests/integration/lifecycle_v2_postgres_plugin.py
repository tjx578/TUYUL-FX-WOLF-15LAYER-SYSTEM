"""Shared disposable-PostgreSQL fixture for Lifecycle V2 integration gates."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib import import_module
from typing import Any

import pytest
import pytest_asyncio

_RUN_FLAG = "WOLF15_RUN_POSTGRES_INTEGRATION"


class PoolBackedPostgres:
    """Production-like pool semantics backed by disposable PostgreSQL."""

    def __init__(self, pool: Any, foreign_key_violation_error: type[Exception]) -> None:
        self._pool = pool
        self.foreign_key_violation_error = foreign_key_violation_error
        self.check_violation_error: type[Exception] = Exception

    @property
    def is_available(self) -> bool:
        return True

    async def execute(self, query: str, *args: Any) -> str:
        async with self._pool.acquire() as connection:
            return str(await connection.execute(query, *args))

    async def fetch(self, query: str, *args: Any) -> list[Any]:
        async with self._pool.acquire() as connection:
            return list(await connection.fetch(query, *args))

    async def fetchrow(self, query: str, *args: Any) -> Any | None:
        async with self._pool.acquire() as connection:
            return await connection.fetchrow(query, *args)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Any]:
        async with self._pool.acquire() as connection, connection.transaction():
            yield connection


@pytest_asyncio.fixture
async def postgres() -> AsyncIterator[PoolBackedPostgres]:
    if os.getenv(_RUN_FLAG) != "1":
        pytest.skip(f"set {_RUN_FLAG}=1 to use a disposable PostgreSQL database")

    dsn = os.getenv("DATABASE_URL", "")
    if not dsn:
        pytest.fail(f"{_RUN_FLAG}=1 requires DATABASE_URL")

    try:
        asyncpg = import_module("asyncpg")
    except ModuleNotFoundError:
        pytest.fail(f"{_RUN_FLAG}=1 requires the asyncpg dependency")

    pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=4, command_timeout=10)
    try:
        backend = PoolBackedPostgres(pool, asyncpg.ForeignKeyViolationError)
        backend.check_violation_error = asyncpg.CheckViolationError
        yield backend
    finally:
        await pool.close()


__all__ = ["PoolBackedPostgres", "postgres"]
