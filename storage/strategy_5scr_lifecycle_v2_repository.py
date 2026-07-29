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

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from contracts.strategy_5scr_lifecycle_v2 import (
    ACTIVE_LIFECYCLE_STATES,
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


class LifecycleV2PersistenceError(RuntimeError):
    """Base error for durable lifecycle V2 persistence."""


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
        state=str(_row_value(row, "state")),
        direction_state=str(_row_value(row, "direction_state")),
        opened_at_utc=_row_value(row, "opened_at"),
        last_event_at_utc=_row_value(row, "last_event_at"),
        last_continuity_event_at_utc=_row_value(row, "last_continuity_event_at"),
        last_material_event_at_utc=_row_value(row, "last_material_event_at"),
        rule_version=str(_row_value(row, "rule_version")),
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
        """Non-secret readiness snapshot for migration ``20260729_01``."""
        if not self._pg.is_available:
            return {
                "missing_tables": tuple(sorted(_REQUIRED_TABLES)),
                "missing_indexes": tuple(sorted(_REQUIRED_INDEXES)),
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
        present_tables = {str(_row_value(row, "tablename") or "") for row in table_rows}
        present_indexes = {str(_row_value(row, "indexname") or "") for row in index_rows}
        return {
            "missing_tables": tuple(sorted(_REQUIRED_TABLES - present_tables)),
            "missing_indexes": tuple(sorted(_REQUIRED_INDEXES - present_indexes)),
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
        async with self._pg.transaction() as connection:
            await self.upsert_lifecycle(lifecycle, _executor=connection)
            return await self.link_event(link, _executor=connection)

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
    "LifecycleV2PersistenceError",
    "StrategyLifecycleV2Repository",
    "lifecycle_from_row",
]
