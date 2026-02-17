"""
Database access layer with enforced parameterized queries.

Zone: dashboard (data access). No market analysis or execution logic.

SECURITY: All queries MUST use parameterized placeholders ($1, $2, ... for asyncpg
or %s for psycopg2). String interpolation into SQL is BANNED.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from contextlib import asynccontextmanager
from typing import Any  # noqa: UP035

logger = logging.getLogger(__name__)

# ── SQL Injection Guard ──────────────────────────────────────────────

# Patterns that indicate dangerous string interpolation in SQL
_INJECTION_PATTERNS = [
    re.compile(r"'[^']*\b(OR|AND|UNION|SELECT|DROP|DELETE|INSERT|UPDATE|ALTER|EXEC)\b", re.IGNORECASE),
    re.compile(r";\s*(DROP|DELETE|INSERT|UPDATE|ALTER|EXEC)\b", re.IGNORECASE),
    re.compile(r"--"),           # SQL comment injection
    re.compile(r"/\*"),          # Block comment injection
    re.compile(r"'\s*=\s*'"),    # Tautology: ' = '
]

# Detect f-string / .format() style interpolation in query text
_INTERPOLATION_PATTERN = re.compile(
    r"(?:"
    r"(?<!\$)\{[^}]+\}"           # {variable} but NOT ${pg_cast}
    r"|%\([^)]+\)s"               # %(name)s — old-style named
    r"|'%s'"                       # '%s' — quoted %s (should be unquoted for params)
    r"|f['\"]"                     # f-string prefix
    r")"
)


class SQLInjectionError(Exception):
    """Raised when a query fails injection safety checks."""
    pass


def validate_query(query: str, params: Sequence[Any] | None = None) -> None:
    """
    Validate a SQL query for injection safety.

    Rules:
    1. Query must not contain string interpolation patterns.
    2. Query must use positional ($1, $2) or %s placeholders if params are provided.
    3. Param count must match placeholder count.

    Raises SQLInjectionError if validation fails.
    """
    if not query or not query.strip():
        raise SQLInjectionError("Empty query")

    # Check for interpolation patterns in the query text itself
    interpolation_match = _INTERPOLATION_PATTERN.search(query)
    if interpolation_match:
        raise SQLInjectionError(
            f"Query contains string interpolation pattern: {interpolation_match.group()!r}. "
            f"Use parameterized placeholders ($1, $2, ...) instead."
        )

    # Count expected placeholders
    # asyncpg style: $1, $2, ...
    asyncpg_placeholders = re.findall(r'\$(\d+)', query)
    # psycopg2 style: %s (unquoted)
    psycopg_placeholders = re.findall(r'(?<!%)%s', query)

    placeholder_count = max(
        len(set(asyncpg_placeholders)),
        len(psycopg_placeholders),
    )

    param_count = len(params) if params else 0

    if placeholder_count > 0 and param_count == 0:
        raise SQLInjectionError(
            f"Query has {placeholder_count} placeholders but no params provided."
        )

    if param_count > 0 and placeholder_count == 0:
        raise SQLInjectionError(
            f"Query has {param_count} params but no placeholders in query. "
            f"Params might be concatenated unsafely."
        )

    if asyncpg_placeholders:
        expected = len(set(asyncpg_placeholders))
        if param_count != expected:
            raise SQLInjectionError(
                f"Placeholder/param count mismatch: {expected} placeholders, {param_count} params."
            )


def sanitize_identifier(identifier: str) -> str:
    """
    Sanitize a SQL identifier (table name, column name).

    Only allows alphanumeric characters and underscores.
    This is for dynamic table/column names that CANNOT use parameterized queries.

    Raises ValueError if the identifier contains invalid characters.
    """
    if not identifier:
        raise ValueError("Empty identifier")

    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]{0,62}$', identifier):
        raise ValueError(
            f"Invalid SQL identifier: {identifier!r}. "
            f"Must be alphanumeric/underscore, start with letter/underscore, max 63 chars."
        )

    # Double-quote to prevent keyword conflicts
    return f'"{identifier}"'


# ── Safe Database Wrapper ────────────────────────────────────────────

class SafeDB:
    """
    Database wrapper that enforces parameterized queries.

    Wraps an asyncpg pool or connection. Every query is validated
    before execution.
    """

    def __init__(self, pool: Any) -> None:
        """
        Args:
            pool: An asyncpg.Pool or compatible connection pool.
        """
        self._pool = pool

    async def fetch(
        self, query: str, *params: Any, timeout: float | None = None
    ) -> list[Any]:
        validate_query(query, params)
        async with self._pool.acquire() as conn:
            return await conn.fetch(query, *params, timeout=timeout)

    async def fetchrow(
        self, query: str, *params: Any, timeout: float | None = None
    ) -> Any | None:
        validate_query(query, params)
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(query, *params, timeout=timeout)

    async def fetchval(
        self, query: str, *params: Any, timeout: float | None = None
    ) -> Any:
        validate_query(query, params)
        async with self._pool.acquire() as conn:
            return await conn.fetchval(query, *params, timeout=timeout)

    async def execute(
        self, query: str, *params: Any, timeout: float | None = None
    ) -> str:
        validate_query(query, params)
        async with self._pool.acquire() as conn:
            return await conn.execute(query, *params, timeout=timeout)

    async def executemany(
        self, query: str, args: Sequence[Sequence[Any]], timeout: float | None = None
    ) -> None:
        # Validate with first set of args for placeholder count
        if args:
            validate_query(query, args[0])
        else:
            validate_query(query)
        async with self._pool.acquire() as conn:
            return await conn.executemany(query, args, timeout=timeout)

    @asynccontextmanager
    async def transaction(self):
        """Context manager for transactions with the same safety enforcement."""
        async with self._pool.acquire() as conn, conn.transaction():
            yield SafeConnection(conn)


class SafeConnection:
    """Wraps a single connection within a transaction, with query validation."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    async def fetch(self, query: str, *params: Any) -> list[Any]:
        validate_query(query, params)
        return await self._conn.fetch(query, *params)

    async def fetchrow(self, query: str, *params: Any) -> Any | None:
        validate_query(query, params)
        return await self._conn.fetchrow(query, *params)

    async def execute(self, query: str, *params: Any) -> str:
        validate_query(query, params)
        return await self._conn.execute(query, *params)
