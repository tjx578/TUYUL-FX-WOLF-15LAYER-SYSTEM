from __future__ import annotations

import pytest
from types import TracebackType

from storage.db_revision_guard import DatabaseRevisionMismatchError, assert_required_tables


class _FakeResult:
    def __init__(self, value: str | None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> str | None:
        return self._value


class _FakeConnection:
    def __init__(self, existing_tables: set[str]) -> None:
        self._existing_tables = existing_tables

    async def execute(self, _query: object, params: dict[str, str]) -> _FakeResult:
        fqtn = params["fqtn"]
        if fqtn in self._existing_tables:
            return _FakeResult(fqtn)
        return _FakeResult(None)


class _FakeConnectCtx:
    def __init__(self, existing_tables: set[str]) -> None:
        self._conn = _FakeConnection(existing_tables)

    async def __aenter__(self) -> _FakeConnection:
        return self._conn

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None


class _FakeEngine:
    def __init__(self, existing_tables: set[str]) -> None:
        self._existing_tables = existing_tables

    def connect(self) -> _FakeConnectCtx:
        return _FakeConnectCtx(self._existing_tables)


@pytest.mark.asyncio
async def test_assert_required_tables_all_present() -> None:
    engine = _FakeEngine({"public.trade_outbox", "public.trade_journal"})

    await assert_required_tables(engine, ["trade_outbox", "trade_journal"])  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_assert_required_tables_raises_when_missing() -> None:
    engine = _FakeEngine({"public.trade_outbox"})

    with pytest.raises(DatabaseRevisionMismatchError, match="public.trade_journal"):
        await assert_required_tables(engine, ["trade_outbox", "trade_journal"])  # type: ignore[arg-type]
