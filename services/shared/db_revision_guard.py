"""Database readiness guards for required trading tables."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine


class DatabaseSchemaError(RuntimeError):
    """Raised when required schema objects are missing."""


async def assert_required_tables(engine: AsyncEngine, tables: Iterable[str]) -> None:
    """Validate required tables exist in public schema.

    Args:
        engine: Async SQLAlchemy engine.
        tables: Table names without schema prefix.

    Raises:
        DatabaseSchemaError: If any required table is missing or query fails.
    """
    sql = text("SELECT to_regclass(:fqtn)")
    missing: list[str] = []

    try:
        async with engine.connect() as conn:
            for table_name in tables:
                fqtn = f"public.{table_name}"
                result = await conn.execute(sql, {"fqtn": fqtn})
                exists = result.scalar_one_or_none()
                if exists is None:
                    missing.append(fqtn)
    except SQLAlchemyError as exc:
        raise DatabaseSchemaError(f"Failed database schema readiness check: {exc.__class__.__name__}") from exc

    if missing:
        raise DatabaseSchemaError(
            "Missing required DB tables: "
            + ", ".join(missing)
            + ". Run `alembic upgrade head` before starting services."
        )
