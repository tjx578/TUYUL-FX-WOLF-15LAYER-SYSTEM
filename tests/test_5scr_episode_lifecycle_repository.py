"""Durability rules for the Strategy Lifecycle V2 repository.

The properties that matter: an episode survives restart, a redelivered event
cannot inflate it, and the episode and its link are written together or not at
all.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from analysis.strategy_5scr_v3.episode_hash import (
    build_material_state_hash,
    build_strategy_lifecycle_id,
)
from contracts.strategy_5scr_lifecycle_v2 import (
    StrategyLifecycleEventLink,
    StrategyLifecycleV2,
)
from storage.strategy_5scr_lifecycle_v2_repository import (
    LIFECYCLE_TABLE,
    LINK_TABLE,
    StrategyLifecycleV2Repository,
    lifecycle_from_row,
)

START = datetime(2026, 7, 17, 13, 0, 0, tzinfo=UTC)


class _FakeTransactionConnection:
    def __init__(self, postgres: _FakePostgres) -> None:
        self._postgres = postgres

    async def execute(self, query: str, *args: Any) -> str:
        self._postgres.transaction_execute_calls += 1
        return await self._postgres.execute(query, *args)


class _FakePostgres:
    """Minimal in-memory stand-in for the queries this repository issues."""

    def __init__(self, *, available: bool = True) -> None:
        self.is_available = available
        self.lifecycles: dict[str, dict[str, Any]] = {}
        self.links: dict[str, dict[str, Any]] = {}
        self.transactions = 0
        self.transaction_execute_calls = 0
        self.fail_link = False

    async def execute(self, query: str, *args: Any) -> str:
        normalized = " ".join(query.split())
        if f"INSERT INTO {LIFECYCLE_TABLE}" in normalized:
            existing = self.lifecycles.get(args[0])
            row = {
                "strategy_lifecycle_id": args[0],
                "symbol": args[1],
                "state": args[2],
                "direction_state": args[3],
                "opened_at": args[4],
                "last_event_at": args[5],
                "last_continuity_event_at": args[6],
                "last_material_event_at": args[7],
                "rule_version": args[8],
                "material_state_hash": args[9],
                "event_count": args[10],
                "clean_block_count": args[11],
                "watch_count": args[12],
            }
            if existing:
                row["last_event_at"] = max(existing["last_event_at"], args[5])
                row["last_continuity_event_at"] = max(existing["last_continuity_event_at"], args[6])
                row["last_material_event_at"] = max(existing["last_material_event_at"], args[7])
            self.lifecycles[args[0]] = row
            return "INSERT 0 1"
        if f"INSERT INTO {LINK_TABLE}" in normalized:
            if self.fail_link:
                raise ConnectionError("crash before commit")
            if args[0] in self.links:
                return "INSERT 0 0"
            self.links[args[0]] = {
                "pressure_event_id": args[0],
                "strategy_lifecycle_id": args[1],
                "transport_lifecycle_id": args[2],
                "source_clean_block_id": args[3],
                "source_watch_id": args[4],
                "linked_at": args[5],
                "link_reason": args[6],
            }
            return "INSERT 0 1"
        return "UPDATE 1"

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        normalized = " ".join(query.split())
        if f"FROM {LIFECYCLE_TABLE}" in normalized:
            candidates = [
                row for row in self.lifecycles.values() if row["symbol"] == args[0] and row["state"] in set(args[1])
            ]
            if not candidates:
                return None
            return max(candidates, key=lambda row: row["last_continuity_event_at"])
        if f"FROM {LINK_TABLE}" in normalized:
            rows = list(self.links.values())
            return {
                "events": len(rows),
                "transport_lifecycles": len({r["transport_lifecycle_id"] for r in rows}),
                "strategy_lifecycles": len({r["strategy_lifecycle_id"] for r in rows}),
                "events_without_canonical_anchor": sum(
                    1 for r in rows if not r["source_clean_block_id"] and not r["source_watch_id"]
                ),
            }
        return None

    async def fetch(self, query: str, *args: Any) -> list[Any]:
        return []

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Any]:
        self.transactions += 1
        snapshot_lifecycles = dict(self.lifecycles)
        snapshot_links = dict(self.links)
        try:
            yield _FakeTransactionConnection(self)
        except Exception:
            self.lifecycles = snapshot_lifecycles
            self.links = snapshot_links
            raise


def _lifecycle(*, symbol="CHFJPY", direction="BUY", offset=0, event_count=1, state="ANALYSIS_OPEN"):
    opened = START
    material = START + timedelta(seconds=offset)
    return StrategyLifecycleV2(
        strategy_lifecycle_id=build_strategy_lifecycle_id(
            symbol=symbol, opened_at_utc=opened, opening_direction_state=direction
        ),
        symbol=symbol,
        state=state,
        direction_state=direction,
        opened_at_utc=opened,
        last_event_at_utc=material,
        last_continuity_event_at_utc=material,
        last_material_event_at_utc=material,
        material_state_hash=build_material_state_hash(
            symbol=symbol,
            state=state,
            direction_state=direction,
            opened_at_utc=opened,
            last_material_event_at_utc=material,
        ),
        event_count=event_count,
    )


def _link(lifecycle, *, event_id="evt-1", clean_block=None):
    return StrategyLifecycleEventLink(
        strategy_lifecycle_id=lifecycle.strategy_lifecycle_id,
        pressure_event_id=event_id,
        transport_lifecycle_id=f"transport-{event_id}",
        source_clean_block_id=clean_block,
        linked_at_utc=lifecycle.last_event_at_utc,
        link_reason="EPISODE_OPENED",
    )


@pytest.fixture
def repo():
    pg = _FakePostgres()
    return StrategyLifecycleV2Repository(pg=pg), pg


@pytest.mark.asyncio
async def test_upsert_then_recover_active_lifecycle(repo):
    repository, _pg = repo
    lifecycle = _lifecycle()

    await repository.upsert_lifecycle(lifecycle)
    recovered = await repository.active_lifecycle("CHFJPY")

    assert recovered is not None
    assert recovered.strategy_lifecycle_id == lifecycle.strategy_lifecycle_id
    assert recovered.direction_state == "BUY"


@pytest.mark.asyncio
async def test_upsert_is_idempotent_on_lifecycle_id(repo):
    repository, pg = repo
    lifecycle = _lifecycle()

    await repository.upsert_lifecycle(lifecycle)
    await repository.upsert_lifecycle(lifecycle.model_copy(update={"event_count": 5}))

    assert len(pg.lifecycles) == 1
    assert pg.lifecycles[lifecycle.strategy_lifecycle_id]["event_count"] == 5


@pytest.mark.asyncio
async def test_redelivered_event_is_not_linked_twice(repo):
    repository, pg = repo
    lifecycle = _lifecycle()
    await repository.upsert_lifecycle(lifecycle)
    link = _link(lifecycle)

    assert await repository.link_event(link) is True
    assert await repository.link_event(link) is False
    assert len(pg.links) == 1


@pytest.mark.asyncio
async def test_persist_writes_lifecycle_and_link_together(repo):
    repository, pg = repo
    lifecycle = _lifecycle()

    inserted = await repository.persist(lifecycle, _link(lifecycle))

    assert inserted is True
    assert pg.transactions == 1
    assert pg.transaction_execute_calls == 2
    assert len(pg.lifecycles) == 1 and len(pg.links) == 1


@pytest.mark.asyncio
async def test_persist_rolls_back_when_the_link_fails(repo):
    """A lifecycle whose counters advanced without a link would double-count."""
    repository, pg = repo
    pg.fail_link = True

    with pytest.raises(ConnectionError):
        await repository.persist(_lifecycle(), _link(_lifecycle()))

    assert pg.lifecycles == {}
    assert pg.links == {}


@pytest.mark.asyncio
async def test_duplicate_persist_rolls_back_a_stale_lifecycle_snapshot(repo):
    repository, pg = repo
    current = _lifecycle(offset=5, event_count=5)
    link = _link(current)
    assert await repository.persist(current, link) is True

    stale = _lifecycle(offset=1, event_count=1)
    assert stale.strategy_lifecycle_id == current.strategy_lifecycle_id
    assert await repository.persist(stale, link) is False

    stored = pg.lifecycles[current.strategy_lifecycle_id]
    assert stored["event_count"] == current.event_count
    assert stored["last_event_at"] == current.last_event_at_utc


@pytest.mark.asyncio
async def test_terminal_lifecycle_is_not_recovered_as_active(repo):
    repository, _pg = repo
    await repository.upsert_lifecycle(_lifecycle(state="TERMINAL_NO_TRADE"))

    assert await repository.active_lifecycle("CHFJPY") is None


@pytest.mark.asyncio
async def test_transition_pending_is_still_active(repo):
    repository, _pg = repo
    lifecycle = _lifecycle(direction="CONFLICT", state="TRANSITION_PENDING")
    await repository.upsert_lifecycle(lifecycle)

    recovered = await repository.active_lifecycle("CHFJPY")

    assert recovered is not None
    assert recovered.state == "TRANSITION_PENDING"


@pytest.mark.asyncio
async def test_other_symbols_do_not_leak_into_recovery(repo):
    repository, _pg = repo
    await repository.upsert_lifecycle(_lifecycle(symbol="CHFJPY"))

    assert await repository.active_lifecycle("NZDCAD") is None


@pytest.mark.asyncio
async def test_compression_snapshot_contrasts_transport_and_episode(repo):
    repository, _pg = repo
    lifecycle = _lifecycle()
    await repository.upsert_lifecycle(lifecycle)
    for index in range(9):
        await repository.link_event(_link(lifecycle, event_id=f"evt-{index}"))

    snapshot = await repository.compression_snapshot()

    assert snapshot["pressure_events_total"] == 9
    assert snapshot["strategy_lifecycles_v2_total"] == 1
    assert snapshot["legacy_transport_lifecycles_total"] == 9
    assert snapshot["lifecycle_v2_compression_ratio"] == pytest.approx(9.0)
    assert snapshot["legacy_compression_ratio"] == pytest.approx(1.0)
    assert snapshot["events_without_canonical_anchor_total"] == 9


class _SchemaProbePostgres:
    """Fake whose catalog answers can be bent into wrong shapes."""

    is_available = True

    def __init__(self, *, columns=None, constraints=None):
        self.columns = columns if columns is not None else _good_columns()
        self.constraints = constraints if constraints is not None else _good_constraints()

    async def fetch(self, query: str, *args):
        normalized = " ".join(query.split())
        if "pg_tables" in normalized:
            return [{"tablename": name} for name in (LIFECYCLE_TABLE, LINK_TABLE)]
        if "pg_indexes" in normalized:
            return [
                {"indexname": name}
                for name in (
                    "ix_5scr_lifecycle_v2_active_symbol",
                    "ix_5scr_lifecycle_v2_links_lifecycle",
                    "ix_5scr_lifecycle_v2_links_transport",
                )
            ]
        if "information_schema.columns" in normalized:
            return self.columns
        if "pg_constraint" in normalized:
            return self.constraints
        return []

    async def fetchrow(self, query: str, *args):
        return None

    async def execute(self, query: str, *args):
        return "UPDATE 1"


def _good_columns():
    return [
        {
            "table_name": LIFECYCLE_TABLE,
            "column_name": "execution_authority",
            "data_type": "boolean",
            "is_nullable": "NO",
            "column_default": "false",
        },
        {
            "table_name": LINK_TABLE,
            "column_name": "transport_lifecycle_id",
            "data_type": "text",
            "is_nullable": "NO",
            "column_default": None,
        },
        {
            "table_name": LINK_TABLE,
            "column_name": "pressure_event_id",
            "data_type": "text",
            "is_nullable": "NO",
            "column_default": None,
        },
    ]


def _good_constraints():
    return [
        {
            "conname": "ck_5scr_lifecycle_v2_shadow_only",
            "table_name": LIFECYCLE_TABLE,
            "contype": "c",
            "definition": "CHECK ((execution_authority = false))",
        },
        {
            "conname": "fk_5scr_lifecycle_v2_event_link",
            "table_name": LINK_TABLE,
            "contype": "f",
            "definition": (f"FOREIGN KEY (strategy_lifecycle_id) REFERENCES {LIFECYCLE_TABLE}(strategy_lifecycle_id)"),
        },
    ]


@pytest.mark.asyncio
async def test_schema_status_is_ready_when_everything_matches():
    status = await StrategyLifecycleV2Repository(pg=_SchemaProbePostgres()).schema_status()

    assert not any(status.values())


@pytest.mark.asyncio
async def test_same_named_constraint_on_another_table_is_not_accepted():
    """Name alone must not satisfy a guarantee."""
    wrong = _good_constraints()
    wrong[0]["table_name"] = "some_other_table"
    status = await StrategyLifecycleV2Repository(pg=_SchemaProbePostgres(constraints=wrong)).schema_status()

    assert "ck_5scr_lifecycle_v2_shadow_only" in status["missing_constraints"]


@pytest.mark.asyncio
async def test_altered_check_definition_is_not_accepted():
    """A CHECK that no longer forbids execution authority is not the guarantee."""
    wrong = _good_constraints()
    wrong[0]["definition"] = "CHECK ((execution_authority = true))"
    status = await StrategyLifecycleV2Repository(pg=_SchemaProbePostgres(constraints=wrong)).schema_status()

    assert "ck_5scr_lifecycle_v2_shadow_only" in status["missing_constraints"]


@pytest.mark.asyncio
async def test_check_downgraded_to_another_constraint_type_is_not_accepted():
    wrong = _good_constraints()
    wrong[0]["contype"] = "u"
    status = await StrategyLifecycleV2Repository(pg=_SchemaProbePostgres(constraints=wrong)).schema_status()

    assert "ck_5scr_lifecycle_v2_shadow_only" in status["missing_constraints"]


@pytest.mark.asyncio
async def test_foreign_key_pointing_elsewhere_is_not_accepted():
    wrong = _good_constraints()
    wrong[1]["definition"] = "FOREIGN KEY (strategy_lifecycle_id) REFERENCES unrelated_table(id)"
    status = await StrategyLifecycleV2Repository(pg=_SchemaProbePostgres(constraints=wrong)).schema_status()

    assert "fk_5scr_lifecycle_v2_event_link" in status["missing_constraints"]


@pytest.mark.asyncio
async def test_check_widened_with_or_true_is_not_accepted():
    """Contains the expected fragment, forbids nothing."""
    wrong = _good_constraints()
    wrong[0]["definition"] = "CHECK (((execution_authority = false) OR true))"
    status = await StrategyLifecycleV2Repository(pg=_SchemaProbePostgres(constraints=wrong)).schema_status()

    assert "ck_5scr_lifecycle_v2_shadow_only" in status["missing_constraints"]


@pytest.mark.asyncio
async def test_foreign_key_on_the_wrong_source_column_is_not_accepted():
    """Mentions the right target table, constrains the wrong column."""
    wrong = _good_constraints()
    wrong[1]["definition"] = f"FOREIGN KEY (transport_lifecycle_id) REFERENCES {LIFECYCLE_TABLE}(strategy_lifecycle_id)"
    status = await StrategyLifecycleV2Repository(pg=_SchemaProbePostgres(constraints=wrong)).schema_status()

    assert "fk_5scr_lifecycle_v2_event_link" in status["missing_constraints"]


@pytest.mark.asyncio
async def test_default_not_false_is_not_accepted():
    """``(NOT false)`` contains "false" while meaning true."""
    wrong = _good_columns()
    wrong[0]["column_default"] = "(NOT false)"
    status = await StrategyLifecycleV2Repository(pg=_SchemaProbePostgres(columns=wrong)).schema_status()

    assert f"{LIFECYCLE_TABLE}.execution_authority" in status["missing_columns"]


@pytest.mark.asyncio
async def test_nullable_execution_authority_is_not_accepted():
    """A nullable flag defeats the CHECK it exists to support."""
    wrong = _good_columns()
    wrong[0]["is_nullable"] = "YES"
    status = await StrategyLifecycleV2Repository(pg=_SchemaProbePostgres(columns=wrong)).schema_status()

    assert f"{LIFECYCLE_TABLE}.execution_authority" in status["missing_columns"]


@pytest.mark.asyncio
async def test_execution_authority_without_false_default_is_not_accepted():
    wrong = _good_columns()
    wrong[0]["column_default"] = "true"
    status = await StrategyLifecycleV2Repository(pg=_SchemaProbePostgres(columns=wrong)).schema_status()

    assert f"{LIFECYCLE_TABLE}.execution_authority" in status["missing_columns"]


@pytest.mark.asyncio
async def test_wrong_column_type_is_not_accepted():
    """pressure_event_id as UUID would reject replay ids at insert time."""
    wrong = _good_columns()
    wrong[2]["data_type"] = "uuid"
    status = await StrategyLifecycleV2Repository(pg=_SchemaProbePostgres(columns=wrong)).schema_status()

    assert f"{LINK_TABLE}.pressure_event_id" in status["missing_columns"]


@pytest.mark.asyncio
async def test_schema_status_reports_missing_when_unavailable():
    repository = StrategyLifecycleV2Repository(pg=_FakePostgres(available=False))

    status = await repository.schema_status()

    assert LIFECYCLE_TABLE in status["missing_tables"]
    assert LINK_TABLE in status["missing_tables"]


def test_lifecycle_from_row_round_trips():
    lifecycle = _lifecycle()
    row = {
        "strategy_lifecycle_id": lifecycle.strategy_lifecycle_id,
        "symbol": lifecycle.symbol,
        "state": lifecycle.state,
        "direction_state": lifecycle.direction_state,
        "opened_at": lifecycle.opened_at_utc,
        "last_event_at": lifecycle.last_event_at_utc,
        "last_continuity_event_at": lifecycle.last_continuity_event_at_utc,
        "last_material_event_at": lifecycle.last_material_event_at_utc,
        "rule_version": lifecycle.rule_version,
        "material_state_hash": lifecycle.material_state_hash,
        "event_count": lifecycle.event_count,
        "clean_block_count": lifecycle.clean_block_count,
        "watch_count": lifecycle.watch_count,
    }

    assert lifecycle_from_row(row) == lifecycle


def test_persisted_lifecycle_never_claims_execution_authority():
    assert _lifecycle().execution_authority is False
