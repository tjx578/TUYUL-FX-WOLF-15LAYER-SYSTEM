from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


class DatabaseRevisionMismatchError(RuntimeError):
    """Raised when DB revision is not at expected Alembic head."""


async def assert_required_tables(engine: AsyncEngine, required_tables: list[str]) -> None:
    query = text("SELECT to_regclass(:fqtn)")
    async with engine.connect() as conn:
        for table in required_tables:
            fqtn = f"public.{table}"
            result = await conn.execute(query, {"fqtn": fqtn})
            if result.scalar_one_or_none() is None:
                raise DatabaseRevisionMismatchError(
                    f"Required table missing: {fqtn}. Run alembic upgrade head."
                )
