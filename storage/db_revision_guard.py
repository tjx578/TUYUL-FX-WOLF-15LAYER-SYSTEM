from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy.ext.asyncio import AsyncEngine

from services.shared.db_revision_guard import DatabaseSchemaError, assert_required_tables as _assert_required_tables


class DatabaseRevisionMismatchError(RuntimeError):
    """Raised when DB revision is not at expected Alembic head."""


async def assert_required_tables(engine: AsyncEngine, required_tables: Iterable[str]) -> None:
    try:
        await _assert_required_tables(engine, required_tables)
    except DatabaseSchemaError as exc:
        raise DatabaseRevisionMismatchError(str(exc)) from exc
