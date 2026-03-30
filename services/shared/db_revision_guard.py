"""Database readiness guards for required trading tables."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine


class DatabaseSchemaError(RuntimeError):
    """Raised when required schema objects are missing."""


async def assert_required_tables(
    engine: AsyncEngine,
    tables: Iterable[str],
    *,
    default_schema: str = "public",
) -> None:
    """Validate required tables exist in the database.

    Args:
        engine: Async SQLAlchemy engine.
        tables: Table names — bare names (e.g. ``trade_outbox``) are
            qualified with *default_schema*; names that already contain
            a dot (e.g. ``wolf15.trade_outbox``) are used as-is.
        default_schema: Schema prefix applied to bare table names.

    Raises:
        DatabaseSchemaError: If any required table is missing or query fails.
    """
    sql = text("SELECT to_regclass(:fqtn)")
    missing: list[str] = []

    try:
        async with engine.connect() as conn:
            for table_name in tables:
                fqtn = table_name if "." in table_name else f"{default_schema}.{table_name}"
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
