"""Durable, shadow-only ownership repository for Lifecycle V2 evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from contracts.strategy_5scr_lifecycle_v2 import StrategyLifecycleEventLink, StrategyLifecycleV2
from contracts.strategy_5scr_shadow_evidence_v2 import (
    StrategyEvidenceComparisonV2,
    StrategyLifecycleAdmissionLinkV2,
    StrategyShadowEvidenceSnapshotV2,
)
from storage.postgres_client import PostgresClient, pg_client
from storage.strategy_5scr_lifecycle_v2_repository import StrategyLifecycleV2Repository

ADMISSION_LINK_TABLE = "strategy_5scr_lifecycle_admission_links_v2"
EVIDENCE_JOB_TABLE = "strategy_5scr_evidence_jobs_v2"
EVIDENCE_SNAPSHOT_TABLE = "strategy_5scr_evidence_snapshots_v2"
EVIDENCE_COMPARISON_TABLE = "strategy_5scr_evidence_comparisons_v2"

_REQUIRED_TABLES = frozenset(
    {ADMISSION_LINK_TABLE, EVIDENCE_JOB_TABLE, EVIDENCE_SNAPSHOT_TABLE, EVIDENCE_COMPARISON_TABLE}
)
_REQUIRED_INDEXES = frozenset(
    {
        "ix_5scr_admission_links_lifecycle_v2",
        "ix_5scr_evidence_jobs_pending_v2",
        "ix_5scr_evidence_snapshots_decision_v2",
    }
)
# Column shape is part of readiness.  Presence alone would accept a nullable
# execution flag or a default of true, defeating the shadow-only contract.
# ``(table, column) -> (data_type, is_nullable, normalized_default)``
_REQUIRED_COLUMNS: dict[tuple[str, str], tuple[str, str, str]] = {
    (ADMISSION_LINK_TABLE, "raw_lineage_hash"): ("character varying", "NO", ""),
    (ADMISSION_LINK_TABLE, "admission_rule_version"): ("character varying", "NO", ""),
    (ADMISSION_LINK_TABLE, "execution_authority"): ("boolean", "NO", "false"),
    (EVIDENCE_JOB_TABLE, "decision_time"): ("timestamp with time zone", "YES", ""),
    (EVIDENCE_SNAPSHOT_TABLE, "max_source_candle_close"): (
        "timestamp with time zone",
        "YES",
        "",
    ),
    (EVIDENCE_SNAPSHOT_TABLE, "valid_for_execution"): ("boolean", "NO", "false"),
    (EVIDENCE_SNAPSHOT_TABLE, "execution_authority"): ("boolean", "NO", "false"),
    (EVIDENCE_COMPARISON_TABLE, "reason_codes"): ("jsonb", "NO", ""),
    (EVIDENCE_COMPARISON_TABLE, "execution_authority"): ("boolean", "NO", "false"),
}

# A constraint is identified by its table, type and complete normalized
# definition.  A same-named CHECK containing ``OR true`` must fail readiness.
# ``name -> (table, contype, normalized_definition)``
_REQUIRED_CONSTRAINTS: dict[str, tuple[str, str, str]] = {
    "ck_5scr_admission_link_shadow_only_v2": (
        ADMISSION_LINK_TABLE,
        "c",
        "check ((execution_authority = false))",
    ),
    "ck_5scr_evidence_snapshot_asof_v2": (
        EVIDENCE_SNAPSHOT_TABLE,
        "c",
        "check (((all_candles_closed = true) and ((max_source_candle_close is null) "
        "or (max_source_candle_close <= decision_time))))",
    ),
    "ck_5scr_evidence_snapshot_shadow_only_v2": (
        EVIDENCE_SNAPSHOT_TABLE,
        "c",
        "check (((valid_for_execution = false) and (execution_authority = false)))",
    ),
    "ck_5scr_evidence_comparison_shadow_only_v2": (
        EVIDENCE_COMPARISON_TABLE,
        "c",
        "check ((execution_authority = false))",
    ),
    "fk_5scr_admission_link_lifecycle_v2": (
        ADMISSION_LINK_TABLE,
        "f",
        "foreign key (strategy_lifecycle_id) references "
        "strategy_5scr_analysis_lifecycles_v2(strategy_lifecycle_id) on delete restrict",
    ),
    "fk_5scr_evidence_job_admission_v2": (
        EVIDENCE_JOB_TABLE,
        "f",
        f"foreign key (admission_event_id) references {ADMISSION_LINK_TABLE}(admission_event_id) on delete restrict",
    ),
    "fk_5scr_evidence_snapshot_job_v2": (
        EVIDENCE_SNAPSHOT_TABLE,
        "f",
        f"foreign key (evidence_job_id) references {EVIDENCE_JOB_TABLE}(evidence_job_id) on delete restrict",
    ),
    "fk_5scr_evidence_comparison_snapshot_v2": (
        EVIDENCE_COMPARISON_TABLE,
        "f",
        f"foreign key (v2_snapshot_id) references {EVIDENCE_SNAPSHOT_TABLE}(snapshot_id) on delete restrict",
    ),
}


class ShadowEvidenceV2PersistenceError(RuntimeError):
    """Durable owner invariant failed."""


class _DuplicateOwnerEventError(Exception):
    """Rollback a stale retry whose event is already linked."""


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, TypeError):
        return default


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _normalize_sql(value: Any) -> str:
    return " ".join(str(value or "").split()).lower()


def shadow_evidence_job_id(strategy_lifecycle_id: str) -> str:
    digest = hashlib.sha256(f"job|{strategy_lifecycle_id}".encode()).hexdigest()[:32]
    return f"5scr-evidence-job-v2:{digest}"


@dataclass(frozen=True)
class ShadowEvidenceWorkItemV2:
    evidence_job_id: str
    strategy_lifecycle_id: str
    admission_event_id: str
    pressure_event_id: str
    symbol: str
    lifecycle_state: str
    opened_at_utc: datetime
    admitted_at_utc: datetime
    decision_time_utc: datetime | None
    legacy_lifecycle_id: str
    attempt_count: int


class StrategyShadowEvidenceV2Repository:
    """Own admission linkage, one job per episode, snapshots and comparisons."""

    def __init__(self, *, pg: PostgresClient | None = None) -> None:
        self._pg = pg or pg_client
        self._lifecycles = StrategyLifecycleV2Repository(pg=self._pg)

    @property
    def is_available(self) -> bool:
        return self._pg.is_available

    async def schema_status(self) -> dict[str, tuple[str, ...]]:
        expected_columns = tuple(sorted(f"{table}.{column}" for table, column in _REQUIRED_COLUMNS))
        if not self._pg.is_available:
            return {
                "missing_tables": tuple(sorted(_REQUIRED_TABLES)),
                "missing_indexes": tuple(sorted(_REQUIRED_INDEXES)),
                "missing_columns": expected_columns,
                "missing_constraints": tuple(sorted(_REQUIRED_CONSTRAINTS)),
            }
        table_rows = await self._pg.fetch(
            "SELECT tablename FROM pg_catalog.pg_tables "
            "WHERE schemaname = current_schema() AND tablename = ANY($1::text[])",
            sorted(_REQUIRED_TABLES),
        )
        index_rows = await self._pg.fetch(
            "SELECT indexname FROM pg_catalog.pg_indexes "
            "WHERE schemaname = current_schema() AND indexname = ANY($1::text[])",
            sorted(_REQUIRED_INDEXES),
        )
        column_rows = await self._pg.fetch(
            "SELECT table_name, column_name, data_type, is_nullable, column_default "
            "FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = ANY($1::text[])",
            sorted(_REQUIRED_TABLES),
        )
        constraint_rows = await self._pg.fetch(
            "SELECT conname, conrelid::regclass::text AS table_name, "
            "contype::text AS contype, pg_get_constraintdef(oid) AS definition "
            "FROM pg_catalog.pg_constraint "
            "WHERE connamespace = current_schema()::regnamespace "
            "AND conname = ANY($1::text[])",
            sorted(_REQUIRED_CONSTRAINTS),
        )
        present_tables = {str(_row_value(row, "tablename")) for row in table_rows}
        present_indexes = {str(_row_value(row, "indexname")) for row in index_rows}
        satisfied_columns: set[str] = set()
        for row in column_rows:
            key = (str(_row_value(row, "table_name")), str(_row_value(row, "column_name")))
            expected = _REQUIRED_COLUMNS.get(key)
            if expected is None:
                continue
            actual = (
                str(_row_value(row, "data_type")),
                str(_row_value(row, "is_nullable")),
                _normalize_sql(_row_value(row, "column_default")),
            )
            if actual == expected:
                satisfied_columns.add(f"{key[0]}.{key[1]}")

        satisfied_constraints: set[str] = set()
        for row in constraint_rows:
            name = str(_row_value(row, "conname") or "")
            expected = _REQUIRED_CONSTRAINTS.get(name)
            if expected is None:
                continue
            actual = (
                str(_row_value(row, "table_name")),
                str(_row_value(row, "contype")),
                _normalize_sql(_row_value(row, "definition")),
            )
            if actual == expected:
                satisfied_constraints.add(name)
        return {
            "missing_tables": tuple(sorted(_REQUIRED_TABLES - present_tables)),
            "missing_indexes": tuple(sorted(_REQUIRED_INDEXES - present_indexes)),
            "missing_columns": tuple(sorted(set(expected_columns) - satisfied_columns)),
            "missing_constraints": tuple(sorted(set(_REQUIRED_CONSTRAINTS) - satisfied_constraints)),
        }

    async def persist_owner_bundle(
        self,
        lifecycle: StrategyLifecycleV2,
        event_link: StrategyLifecycleEventLink,
        admission_link: StrategyLifecycleAdmissionLinkV2,
    ) -> bool:
        """Atomically persist episode, event, admission lineage and its one job."""

        if lifecycle.strategy_lifecycle_id != event_link.strategy_lifecycle_id:
            raise ShadowEvidenceV2PersistenceError("event link lifecycle mismatch")
        if lifecycle.strategy_lifecycle_id != admission_link.strategy_lifecycle_id:
            raise ShadowEvidenceV2PersistenceError("admission link lifecycle mismatch")
        if event_link.pressure_event_id != admission_link.pressure_event_id:
            raise ShadowEvidenceV2PersistenceError("admission pressure event mismatch")
        job_id = shadow_evidence_job_id(lifecycle.strategy_lifecycle_id)
        try:
            async with self._pg.transaction() as connection:
                await self._lifecycles.upsert_lifecycle(lifecycle, _executor=connection)
                if not await self._lifecycles.link_event(event_link, _executor=connection):
                    raise _DuplicateOwnerEventError
                await connection.execute(
                    f"""
                    INSERT INTO {ADMISSION_LINK_TABLE} (
                        admission_event_id, strategy_lifecycle_id, pressure_event_id,
                        raw_lineage_hash, admission_rule_version, admitted_at,
                        linked_at, execution_authority
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, false)
                    ON CONFLICT (admission_event_id) DO NOTHING
                    """,
                    admission_link.admission_event_id,
                    admission_link.strategy_lifecycle_id,
                    admission_link.pressure_event_id,
                    admission_link.raw_lineage_hash,
                    admission_link.admission_rule_version,
                    admission_link.admitted_at_utc,
                    admission_link.linked_at_utc,
                )
                stored = await connection.fetchrow(
                    f"""
                    SELECT strategy_lifecycle_id, pressure_event_id, raw_lineage_hash,
                           admission_rule_version, admitted_at
                    FROM {ADMISSION_LINK_TABLE}
                    WHERE admission_event_id = $1
                    """,
                    admission_link.admission_event_id,
                )
                expected = (
                    admission_link.strategy_lifecycle_id,
                    admission_link.pressure_event_id,
                    admission_link.raw_lineage_hash,
                    admission_link.admission_rule_version,
                    admission_link.admitted_at_utc,
                )
                actual = (
                    str(_row_value(stored, "strategy_lifecycle_id")),
                    str(_row_value(stored, "pressure_event_id")),
                    str(_row_value(stored, "raw_lineage_hash")),
                    str(_row_value(stored, "admission_rule_version")),
                    _row_value(stored, "admitted_at"),
                )
                if actual != expected:
                    raise ShadowEvidenceV2PersistenceError("admission identity is immutable")
                await connection.execute(
                    f"""
                    INSERT INTO {EVIDENCE_JOB_TABLE} (
                        evidence_job_id, strategy_lifecycle_id, admission_event_id,
                        pressure_event_id, status
                    ) VALUES ($1, $2, $3, $4, 'PENDING')
                    ON CONFLICT (strategy_lifecycle_id) DO NOTHING
                    """,
                    job_id,
                    lifecycle.strategy_lifecycle_id,
                    admission_link.admission_event_id,
                    event_link.pressure_event_id,
                )
        except _DuplicateOwnerEventError:
            return False
        return True

    async def load_pending(self, *, limit: int) -> tuple[ShadowEvidenceWorkItemV2, ...]:
        rows = await self._pg.fetch(
            f"""
            SELECT j.evidence_job_id, j.strategy_lifecycle_id, j.admission_event_id,
                   j.pressure_event_id, j.decision_time, j.attempt_count,
                   l.symbol, l.state AS lifecycle_state, l.opened_at,
                   a.admitted_at, e.transport_lifecycle_id
            FROM {EVIDENCE_JOB_TABLE} j
            JOIN strategy_5scr_analysis_lifecycles_v2 l
              ON l.strategy_lifecycle_id = j.strategy_lifecycle_id
            JOIN {ADMISSION_LINK_TABLE} a
              ON a.admission_event_id = j.admission_event_id
            JOIN strategy_5scr_lifecycle_event_links_v2 e
              ON e.pressure_event_id = j.pressure_event_id
            WHERE j.status = 'PENDING'
            ORDER BY j.created_at, j.evidence_job_id
            LIMIT $1
            """,
            max(1, int(limit)),
        )
        return tuple(
            ShadowEvidenceWorkItemV2(
                evidence_job_id=str(_row_value(row, "evidence_job_id")),
                strategy_lifecycle_id=str(_row_value(row, "strategy_lifecycle_id")),
                admission_event_id=str(_row_value(row, "admission_event_id")),
                pressure_event_id=str(_row_value(row, "pressure_event_id")),
                symbol=str(_row_value(row, "symbol")),
                lifecycle_state=str(_row_value(row, "lifecycle_state")),
                opened_at_utc=_row_value(row, "opened_at"),
                admitted_at_utc=_row_value(row, "admitted_at"),
                decision_time_utc=_row_value(row, "decision_time"),
                legacy_lifecycle_id=str(_row_value(row, "transport_lifecycle_id")),
                attempt_count=int(_row_value(row, "attempt_count", 0) or 0),
            )
            for row in rows
        )

    async def freeze_decision_time(self, evidence_job_id: str, decision_time: datetime) -> datetime:
        row = await self._pg.fetchrow(
            f"""
            UPDATE {EVIDENCE_JOB_TABLE}
            SET decision_time = COALESCE(decision_time, $2),
                attempt_count = attempt_count + 1,
                updated_at = NOW()
            WHERE evidence_job_id = $1 AND status = 'PENDING'
            RETURNING decision_time
            """,
            evidence_job_id,
            decision_time,
        )
        if row is None:
            raise ShadowEvidenceV2PersistenceError("evidence job is not pending")
        return _row_value(row, "decision_time")

    async def legacy_evidence(self, pressure_event_id: str) -> dict[str, Any] | None:
        row = await self._pg.fetchrow(
            """
            SELECT s.snapshot_id, s.lifecycle_id, s.payload,
                   i.status AS inbox_status, i.result_payload, i.last_error
            FROM strategy_5scr_evidence_snapshots s
            LEFT JOIN strategy_5scr_inbox i ON i.event_id = s.event_id
            WHERE s.event_id::text = $1
            """,
            pressure_event_id,
        )
        return None if row is None else dict(row)

    async def grouping_snapshot(self, strategy_lifecycle_id: str) -> dict[str, int]:
        row = await self._pg.fetchrow(
            """
            SELECT count(*)::bigint AS events,
                   count(DISTINCT transport_lifecycle_id)::bigint AS transport_lifecycles,
                   count(DISTINCT source_clean_block_id) FILTER (
                       WHERE source_clean_block_id IS NOT NULL
                   )::bigint AS clean_blocks
            FROM strategy_5scr_lifecycle_event_links_v2
            WHERE strategy_lifecycle_id = $1
            """,
            strategy_lifecycle_id,
        )
        return {
            "events": int(_row_value(row, "events", 0) or 0),
            "transport_lifecycles": int(_row_value(row, "transport_lifecycles", 0) or 0),
            "clean_blocks": int(_row_value(row, "clean_blocks", 0) or 0),
        }

    async def persist_result(
        self,
        snapshot: StrategyShadowEvidenceSnapshotV2,
        comparison: StrategyEvidenceComparisonV2,
    ) -> bool:
        snapshot_payload = snapshot.model_dump(mode="json")
        comparison_payload = comparison.model_dump(mode="json")
        candle_ids = [item.candle_id for item in snapshot.source_candles]
        max_close = max((item.period_close_utc for item in snapshot.source_candles), default=None)
        async with self._pg.transaction() as connection:
            await connection.execute(
                f"""
                INSERT INTO {EVIDENCE_SNAPSHOT_TABLE} (
                    snapshot_id, evidence_job_id, strategy_lifecycle_id,
                    admission_event_id, decision_time, provider_calendar_version,
                    source_candle_ids, max_source_candle_close, all_candles_closed,
                    coverage_status, context_hash, evidence_hash, result_state,
                    terminal_reason, trade_geometry_hash, payload,
                    valid_for_execution, execution_authority
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7::jsonb, $8, true,
                    $9, $10, $11, $12, $13, $14, $15::jsonb, false, false
                )
                ON CONFLICT (snapshot_id) DO NOTHING
                """,
                snapshot.snapshot_id,
                snapshot.evidence_job_id,
                snapshot.strategy_lifecycle_id,
                snapshot.admission_event_id,
                snapshot.decision_time_utc,
                snapshot.provider_calendar_version,
                _json(candle_ids),
                max_close,
                snapshot.coverage_status,
                snapshot.context_hash,
                snapshot.evidence_hash,
                snapshot.result_state,
                snapshot.terminal_reason,
                snapshot.trade_geometry_hash,
                _json(snapshot_payload),
            )
            stored = await connection.fetchrow(
                f"SELECT evidence_hash FROM {EVIDENCE_SNAPSHOT_TABLE} WHERE snapshot_id = $1",
                snapshot.snapshot_id,
            )
            if str(_row_value(stored, "evidence_hash")) != snapshot.evidence_hash:
                raise ShadowEvidenceV2PersistenceError("evidence snapshot is immutable")
            await connection.execute(
                f"""
                INSERT INTO {EVIDENCE_COMPARISON_TABLE} (
                    comparison_id, strategy_lifecycle_id, v2_snapshot_id,
                    legacy_lifecycle_id, legacy_snapshot_id,
                    same_lifecycle_grouping, same_candle_set, same_context_hash,
                    same_terminal_reason, same_trade_geometry, reason_codes,
                    payload, execution_authority
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                    $11::jsonb, $12::jsonb, false
                )
                ON CONFLICT (comparison_id) DO NOTHING
                """,
                comparison.comparison_id,
                comparison.strategy_lifecycle_id,
                comparison.v2_snapshot_id,
                comparison.legacy_lifecycle_id,
                comparison.legacy_snapshot_id,
                comparison.same_lifecycle_grouping,
                comparison.same_candle_set,
                comparison.same_context_hash,
                comparison.same_terminal_reason,
                comparison.same_trade_geometry,
                _json(list(comparison.reason_codes)),
                _json(comparison_payload),
            )
            result = await connection.execute(
                f"""
                UPDATE {EVIDENCE_JOB_TABLE}
                SET status = 'COMPLETED', last_error = NULL, updated_at = NOW()
                WHERE evidence_job_id = $1 AND status = 'PENDING'
                """,
                snapshot.evidence_job_id,
            )
        return bool(str(result).endswith(" 1"))

    async def record_failure(self, evidence_job_id: str, *, error: str, max_attempts: int) -> bool:
        result = await self._pg.execute(
            f"""
            UPDATE {EVIDENCE_JOB_TABLE}
            SET status = CASE WHEN attempt_count >= $3 THEN 'FAILED' ELSE 'PENDING' END,
                last_error = $2, updated_at = NOW()
            WHERE evidence_job_id = $1 AND status = 'PENDING'
            """,
            evidence_job_id,
            error[:2000],
            max(1, int(max_attempts)),
        )
        return bool(str(result).endswith(" 1"))

    async def metrics_snapshot(self) -> dict[str, int | float | None]:
        row = await self._pg.fetchrow(
            f"""
            SELECT
                (SELECT count(*) FROM {ADMISSION_LINK_TABLE})::bigint AS admissions,
                (SELECT count(*) FROM strategy_5scr_lifecycles)::bigint AS legacy_lifecycles,
                (SELECT count(*) FROM strategy_5scr_analysis_lifecycles_v2)::bigint AS lifecycles,
                (SELECT count(*) FROM strategy_5scr_lifecycle_event_links_v2)::bigint AS events,
                (SELECT count(DISTINCT source_clean_block_id)
                   FROM strategy_5scr_lifecycle_event_links_v2
                  WHERE source_clean_block_id IS NOT NULL)::bigint AS clean_blocks,
                (SELECT count(*) FROM {EVIDENCE_JOB_TABLE})::bigint AS jobs,
                (SELECT count(*) FROM {EVIDENCE_SNAPSHOT_TABLE})::bigint AS snapshots,
                (SELECT count(*) FROM {EVIDENCE_SNAPSHOT_TABLE}
                  WHERE coverage_status = 'COMPLETE')::bigint AS complete_snapshots,
                (SELECT count(*) FROM {EVIDENCE_SNAPSHOT_TABLE}
                  WHERE result_state = 'WAIT')::bigint AS wait_results,
                (SELECT count(*) FROM {EVIDENCE_SNAPSHOT_TABLE}
                  WHERE result_state = 'NO_TRADE')::bigint AS no_trade_results,
                (SELECT count(*) FROM {EVIDENCE_SNAPSHOT_TABLE}
                  WHERE result_state = 'CONDITIONAL')::bigint AS conditional_results,
                (SELECT count(*) FROM {EVIDENCE_COMPARISON_TABLE}
                  WHERE reason_codes <> '[]'::jsonb)::bigint AS divergences,
                (SELECT count(*)
                   FROM {EVIDENCE_JOB_TABLE} j
                   LEFT JOIN {EVIDENCE_SNAPSHOT_TABLE} s
                     ON s.evidence_job_id = j.evidence_job_id
                  WHERE j.status = 'COMPLETED' AND s.snapshot_id IS NULL)::bigint
                  AS restart_parity_failures
            """
        )
        admissions = int(_row_value(row, "admissions", 0) or 0)
        legacy_lifecycles = int(_row_value(row, "legacy_lifecycles", 0) or 0)
        lifecycles = int(_row_value(row, "lifecycles", 0) or 0)
        events = int(_row_value(row, "events", 0) or 0)
        clean_blocks = int(_row_value(row, "clean_blocks", 0) or 0)
        snapshots = int(_row_value(row, "snapshots", 0) or 0)
        complete = int(_row_value(row, "complete_snapshots", 0) or 0)
        return {
            "emission_count": admissions,
            "legacy_lifecycle_count": legacy_lifecycles,
            "lifecycle_v2_count": lifecycles,
            "evidence_job_count": int(_row_value(row, "jobs", 0) or 0),
            "evidence_snapshot_count": snapshots,
            "evidence_complete_count": complete,
            "wait_result_count": int(_row_value(row, "wait_results", 0) or 0),
            "no_trade_result_count": int(_row_value(row, "no_trade_results", 0) or 0),
            "conditional_result_count": int(_row_value(row, "conditional_results", 0) or 0),
            "legacy_v2_divergence_count": int(_row_value(row, "divergences", 0) or 0),
            "compression_ratio_legacy_per_v2": (round(legacy_lifecycles / lifecycles, 4) if lifecycles else None),
            "events_per_v2_lifecycle": round(events / lifecycles, 4) if lifecycles else None,
            "clean_blocks_per_v2_lifecycle": (round(clean_blocks / lifecycles, 4) if lifecycles else None),
            "evidence_completeness_ratio": round(complete / snapshots, 4) if snapshots else None,
            "restart_parity_failure_count": int(_row_value(row, "restart_parity_failures", 0) or 0),
        }


__all__ = [
    "ADMISSION_LINK_TABLE",
    "EVIDENCE_COMPARISON_TABLE",
    "EVIDENCE_JOB_TABLE",
    "EVIDENCE_SNAPSHOT_TABLE",
    "ShadowEvidenceV2PersistenceError",
    "ShadowEvidenceWorkItemV2",
    "StrategyShadowEvidenceV2Repository",
    "shadow_evidence_job_id",
]
