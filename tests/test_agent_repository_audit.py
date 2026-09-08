from __future__ import annotations

import json
from datetime import UTC, date, datetime, time
from enum import StrEnum
from typing import Any
from uuid import uuid4

import pytest

from agents.repository import AgentRepository


class _Mode(StrEnum):
    SHADOW = "SHADOW"


class _FakePostgres:
    def __init__(self) -> None:
        self.args: tuple[Any, ...] | None = None

    async def fetchrow(self, _query: str, *args: Any) -> dict[str, str]:
        self.args = args
        return {"id": "audit-row"}


@pytest.mark.asyncio
async def test_insert_audit_log_serializes_database_scalar_types() -> None:
    postgres = _FakePostgres()
    repository = AgentRepository()
    repository._pg = postgres  # type: ignore[assignment]
    agent_id = uuid4()
    created_at = datetime(2026, 8, 3, 2, 0, tzinfo=UTC)

    await repository.insert_audit_log(
        agent_id=str(agent_id),
        action="CREATE_AGENT",
        performed_by="test",
        details={"mode": _Mode.SHADOW},
        previous_state={"day": date(2026, 8, 2), "at": time(23, 59)},
        new_state={"id": agent_id, "created_at": created_at},
    )

    assert postgres.args is not None
    assert json.loads(postgres.args[3]) == {"mode": "SHADOW"}
    assert json.loads(postgres.args[4]) == {"day": "2026-08-02", "at": "23:59:00"}
    assert json.loads(postgres.args[5]) == {
        "id": str(agent_id),
        "created_at": "2026-08-03T02:00:00+00:00",
    }


@pytest.mark.asyncio
async def test_insert_audit_log_rejects_unknown_scalar_types() -> None:
    postgres = _FakePostgres()
    repository = AgentRepository()
    repository._pg = postgres  # type: ignore[assignment]

    with pytest.raises(TypeError, match="Object of type object is not JSON serializable"):
        await repository.insert_audit_log(
            agent_id=str(uuid4()),
            action="CREATE_AGENT",
            performed_by="test",
            details={"unsupported": object()},
            previous_state=None,
            new_state=None,
        )

    assert postgres.args is None
