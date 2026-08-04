"""Durable persistence for Strategy Analysis Lifecycle V2 (market episodes).

Shadow-only by construction.  This repository writes to two new tables and
reads nothing that any execution path depends on.  It never touches
``pressure_outbox``, ``strategy_5scr_inbox`` or the existing
``strategy_5scr_lifecycles``, so transport identity and delivery semantics are
unchanged.

Restart safety matters more than throughput here: the active episode is
recovered from the database rather than from process memory, so a worker
restart continues an episode instead of forking it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, cast

from contracts.strategy_5scr_lifecycle_v2 import (
    ACTIVE_LIFECYCLE_STATES,
    DirectionState,
    LifecycleState,
    StrategyLifecycleEventLink,
    StrategyLifecycleV2,
)
from storage.postgres_client import PostgresClient, pg_client

LIFECYCLE_TABLE = "strategy_5scr_analysis_lifecycles_v2"
LINK_TABLE = "strategy_5scr_lifecycle_event_links_v2"

_REQUIRED_TABLES = frozenset({LIFECYCLE_TABLE, LINK_TABLE})
_REQUIRED_INDEXES = frozenset(
    {
        "ix_5scr_lifecycle_v2_active_symbol",
        "ix_5scr_lifecycle_v2_links_lifecycle",
        "ix_5scr_lifecycle_v2_links_transport",
    }
)
#: Columns whose *shape* is a guarantee, not just their presence.  A nullable
#: ``execution_authority`` with no default would satisfy an existence check
#: while silently permitting the row the CHECK exists to forbid.
#: ``(table, column) -> (data_type, is_nullable, exact_normalized_default | None)``
_REQUIRED_COLUMNS: dict[tuple[str, str], tuple[str, str, str | None]] = {
    # Exact, not a substring: ``(NOT false)`` also contains "false" while
    # meaning the opposite.
    (LIFECYCLE_TABLE, "execution_authority"): ("boolean", "NO", "false"),
    (LINK_TABLE, "transport_lifecycle_id"): ("text", "NO", None),
    (LINK_TABLE, "pressure_event_id"): ("text", "NO", None),
}
#: Constraints that *are* the guarantees.  Neither the name nor a fragment of
#: the definition is sufficient evidence:
#:
#:   * a same-named constraint on another table proves nothing;
#:   * ``CHECK ((execution_authority = false) OR true)`` *contains* the
#:     expected fragment while forbidding nothing;
#:   * an FK declared on the wrong source column still mentions the right
#:     target table.
#:
#: So the full definition is compared, normalized, against what PostgreSQL
#: renders for the migration's own DDL.
#: ``name -> (table, contype, exact_normalized_definition)``
_REQUIRED_CONSTRAINTS: dict[str, tuple[str, str, str]] = {
    "ck_5scr_lifecycle_v2_shadow_only": (
        LIFECYCLE_TABLE,
        "c",
        "check ((execution_authority = false))",
    ),
    "fk_5scr_lifecycle_v2_event_link": (
        LINK_TABLE,
        "f",
        f"foreign key (strategy_lifecycle_id) references {LIFECYCLE_TABLE}(strategy_lifecycle_id)",
    ),
}


def _normalize_sql(value: Any) -> str:
    """Collapse whitespace and case so definitions compare exactly.

    Deliberately does not strip parentheses: ``(a = false)`` and
    ``((a = false) OR true)`` must not normalize to the same thing.
    """
    return " ".join(str(value or "").split()).lower()


class LifecycleV2PersistenceError(RuntimeError):
    """Base error for durable lifecycle V2 persistence."""


class _DuplicateEventLinkRollbackError(Exception):
    """Abort a transaction whose event link already exists."""


@dataclass(frozen=True)
class LifecycleV2RecoveryState:
    lifecycle: StrategyLifecycleV2
    known_lineage: tuple[str, ...] = ()
    context_hash: str | None = None
    transport_lifecycle_id: str | None = None


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, TypeError):
        return default


def lifecycle_from_row(row: Any) -> StrategyLifecycleV2:
    return StrategyLifecycleV2(
        strategy_lifecycle_id=str(_row_value(row, "strategy_lifecycle_id")),
        symbol=str(_row_value(row, "symbol")),
        state=cast(LifecycleState, str(_row_value(row, "state"))),
        direction_state=cast(DirectionState, str(_row_value(row, "direction_state"))),
        opened_at_utc=_row_value(row, "opened_at"),
        last_event_at_utc=_row_value(row, "last_event_at"),
        last_continuity_event_at_utc=_row_value(row, "last_continuity_event_at"),
        last_material_event_at_utc=_row_value(row, "last_material_event_at"),
        rule_version=cast(
            Literal["5scr.market-episode.v1"],
            str(_row_value(row, "rule_version")),
        ),
        material_state_hash=str(_row_value(row, "material_state_hash")),
        event_count=int(_row_value(row, "event_count", 0) or 0),
        clean_block_count=int(_row_value(row, "clean_block_count", 0) or 0),
        watch_count=int(_row_value(row, "watch_count", 0) or 0),
    )


class StrategyLifecycleV2Repository:
    """Upsert episodes and their event links; read back the active episode."""

    def __init__(self, *, pg: PostgresClient | None = None) -> None:
        self._pg = pg or pg_client

    @property
    def is_available(self) -> bool:
        return self._pg.is_available

    async def schema_status(self) -> dict[str, tuple[str, ...]]:
        """Non-secret readiness snapshot for migration ``20260729_01``.

        Reports columns and constraints as well as tables and indexes: the
        shadow-only CHECK and the event-link FK *are* the guarantees this layer
        relies on, so a database missing them must not be reported ready.
        """
        expected_columns = tuple(sorted(f"{table}.{column}" for table, column in _REQUIRED_COLUMNS))
        if not self._pg.is_available:
            return {
                "missing_tables": tuple(sorted(_REQUIRED_TABLES)),
                "missing_indexes": tuple(sorted(_REQUIRED_INDEXES)),
                "missing_columns": expected_columns,
                "missing_constraints": tuple(sorted(_REQUIRED_CONSTRAINTS)),
            }
        table_rows = await self._pg.fetch(
            """
            SELECT tablename FROM pg_catalog.pg_tables
            WHERE schemaname = current_schema() AND tablename = ANY($1::text[])
            """,
            sorted(_REQUIRED_TABLES),
        )
        index_rows = await self._pg.fetch(
            """
            SELECT indexname FROM pg_catalog.pg_indexes
            WHERE schemaname = current_schema() AND indexname = ANY($1::text[])
            """,
            sorted(_REQUIRED_INDEXES),
        )
        # Column *shape*, not just presence.
        column_rows = await self._pg.fetch(
            """
            SELECT table_name, column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = current_schema() AND table_name = ANY($1::text[])
            """,
            sorted(_REQUIRED_TABLES),
        )
        # Constraint identity is (table, type, definition), never the name
        # alone: a same-named constraint elsewhere, or one whose definition was
        # altered, must not read as satisfied.
        constraint_rows = await self._pg.fetch(
            """
            SELECT conname,
                   conrelid::regclass::text AS table_name,
                   contype::text AS contype,
                   pg_get_constraintdef(oid) AS definition
            FROM pg_catalog.pg_constraint
            WHERE connamespace = current_schema()::regnamespace
              AND conname = ANY($1::text[])
            """,
            sorted(_REQUIRED_CONSTRAINTS),
        )
        present_tables = {str(_row_value(row, "tablename") or "") for row in table_rows}
        present_indexes = {str(_row_value(row, "indexname") or "") for row in index_rows}

        satisfied_columns: set[str] = set()
        for row in column_rows:
            key = (str(_row_value(row, "table_name")), str(_row_value(row, "column_name")))
            expected = _REQUIRED_COLUMNS.get(key)
            if expected is None:
                continue
            data_type, nullable, expected_default = expected
            if str(_row_value(row, "data_type")) != data_type:
                continue
            if str(_row_value(row, "is_nullable")) != nullable:
                continue
            if expected_default is not None and _normalize_sql(_row_value(row, "column_default")) != expected_default:
                continue
            satisfied_columns.add(f"{key[0]}.{key[1]}")

        satisfied_constraints: set[str] = set()
        for row in constraint_rows:
            name = str(_row_value(row, "conname") or "")
            expected_constraint = _REQUIRED_CONSTRAINTS.get(name)
            if expected_constraint is None:
                continue
            table, contype, expected_definition = expected_constraint
            if str(_row_value(row, "table_name")) != table:
                continue
            if str(_row_value(row, "contype")) != contype:
                continue
            # Exact match on the whole normalized definition. A fragment check
            # would accept "(execution_authority = false) OR true".
            if _normalize_sql(_row_value(row, "definition")) != expected_definition:
                continue
            satisfied_constraints.add(name)

        return {
            "missing_tables": tuple(sorted(_REQUIRED_TABLES - present_tables)),
            "missing_indexes": tuple(sorted(_REQUIRED_INDEXES - present_indexes)),
            "missing_columns": tuple(sorted(set(expected_columns) - satisfied_columns)),
            "missing_constraints": tuple(sorted(set(_REQUIRED_CONSTRAINTS) - satisfied_constraints)),
        }

    async def active_lifecycle(self, symbol: str) -> StrategyLifecycleV2 | None:
        """Recover the open episode for a symbol so restarts do not fork it."""
        row = await self._pg.fetchrow(
            f"""
            SELECT * FROM {LIFECYCLE_TABLE}
            WHERE symbol = $1 AND state = ANY($2::text[])
            ORDER BY last_continuity_event_at DESC
            LIMIT 1
            """,
            symbol.upper(),
            sorted(ACTIVE_LIFECYCLE_STATES),
        )
        return None if row is None else lifecycle_from_row(row)

    async def active_recovery_state(self, symbol: str) -> LifecycleV2RecoveryState | None:
        """Recover process-local reducer memory from durable event lineage."""

        lifecycle = await self.active_lifecycle(symbol)
        if lifecycle is None:
            return None
        rows = await self._pg.fetch(
            f"""
            SELECT link.transport_lifecycle_id, link.source_clean_block_id,
                   link.source_watch_id, outbox.payload
            FROM {LINK_TABLE} link
            LEFT JOIN pressure_outbox outbox
              ON outbox.event_id::text = link.pressure_event_id
            WHERE link.strategy_lifecycle_id = $1
            ORDER BY link.linked_at, link.pressure_event_id
            """,
            lifecycle.strategy_lifecycle_id,
        )
        known_lineage: set[str] = set()
        context_hash: str | None = None
        transport_lifecycle_id: str | None = None
        for row in rows:
            for key in ("source_clean_block_id", "source_watch_id"):
                value = _row_value(row, key)
                if value is not None and str(value).strip():
                    known_lineage.add(str(value).strip())
            transport_value = _row_value(row, "transport_lifecycle_id")
            if transport_value is not None and str(transport_value).strip():
                transport_lifecycle_id = str(transport_value).strip()
            payload = _row_value(row, "payload")
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except (TypeError, ValueError):
                    payload = None
            if isinstance(payload, Mapping):
                raw_context = payload.get("material_context_hash") or payload.get("context_version")
                if raw_context is not None and str(raw_context).strip():
                    context_hash = str(raw_context).strip()
        return LifecycleV2RecoveryState(
            lifecycle=lifecycle,
            known_lineage=tuple(sorted(known_lineage)),
            context_hash=context_hash,
            transport_lifecycle_id=transport_lifecycle_id,
        )

    async def upsert_lifecycle(
        self,
        lifecycle: StrategyLifecycleV2,
        *,
        _executor: Any | None = None,
    ) -> None:
        """Persist an episode.  Idempotent on ``strategy_lifecycle_id``."""
        executor = self._pg if _executor is None else _executor
        await executor.execute(
            f"""
            INSERT INTO {LIFECYCLE_TABLE} (
                strategy_lifecycle_id, symbol, state, direction_state,
                opened_at, last_event_at, last_continuity_event_at,
                last_material_event_at, rule_version, material_state_hash,
                event_count, clean_block_count, watch_count
            )
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
            ON CONFLICT (strategy_lifecycle_id) DO UPDATE SET
                state = EXCLUDED.state,
                direction_state = EXCLUDED.direction_state,
                last_event_at = GREATEST(
                    {LIFECYCLE_TABLE}.last_event_at, EXCLUDED.last_event_at
                ),
                last_continuity_event_at = GREATEST(
                    {LIFECYCLE_TABLE}.last_continuity_event_at,
                    EXCLUDED.last_continuity_event_at
                ),
                last_material_event_at = GREATEST(
                    {LIFECYCLE_TABLE}.last_material_event_at,
                    EXCLUDED.last_material_event_at
                ),
                material_state_hash = EXCLUDED.material_state_hash,
                event_count = EXCLUDED.event_count,
                clean_block_count = EXCLUDED.clean_block_count,
                watch_count = EXCLUDED.watch_count,
                updated_at = now()
            """,
            lifecycle.strategy_lifecycle_id,
            lifecycle.symbol,
            lifecycle.state,
            lifecycle.direction_state,
            lifecycle.opened_at_utc,
            lifecycle.last_event_at_utc,
            lifecycle.last_continuity_event_at_utc,
            lifecycle.last_material_event_at_utc,
            lifecycle.rule_version,
            lifecycle.material_state_hash,
            lifecycle.event_count,
            lifecycle.clean_block_count,
            lifecycle.watch_count,
        )

    async def link_event(
        self,
        link: StrategyLifecycleEventLink,
        *,
        _executor: Any | None = None,
    ) -> bool:
        """Attach a pressure event to an episode.

        Returns ``False`` when the event was already linked, so an at-least-once
        redelivery cannot inflate an episode's event count.
        """
        executor = self._pg if _executor is None else _executor
        result = await executor.execute(
            f"""
            INSERT INTO {LINK_TABLE} (
                pressure_event_id, strategy_lifecycle_id, transport_lifecycle_id,
                source_clean_block_id, source_watch_id, linked_at, link_reason
            )
            VALUES ($1,$2,$3,$4,$5,$6,$7)
            ON CONFLICT (pressure_event_id) DO NOTHING
            """,
            link.pressure_event_id,
            link.strategy_lifecycle_id,
            link.transport_lifecycle_id,
            link.source_clean_block_id,
            link.source_watch_id,
            link.linked_at_utc,
            link.link_reason,
        )
        return _inserted(result)

    async def persist(
        self,
        lifecycle: StrategyLifecycleV2,
        link: StrategyLifecycleEventLink,
    ) -> bool:
        """Write episode and link atomically.

        A link without its lifecycle would violate the foreign key; a lifecycle
        whose counters advanced without a link would double-count on retry.
        """
        try:
            async with self._pg.transaction() as connection:
                await self.upsert_lifecycle(lifecycle, _executor=connection)
                if not await self.link_event(link, _executor=connection):
                    # The lifecycle upsert happened first to satisfy the FK.
                    # Roll it back when another worker already linked this
                    # event, otherwise a lagging worker could overwrite newer
                    # counters or state with its stale snapshot.
                    raise _DuplicateEventLinkRollbackError
        except _DuplicateEventLinkRollbackError:
            return False
        return True

    async def fetch_unlinked_events(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Read delivered pressure events that have no episode link yet.

        Reads the durable inbox joined to its outbox payload.  Deliberately
        takes no lease and updates no status: the dispatcher owns delivery, and
        a shadow reader must never compete for those rows.  "Not yet linked" is
        the cursor, which makes the read idempotent and restart-safe.
        """
        rows = await self._pg.fetch(
            f"""
            SELECT o.event_id, o.symbol, o.lifecycle_id, o.signal_valid_at, o.payload
            FROM strategy_5scr_inbox i
            JOIN pressure_outbox o ON o.event_id = i.event_id
            LEFT JOIN {LINK_TABLE} l ON l.pressure_event_id = o.event_id::text
            WHERE l.pressure_event_id IS NULL
            ORDER BY o.symbol, o.signal_valid_at, o.event_id
            LIMIT $1
            """,
            limit,
        )
        return [dict(row) if isinstance(row, Mapping) else row for row in rows]

    async def compression_snapshot(self, *, since: datetime | None = None) -> dict[str, Any]:
        """Compare transport grouping against episode grouping.

        This is the number the shadow period exists to produce.
        """
        row = await self._pg.fetchrow(
            f"""
            SELECT
                count(*)::bigint AS events,
                count(DISTINCT transport_lifecycle_id)::bigint AS transport_lifecycles,
                count(DISTINCT strategy_lifecycle_id)::bigint AS strategy_lifecycles,
                count(*) FILTER (
                    WHERE source_clean_block_id IS NULL AND source_watch_id IS NULL
                )::bigint AS events_without_canonical_anchor
            FROM {LINK_TABLE}
            WHERE ($1::timestamptz IS NULL OR linked_at >= $1)
            """,
            since,
        )
        events = int(_row_value(row, "events", 0) or 0)
        transport = int(_row_value(row, "transport_lifecycles", 0) or 0)
        strategy = int(_row_value(row, "strategy_lifecycles", 0) or 0)
        return {
            "pressure_events_total": events,
            "legacy_transport_lifecycles_total": transport,
            "strategy_lifecycles_v2_total": strategy,
            "legacy_compression_ratio": round(events / transport, 4) if transport else None,
            "lifecycle_v2_compression_ratio": round(events / strategy, 4) if strategy else None,
            "events_without_canonical_anchor_total": int(_row_value(row, "events_without_canonical_anchor", 0) or 0),
        }


def _inserted(result: Any) -> bool:
    """Interpret an ``INSERT ... ON CONFLICT DO NOTHING`` command tag."""
    if isinstance(result, str) and result.upper().startswith("INSERT"):
        return not result.strip().endswith(" 0")
    return bool(result)


__all__ = [
    "LIFECYCLE_TABLE",
    "LINK_TABLE",
    "LifecycleV2RecoveryState",
    "LifecycleV2PersistenceError",
    "StrategyLifecycleV2Repository",
    "lifecycle_from_row",
]
