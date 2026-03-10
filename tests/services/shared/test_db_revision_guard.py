from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from services.shared.db_revision_guard import DatabaseSchemaError, assert_required_tables


pytestmark = pytest.mark.asyncio


async def test_assert_required_tables_raises_for_missing_table() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    try:
        with pytest.raises(DatabaseSchemaError):
            await assert_required_tables(engine, ["trade_outbox"])
    finally:
        await engine.dispose()
