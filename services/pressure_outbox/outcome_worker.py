"""Automatic, non-executable M1 outcome tracking for durable 5S-CR candidates."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from loguru import logger

from analysis.strategy_5scr_m1_outcome import (
    classify_strategy_5scr_m1_outcome,
    tradeplan_from_candidate_payload,
)
from contracts.canonical_candle import CanonicalCandle, as_utc
from contracts.strategy_5scr_pressure import Strategy5SCRTradePlan
from contracts.strategy_5scr_replay import Strategy5SCRM1Outcome
from storage.postgres_client import PostgresClient, pg_client
from storage.strategy_5scr_candle_store import PostgresClosedCandleStore

_REQUIRED_TABLES = frozenset(
    {
        "strategy_5scr_tradeplan_candidates",
        "strategy_5scr_m1_outcomes",
    }
)
_REQUIRED_INDEXES = frozenset(
    {
        "ix_5scr_candidates_symbol_decision",
        "ix_5scr_outcomes_status_created",
    }
)


def _enabled(value: str | None) -> bool:
    return str(value or "false").strip().lower() == "true"


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, TypeError):
        return default


@dataclass(frozen=True)
class OutcomeRuntimeConfig:
    enabled: bool = False
    poll_seconds: float = 30.0
    batch_size: int = 25
    horizon_minutes: int = 240

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> OutcomeRuntimeConfig:
        source = os.environ if environ is None else environ
        return cls(
            enabled=_enabled(source.get("STRATEGY_5SCR_OUTCOME_ENABLED")),
            poll_seconds=max(
                1.0,
                float(source.get("STRATEGY_5SCR_OUTCOME_POLL_SECONDS") or "30"),
            ),
            batch_size=max(
                1,
                int(source.get("STRATEGY_5SCR_OUTCOME_BATCH_SIZE") or "25"),
            ),
            horizon_minutes=max(
                15,
                int(source.get("STRATEGY_5SCR_OUTCOME_HORIZON_MINUTES") or "240"),
            ),
        )


@dataclass(frozen=True)
class OutcomeSchemaStatus:
    missing_tables: tuple[str, ...]
    missing_indexes: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.missing_tables and not self.missing_indexes


@dataclass(frozen=True)
class CandidateWorkItem:
    tradeplan: Strategy5SCRTradePlan


class OutcomeRepository(Protocol):
    async def load_pending(self, *, limit: int) -> Sequence[CandidateWorkItem]: ...

    async def record_outcome(self, outcome: Strategy5SCRM1Outcome) -> bool: ...


class OutcomeCandleStore(Protocol):
    async def load_outcome_candles(
        self,
        *,
        symbol: str,
        after_utc: datetime,
        until_utc: datetime,
        limit: int,
    ) -> Sequence[CanonicalCandle]: ...


class PostgresOutcomeRepository:
    """Read pending candidates and append one immutable final replay outcome."""

    def __init__(self, *, pg: PostgresClient | None = None) -> None:
        self._pg = pg or pg_client

    async def schema_status(self) -> OutcomeSchemaStatus:
        if not self._pg.is_available:
            return OutcomeSchemaStatus(
                missing_tables=tuple(sorted(_REQUIRED_TABLES)),
                missing_indexes=tuple(sorted(_REQUIRED_INDEXES)),
            )
        table_rows = await self._pg.fetch(
            """
            SELECT tablename
            FROM pg_catalog.pg_tables
            WHERE schemaname = current_schema()
              AND tablename = ANY($1::text[])
            """,
            list(_REQUIRED_TABLES),
        )
        index_rows = await self._pg.fetch(
            """
            SELECT indexname
            FROM pg_catalog.pg_indexes
            WHERE schemaname = current_schema()
              AND indexname = ANY($1::text[])
            """,
            list(_REQUIRED_INDEXES),
        )
        tables = {str(_row_value(row, "tablename") or "") for row in table_rows}
        indexes = {str(_row_value(row, "indexname") or "") for row in index_rows}
        return OutcomeSchemaStatus(
            missing_tables=tuple(sorted(_REQUIRED_TABLES - tables)),
            missing_indexes=tuple(sorted(_REQUIRED_INDEXES - indexes)),
        )

    async def load_pending(self, *, limit: int) -> Sequence[CandidateWorkItem]:
        rows = await self._pg.fetch(
            """
            SELECT candidate.payload
            FROM strategy_5scr_tradeplan_candidates AS candidate
            WHERE NOT EXISTS (
                SELECT 1
                FROM strategy_5scr_m1_outcomes AS outcome
                WHERE outcome.tradeplan_id = candidate.tradeplan_id
            )
            ORDER BY candidate.decision_at, candidate.tradeplan_id
            LIMIT $1
            """,
            max(1, int(limit)),
        )
        items: list[CandidateWorkItem] = []
        for row in rows:
            raw = _row_value(row, "payload")
            payload = json.loads(raw) if isinstance(raw, str) else raw
            if not isinstance(payload, Mapping):
                raise RuntimeError("STRATEGY_5SCR_CANDIDATE_PAYLOAD_INVALID")
            items.append(
                CandidateWorkItem(
                    tradeplan=tradeplan_from_candidate_payload(payload),
                )
            )
        return tuple(items)

    async def record_outcome(self, outcome: Strategy5SCRM1Outcome) -> bool:
        if outcome.evaluated_until_utc is None:
            raise RuntimeError("STRATEGY_5SCR_OUTCOME_HORIZON_REQUIRED")
        payload = outcome.model_dump(mode="json")
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        payload_hash = hashlib.sha256(encoded.encode()).hexdigest()
        async with self._pg.transaction() as conn:
            result = await conn.execute(
                """
                INSERT INTO strategy_5scr_m1_outcomes (
                    outcome_id, tradeplan_id, status, evaluated_until,
                    payload, payload_hash
                ) VALUES ($1, $2, $3, $4, $5::jsonb, $6)
                ON CONFLICT (tradeplan_id) DO NOTHING
                """,
                outcome.outcome_id,
                outcome.tradeplan_id,
                outcome.status,
                outcome.evaluated_until_utc,
                encoded,
                payload_hash,
            )
            stored = await conn.fetchrow(
                """
                SELECT outcome_id, payload_hash
                FROM strategy_5scr_m1_outcomes
                WHERE tradeplan_id = $1
                """,
                outcome.tradeplan_id,
            )
            if (
                stored is None
                or str(_row_value(stored, "outcome_id") or "") != outcome.outcome_id
                or str(_row_value(stored, "payload_hash") or "") != payload_hash
            ):
                raise RuntimeError("STRATEGY_5SCR_OUTCOME_IMMUTABILITY_VIOLATION")
        return bool(result.endswith(" 1"))


class Strategy5SCROutcomeWorker:
    """Poll durable candidates until a terminal touch or bounded horizon."""

    def __init__(
        self,
        *,
        repository: OutcomeRepository,
        candle_store: OutcomeCandleStore,
        config: OutcomeRuntimeConfig | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._candles = candle_store
        self._config = config or OutcomeRuntimeConfig.from_env()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._running = False

    async def process_once(self) -> int:
        if not self._config.enabled:
            return 0
        now = as_utc(self._clock(), "outcome evaluation clock")
        pending = await self._repository.load_pending(limit=self._config.batch_size)
        processed = 0
        for item in pending:
            tradeplan = item.tradeplan
            horizon = tradeplan.decision_at_utc + timedelta(minutes=self._config.horizon_minutes)
            until = min(now, horizon)
            if until <= tradeplan.decision_at_utc:
                continue
            candles = await self._candles.load_outcome_candles(
                symbol=tradeplan.symbol,
                after_utc=tradeplan.decision_at_utc,
                until_utc=until,
                limit=self._config.horizon_minutes,
            )
            outcome = classify_strategy_5scr_m1_outcome(
                tradeplan,
                candles,
                until_utc=until,
                max_bars=self._config.horizon_minutes,
            )
            terminal = outcome.status in {
                "TP1_FIRST",
                "SL_FIRST",
                "AMBIGUOUS_SAME_CANDLE",
            }
            if terminal or now >= horizon:
                await self._repository.record_outcome(outcome)
                processed += 1
        return processed

    async def run(self) -> None:
        self._running = True
        while self._running:
            try:
                await self.process_once()
            except Exception:
                logger.exception("5S-CR M1 outcome worker iteration failed")
            await asyncio.sleep(self._config.poll_seconds)

    async def stop(self) -> None:
        self._running = False


def build_outcome_worker(
    *,
    pg: PostgresClient | None = None,
    config: OutcomeRuntimeConfig | None = None,
) -> Strategy5SCROutcomeWorker:
    resolved_pg = pg or pg_client
    return Strategy5SCROutcomeWorker(
        repository=PostgresOutcomeRepository(pg=resolved_pg),
        candle_store=PostgresClosedCandleStore(pg=resolved_pg),
        config=config,
    )


__all__ = [
    "CandidateWorkItem",
    "OutcomeRuntimeConfig",
    "OutcomeSchemaStatus",
    "PostgresOutcomeRepository",
    "Strategy5SCROutcomeWorker",
    "build_outcome_worker",
]
