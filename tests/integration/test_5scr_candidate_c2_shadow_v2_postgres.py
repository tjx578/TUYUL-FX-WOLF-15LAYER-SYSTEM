"""Disposable-PostgreSQL gates for CandidateV2 -> C2 SHADOW risk V2."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal, cast
from uuid import UUID, uuid4

import pytest

from contracts.mt5_execution_protocol import (
    AccountSnapshotV1,
    CommandSource,
    ExecutionCommandV1,
    MarginMode,
    SymbolCapability,
    sign_execution_command,
)
from contracts.strategy_5scr_candidate_c2_shadow_v2 import (
    C2ShadowExistingRiskEvidenceV2,
    C2ShadowGovernanceEvidenceV2,
    CandidateC2ShadowBuildEvidenceV2,
    account_snapshot_authority_hash_v2,
    c2_shadow_existing_risk_evidence_v2,
    symbol_capability_authority_hash_v2,
)
from contracts.strategy_5scr_tradeplan_candidate_v2 import TradePlanCandidateV2, canonical_hash_v1
from execution.mt5_command_repository import MT5CommandRepository
from storage.strategy_5scr_candidate_c2_shadow_v2_repository import (
    _CONSTRAINT_TABLES,
    CAMPAIGN_TABLE,
    EVALUATION_TABLE,
    HANDOFF_TABLE,
    OUTBOX_TABLE,
    RESERVATION_TABLE,
    RISK_LOCK_TABLE,
    CandidateC2ShadowV2IntegrityError,
    Strategy5SCRCandidateC2ShadowV2Repository,
)
from storage.strategy_5scr_directional_thesis_v1_repository import (
    Strategy5SCRDirectionalThesisV1Repository,
    _context_from_row,
)
from storage.strategy_5scr_execution_box_v1_repository import (
    BOX_TABLE as P5_BOX_TABLE,
)
from storage.strategy_5scr_execution_box_v1_repository import (
    Strategy5SCRExecutionBoxV1Repository,
)
from storage.strategy_5scr_tradeplan_candidate_v2_repository import (
    CANDIDATE_TABLE,
    Strategy5SCRTradePlanCandidateV2Repository,
)
from tests.integration.test_5scr_execution_box_v1_postgres import (
    _evidence as _p5_build_evidence,
)
from tests.integration.test_5scr_execution_box_v1_postgres import (
    _insert_canonical_m1_evidence as _insert_p5_m1,
)
from tests.integration.test_5scr_execution_box_v1_postgres import (
    _m1_cohort as _p5_m1_cohort,
)
from tests.integration.test_5scr_execution_box_v1_postgres import (
    _seed as _seed_p5_parent,
)
from tests.integration.test_5scr_tradeplan_candidate_v2_postgres import (
    _DECISION as _P6_DECISION,
)
from tests.integration.test_5scr_tradeplan_candidate_v2_postgres import (
    _build_evidence as _p6_evidence,
)
from tests.integration.test_5scr_tradeplan_candidate_v2_postgres import (
    _cleanup as _cleanup_p6,
)
from tests.integration.test_5scr_tradeplan_candidate_v2_postgres import (
    _insert_target_cohort,
    _seed_parent,
    _seed_sell_parent,
)

if TYPE_CHECKING:
    from tests.integration.lifecycle_v2_postgres_plugin import PoolBackedPostgres

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
pytest_plugins = ("tests.integration.lifecycle_v2_postgres_plugin",)

_P7_DECISION = _P6_DECISION + timedelta(seconds=5)
_P7_TABLES = (HANDOFF_TABLE, RISK_LOCK_TABLE, RESERVATION_TABLE, CAMPAIGN_TABLE, OUTBOX_TABLE, EVALUATION_TABLE)
_P7_MUTABLE_TABLES = (RISK_LOCK_TABLE, RESERVATION_TABLE, CAMPAIGN_TABLE, OUTBOX_TABLE)
_P7_IMMUTABLE_TABLES = (HANDOFF_TABLE, EVALUATION_TABLE)
_BROKER_SERVER = "XMGlobal-MT5 10"
_COMMAND_SIGNING_SECRET = "p7-command-race-signing-secret-value-0123456789"
_COMMAND_SIGNING_KEY_ID = "p7-command-race.v1"


@dataclass(frozen=True, slots=True)
class _SeededP7:
    lifecycle_id: str
    candidate: TradePlanCandidateV2
    evidence: CandidateC2ShadowBuildEvidenceV2
    executor_id: UUID
    account_id: str
    governance_before: dict[str, Any]


@dataclass(frozen=True, slots=True)
class _SeededP7BoxV3:
    seeded: _SeededP7
    predecessor_v1_id: str


class _SnapshotFenceConnection:
    def __init__(self, connection: Any, reached: asyncio.Event, release: asyncio.Event) -> None:
        self._connection = connection
        self._reached = reached
        self._release = release
        self._paused = False

    async def execute(self, query: str, *args: Any) -> Any:
        result = await self._connection.execute(query, *args)
        if not self._paused and "LOCK TABLE executor_account_snapshots IN SHARE MODE" in query:
            self._paused = True
            self._reached.set()
            await asyncio.wait_for(self._release.wait(), timeout=5)
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)


class _SnapshotFencePostgres:
    def __init__(self, postgres: PoolBackedPostgres) -> None:
        self._postgres = postgres
        self.reached = asyncio.Event()
        self.release = asyncio.Event()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Any]:
        async with self._postgres.transaction() as connection:
            yield _SnapshotFenceConnection(connection, self.reached, self.release)


class _DerivedRiskFenceConnection:
    def __init__(self, connection: Any, reached: asyncio.Event, release: asyncio.Event) -> None:
        self._connection = connection
        self._reached = reached
        self._release = release
        self._paused = False

    async def fetchrow(self, query: str, *args: Any) -> Any:
        result = await self._connection.fetchrow(query, *args)
        if not self._paused and "legacy_risk" in query and "pending_commands" in query:
            self._paused = True
            self._reached.set()
            await asyncio.wait_for(self._release.wait(), timeout=5)
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)


class _DerivedRiskFencePostgres:
    def __init__(self, postgres: PoolBackedPostgres) -> None:
        self._postgres = postgres
        self.reached = asyncio.Event()
        self.release = asyncio.Event()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Any]:
        async with self._postgres.transaction() as connection:
            yield _DerivedRiskFenceConnection(connection, self.reached, self.release)


class _ExecutorLockProbeConnection:
    def __init__(self, connection: Any, reached: asyncio.Event) -> None:
        self._connection = connection
        self._reached = reached

    async def fetchrow(self, query: str, *args: Any) -> Any:
        if "FROM executor_instances" in query and ("FOR NO KEY UPDATE" in query or "FOR UPDATE" in query):
            self._reached.set()
        return await self._connection.fetchrow(query, *args)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)


class _ExecutorLockProbePostgres:
    def __init__(self, postgres: PoolBackedPostgres) -> None:
        self._postgres = postgres
        self.reached = asyncio.Event()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Any]:
        async with self._postgres.transaction() as connection:
            yield _ExecutorLockProbeConnection(connection, self.reached)


class _FirstAwaitBarrierPostgres:
    def __init__(self, postgres: PoolBackedPostgres) -> None:
        self._postgres = postgres
        self.reached = asyncio.Event()
        self.release = asyncio.Event()

    @property
    def is_available(self) -> bool:
        return self._postgres.is_available

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Any]:
        self.reached.set()
        await asyncio.wait_for(self.release.wait(), timeout=5)
        async with self._postgres.transaction() as connection:
            yield connection


class _ExecutorHoldConnection:
    def __init__(self, connection: Any, reached: asyncio.Event, release: asyncio.Event) -> None:
        self._connection = connection
        self._reached = reached
        self._release = release
        self._paused = False

    async def fetchrow(self, query: str, *args: Any) -> Any:
        result = await self._connection.fetchrow(query, *args)
        if (
            not self._paused
            and "FROM executor_instances" in query
            and ("FOR NO KEY UPDATE" in query or "FOR UPDATE" in query)
        ):
            self._paused = True
            self._reached.set()
            await asyncio.wait_for(self._release.wait(), timeout=5)
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)


class _ExecutorHoldPostgres:
    def __init__(self, postgres: PoolBackedPostgres) -> None:
        self._postgres = postgres
        self.reached = asyncio.Event()
        self.release = asyncio.Event()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Any]:
        async with self._postgres.transaction() as connection:
            yield _ExecutorHoldConnection(connection, self.reached, self.release)


class _ProofLockProbeConnection:
    def __init__(self, connection: Any, reached: asyncio.Event) -> None:
        self._connection = connection
        self._reached = reached

    async def fetchrow(self, query: str, *args: Any) -> Any:
        if "FROM strategy_5scr_h1_structure_proofs_v1" in query and "FOR UPDATE" in query:
            self._reached.set()
        return await self._connection.fetchrow(query, *args)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)


class _ProofLockProbePostgres:
    def __init__(self, postgres: PoolBackedPostgres) -> None:
        self._postgres = postgres
        self.reached = asyncio.Event()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Any]:
        async with self._postgres.transaction() as connection:
            yield _ProofLockProbeConnection(connection, self.reached)


class _SingleConnectionPostgres:
    def __init__(self, connection: Any) -> None:
        self._connection = connection

    @property
    def is_available(self) -> bool:
        return True

    async def execute(self, query: str, *args: Any) -> str:
        return str(await self._connection.execute(query, *args))

    async def fetch(self, query: str, *args: Any) -> list[Any]:
        return list(await self._connection.fetch(query, *args))

    async def fetchrow(self, query: str, *args: Any) -> Any | None:
        return await self._connection.fetchrow(query, *args)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Any]:
        yield self._connection


class _FixedClockRepository(Strategy5SCRCandidateC2ShadowV2Repository):
    """Pin only the protected DB-clock hook for fixed historical fixtures."""

    def __init__(self, postgres: Any, *, now: datetime = _P7_DECISION + timedelta(seconds=1)) -> None:
        super().__init__(postgres)
        self.now = now

    async def _database_now(self, connection: Any) -> datetime:
        del connection
        return self.now


def _repository(
    postgres: PoolBackedPostgres,
    *,
    now: datetime = _P7_DECISION + timedelta(seconds=1),
) -> Strategy5SCRCandidateC2ShadowV2Repository:
    return _FixedClockRepository(cast(Any, postgres), now=now)


def _snapshot(
    candidate: TradePlanCandidateV2,
    executor_id: UUID,
    account_id: str,
    *,
    captured_at: datetime = _P7_DECISION,
    open_positions: list[dict[str, object]] | None = None,
    pending_orders: list[dict[str, object]] | None = None,
    broker_ledger_reconciled: bool = True,
) -> AccountSnapshotV1:
    return AccountSnapshotV1.model_validate(
        {
            "snapshot_id": f"p7-snapshot-{executor_id.hex}",
            "captured_at_utc": captured_at,
            "executor_id": executor_id,
            "account_id": account_id,
            "currency": "USD",
            "balance": 1000.0,
            "equity": 1000.0,
            "floating_pnl": 0.0,
            "used_margin": 0.0,
            "free_margin": 1000.0,
            "margin_level_pct": None,
            "margin_mode": MarginMode.HEDGING,
            "trade_allowed": True,
            "autotrading_enabled": True,
            "open_positions": open_positions or [],
            "pending_orders": pending_orders or [],
            "broker_ledger_reconciled": broker_ledger_reconciled,
            "symbols": [
                SymbolCapability(
                    canonical_symbol=candidate.symbol,
                    broker_symbol=candidate.symbol,
                    digits=candidate.broker_digits,
                    point=float(candidate.broker_point),
                    tick_size=float(candidate.broker_tick_size),
                    tick_value_profit=1.0,
                    tick_value_loss=1.0,
                    volume_min=0.01,
                    volume_max=50.0,
                    volume_step=0.01,
                    stops_level_points=0,
                    freeze_level_points=0,
                    expiration_modes=["SPECIFIED"],
                ).model_dump(mode="json")
            ],
        }
    )


def _governance(
    executor_id: UUID,
    account_id: str,
    *,
    kill_switch_active: bool,
    verified_at: datetime = _P7_DECISION,
    execution_mode: Literal["SHADOW", "DEMO", "LIVE"] = "SHADOW",
    broker_server: str = _BROKER_SERVER,
) -> C2ShadowGovernanceEvidenceV2:
    payload = {
        "executor_id": executor_id,
        "account_id": account_id,
        "broker_server": broker_server,
        "executor_registered": True,
        "executor_revoked": False,
        "execution_mode": execution_mode,
        "kill_switch_state": "ENGAGED" if kill_switch_active else "DISENGAGED",
        "verified_at_utc": verified_at,
    }
    return C2ShadowGovernanceEvidenceV2(**payload, evidence_hash=canonical_hash_v1(payload))


def _build_p7_evidence(
    candidate: TradePlanCandidateV2,
    executor_id: UUID,
    account_id: str,
    snapshot: AccountSnapshotV1,
    *,
    request: str = "p7-c2-shadow-request-1",
    kill_switch_active: bool = False,
    decision_at: datetime = _P7_DECISION,
) -> CandidateC2ShadowBuildEvidenceV2:
    existing_risk_payload = {
        "account_id": account_id,
        "tradeplan_id": candidate.tradeplan_id,
        "active_campaign_count": 0,
        "active_reservation_count": 0,
        "pending_order_count": len(snapshot.pending_orders),
        "broker_ledger_reconciled": snapshot.broker_ledger_reconciled,
        "committed_or_reserved_campaign_risk_usd": Decimal("0"),
        "account_total_open_risk_usd": Decimal("0"),
        "captured_at_utc": decision_at,
    }
    return CandidateC2ShadowBuildEvidenceV2(
        source_request_id=request,
        decision_at_utc=decision_at,
        expires_at_utc=decision_at + timedelta(seconds=60),
        candidate=candidate,
        governance=_governance(
            executor_id,
            account_id,
            kill_switch_active=kill_switch_active,
            verified_at=decision_at,
        ),
        account_snapshot=snapshot,
        account_snapshot_hash=account_snapshot_authority_hash_v2(snapshot),
        existing_risk=C2ShadowExistingRiskEvidenceV2(
            **existing_risk_payload,
            evidence_hash=canonical_hash_v1(existing_risk_payload),
        ),
        broker_symbol=candidate.symbol,
        source_deployment_id="p7-postgres-test",
        source_replica_id="p7-postgres-test-1",
    )


def _pending_command(seeded: _SeededP7) -> ExecutionCommandV1:
    now = _P7_DECISION + timedelta(seconds=1)
    payload = {
        "command_id": uuid4(),
        "idempotency_key": f"{seeded.account_id}:p7-command-race:{uuid4().hex}",
        "revision": 1,
        "issued_at_utc": now,
        "not_before_utc": now,
        "expires_at_utc": now + timedelta(minutes=30),
        "executor_binding": {
            "executor_id": seeded.executor_id,
            "account_id": seeded.account_id,
            "login_hash": "sha256:" + "7" * 64,
            "broker_server": _BROKER_SERVER,
            "execution_mode": "SHADOW",
        },
        "source": {
            "source_event": "signal_json",
            "source_schema_version": "2.0",
            "source_signal_id": f"p7-race-signal-{uuid4().hex}",
            "source_signal_hash": "sha256:" + "b" * 64,
            "campaign_id": f"p7-race-campaign-{uuid4().hex}",
            "block_id": "p7-race-parent",
            "block_role": "PARENT",
            "lifecycle_anchor": seeded.lifecycle_id,
            "valid_for_execution": True,
            "execution_gate_passed": True,
            "tradeplan_valid": True,
            "strategy_model": "STRATEGY_5S_CR_FINAL",
            "strategy_rule_version": "5scr.final.2026-07-19",
            "strategy_rule_status": "FROZEN",
            "strategy_proof_hash": "sha256:" + "c" * 64,
            "context_resolution_status": "RESOLVED",
            "confirmation_policy": "H1_CLOSED_PLUS_M15_BREAK_ACCEPTANCE_OR_FAILED_RECLAIM_RETEST",
        },
        "action": "PLACE_PENDING",
        "order": {
            "canonical_symbol": seeded.candidate.symbol,
            "broker_symbol": seeded.candidate.symbol,
            "side": seeded.candidate.direction,
            "order_type": "BUY_LIMIT" if seeded.candidate.direction == "BUY" else "SELL_LIMIT",
            "volume": 0.01,
            "entry_price": float(seeded.candidate.candidate_price),
            "stop_loss": float(seeded.candidate.stop_authority.structural_stop_price),
            "take_profit": float(seeded.candidate.target_authority.target_price),
            "magic": 150015,
            "comment_tag": "W15:P7RACE0001",
            "time_in_force": "SPECIFIED",
            "broker_expiration_utc": now + timedelta(minutes=30),
        },
        "guards": {
            "max_spread_points": 25,
            "max_price_drift_points": 15,
            "expected_margin_mode": "HEDGING",
            "risk_snapshot_id": seeded.evidence.account_snapshot.snapshot_id,
            "risk_reservation_id": "p7-race-reservation",
            "balance_snapshot": seeded.evidence.account_snapshot.balance,
            "equity_snapshot": seeded.evidence.account_snapshot.equity,
        },
    }
    return sign_execution_command(
        payload,
        secret=_COMMAND_SIGNING_SECRET,
        key_id=_COMMAND_SIGNING_KEY_ID,
    )


async def _insert_terminal_command(
    postgres: PoolBackedPostgres,
    seeded: _SeededP7,
    *,
    state: Literal[
        "QUEUED",
        "FILLED",
        "COMPLETED",
        "CANCELLED",
        "EXPIRED",
        "REJECTED",
        "SHADOW_COMPLETED",
        "SHADOW_REJECTED",
    ],
    terminal_at: datetime | None,
    account_id: str | None = None,
) -> UUID:
    command = _pending_command(seeded)
    assert isinstance(command.source, CommandSource)
    await postgres.execute("ALTER TABLE execution_commands DISABLE TRIGGER trg_execution_command_require_signed_wire")
    try:
        await postgres.execute(
            """INSERT INTO execution_commands (
                   command_id,executor_id,account_id,source_event,source_signal_id,source_signal_hash,
                   idempotency_key,revision,action,payload,payload_hash,state,issued_at,not_before,
                   expires_at,terminal_at,wire_format
               ) VALUES ($1::uuid,$2::uuid,$3,'signal_json',$4,$5,$6,1,'PLACE_PENDING',$7::jsonb,$8,
                         $9,$10,$10,$11,$12,'legacy-json-v1')""",
            str(command.command_id),
            str(seeded.executor_id),
            account_id or seeded.account_id,
            command.source.source_signal_id,
            command.source.source_signal_hash,
            command.idempotency_key,
            json.dumps(command.model_dump(mode="json"), sort_keys=True, separators=(",", ":")),
            "sha256:" + "d" * 64,
            state,
            command.issued_at_utc,
            command.expires_at_utc,
            terminal_at,
        )
    finally:
        await postgres.execute(
            "ALTER TABLE execution_commands ENABLE TRIGGER trg_execution_command_require_signed_wire"
        )
    return command.command_id


async def _insert_executor_snapshot(
    postgres: PoolBackedPostgres,
    candidate: TradePlanCandidateV2,
    *,
    kill_switch_active: bool,
    broker_ledger_reconciled: bool,
    pending_orders: list[dict[str, object]] | None,
) -> tuple[UUID, str, AccountSnapshotV1, dict[str, Any]]:
    executor_id = uuid4()
    account_id = f"p7-account-{executor_id.hex[:16]}"
    snapshot = _snapshot(
        candidate,
        executor_id,
        account_id,
        broker_ledger_reconciled=broker_ledger_reconciled,
        pending_orders=pending_orders,
    )
    before = await postgres.fetchrow(
        """SELECT kill_switch_active,kill_switch_reason,governance_version,updated_by,updated_at
           FROM executor_bridge_governance WHERE singleton_id=1"""
    )
    assert before is not None
    await postgres.execute(
        """INSERT INTO ea_agents (
               id,agent_name,ea_class,ea_subtype,execution_mode,reporter_mode,status,locked
           ) VALUES ($1::uuid,$2,'PRIMARY','EDUMB','SHADOW','FULL','OFFLINE',false)""",
        str(executor_id),
        f"P7 PostgreSQL {executor_id}",
    )
    await postgres.execute(
        """INSERT INTO executor_instances (
               executor_id,account_id,login_hash,broker_server,terminal_build,ea_version,
               protocol_version,execution_mode,status,last_heartbeat_at,created_at,updated_at
           ) VALUES ($1::uuid,$2,$3,$4,5000,'p7-shadow-v2','wolf15.mt5.exec.v1',
                     'SHADOW','ONLINE',$5,$5,$5)""",
        str(executor_id),
        account_id,
        "sha256:" + "7" * 64,
        _BROKER_SERVER,
        _P7_DECISION,
    )
    await postgres.execute(
        """INSERT INTO executor_account_snapshots (
               snapshot_id,executor_id,account_id,captured_at,balance,equity,floating_pnl,
               used_margin,free_margin,margin_level_pct,margin_mode,trade_allowed,
               autotrading_enabled,payload
           ) VALUES ($1,$2::uuid,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14::jsonb)""",
        snapshot.snapshot_id,
        str(executor_id),
        account_id,
        snapshot.captured_at_utc,
        snapshot.balance,
        snapshot.equity,
        snapshot.floating_pnl,
        snapshot.used_margin,
        snapshot.free_margin,
        snapshot.margin_level_pct,
        snapshot.margin_mode.value,
        snapshot.trade_allowed,
        snapshot.autotrading_enabled,
        json.dumps(snapshot.model_dump(mode="json"), sort_keys=True, separators=(",", ":")),
    )
    await postgres.execute(
        """UPDATE executor_bridge_governance SET kill_switch_active=$1,
               kill_switch_reason=$2,governance_version=governance_version+1,
               updated_by='P7_POSTGRES_TEST',updated_at=$3 WHERE singleton_id=1""",
        kill_switch_active,
        "P7_TEST_ENGAGED" if kill_switch_active else "P7_TEST_DISENGAGED",
        _P7_DECISION,
    )
    return executor_id, account_id, snapshot, dict(before)


async def _insert_snapshot_row(postgres: PoolBackedPostgres, snapshot: AccountSnapshotV1) -> None:
    await postgres.execute(
        """INSERT INTO executor_account_snapshots (
               snapshot_id,executor_id,account_id,captured_at,balance,equity,floating_pnl,
               used_margin,free_margin,margin_level_pct,margin_mode,trade_allowed,
               autotrading_enabled,payload
           ) VALUES ($1,$2::uuid,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14::jsonb)""",
        snapshot.snapshot_id,
        str(snapshot.executor_id),
        snapshot.account_id,
        snapshot.captured_at_utc,
        snapshot.balance,
        snapshot.equity,
        snapshot.floating_pnl,
        snapshot.used_margin,
        snapshot.free_margin,
        snapshot.margin_level_pct,
        snapshot.margin_mode.value,
        snapshot.trade_allowed,
        snapshot.autotrading_enabled,
        json.dumps(snapshot.model_dump(mode="json"), sort_keys=True, separators=(",", ":")),
    )


async def _seed(
    postgres: PoolBackedPostgres,
    *,
    direction: Literal["BUY", "SELL"] = "BUY",
    kill_switch_active: bool = False,
    broker_ledger_reconciled: bool = True,
    pending_orders: list[dict[str, object]] | None = None,
) -> _SeededP7:
    if direction == "BUY":
        lifecycle_id, thesis, box, context = await _seed_parent(postgres)
        p6_input = _p6_evidence(thesis, box, context)
    else:
        lifecycle_id, thesis, box, context = await _seed_sell_parent(postgres)
        p6_input = _p6_evidence(
            thesis,
            box,
            context,
            near=Decimal("1.1000"),
            far=Decimal("1.0990"),
        )
    await _insert_target_cohort(postgres, p6_input)
    p6 = await Strategy5SCRTradePlanCandidateV2Repository(cast(Any, postgres)).process_evidence(p6_input)
    assert p6.status == "PERSISTED" and p6.candidate is not None
    executor_id, account_id, snapshot, governance_before = await _insert_executor_snapshot(
        postgres,
        p6.candidate,
        kill_switch_active=kill_switch_active,
        broker_ledger_reconciled=broker_ledger_reconciled,
        pending_orders=pending_orders,
    )
    return _SeededP7(
        lifecycle_id=lifecycle_id,
        candidate=p6.candidate,
        evidence=_build_p7_evidence(
            p6.candidate,
            executor_id,
            account_id,
            snapshot,
            kill_switch_active=kill_switch_active,
        ),
        executor_id=executor_id,
        account_id=account_id,
        governance_before=governance_before,
    )


async def _seed_box_v3(postgres: PoolBackedPostgres) -> _SeededP7BoxV3:
    lifecycle_id, thesis, first_evidence = await _seed_p5_parent(postgres)
    p5 = Strategy5SCRExecutionBoxV1Repository(cast(Any, postgres))
    first = await p5.process_evidence(first_evidence)
    assert first.status == "PERSISTED" and first.box is not None

    second_evidence = _p5_build_evidence(
        thesis,
        index=2,
        candles=_p5_m1_cohort(4, reference_low=1.0990),
    )
    await _insert_p5_m1(postgres, second_evidence)
    second = await p5.process_evidence(second_evidence)
    assert second.status == "SUPERSEDED" and second.box is not None

    third_evidence = _p5_build_evidence(thesis, index=3)
    third = await p5.process_evidence(third_evidence)
    assert third.status == "SUPERSEDED" and third.box is not None
    frozen = await p5.process_evidence(_p5_build_evidence(thesis, index=4, freeze=True))
    assert frozen.status == "FROZEN" and frozen.box is not None
    assert frozen.box.box_version == 3

    context_row = await postgres.fetchrow(
        "SELECT * FROM strategy_5scr_context_epochs_v1 WHERE context_epoch_id=$1",
        thesis.context_epoch_id,
    )
    assert context_row is not None
    p6_input = _p6_evidence(thesis, frozen.box, _context_from_row(context_row))
    await _insert_target_cohort(postgres, p6_input)
    p6 = await Strategy5SCRTradePlanCandidateV2Repository(cast(Any, postgres)).process_evidence(p6_input)
    assert p6.status == "PERSISTED" and p6.candidate is not None
    executor_id, account_id, snapshot, governance_before = await _insert_executor_snapshot(
        postgres,
        p6.candidate,
        kill_switch_active=False,
        broker_ledger_reconciled=True,
        pending_orders=None,
    )
    seeded = _SeededP7(
        lifecycle_id=lifecycle_id,
        candidate=p6.candidate,
        evidence=_build_p7_evidence(p6.candidate, executor_id, account_id, snapshot),
        executor_id=executor_id,
        account_id=account_id,
        governance_before=governance_before,
    )
    return _SeededP7BoxV3(seeded=seeded, predecessor_v1_id=first.box.execution_box_id)


async def _restore_governance(postgres: PoolBackedPostgres, before: dict[str, Any]) -> None:
    await postgres.execute(
        """UPDATE executor_bridge_governance SET kill_switch_active=$1,kill_switch_reason=$2,
               governance_version=$3,updated_by=$4,updated_at=$5 WHERE singleton_id=1""",
        before["kill_switch_active"],
        before["kill_switch_reason"],
        before["governance_version"],
        before["updated_by"],
        before["updated_at"],
    )


async def _cleanup_p7(postgres: PoolBackedPostgres, seeded: _SeededP7) -> None:
    async with postgres.transaction() as connection:
        # P7 intentionally has an authority cycle guarded by ON DELETE RESTRICT;
        # PostgreSQL RESTRICT is immediate even on a deferrable constraint. The
        # fixture runs only against a disposable superuser-owned database, so
        # suppress every trigger locally while deleting this exact tradeplan.
        await connection.execute("SET LOCAL session_replication_role = replica")
        for table in (
            EVALUATION_TABLE,
            OUTBOX_TABLE,
            CAMPAIGN_TABLE,
            RESERVATION_TABLE,
            RISK_LOCK_TABLE,
            HANDOFF_TABLE,
        ):
            await connection.execute(f"DELETE FROM {table} WHERE tradeplan_id=$1", seeded.candidate.tradeplan_id)
    await postgres.execute("DELETE FROM executor_account_snapshots WHERE executor_id=$1::uuid", str(seeded.executor_id))
    await postgres.execute("DELETE FROM executor_instances WHERE executor_id=$1::uuid", str(seeded.executor_id))
    await postgres.execute("DELETE FROM ea_agents WHERE id=$1::uuid", str(seeded.executor_id))
    await _restore_governance(postgres, seeded.governance_before)
    await _cleanup_p6(postgres, seeded.lifecycle_id)


@asynccontextmanager
async def _seeded(
    postgres: PoolBackedPostgres,
    *,
    direction: Literal["BUY", "SELL"] = "BUY",
    kill_switch_active: bool = False,
    broker_ledger_reconciled: bool = True,
    pending_orders: list[dict[str, object]] | None = None,
) -> AsyncIterator[_SeededP7]:
    seeded = await _seed(
        postgres,
        direction=direction,
        kill_switch_active=kill_switch_active,
        broker_ledger_reconciled=broker_ledger_reconciled,
        pending_orders=pending_orders,
    )
    try:
        yield seeded
    finally:
        await _cleanup_p7(postgres, seeded)


async def _p7_counts(postgres: PoolBackedPostgres, tradeplan_id: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for table in _P7_TABLES:
        row = await postgres.fetchrow(f"SELECT count(*) AS n FROM {table} WHERE tradeplan_id=$1", tradeplan_id)
        assert row is not None
        result[table] = int(row["n"])
    return result


async def _external_counts(postgres: PoolBackedPostgres, seeded: _SeededP7) -> dict[str, int]:
    queries = {
        "legacy_candidate": (
            "SELECT count(*) AS n FROM strategy_5scr_tradeplan_candidates WHERE tradeplan_id=$1",
            seeded.candidate.tradeplan_id,
        ),
        "legacy_reservation": (
            "SELECT count(*) AS n FROM strategy_5scr_risk_reservations WHERE tradeplan_id=$1",
            seeded.candidate.tradeplan_id,
        ),
        "legacy_outbox": (
            "SELECT count(*) AS n FROM strategy_5scr_final_signal_outbox WHERE tradeplan_id=$1",
            seeded.candidate.tradeplan_id,
        ),
        "commands": ("SELECT count(*) AS n FROM execution_commands WHERE account_id=$1", seeded.account_id),
        "reports": ("SELECT count(*) AS n FROM execution_reports WHERE executor_id=$1::uuid", str(seeded.executor_id)),
        "broker": (
            """SELECT count(*) AS n FROM broker_entities be JOIN execution_commands ec ON ec.command_id=be.command_id
               WHERE ec.account_id=$1""",
            seeded.account_id,
        ),
    }
    result: dict[str, int] = {}
    for name, (query, value) in queries.items():
        row = await postgres.fetchrow(query, value)
        assert row is not None
        result[name] = int(row["n"])
    return result


async def _insert_legacy_active_risk(
    postgres: PoolBackedPostgres,
    seeded: _SeededP7,
) -> tuple[str, str, str, Decimal]:
    suffix = uuid4().hex
    lifecycle_id = f"legacy-p7-lifecycle:{suffix}"
    evidence_snapshot_id = f"legacy-p7-evidence:{suffix}"
    tradeplan_id = f"legacy-p7-tradeplan:{suffix}"
    campaign_id = f"legacy-p7-campaign:{suffix}"
    empty_hash = hashlib.sha256(b"{}").hexdigest()
    await postgres.execute(
        """INSERT INTO strategy_5scr_lifecycles (
               lifecycle_id,symbol,anchor_at,anchor_event_id,anchor_sequence,latest_event_at,last_sequence
           ) VALUES ($1,$2,$3,$4::uuid,1,$3,1)""",
        lifecycle_id,
        seeded.candidate.symbol,
        _P7_DECISION,
        str(uuid4()),
    )
    await postgres.execute(
        """INSERT INTO strategy_5scr_evidence_snapshots (
               snapshot_id,lifecycle_id,event_id,decision_at,lifecycle_anchor_at,payload,payload_hash
           ) VALUES ($1,$2,$3::uuid,$4,$4,'{}'::jsonb,$5)""",
        evidence_snapshot_id,
        lifecycle_id,
        str(uuid4()),
        _P7_DECISION,
        empty_hash,
    )
    await postgres.execute(
        """INSERT INTO strategy_5scr_tradeplan_candidates (
               tradeplan_id,lifecycle_id,event_id,evidence_snapshot_id,symbol,direction,decision_at,payload,payload_hash
           ) VALUES ($1,$2,$3::uuid,$4,$5,$6,$7,'{}'::jsonb,$8)""",
        tradeplan_id,
        lifecycle_id,
        str(uuid4()),
        evidence_snapshot_id,
        seeded.candidate.symbol,
        seeded.candidate.direction,
        _P7_DECISION,
        empty_hash,
    )
    await postgres.execute(
        """INSERT INTO strategy_5scr_campaign_risk_locks (
               campaign_id,account_id,executor_id,account_snapshot_id,policy_id,state,
               balance_base,risk_percent_per_entry,risk_unit_usd,max_campaign_risk_usd,locked_at
           ) VALUES ($1,$2,$3::uuid,$4,'LEGACY_P7_CONFLICT','ACTIVE',1000,0.01,10,30,$5)""",
        campaign_id,
        seeded.account_id,
        str(seeded.executor_id),
        seeded.evidence.account_snapshot.snapshot_id,
        _P7_DECISION,
    )
    # The legacy table is NUMERIC(24,8); the evidence hash must preserve the
    # exact durable scale used by the repository's canonical hash.
    reserved_risk = Decimal("10.00000000")
    await postgres.execute(
        """INSERT INTO strategy_5scr_risk_reservations (
               reservation_id,campaign_id,tradeplan_id,executor_id,account_id,account_snapshot_id,
               source_candidate_hash,signal_id,signal_hash,policy_id,state,canonical_symbol,broker_symbol,
               entry_role,direction,volume,entry_price,stop_loss,take_profit,risk_unit_usd,reserved_risk_usd,
               balance_snapshot,equity_snapshot,reserved_at,expires_at
           ) VALUES ($1::uuid,$2,$3,$4::uuid,$5,$6,$7,$8,$9,'LEGACY_P7_CONFLICT','HELD',$10,$10,
                     'PARENT',$11,0.01,$12,$13,$14,10,$15,1000,1000,$16,$17)""",
        str(uuid4()),
        campaign_id,
        tradeplan_id,
        str(seeded.executor_id),
        seeded.account_id,
        seeded.evidence.account_snapshot.snapshot_id,
        "a" * 64,
        f"5scr-signal:{suffix}",
        "sha256:" + "b" * 64,
        seeded.candidate.symbol,
        seeded.candidate.direction,
        seeded.candidate.candidate_price,
        seeded.candidate.stop_authority.structural_stop_price,
        seeded.candidate.target_authority.target_price,
        reserved_risk,
        _P7_DECISION,
        _P7_DECISION + timedelta(seconds=120),
    )
    return lifecycle_id, tradeplan_id, campaign_id, reserved_risk


async def _delete_legacy_active_risk(
    postgres: PoolBackedPostgres,
    *,
    lifecycle_id: str,
    tradeplan_id: str,
    campaign_id: str,
) -> None:
    await postgres.execute("DELETE FROM strategy_5scr_risk_reservations WHERE tradeplan_id=$1", tradeplan_id)
    await postgres.execute(
        "DELETE FROM strategy_5scr_campaign_risk_locks WHERE campaign_id=$1",
        campaign_id,
    )
    await postgres.execute("DELETE FROM strategy_5scr_tradeplan_candidates WHERE tradeplan_id=$1", tradeplan_id)
    await postgres.execute("DELETE FROM strategy_5scr_evidence_snapshots WHERE lifecycle_id=$1", lifecycle_id)
    await postgres.execute("DELETE FROM strategy_5scr_lifecycles WHERE lifecycle_id=$1", lifecycle_id)


async def _insert_legacy_terminal_parent(
    postgres: PoolBackedPostgres,
    seeded: _SeededP7,
) -> tuple[str, str, str, str]:
    """Create a constraint-valid CLOSED legacy parent for guard tests."""

    suffix = uuid4().hex
    lifecycle_id = f"legacy-p7-terminal-lifecycle:{suffix}"
    evidence_snapshot_id = f"legacy-p7-terminal-evidence:{suffix}"
    tradeplan_id = f"legacy-p7-terminal-tradeplan:{suffix}"
    campaign_id = f"legacy-p7-terminal-campaign:{suffix}"
    empty_hash = hashlib.sha256(b"{}").hexdigest()
    await postgres.execute(
        """INSERT INTO strategy_5scr_lifecycles (
               lifecycle_id,symbol,anchor_at,anchor_event_id,anchor_sequence,latest_event_at,last_sequence
           ) VALUES ($1,$2,$3,$4::uuid,1,$3,1)""",
        lifecycle_id,
        seeded.candidate.symbol,
        _P7_DECISION,
        str(uuid4()),
    )
    await postgres.execute(
        """INSERT INTO strategy_5scr_evidence_snapshots (
               snapshot_id,lifecycle_id,event_id,decision_at,lifecycle_anchor_at,payload,payload_hash
           ) VALUES ($1,$2,$3::uuid,$4,$4,'{}'::jsonb,$5)""",
        evidence_snapshot_id,
        lifecycle_id,
        str(uuid4()),
        _P7_DECISION,
        empty_hash,
    )
    await postgres.execute(
        """INSERT INTO strategy_5scr_tradeplan_candidates (
               tradeplan_id,lifecycle_id,event_id,evidence_snapshot_id,symbol,direction,decision_at,payload,payload_hash
           ) VALUES ($1,$2,$3::uuid,$4,$5,$6,$7,'{}'::jsonb,$8)""",
        tradeplan_id,
        lifecycle_id,
        str(uuid4()),
        evidence_snapshot_id,
        seeded.candidate.symbol,
        seeded.candidate.direction,
        _P7_DECISION,
        empty_hash,
    )
    await postgres.execute(
        """INSERT INTO strategy_5scr_campaign_risk_locks (
               campaign_id,account_id,executor_id,account_snapshot_id,policy_id,state,
               balance_base,risk_percent_per_entry,risk_unit_usd,max_campaign_risk_usd,
               locked_at,closed_at
           ) VALUES ($1,$2,$3::uuid,$4,'LEGACY_P7_TERMINAL','CLOSED',1000,0.01,10,30,$5,$6)""",
        campaign_id,
        seeded.account_id,
        str(seeded.executor_id),
        seeded.evidence.account_snapshot.snapshot_id,
        _P7_DECISION,
        _P7_DECISION + timedelta(seconds=1),
    )
    return lifecycle_id, tradeplan_id, campaign_id, suffix


async def _insert_legacy_reservation(
    postgres: PoolBackedPostgres,
    seeded: _SeededP7,
    *,
    tradeplan_id: str,
    campaign_id: str,
    suffix: str,
    state: Literal["HELD", "CONSUMED", "OPEN", "RELEASED", "EXPIRED"],
) -> UUID:
    reservation_id = uuid4()
    command_id = uuid4() if state in {"CONSUMED", "OPEN"} else None
    consumed_at = _P7_DECISION + timedelta(seconds=1) if state in {"CONSUMED", "OPEN"} else None
    opened_at = _P7_DECISION + timedelta(seconds=2) if state == "OPEN" else None
    released_at = _P7_DECISION + timedelta(seconds=3) if state == "RELEASED" else None
    expired_at = _P7_DECISION + timedelta(seconds=120) if state == "EXPIRED" else None
    await postgres.execute(
        """INSERT INTO strategy_5scr_risk_reservations (
               reservation_id,campaign_id,tradeplan_id,executor_id,account_id,account_snapshot_id,
               source_candidate_hash,signal_id,signal_hash,policy_id,state,canonical_symbol,broker_symbol,
               entry_role,direction,volume,entry_price,stop_loss,take_profit,risk_unit_usd,reserved_risk_usd,
               balance_snapshot,equity_snapshot,command_id,reserved_at,expires_at,consumed_at,opened_at,
               released_at,expired_at
           ) VALUES ($1::uuid,$2,$3,$4::uuid,$5,$6,$7,$8,$9,'LEGACY_P7_TERMINAL',$10,$11,$11,
                     'PARENT',$12,0.01,$13,$14,$15,10,10,1000,1000,$16::uuid,$17,$18,$19,$20,$21,$22)""",
        str(reservation_id),
        campaign_id,
        tradeplan_id,
        str(seeded.executor_id),
        seeded.account_id,
        seeded.evidence.account_snapshot.snapshot_id,
        "a" * 64,
        f"5scr-signal:{suffix}",
        "sha256:" + "b" * 64,
        state,
        seeded.candidate.symbol,
        seeded.candidate.direction,
        seeded.candidate.candidate_price,
        seeded.candidate.stop_authority.structural_stop_price,
        seeded.candidate.target_authority.target_price,
        str(command_id) if command_id is not None else None,
        _P7_DECISION,
        _P7_DECISION + timedelta(seconds=120),
        consumed_at,
        opened_at,
        released_at,
        expired_at,
    )
    return reservation_id


async def test_default_repository_clock_is_postgres_wall_clock(
    postgres: PoolBackedPostgres,
) -> None:
    repository = Strategy5SCRCandidateC2ShadowV2Repository(cast(Any, postgres))
    async with postgres.transaction() as connection:
        before = await connection.fetchval("SELECT clock_timestamp()")
        observed = await repository._database_now(connection)
        after = await connection.fetchval("SELECT clock_timestamp()")
        assert before <= observed <= after


@pytest.mark.parametrize("operation", ["process", "load"])
async def test_executor_lock_precedes_governance_lock(
    postgres: PoolBackedPostgres,
    operation: Literal["process", "load"],
) -> None:
    async with _seeded(postgres) as seeded:
        if operation == "load":
            opened = await _repository(postgres).process_evidence(seeded.evidence)
            assert opened.status == "APPROVED" and opened.authority_bundle is not None

        probed_postgres = _ExecutorLockProbePostgres(postgres)
        repository = _FixedClockRepository(probed_postgres)
        pending: asyncio.Task[Any] | None = None
        try:
            async with postgres.transaction() as blocker:
                await blocker.fetchval(
                    "SELECT executor_id FROM executor_instances WHERE executor_id=$1::uuid FOR UPDATE",
                    str(seeded.executor_id),
                )
                if operation == "process":
                    pending = asyncio.create_task(repository.process_evidence(seeded.evidence))
                else:
                    pending = asyncio.create_task(repository.load_authority(seeded.candidate.tradeplan_id))
                await asyncio.wait_for(probed_postgres.reached.wait(), timeout=5)
                assert not pending.done(), "P7 crossed the externally-held executor lock"
                governance_id = await blocker.fetchval(
                    "SELECT singleton_id FROM executor_bridge_governance WHERE singleton_id=1 FOR UPDATE NOWAIT"
                )
                assert governance_id == 1
        finally:
            assert pending is not None
            result = await asyncio.wait_for(pending, timeout=5)

        if operation == "process":
            assert result.status == "APPROVED" and result.authority_bundle is not None
        else:
            assert result is not None


@pytest.mark.parametrize("operation", ["process", "load"])
@pytest.mark.parametrize("writer_kind", ["command", "snapshot"])
async def test_executor_lock_allows_fk_writers_without_deadlock(
    postgres: PoolBackedPostgres,
    monkeypatch: pytest.MonkeyPatch,
    operation: Literal["process", "load"],
    writer_kind: Literal["command", "snapshot"],
) -> None:
    async with _seeded(postgres) as seeded:
        opened = None
        if operation == "load":
            opened = await _repository(postgres).process_evidence(seeded.evidence)
            assert opened.status == "APPROVED" and opened.authority_bundle is not None

        evidence = seeded.evidence
        if writer_kind == "command" and operation == "process":
            risk_payload = evidence.existing_risk.model_dump(mode="python")
            risk_payload["pending_order_count"] = 1
            risk_payload.pop("evidence_hash")
            risk_payload.pop("execution_authority")
            evidence = evidence.model_copy(
                update={
                    "source_request_id": "p7-fk-writer-command",
                    "existing_risk": C2ShadowExistingRiskEvidenceV2(
                        **risk_payload,
                        evidence_hash=canonical_hash_v1(risk_payload),
                    ),
                }
            )

        held = _ExecutorHoldPostgres(postgres)
        repository = _FixedClockRepository(cast(Any, held))
        pending = asyncio.create_task(
            repository.process_evidence(evidence)
            if operation == "process"
            else repository.load_authority(seeded.candidate.tradeplan_id)
        )
        command: ExecutionCommandV1 | None = None
        try:
            await asyncio.wait_for(held.reached.wait(), timeout=5)
            if writer_kind == "command":
                monkeypatch.setenv("EXECUTOR_COMMAND_SIGNING_SECRET", _COMMAND_SIGNING_SECRET)
                monkeypatch.setenv("EXECUTOR_COMMAND_SIGNING_KEY_ID", _COMMAND_SIGNING_KEY_ID)
                command = _pending_command(seeded)
                writer = asyncio.create_task(MT5CommandRepository(pg=cast(Any, postgres)).enqueue_command(command))
                if operation == "load":
                    with pytest.raises(postgres.check_violation_error):
                        await asyncio.wait_for(writer, timeout=5)
                else:
                    await asyncio.wait_for(writer, timeout=5)
            else:
                newer = seeded.evidence.account_snapshot.model_copy(
                    update={
                        "snapshot_id": f"p7-fk-writer-{seeded.executor_id.hex}",
                        "captured_at_utc": _P7_DECISION + timedelta(seconds=1),
                    }
                )
                await asyncio.wait_for(_insert_snapshot_row(postgres, newer), timeout=5)
            assert not pending.done(), "P7 must remain paused while the FK writer commits"
        finally:
            held.release.set()

        result: Any = await asyncio.wait_for(pending, timeout=10)
        if operation == "process":
            if writer_kind == "command":
                assert result.status == "REJECTED"
                assert result.reason_code == "C2_PARENT_REQUIRES_NO_PENDING_ORDERS"
            else:
                assert result.status == "QUARANTINED"
                assert result.reason_code == "C2_ACCOUNT_SNAPSHOT_CHANGED_DURING_READ"
        else:
            assert opened is not None
            assert result == opened.authority_bundle

        if command is not None:
            await postgres.execute(
                "DELETE FROM execution_commands WHERE command_id=$1::uuid",
                str(command.command_id),
            )


async def test_nested_snapshot_mutation_after_first_await_cannot_change_admitted_authority(
    postgres: PoolBackedPostgres,
) -> None:
    async with _seeded(postgres) as seeded:
        barrier = _FirstAwaitBarrierPostgres(postgres)
        repository = _FixedClockRepository(cast(Any, barrier))
        original_snapshot = seeded.evidence.account_snapshot.model_copy(deep=True)
        pending = asyncio.create_task(repository.process_evidence(seeded.evidence))
        await asyncio.wait_for(barrier.reached.wait(), timeout=5)
        seeded.evidence.account_snapshot.symbols[0].volume_step = 0.25
        barrier.release.set()

        result = await asyncio.wait_for(pending, timeout=10)

        assert result.status == "APPROVED" and result.authority_bundle is not None
        assert result.authority_bundle.reservation.account_snapshot_hash == account_snapshot_authority_hash_v2(
            original_snapshot
        )
        assert result.authority_bundle.reservation.account_snapshot_hash != account_snapshot_authority_hash_v2(
            seeded.evidence.account_snapshot
        )
        assert result.authority_bundle.reservation.symbol_capability_hash == symbol_capability_authority_hash_v2(
            original_snapshot.symbols[0]
        )


@pytest.mark.parametrize("operation", ["process", "load"])
async def test_thesis_proof_lock_precedes_execution_box_lock(
    postgres: PoolBackedPostgres,
    operation: Literal["process", "load"],
) -> None:
    async with _seeded(postgres) as seeded:
        if operation == "load":
            opened = await _repository(postgres).process_evidence(seeded.evidence)
            assert opened.status == "APPROVED" and opened.authority_bundle is not None
        thesis = await postgres.fetchrow(
            "SELECT h1_proof_id FROM strategy_5scr_directional_theses_v1 WHERE strategy_thesis_id=$1",
            seeded.candidate.strategy_thesis_id,
        )
        assert thesis is not None
        probed_postgres = _ProofLockProbePostgres(postgres)
        repository = _FixedClockRepository(probed_postgres)
        pending: asyncio.Task[Any] | None = None
        try:
            async with postgres.transaction() as blocker:
                await blocker.fetchval(
                    "SELECT h1_proof_id FROM strategy_5scr_h1_structure_proofs_v1 WHERE h1_proof_id=$1 FOR UPDATE",
                    thesis["h1_proof_id"],
                )
                if operation == "process":
                    pending = asyncio.create_task(repository.process_evidence(seeded.evidence))
                else:
                    pending = asyncio.create_task(repository.load_authority(seeded.candidate.tradeplan_id))
                await asyncio.wait_for(probed_postgres.reached.wait(), timeout=5)
                assert not pending.done(), "P7 crossed the externally-held thesis proof lock"
                box_id = await blocker.fetchval(
                    "SELECT execution_box_id FROM strategy_5scr_execution_boxes_v1 "
                    "WHERE execution_box_id=$1 FOR UPDATE NOWAIT",
                    seeded.candidate.execution_box_id,
                )
                assert box_id == seeded.candidate.execution_box_id
        finally:
            assert pending is not None
            result = await asyncio.wait_for(pending, timeout=5)

        if operation == "process":
            assert result.status == "APPROVED" and result.authority_bundle is not None
        else:
            assert result is not None


async def test_engaged_kill_switch_persists_rejected_audit_without_authority(
    postgres: PoolBackedPostgres,
) -> None:
    async with _seeded(postgres, kill_switch_active=True) as seeded:
        before = await _external_counts(postgres, seeded)
        result = await _repository(postgres).process_evidence(seeded.evidence)
        assert (result.status, result.reason_code) == ("REJECTED", "C2_KILL_SWITCH_ENGAGED")
        assert result.evaluation is not None and result.evaluation.decision == "REJECTED"
        assert result.authority_bundle is None
        counts = await _p7_counts(postgres, seeded.candidate.tradeplan_id)
        assert counts[EVALUATION_TABLE] == 1
        assert all(counts[table] == 0 for table in _P7_TABLES if table != EVALUATION_TABLE)
        assert await _external_counts(postgres, seeded) == before


async def test_missing_durable_snapshot_returns_typed_rejection_without_evaluation_fk(
    postgres: PoolBackedPostgres,
) -> None:
    async with _seeded(postgres) as seeded:
        await postgres.execute(
            "DELETE FROM executor_account_snapshots WHERE snapshot_id=$1",
            seeded.evidence.account_snapshot.snapshot_id,
        )

        result = await _repository(postgres).process_evidence(seeded.evidence)

        assert (result.status, result.reason_code, result.evaluation, result.authority_bundle) == (
            "REJECTED",
            "C2_ACCOUNT_SNAPSHOT_MISSING",
            None,
            None,
        )
        assert await _p7_counts(postgres, seeded.candidate.tradeplan_id) == {table: 0 for table in _P7_TABLES}


@pytest.mark.parametrize("durable_gate", ["revoked", "mode", "kill"])
async def test_pre_snapshot_governance_rejection_never_inserts_caller_snapshot_fk(
    postgres: PoolBackedPostgres,
    durable_gate: str,
) -> None:
    async with _seeded(postgres, kill_switch_active=durable_gate == "kill") as seeded:
        if durable_gate == "revoked":
            await postgres.execute(
                "UPDATE executor_instances SET revoked_at=$2,updated_at=$2 WHERE executor_id=$1::uuid",
                str(seeded.executor_id),
                _P7_DECISION,
            )
        elif durable_gate == "mode":
            await postgres.execute(
                "UPDATE executor_instances SET execution_mode='LIVE',mode_changed_at=$2,updated_at=$2 "
                "WHERE executor_id=$1::uuid",
                str(seeded.executor_id),
                _P7_DECISION,
            )
        await postgres.execute(
            "DELETE FROM executor_account_snapshots WHERE snapshot_id=$1",
            seeded.evidence.account_snapshot.snapshot_id,
        )

        result = await _repository(postgres).process_evidence(seeded.evidence)

        assert (result.status, result.reason_code, result.evaluation, result.authority_bundle) == (
            "REJECTED",
            "C2_ACCOUNT_SNAPSHOT_MISSING",
            None,
            None,
        )
        assert await _p7_counts(postgres, seeded.candidate.tradeplan_id) == {table: 0 for table in _P7_TABLES}


async def test_terminal_parent_without_authority_never_inserts_caller_snapshot_fk(
    postgres: PoolBackedPostgres,
) -> None:
    async with _seeded(postgres) as seeded:
        terminal_at = seeded.candidate.decision_at_utc + timedelta(seconds=1)
        await postgres.execute(
            f"""UPDATE {CANDIDATE_TABLE} SET lifecycle_state='INVALIDATED',invalidated_at=$2,
                       state_version=state_version+1,updated_at=$2 WHERE tradeplan_id=$1""",
            seeded.candidate.tradeplan_id,
            terminal_at,
        )
        await postgres.execute(
            "DELETE FROM executor_account_snapshots WHERE snapshot_id=$1",
            seeded.evidence.account_snapshot.snapshot_id,
        )

        result = await _repository(postgres).process_evidence(seeded.evidence)

        assert (result.status, result.reason_code, result.evaluation, result.authority_bundle) == (
            "REJECTED",
            "C2_PARENT_AUTHORITY_TERMINAL",
            None,
            None,
        )
        assert await _p7_counts(postgres, seeded.candidate.tradeplan_id) == {table: 0 for table in _P7_TABLES}


async def test_unattested_snapshot_does_not_fabricate_reconciliation_authority(
    postgres: PoolBackedPostgres,
) -> None:
    """An empty broker ledger is absence of evidence, not reconciliation evidence."""

    async with _seeded(postgres, broker_ledger_reconciled=False) as seeded:
        assert await _external_counts(postgres, seeded) == {
            "legacy_candidate": 0,
            "legacy_reservation": 0,
            "legacy_outbox": 0,
            "commands": 0,
            "reports": 0,
            "broker": 0,
        }
        result = await _repository(postgres).process_evidence(seeded.evidence)
        assert (result.status, result.reason_code) == (
            "REJECTED",
            "C2_BROKER_LEDGER_NOT_RECONCILED",
        )
        assert result.evaluation is not None and result.evaluation.decision == "REJECTED"
        assert result.authority_bundle is None
        counts = await _p7_counts(postgres, seeded.candidate.tradeplan_id)
        assert counts[EVALUATION_TABLE] == 1
        assert all(counts[table] == 0 for table in _P7_TABLES if table != EVALUATION_TABLE)


async def test_attested_snapshot_with_pending_order_rejects_without_authority(
    postgres: PoolBackedPostgres,
) -> None:
    pending = [
        {
            "order_ticket": 701,
            "symbol": "EURUSD",
            "order_type": "BUY_LIMIT",
            "volume": 0.01,
            "requested_price": 1.099,
            "magic": 150015,
        }
    ]
    async with _seeded(postgres, pending_orders=pending) as seeded:
        result = await _repository(postgres).process_evidence(seeded.evidence)
        assert (result.status, result.reason_code) == (
            "REJECTED",
            "C2_PARENT_REQUIRES_NO_PENDING_ORDERS",
        )
        assert result.evaluation is not None
        counts = await _p7_counts(postgres, seeded.candidate.tradeplan_id)
        assert counts[EVALUATION_TABLE] == 1
        assert all(counts[table] == 0 for table in _P7_TABLES if table != EVALUATION_TABLE)


@pytest.mark.parametrize(
    ("command_state", "terminal_clock", "expected_status"),
    [
        *(
            (state, clock, "REJECTED")
            for state in ("FILLED", "COMPLETED", "CANCELLED", "EXPIRED")
            for clock in ("null", "equal", "before")
        ),
        *((state, "after", "APPROVED") for state in ("FILLED", "COMPLETED", "CANCELLED", "EXPIRED")),
        ("REJECTED", "null", "APPROVED"),
        ("SHADOW_COMPLETED", "null", "APPROVED"),
        ("SHADOW_REJECTED", "null", "APPROVED"),
    ],
)
async def test_terminal_command_requires_strictly_newer_reconciled_snapshot(
    postgres: PoolBackedPostgres,
    command_state: Literal[
        "FILLED",
        "COMPLETED",
        "CANCELLED",
        "EXPIRED",
        "REJECTED",
        "SHADOW_COMPLETED",
        "SHADOW_REJECTED",
    ],
    terminal_clock: Literal["null", "equal", "before", "after"],
    expected_status: Literal["REJECTED", "APPROVED"],
) -> None:
    async with _seeded(postgres) as seeded:
        captured_at = seeded.evidence.account_snapshot.captured_at_utc
        terminal_at = {
            "null": None,
            "equal": captured_at,
            "before": captured_at + timedelta(seconds=1),
            "after": captured_at - timedelta(seconds=1),
        }[terminal_clock]
        command_id = await _insert_terminal_command(
            postgres,
            seeded,
            state=command_state,
            terminal_at=terminal_at,
        )
        try:
            pending_count = 0 if expected_status == "APPROVED" else 1
            risk_payload = seeded.evidence.existing_risk.model_dump(mode="python")
            risk_payload["pending_order_count"] = pending_count
            risk_payload.pop("evidence_hash")
            risk_payload.pop("execution_authority")
            evidence = seeded.evidence.model_copy(
                update={
                    "existing_risk": C2ShadowExistingRiskEvidenceV2(
                        **risk_payload,
                        evidence_hash=canonical_hash_v1(risk_payload),
                    )
                }
            )
            result = await _repository(postgres).process_evidence(evidence)
            assert result.status == expected_status
            counts = await _p7_counts(postgres, seeded.candidate.tradeplan_id)
            if expected_status == "REJECTED":
                assert result.reason_code == "C2_PARENT_REQUIRES_NO_PENDING_ORDERS"
                assert counts[EVALUATION_TABLE] == 1
                assert all(counts[table] == 0 for table in _P7_TABLES if table != EVALUATION_TABLE)
            else:
                assert result.authority_bundle is not None
                assert counts == {table: 1 for table in _P7_TABLES}
        finally:
            await postgres.execute(
                "DELETE FROM execution_commands WHERE command_id=$1::uuid",
                str(command_id),
            )


async def test_durable_pending_command_committed_before_p7_is_rejected(
    postgres: PoolBackedPostgres,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _seeded(postgres) as seeded:
        monkeypatch.setenv("EXECUTOR_COMMAND_SIGNING_SECRET", _COMMAND_SIGNING_SECRET)
        monkeypatch.setenv("EXECUTOR_COMMAND_SIGNING_KEY_ID", _COMMAND_SIGNING_KEY_ID)
        command = _pending_command(seeded)
        await MT5CommandRepository(pg=cast(Any, postgres)).enqueue_command(command)
        try:
            risk_payload = seeded.evidence.existing_risk.model_dump(mode="python")
            risk_payload["pending_order_count"] = 1
            risk_payload.pop("evidence_hash")
            risk_payload.pop("execution_authority")
            evidence = seeded.evidence.model_copy(
                update={
                    "source_request_id": "p7-durable-command-before-authority",
                    "existing_risk": C2ShadowExistingRiskEvidenceV2(
                        **risk_payload,
                        evidence_hash=canonical_hash_v1(risk_payload),
                    ),
                }
            )
            result = await _repository(postgres).process_evidence(evidence)
            assert (result.status, result.reason_code) == (
                "REJECTED",
                "C2_PARENT_REQUIRES_NO_PENDING_ORDERS",
            )
            counts = await _p7_counts(postgres, seeded.candidate.tradeplan_id)
            assert counts[EVALUATION_TABLE] == 1
            assert all(counts[table] == 0 for table in _P7_TABLES if table != EVALUATION_TABLE)
        finally:
            await postgres.execute(
                "DELETE FROM execution_commands WHERE command_id=$1::uuid",
                str(command.command_id),
            )


async def test_command_insert_requires_registered_executor_account_binding(
    postgres: PoolBackedPostgres,
) -> None:
    async with _seeded(postgres) as seeded:
        with pytest.raises(postgres.check_violation_error) as raised:
            await _insert_terminal_command(
                postgres,
                seeded,
                state="SHADOW_REJECTED",
                terminal_at=_P7_DECISION,
                account_id=f"p7-mismatched-account-{uuid4().hex[:16]}",
            )
        assert getattr(raised.value, "constraint_name", None) == "ck_execution_command_executor_account_binding_c2_v2"


async def test_live_p7_allows_safe_command_update_but_rejects_authority_resurrection(
    postgres: PoolBackedPostgres,
) -> None:
    async with _seeded(postgres) as seeded:
        approved = await _repository(postgres).process_evidence(seeded.evidence)
        assert approved.status == "APPROVED" and approved.authority_bundle is not None
        command_id = await _insert_terminal_command(
            postgres,
            seeded,
            state="SHADOW_COMPLETED",
            terminal_at=_P7_DECISION,
        )
        try:
            await postgres.execute(
                "UPDATE execution_commands SET state='SHADOW_REJECTED' WHERE command_id=$1::uuid",
                str(command_id),
            )
            with pytest.raises(postgres.check_violation_error) as raised:
                await postgres.execute(
                    "UPDATE execution_commands SET state='QUEUED',terminal_at=NULL WHERE command_id=$1::uuid",
                    str(command_id),
                )
            assert getattr(raised.value, "constraint_name", None) == "ck_execution_command_no_live_c2_shadow_v2"
            state = await postgres.fetchrow(
                "SELECT state FROM execution_commands WHERE command_id=$1::uuid",
                str(command_id),
            )
            assert state is not None and state["state"] == "SHADOW_REJECTED"
        finally:
            await postgres.execute(
                "DELETE FROM execution_commands WHERE command_id=$1::uuid",
                str(command_id),
            )


async def test_live_p7_rejects_command_resurrection_with_account_rebinding(
    postgres: PoolBackedPostgres,
) -> None:
    async with _seeded(postgres) as seeded:
        approved = await _repository(postgres).process_evidence(seeded.evidence)
        assert approved.status == "APPROVED" and approved.authority_bundle is not None
        command_id = await _insert_terminal_command(
            postgres,
            seeded,
            state="SHADOW_REJECTED",
            terminal_at=_P7_DECISION,
        )
        rebound_account = f"p7-rebound-account-{uuid4().hex[:16]}"
        try:
            with pytest.raises(postgres.check_violation_error) as raised:
                await postgres.execute(
                    """UPDATE execution_commands
                       SET state='QUEUED',terminal_at=NULL,account_id=$2 WHERE command_id=$1::uuid""",
                    str(command_id),
                    rebound_account,
                )
            assert (
                getattr(raised.value, "constraint_name", None) == "ck_execution_command_executor_account_binding_c2_v2"
            )
            state = await postgres.fetchrow(
                "SELECT state,account_id FROM execution_commands WHERE command_id=$1::uuid",
                str(command_id),
            )
            assert state is not None
            assert tuple(state) == ("SHADOW_REJECTED", seeded.account_id)
        finally:
            await postgres.execute(
                "DELETE FROM execution_commands WHERE command_id=$1::uuid",
                str(command_id),
            )


async def test_live_p7_rejects_safe_command_account_laundering_first_step(
    postgres: PoolBackedPostgres,
) -> None:
    async with _seeded(postgres) as seeded:
        approved = await _repository(postgres).process_evidence(seeded.evidence)
        assert approved.status == "APPROVED" and approved.authority_bundle is not None
        command_id = await _insert_terminal_command(
            postgres,
            seeded,
            state="SHADOW_REJECTED",
            terminal_at=_P7_DECISION,
        )
        rebound_account = f"p7-laundered-account-{uuid4().hex[:16]}"
        try:
            with pytest.raises(postgres.check_violation_error) as raised:
                await postgres.execute(
                    "UPDATE execution_commands SET account_id=$2 WHERE command_id=$1::uuid",
                    str(command_id),
                    rebound_account,
                )
            assert (
                getattr(raised.value, "constraint_name", None) == "ck_execution_command_executor_account_binding_c2_v2"
            )
            state = await postgres.fetchrow(
                "SELECT state,account_id FROM execution_commands WHERE command_id=$1::uuid",
                str(command_id),
            )
            assert state is not None
            assert tuple(state) == ("SHADOW_REJECTED", seeded.account_id)
        finally:
            await postgres.execute(
                "DELETE FROM execution_commands WHERE command_id=$1::uuid",
                str(command_id),
            )


async def test_preexisting_command_account_label_cannot_hide_bound_executor_risk(
    postgres: PoolBackedPostgres,
) -> None:
    async with _seeded(postgres) as seeded:
        trigger = "trg_5scr_guard_execution_command_against_c2_v2"
        await postgres.execute(f"ALTER TABLE execution_commands DISABLE TRIGGER {trigger}")
        try:
            command_id = await _insert_terminal_command(
                postgres,
                seeded,
                state="QUEUED",
                terminal_at=None,
                account_id=f"p7-laundered-account-{uuid4().hex[:16]}",
            )
        finally:
            await postgres.execute(f"ALTER TABLE execution_commands ENABLE TRIGGER {trigger}")
        try:
            risk_payload = seeded.evidence.existing_risk.model_dump(mode="python")
            risk_payload["pending_order_count"] = 1
            risk_payload.pop("evidence_hash")
            risk_payload.pop("execution_authority")
            evidence = seeded.evidence.model_copy(
                update={
                    "source_request_id": "p7-preexisting-command-account-laundering",
                    "existing_risk": C2ShadowExistingRiskEvidenceV2(
                        **risk_payload,
                        evidence_hash=canonical_hash_v1(risk_payload),
                    ),
                }
            )

            result = await _repository(postgres).process_evidence(evidence)

            assert (result.status, result.reason_code) == (
                "REJECTED",
                "C2_PARENT_REQUIRES_NO_PENDING_ORDERS",
            )
            counts = await _p7_counts(postgres, seeded.candidate.tradeplan_id)
            assert counts[EVALUATION_TABLE] == 1
            assert all(counts[table] == 0 for table in _P7_TABLES if table != EVALUATION_TABLE)
        finally:
            await postgres.execute(
                "DELETE FROM execution_commands WHERE command_id=$1::uuid",
                str(command_id),
            )


@pytest.mark.parametrize("field", ["account_id", "broker_server"])
async def test_live_p7_rejects_executor_identity_mutation(
    postgres: PoolBackedPostgres,
    field: Literal["account_id", "broker_server"],
) -> None:
    async with _seeded(postgres) as seeded:
        approved = await _repository(postgres).process_evidence(seeded.evidence)
        assert approved.status == "APPROVED" and approved.authority_bundle is not None
        value = f"p7-rebound-{uuid4().hex[:16]}"
        with pytest.raises(postgres.check_violation_error) as raised:
            await postgres.execute(
                f"UPDATE executor_instances SET {field}=$2 WHERE executor_id=$1::uuid",
                str(seeded.executor_id),
                value,
            )
        assert getattr(raised.value, "constraint_name", None) == "ck_executor_identity_no_live_c2_shadow_v2"


async def test_command_guard_binds_live_p7_by_executor_after_forced_account_rebind(
    postgres: PoolBackedPostgres,
) -> None:
    async with _seeded(postgres) as seeded:
        approved = await _repository(postgres).process_evidence(seeded.evidence)
        assert approved.status == "APPROVED" and approved.authority_bundle is not None
        trigger = "trg_5scr_guard_executor_identity_against_c2_v2"
        rebound_account = f"p7-forced-rebound-{uuid4().hex[:16]}"
        await postgres.execute(f"ALTER TABLE executor_instances DISABLE TRIGGER {trigger}")
        try:
            await postgres.execute(
                "UPDATE executor_instances SET account_id=$2 WHERE executor_id=$1::uuid",
                str(seeded.executor_id),
                rebound_account,
            )
        finally:
            await postgres.execute(f"ALTER TABLE executor_instances ENABLE TRIGGER {trigger}")
        try:
            with pytest.raises(postgres.check_violation_error) as raised:
                await _insert_terminal_command(
                    postgres,
                    seeded,
                    state="QUEUED",
                    terminal_at=None,
                    account_id=rebound_account,
                )
            assert getattr(raised.value, "constraint_name", None) == "ck_execution_command_no_live_c2_shadow_v2"
        finally:
            await postgres.execute(f"ALTER TABLE executor_instances DISABLE TRIGGER {trigger}")
            try:
                await postgres.execute(
                    "UPDATE executor_instances SET account_id=$2 WHERE executor_id=$1::uuid",
                    str(seeded.executor_id),
                    seeded.account_id,
                )
            finally:
                await postgres.execute(f"ALTER TABLE executor_instances ENABLE TRIGGER {trigger}")


async def test_unrepresentable_snapshot_capability_rejects_before_db_authority_checks(
    postgres: PoolBackedPostgres,
) -> None:
    async with _seeded(postgres) as seeded:
        capability = seeded.evidence.account_snapshot.symbols[0].model_copy(update={"volume_step": 0.0100000000001})
        snapshot = seeded.evidence.account_snapshot.model_copy(update={"symbols": [capability]})
        await postgres.execute(
            "UPDATE executor_account_snapshots SET payload=$2::jsonb WHERE snapshot_id=$1",
            snapshot.snapshot_id,
            json.dumps(snapshot.model_dump(mode="json"), sort_keys=True, separators=(",", ":")),
        )
        evidence = seeded.evidence.model_copy(
            update={
                "source_request_id": "p7-unrepresentable-snapshot-capability",
                "account_snapshot": snapshot,
                "account_snapshot_hash": account_snapshot_authority_hash_v2(snapshot),
            }
        )

        result = await _repository(postgres).process_evidence(evidence)

        assert (result.status, result.reason_code) == (
            "REJECTED",
            "C2_RISK_NUMERIC_GRID_UNREPRESENTABLE",
        )
        assert result.evaluation is not None and result.evaluation.decision == "REJECTED"
        assert result.authority_bundle is None
        counts = await _p7_counts(postgres, seeded.candidate.tradeplan_id)
        assert counts[EVALUATION_TABLE] == 1
        assert all(counts[table] == 0 for table in _P7_TABLES if table != EVALUATION_TABLE)


async def test_legacy_active_lock_and_held_reservation_block_p7_without_mutation(
    postgres: PoolBackedPostgres,
) -> None:
    async with _seeded(postgres) as seeded:
        lifecycle_id, tradeplan_id, campaign_id, reserved_risk = await _insert_legacy_active_risk(
            postgres,
            seeded,
        )
        try:
            existing_risk_payload = {
                "account_id": seeded.account_id,
                "tradeplan_id": seeded.candidate.tradeplan_id,
                "active_campaign_count": 1,
                "active_reservation_count": 1,
                "pending_order_count": 0,
                "broker_ledger_reconciled": True,
                "committed_or_reserved_campaign_risk_usd": reserved_risk,
                "account_total_open_risk_usd": reserved_risk,
                "captured_at_utc": seeded.evidence.decision_at_utc,
            }
            evidence = seeded.evidence.model_copy(
                update={
                    "source_request_id": "p7-legacy-active-risk-rejected",
                    "existing_risk": C2ShadowExistingRiskEvidenceV2(
                        **existing_risk_payload,
                        evidence_hash=canonical_hash_v1(existing_risk_payload),
                    ),
                }
            )
            result = await _repository(postgres).process_evidence(evidence)
            assert (result.status, result.reason_code) == (
                "REJECTED",
                "C2_EXISTING_RISK_NOT_FLAT",
            )
            counts = await _p7_counts(postgres, seeded.candidate.tradeplan_id)
            assert counts[EVALUATION_TABLE] == 1
            assert all(counts[table] == 0 for table in _P7_TABLES if table != EVALUATION_TABLE)
            legacy = await postgres.fetchrow(
                """SELECT
                    (SELECT state FROM strategy_5scr_campaign_risk_locks WHERE campaign_id=$1) lock_state,
                    (SELECT state FROM strategy_5scr_risk_reservations WHERE tradeplan_id=$2) reservation_state,
                    (SELECT reserved_risk_usd FROM strategy_5scr_risk_reservations WHERE tradeplan_id=$2) reserved_risk""",
                campaign_id,
                tradeplan_id,
            )
            assert legacy is not None
            assert tuple(legacy) == ("ACTIVE", "HELD", reserved_risk)
        finally:
            await _delete_legacy_active_risk(
                postgres,
                lifecycle_id=lifecycle_id,
                tradeplan_id=tradeplan_id,
                campaign_id=campaign_id,
            )


async def test_live_p7_authority_rejects_legacy_active_campaign_insert(
    postgres: PoolBackedPostgres,
) -> None:
    async with _seeded(postgres) as seeded:
        approved = await _repository(postgres).process_evidence(seeded.evidence)
        assert approved.status == "APPROVED" and approved.authority_bundle is not None
        with pytest.raises(postgres.check_violation_error) as raised:
            await postgres.execute(
                """INSERT INTO strategy_5scr_campaign_risk_locks (
                       campaign_id,account_id,executor_id,account_snapshot_id,policy_id,state,
                       balance_base,risk_percent_per_entry,risk_unit_usd,max_campaign_risk_usd,locked_at
                   ) VALUES ($1,$2,$3::uuid,$4,'LEGACY_P7_CONFLICT','ACTIVE',1000,0.01,10,30,$5)""",
                f"legacy-p7-conflicting-campaign:{uuid4().hex}",
                seeded.account_id,
                str(seeded.executor_id),
                seeded.evidence.account_snapshot.snapshot_id,
                _P7_DECISION,
            )
        assert getattr(raised.value, "constraint_name", None) == "ck_5scr_legacy_campaign_no_live_c2_shadow_v2"


@pytest.mark.parametrize("state", ["HELD", "CONSUMED", "OPEN"])
async def test_live_p7_authority_rejects_legacy_authority_reservation_insert(
    postgres: PoolBackedPostgres,
    state: Literal["HELD", "CONSUMED", "OPEN"],
) -> None:
    async with _seeded(postgres) as seeded:
        approved = await _repository(postgres).process_evidence(seeded.evidence)
        assert approved.status == "APPROVED" and approved.authority_bundle is not None
        lifecycle_id, tradeplan_id, campaign_id, suffix = await _insert_legacy_terminal_parent(postgres, seeded)
        try:
            with pytest.raises(postgres.check_violation_error) as raised:
                await _insert_legacy_reservation(
                    postgres,
                    seeded,
                    tradeplan_id=tradeplan_id,
                    campaign_id=campaign_id,
                    suffix=suffix,
                    state=state,
                )
            assert getattr(raised.value, "constraint_name", None) == "ck_5scr_legacy_reservation_no_live_c2_shadow_v2"
        finally:
            await _delete_legacy_active_risk(
                postgres,
                lifecycle_id=lifecycle_id,
                tradeplan_id=tradeplan_id,
                campaign_id=campaign_id,
            )


@pytest.mark.parametrize("state", ["RELEASED", "EXPIRED"])
async def test_live_p7_authority_allows_legacy_terminal_cleanup_rows(
    postgres: PoolBackedPostgres,
    state: Literal["RELEASED", "EXPIRED"],
) -> None:
    async with _seeded(postgres) as seeded:
        approved = await _repository(postgres).process_evidence(seeded.evidence)
        assert approved.status == "APPROVED" and approved.authority_bundle is not None
        lifecycle_id, tradeplan_id, campaign_id, suffix = await _insert_legacy_terminal_parent(postgres, seeded)
        try:
            reservation_id = await _insert_legacy_reservation(
                postgres,
                seeded,
                tradeplan_id=tradeplan_id,
                campaign_id=campaign_id,
                suffix=suffix,
                state=state,
            )
            row = await postgres.fetchrow(
                "SELECT state FROM strategy_5scr_risk_reservations WHERE reservation_id=$1::uuid",
                str(reservation_id),
            )
            assert row is not None and row["state"] == state
        finally:
            await _delete_legacy_active_risk(
                postgres,
                lifecycle_id=lifecycle_id,
                tradeplan_id=tradeplan_id,
                campaign_id=campaign_id,
            )


async def test_live_p7_authority_rejects_legacy_campaign_and_reservation_resurrection(
    postgres: PoolBackedPostgres,
) -> None:
    async with _seeded(postgres) as seeded:
        approved = await _repository(postgres).process_evidence(seeded.evidence)
        assert approved.status == "APPROVED" and approved.authority_bundle is not None
        lifecycle_id, tradeplan_id, campaign_id, suffix = await _insert_legacy_terminal_parent(postgres, seeded)
        reservation_id: UUID | None = None
        try:
            await postgres.execute(
                "ALTER TABLE strategy_5scr_campaign_risk_locks DISABLE TRIGGER trg_5scr_campaign_risk_lock_update_v1"
            )
            try:
                with pytest.raises(postgres.check_violation_error) as campaign_error:
                    await postgres.execute(
                        """UPDATE strategy_5scr_campaign_risk_locks
                           SET state='ACTIVE',closed_at=NULL WHERE campaign_id=$1""",
                        campaign_id,
                    )
                assert (
                    getattr(campaign_error.value, "constraint_name", None)
                    == "ck_5scr_legacy_campaign_no_live_c2_shadow_v2"
                )
            finally:
                await postgres.execute(
                    "ALTER TABLE strategy_5scr_campaign_risk_locks ENABLE TRIGGER trg_5scr_campaign_risk_lock_update_v1"
                )

            reservation_id = await _insert_legacy_reservation(
                postgres,
                seeded,
                tradeplan_id=tradeplan_id,
                campaign_id=campaign_id,
                suffix=suffix,
                state="EXPIRED",
            )
            await postgres.execute(
                "ALTER TABLE strategy_5scr_risk_reservations DISABLE TRIGGER trg_5scr_risk_reservation_update_v1"
            )
            try:
                with pytest.raises(postgres.check_violation_error) as reservation_error:
                    await postgres.execute(
                        """UPDATE strategy_5scr_risk_reservations
                           SET state='HELD',expired_at=NULL WHERE reservation_id=$1::uuid""",
                        str(reservation_id),
                    )
                assert (
                    getattr(reservation_error.value, "constraint_name", None)
                    == "ck_5scr_legacy_reservation_no_live_c2_shadow_v2"
                )
            finally:
                await postgres.execute(
                    "ALTER TABLE strategy_5scr_risk_reservations ENABLE TRIGGER trg_5scr_risk_reservation_update_v1"
                )
        finally:
            if reservation_id is not None:
                await postgres.execute(
                    "DELETE FROM strategy_5scr_risk_reservations WHERE reservation_id=$1::uuid",
                    str(reservation_id),
                )
            await _delete_legacy_active_risk(
                postgres,
                lifecycle_id=lifecycle_id,
                tradeplan_id=tradeplan_id,
                campaign_id=campaign_id,
            )


@pytest.mark.parametrize("direction", ["BUY", "SELL"])
async def test_attested_flat_account_persists_complete_dark_authority_bundle(
    postgres: PoolBackedPostgres,
    direction: Literal["BUY", "SELL"],
) -> None:
    async with _seeded(postgres, direction=direction) as seeded:
        before = await _external_counts(postgres, seeded)
        repository = _repository(postgres)
        result = await repository.process_evidence(seeded.evidence)
        assert (result.status, result.reason_code) == ("APPROVED", "C2_SHADOW_RISK_AUTHORIZED")
        assert result.evaluation is not None and result.evaluation.decision == "APPROVED"
        assert result.authority_bundle is not None
        bundle = result.authority_bundle
        assert bundle.handoff.direction == direction
        assert bundle.reservation.state == "RESERVED"
        assert bundle.reservation.risk_authority is True
        assert bundle.reservation.valid_for_execution is True
        assert bundle.reservation.execution_mode == "SHADOW"
        assert bundle.reservation.broker_execution_authority is False
        assert bundle.reservation.command_authority is False
        assert bundle.execution_campaign.state == "PARENT_PENDING"
        assert bundle.execution_campaign.broker_execution_authority is False
        assert bundle.execution_campaign.command_authority is False
        assert bundle.final_signal.valid_for_execution is True
        assert bundle.final_signal.broker_execution_authority is False
        assert bundle.final_signal.command_authority is False
        assert bundle.final_signal.delivery_authority is False
        assert bundle.final_signal.next_required_stage == "C3_MANUAL_SHADOW_PROMOTION"
        assert await _p7_counts(postgres, seeded.candidate.tradeplan_id) == {table: 1 for table in _P7_TABLES}
        restarted = _repository(postgres)
        assert await restarted.load_authority(seeded.candidate.tradeplan_id) == bundle
        assert await restarted.load_evaluations(seeded.candidate.tradeplan_id) == (result.evaluation,)
        assert await _external_counts(postgres, seeded) == before


async def test_exact_retry_restart_and_concurrency_reserve_once(postgres: PoolBackedPostgres) -> None:
    async with _seeded(postgres) as seeded:
        calls = [_repository(postgres).process_evidence(seeded.evidence) for _ in range(20)]
        results = await asyncio.wait_for(asyncio.gather(*calls), timeout=20)
        assert [item.status for item in results].count("APPROVED") == 1
        assert [item.status for item in results].count("DUPLICATE") == 19
        identities = {
            item.authority_bundle.reservation.reservation_id for item in results if item.authority_bundle is not None
        }
        assert len(identities) == 1
        assert await _p7_counts(postgres, seeded.candidate.tradeplan_id) == {table: 1 for table in _P7_TABLES}
        restarted = _repository(postgres)
        replay = await restarted.process_evidence(seeded.evidence)
        assert replay.status == "DUPLICATE"
        assert replay.authority_bundle is not None
        assert replay.authority_bundle.reservation.reservation_id in identities


async def test_exact_replay_after_database_clock_expiry_terminalizes_once(
    postgres: PoolBackedPostgres,
) -> None:
    async with _seeded(postgres) as seeded:
        approved = await _repository(postgres).process_evidence(seeded.evidence)
        assert approved.status == "APPROVED" and approved.authority_bundle is not None
        expires_at = approved.authority_bundle.reservation.expires_at_utc

        expired_repository = _repository(postgres, now=expires_at + timedelta(microseconds=1))
        expired = await expired_repository.process_evidence(seeded.evidence)
        assert (expired.status, expired.reason_code) == (
            "INVALIDATED",
            "C2_AUTHORITY_EXPIRED",
        )
        replay = await expired_repository.process_evidence(seeded.evidence)
        assert (replay.status, replay.reason_code) == (
            "DUPLICATE",
            "C2_AUTHORITY_ALREADY_TERMINAL",
        )
        assert len(await expired_repository.load_evaluations(seeded.candidate.tradeplan_id)) == 1
        states = await postgres.fetchrow(
            f"""SELECT
                (SELECT state FROM {RISK_LOCK_TABLE} WHERE tradeplan_id=$1) risk_lock,
                (SELECT state FROM {RESERVATION_TABLE} WHERE tradeplan_id=$1) reservation,
                (SELECT state FROM {CAMPAIGN_TABLE} WHERE tradeplan_id=$1) campaign,
                (SELECT status FROM {OUTBOX_TABLE} WHERE tradeplan_id=$1) outbox""",
            seeded.candidate.tradeplan_id,
        )
        assert states is not None
        assert tuple(states) == ("CLOSED", "EXPIRED", "EXPIRED", "CANCELLED")
        clocks = await postgres.fetchrow(
            f"""SELECT
                (SELECT closed_at FROM {RISK_LOCK_TABLE} WHERE tradeplan_id=$1) risk_lock,
                (SELECT terminal_at FROM {RESERVATION_TABLE} WHERE tradeplan_id=$1) reservation,
                (SELECT terminal_at FROM {CAMPAIGN_TABLE} WHERE tradeplan_id=$1) campaign,
                (SELECT terminal_at FROM {OUTBOX_TABLE} WHERE tradeplan_id=$1) outbox""",
            seeded.candidate.tradeplan_id,
        )
        assert clocks is not None
        assert set(clocks.values()) == {expires_at}


async def test_already_expired_new_evidence_is_durably_rejected(
    postgres: PoolBackedPostgres,
) -> None:
    async with _seeded(postgres) as seeded:
        expires_at = seeded.evidence.decision_at_utc + timedelta(seconds=1)
        expired_evidence = seeded.evidence.model_copy(update={"expires_at_utc": expires_at})
        repository = _repository(postgres, now=expires_at)
        rejected = await repository.process_evidence(expired_evidence)
        assert (rejected.status, rejected.reason_code) == (
            "REJECTED",
            "C2_AUTHORITY_EXPIRED",
        )
        assert rejected.evaluation is not None and rejected.evaluation.decision == "REJECTED"
        replay = await repository.process_evidence(expired_evidence)
        assert (replay.status, replay.reason_code) == (
            "DUPLICATE",
            "C2_EVALUATION_ALREADY_PERSISTED",
        )
        counts = await _p7_counts(postgres, seeded.candidate.tradeplan_id)
        assert counts[EVALUATION_TABLE] == 1
        assert all(counts[table] == 0 for table in _P7_TABLES if table != EVALUATION_TABLE)


async def test_approved_evaluation_without_bundle_is_integrity_failure(
    postgres: PoolBackedPostgres,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _seeded(postgres) as seeded:
        repository = _repository(postgres)
        approved = await repository.process_evidence(seeded.evidence)
        assert approved.status == "APPROVED"

        async def missing_bundle(*_args: Any, **_kwargs: Any) -> None:
            return None

        monkeypatch.setattr(repository, "_load_bundle", missing_bundle)
        with pytest.raises(
            CandidateC2ShadowV2IntegrityError,
            match="C2_APPROVED_EVALUATION_AUTHORITY_MISSING",
        ):
            await repository.process_evidence(seeded.evidence)


async def test_newer_healthy_heartbeat_preserves_frozen_authority(
    postgres: PoolBackedPostgres,
) -> None:
    async with _seeded(postgres) as seeded:
        repository = _repository(postgres)
        approved = await repository.process_evidence(seeded.evidence)
        assert approved.status == "APPROVED" and approved.authority_bundle is not None

        later_at = _P7_DECISION + timedelta(seconds=1)
        newer = _snapshot(
            seeded.candidate,
            seeded.executor_id,
            seeded.account_id,
            captured_at=later_at,
        ).model_copy(update={"snapshot_id": f"p7-healthy-{seeded.executor_id.hex}"})
        await _insert_snapshot_row(postgres, newer)
        heartbeat = _build_p7_evidence(
            seeded.candidate,
            seeded.executor_id,
            seeded.account_id,
            newer,
            request="p7-newer-healthy-heartbeat",
            decision_at=later_at,
        ).model_copy(update={"governance": seeded.evidence.governance})

        replay = await repository.process_evidence(heartbeat)
        assert (replay.status, replay.reason_code) == (
            "DUPLICATE",
            "C2_AUTHORITY_ALREADY_RESERVED",
        )
        assert replay.authority_bundle == approved.authority_bundle
        assert await repository.load_authority(seeded.candidate.tradeplan_id) == approved.authority_bundle
        assert len(await repository.load_evaluations(seeded.candidate.tradeplan_id)) == 1
        assert await _p7_counts(postgres, seeded.candidate.tradeplan_id) == {table: 1 for table in _P7_TABLES}

        exact_original_replay = await repository.process_evidence(seeded.evidence)
        assert (exact_original_replay.status, exact_original_replay.reason_code) == (
            "DUPLICATE",
            "C2_EVALUATION_ALREADY_PERSISTED",
        )
        assert exact_original_replay.authority_bundle == approved.authority_bundle
        assert len(await repository.load_evaluations(seeded.candidate.tradeplan_id)) == 1
        assert await _p7_counts(postgres, seeded.candidate.tradeplan_id) == {table: 1 for table in _P7_TABLES}


@pytest.mark.parametrize("forged_scope", ["executor", "account", "server", "broker_symbol"])
async def test_forged_retry_scope_cannot_terminalize_valid_authority(
    postgres: PoolBackedPostgres,
    forged_scope: str,
) -> None:
    async with _seeded(postgres) as seeded:
        repository = _repository(postgres)
        approved = await repository.process_evidence(seeded.evidence)
        assert approved.status == "APPROVED" and approved.authority_bundle is not None

        executor_id = uuid4() if forged_scope == "executor" else seeded.executor_id
        account_id = f"p7-forged-{uuid4().hex[:16]}" if forged_scope == "account" else seeded.account_id
        broker_server = "FORGED-BROKER-SERVER" if forged_scope == "server" else _BROKER_SERVER
        snapshot = seeded.evidence.account_snapshot
        if forged_scope in {"executor", "account"}:
            snapshot = snapshot.model_copy(
                update={
                    "snapshot_id": f"p7-forged-snapshot-{uuid4().hex}",
                    "executor_id": executor_id,
                    "account_id": account_id,
                }
            )
        existing_risk_payload = {
            "account_id": account_id,
            "tradeplan_id": seeded.candidate.tradeplan_id,
            "active_campaign_count": 0,
            "active_reservation_count": 0,
            "pending_order_count": 0,
            "broker_ledger_reconciled": True,
            "committed_or_reserved_campaign_risk_usd": Decimal("0"),
            "account_total_open_risk_usd": Decimal("0"),
            "captured_at_utc": seeded.evidence.decision_at_utc,
        }
        forged = CandidateC2ShadowBuildEvidenceV2.model_validate(
            {
                **seeded.evidence.model_dump(mode="python"),
                "source_request_id": f"p7-forged-retry-{forged_scope}",
                "governance": _governance(
                    executor_id,
                    account_id,
                    kill_switch_active=False,
                    broker_server=broker_server,
                ),
                "account_snapshot": snapshot,
                "account_snapshot_hash": account_snapshot_authority_hash_v2(snapshot),
                "existing_risk": C2ShadowExistingRiskEvidenceV2(
                    **existing_risk_payload,
                    evidence_hash=canonical_hash_v1(existing_risk_payload),
                ),
                "broker_symbol": "EURUSD.FORGED" if forged_scope == "broker_symbol" else seeded.evidence.broker_symbol,
            }
        )
        rejected = await repository.process_evidence(forged)
        assert (rejected.status, rejected.reason_code) == (
            "QUARANTINED",
            "C2_CURRENT_AUTHORITY_SCOPE_MISMATCH",
        )
        assert await repository.load_authority(seeded.candidate.tradeplan_id) == approved.authority_bundle
        assert len(await repository.load_evaluations(seeded.candidate.tradeplan_id)) == 1
        states = await postgres.fetchrow(
            f"""SELECT
                (SELECT state FROM {RISK_LOCK_TABLE} WHERE tradeplan_id=$1) risk_lock,
                (SELECT state FROM {RESERVATION_TABLE} WHERE tradeplan_id=$1) reservation,
                (SELECT state FROM {CAMPAIGN_TABLE} WHERE tradeplan_id=$1) campaign,
                (SELECT status FROM {OUTBOX_TABLE} WHERE tradeplan_id=$1) outbox""",
            seeded.candidate.tradeplan_id,
        )
        assert states is not None
        assert tuple(states) == ("ACTIVE", "RESERVED", "PARENT_PENDING", "PENDING")


async def test_exact_retry_with_provenance_drift_is_quarantined_without_mutation(
    postgres: PoolBackedPostgres,
) -> None:
    async with _seeded(postgres) as seeded:
        repository = _repository(postgres)
        approved = await repository.process_evidence(seeded.evidence)
        assert approved.status == "APPROVED" and approved.authority_bundle is not None
        forged = seeded.evidence.model_copy(
            update={
                "source_deployment_id": "p7-forged-deployment",
                "source_replica_id": "p7-forged-replica",
            }
        )

        result = await repository.process_evidence(forged)

        assert (result.status, result.reason_code) == (
            "QUARANTINED",
            "C2_REQUEST_EVIDENCE_DRIFT",
        )
        assert await repository.load_authority(seeded.candidate.tradeplan_id) == approved.authority_bundle
        assert len(await repository.load_evaluations(seeded.candidate.tradeplan_id)) == 1
        assert await _p7_counts(postgres, seeded.candidate.tradeplan_id) == {table: 1 for table in _P7_TABLES}


async def test_terminal_parent_wins_over_forged_missing_snapshot_retry(
    postgres: PoolBackedPostgres,
) -> None:
    async with _seeded(postgres) as seeded:
        repository = _repository(postgres)
        opened = await repository.process_evidence(seeded.evidence)
        assert opened.status == "APPROVED" and opened.authority_bundle is not None
        terminal_at = seeded.evidence.decision_at_utc + timedelta(seconds=1)
        await postgres.execute(
            f"""UPDATE {CANDIDATE_TABLE} SET lifecycle_state='INVALIDATED',invalidated_at=$2,
                       state_version=state_version+1,updated_at=$2 WHERE tradeplan_id=$1""",
            seeded.candidate.tradeplan_id,
            terminal_at,
        )
        forged_snapshot = seeded.evidence.account_snapshot.model_copy(
            update={"snapshot_id": f"p7-missing-snapshot-{uuid4().hex}"}
        )
        forged = seeded.evidence.model_copy(
            update={
                "source_request_id": "p7-terminal-parent-missing-snapshot",
                "decision_at_utc": terminal_at,
                "expires_at_utc": terminal_at + timedelta(seconds=60),
                "account_snapshot": forged_snapshot,
                "account_snapshot_hash": account_snapshot_authority_hash_v2(forged_snapshot),
            }
        )
        before_evaluations = len(await repository.load_evaluations(seeded.candidate.tradeplan_id))

        result = await repository.process_evidence(forged)

        assert (result.status, result.reason_code, result.authority_bundle) == (
            "INVALIDATED",
            "C2_PARENT_AUTHORITY_TERMINAL",
            None,
        )
        assert await repository.load_authority(seeded.candidate.tradeplan_id) is None
        assert len(await repository.load_evaluations(seeded.candidate.tradeplan_id)) == before_evaluations
        states = await postgres.fetchrow(
            f"""SELECT
                (SELECT state FROM {RISK_LOCK_TABLE} WHERE tradeplan_id=$1) risk_lock,
                (SELECT state FROM {RESERVATION_TABLE} WHERE tradeplan_id=$1) reservation,
                (SELECT state FROM {CAMPAIGN_TABLE} WHERE tradeplan_id=$1) campaign,
                (SELECT status FROM {OUTBOX_TABLE} WHERE tradeplan_id=$1) outbox""",
            seeded.candidate.tradeplan_id,
        )
        assert states is not None
        assert tuple(states) == ("CLOSED", "INVALIDATED", "INVALIDATED", "CANCELLED")


async def test_backdated_parent_terminal_clock_is_floored_at_authority_formation(
    postgres: PoolBackedPostgres,
) -> None:
    async with _seeded(postgres) as seeded:
        repository = _repository(postgres)
        opened = await repository.process_evidence(seeded.evidence)
        assert opened.status == "APPROVED" and opened.authority_bundle is not None
        reserved_at = opened.authority_bundle.reservation.reserved_at_utc
        backdated_at = seeded.candidate.decision_at_utc
        assert backdated_at < reserved_at
        await postgres.execute(
            f"""UPDATE {CANDIDATE_TABLE} SET lifecycle_state='INVALIDATED',invalidated_at=$2,
                       state_version=state_version+1,updated_at=$2 WHERE tradeplan_id=$1""",
            seeded.candidate.tradeplan_id,
            backdated_at,
        )

        result = await repository.process_evidence(seeded.evidence)

        assert (result.status, result.reason_code) == (
            "INVALIDATED",
            "C2_PARENT_AUTHORITY_TERMINAL",
        )
        clocks = await postgres.fetchrow(
            f"""SELECT
                (SELECT closed_at FROM {RISK_LOCK_TABLE} WHERE tradeplan_id=$1) risk_lock,
                (SELECT terminal_at FROM {RESERVATION_TABLE} WHERE tradeplan_id=$1) reservation,
                (SELECT terminal_at FROM {CAMPAIGN_TABLE} WHERE tradeplan_id=$1) campaign,
                (SELECT terminal_at FROM {OUTBOX_TABLE} WHERE tradeplan_id=$1) outbox""",
            seeded.candidate.tradeplan_id,
        )
        assert clocks is not None
        assert set(clocks.values()) == {reserved_at}


async def test_adverse_future_snapshot_uses_protected_db_clock_for_terminalization(
    postgres: PoolBackedPostgres,
) -> None:
    async with _seeded(postgres) as seeded:
        repository = _repository(postgres)
        opened = await repository.process_evidence(seeded.evidence)
        assert opened.status == "APPROVED" and opened.authority_bundle is not None
        database_now = _P7_DECISION + timedelta(seconds=2)
        future_at = _P7_DECISION + timedelta(days=365)
        future_snapshot = seeded.evidence.account_snapshot.model_copy(
            update={
                "snapshot_id": f"p7-future-adverse-{seeded.executor_id.hex}",
                "captured_at_utc": future_at,
                "broker_ledger_reconciled": False,
            }
        )
        await _insert_snapshot_row(postgres, future_snapshot)
        retry = seeded.evidence.model_copy(update={"source_request_id": "p7-adverse-future-snapshot"})

        result = await _repository(postgres, now=database_now).process_evidence(retry)

        assert (result.status, result.reason_code) == (
            "INVALIDATED",
            "C2_BROKER_RECONCILIATION_REQUIRED",
        )
        clocks = await postgres.fetchrow(
            f"""SELECT
                (SELECT closed_at FROM {RISK_LOCK_TABLE} WHERE tradeplan_id=$1) risk_lock,
                (SELECT terminal_at FROM {RESERVATION_TABLE} WHERE tradeplan_id=$1) reservation,
                (SELECT terminal_at FROM {CAMPAIGN_TABLE} WHERE tradeplan_id=$1) campaign,
                (SELECT terminal_at FROM {OUTBOX_TABLE} WHERE tradeplan_id=$1) outbox""",
            seeded.candidate.tradeplan_id,
        )
        assert clocks is not None
        assert len(set(clocks.values())) == 1
        assert all(
            opened.authority_bundle.reservation.reserved_at_utc <= clock <= database_now for clock in clocks.values()
        )
        assert all(clock < future_at for clock in clocks.values())


async def test_late_evaluation_failure_rolls_back_all_authority_rows(
    postgres: PoolBackedPostgres,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _seeded(postgres) as seeded:
        repository = _repository(postgres)

        async def fail_late(*_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("forced P7 evaluation failure")

        monkeypatch.setattr(repository, "_insert_evaluation", fail_late)
        with pytest.raises(RuntimeError, match="forced P7 evaluation failure"):
            await repository.process_evidence(seeded.evidence)
        assert await _p7_counts(postgres, seeded.candidate.tradeplan_id) == {table: 0 for table in _P7_TABLES}


async def test_terminal_candidate_closes_bundle_before_malformed_incoming_scope(
    postgres: PoolBackedPostgres,
) -> None:
    async with _seeded(postgres) as seeded:
        repository = _repository(postgres)
        opened = await repository.process_evidence(seeded.evidence)
        assert opened.status == "APPROVED" and opened.authority_bundle is not None
        terminal_at = seeded.evidence.decision_at_utc + timedelta(seconds=1)
        await postgres.execute(
            f"""UPDATE {CANDIDATE_TABLE} SET lifecycle_state='INVALIDATED',invalidated_at=$2,
                       state_version=state_version+1,updated_at=now()
                WHERE tradeplan_id=$1 AND lifecycle_state='ACTIVE'""",
            seeded.candidate.tradeplan_id,
            terminal_at,
        )
        malformed_candidate = seeded.candidate.model_copy(
            update={
                "context_epoch_id": "5scr-context:" + "f" * 32,
                "strategy_thesis_id": "5scr-thesis:" + "f" * 32,
                "execution_box_id": "5scr-execution-box:" + "f" * 32,
            }
        )
        malformed = seeded.evidence.model_copy(
            update={
                "source_request_id": "p7-terminal-malformed",
                "decision_at_utc": terminal_at,
                "expires_at_utc": terminal_at + timedelta(seconds=60),
                "candidate": malformed_candidate,
            }
        )
        closed = await repository.process_evidence(malformed)
        assert (closed.status, closed.reason_code) == ("INVALIDATED", "C2_PARENT_AUTHORITY_TERMINAL")
        states = {
            RISK_LOCK_TABLE: ("state", "CLOSED"),
            RESERVATION_TABLE: ("state", "INVALIDATED"),
            CAMPAIGN_TABLE: ("state", "INVALIDATED"),
            OUTBOX_TABLE: ("status", "CANCELLED"),
        }
        for table, (column, expected) in states.items():
            row = await postgres.fetchrow(
                f"SELECT {column},state_version FROM {table} WHERE tradeplan_id=$1",
                seeded.candidate.tradeplan_id,
            )
            assert row is not None and row[column] == expected and int(row["state_version"]) == 2
        replay = await _repository(postgres).process_evidence(malformed)
        assert (replay.status, replay.reason_code) == ("INVALIDATED", "C2_PARENT_AUTHORITY_TERMINAL")
        assert len(await repository.load_evaluations(seeded.candidate.tradeplan_id)) == 1


async def test_p7_cannot_commit_reservation_or_escalate_command_authority(
    postgres: PoolBackedPostgres,
) -> None:
    async with _seeded(postgres) as seeded:
        approved = await _repository(postgres).process_evidence(seeded.evidence)
        assert approved.status == "APPROVED"
        with pytest.raises(postgres.check_violation_error):
            await postgres.execute(
                f"""UPDATE {RESERVATION_TABLE} SET state='COMMITTED',terminal_at=$2,
                           terminal_reason='FORBIDDEN_P7_COMMIT',state_version=state_version+1
                    WHERE tradeplan_id=$1""",
                seeded.candidate.tradeplan_id,
                seeded.evidence.decision_at_utc + timedelta(seconds=1),
            )
        with pytest.raises(postgres.check_violation_error):
            await postgres.execute(
                f"UPDATE {RESERVATION_TABLE} SET command_authority=true WHERE tradeplan_id=$1",
                seeded.candidate.tradeplan_id,
            )
        with pytest.raises(postgres.check_violation_error):
            await postgres.execute(
                f"UPDATE {OUTBOX_TABLE} SET delivery_authority=true WHERE tradeplan_id=$1",
                seeded.candidate.tradeplan_id,
            )


async def test_postgres_rejects_coherent_noncanonical_risk_policy_amounts(
    postgres: PoolBackedPostgres,
) -> None:
    async with _seeded(postgres) as seeded:
        approved = await _repository(postgres).process_evidence(seeded.evidence)
        assert approved.status == "APPROVED" and approved.authority_bundle is not None
        async with postgres.transaction() as connection:
            await connection.execute("SET LOCAL session_replication_role = replica")
            savepoint = connection.transaction()
            await savepoint.start()
            try:
                with pytest.raises(postgres.check_violation_error) as raised:
                    await connection.execute(
                        f"""UPDATE {RISK_LOCK_TABLE}
                            SET risk_percent_per_entry=0.04,
                                risk_unit_usd=balance_base*0.04,
                                max_campaign_risk_usd=balance_base*0.08
                            WHERE tradeplan_id=$1""",
                        seeded.candidate.tradeplan_id,
                    )
                assert getattr(raised.value, "constraint_name", None) == "ck_5scr_campaign_risk_lock_v2_amounts"
            finally:
                await savepoint.rollback()


async def test_outbox_payload_check_rejects_missing_required_string_keys(
    postgres: PoolBackedPostgres,
) -> None:
    async with _seeded(postgres) as seeded:
        approved = await _repository(postgres).process_evidence(seeded.evidence)
        assert approved.status == "APPROVED" and approved.authority_bundle is not None
        trigger = f"trg_5scr_guard_{OUTBOX_TABLE}_transition"
        await postgres.execute(f"ALTER TABLE {OUTBOX_TABLE} DISABLE TRIGGER {trigger}")
        try:
            for missing_key in ("event", "execution_mode", "next_required_stage"):
                with pytest.raises(postgres.check_violation_error):
                    await postgres.execute(
                        f"UPDATE {OUTBOX_TABLE} SET payload=payload-$2::text WHERE tradeplan_id=$1",
                        seeded.candidate.tradeplan_id,
                        missing_key,
                    )
            payload_row = await postgres.fetchrow(
                f"SELECT payload FROM {OUTBOX_TABLE} WHERE tradeplan_id=$1",
                seeded.candidate.tradeplan_id,
            )
            assert payload_row is not None
            assert all(key in payload_row["payload"] for key in ("event", "execution_mode", "next_required_stage"))
        finally:
            await postgres.execute(f"ALTER TABLE {OUTBOX_TABLE} ENABLE TRIGGER {trigger}")


async def test_durable_authority_crossmix_is_rejected_on_load_and_replay(
    postgres: PoolBackedPostgres,
) -> None:
    async with _seeded(postgres) as seeded:
        repository = _repository(postgres)
        approved = await repository.process_evidence(seeded.evidence)
        assert approved.status == "APPROVED"
        await postgres.execute(f"ALTER TABLE {RESERVATION_TABLE} DISABLE TRIGGER USER")
        try:
            await postgres.execute(
                f"UPDATE {RESERVATION_TABLE} SET symbol_capability_hash=$2 WHERE tradeplan_id=$1",
                seeded.candidate.tradeplan_id,
                "sha256:" + "f" * 64,
            )
            with pytest.raises(CandidateC2ShadowV2IntegrityError, match="C2_DURABLE_DRIFT"):
                await repository.load_authority(seeded.candidate.tradeplan_id)
            with pytest.raises(CandidateC2ShadowV2IntegrityError, match="C2_DURABLE_DRIFT"):
                await repository.process_evidence(seeded.evidence)
        finally:
            await postgres.execute(f"ALTER TABLE {RESERVATION_TABLE} ENABLE TRIGGER USER")


@pytest.mark.parametrize("field", ["outbox_id", "created_at"])
async def test_durable_outbox_identity_and_clock_corruption_fail_closed(
    postgres: PoolBackedPostgres,
    field: Literal["outbox_id", "created_at"],
) -> None:
    async with _seeded(postgres) as seeded:
        repository = _repository(postgres)
        approved = await repository.process_evidence(seeded.evidence)
        assert approved.status == "APPROVED" and approved.authority_bundle is not None
        async with postgres.transaction() as connection:
            await connection.execute("SET LOCAL session_replication_role = replica")
            if field == "outbox_id":
                value: object = f"5scr-c2-outbox-v2:{uuid4().hex}"
            else:
                value = approved.authority_bundle.final_signal.issued_at_utc + timedelta(seconds=1)
            await connection.execute(
                f"UPDATE {OUTBOX_TABLE} SET {field}=$2 WHERE tradeplan_id=$1",
                seeded.candidate.tradeplan_id,
                value,
            )

        with pytest.raises(
            CandidateC2ShadowV2IntegrityError,
            match=rf"C2_DURABLE_DRIFT:{OUTBOX_TABLE}\.{field}",
        ):
            await repository.load_authority(seeded.candidate.tradeplan_id)


async def test_durable_handoff_candidate_scope_corruption_fails_closed(
    postgres: PoolBackedPostgres,
) -> None:
    async with _seeded(postgres) as seeded:
        approved = await _repository(postgres).process_evidence(seeded.evidence)
        assert approved.status == "APPROVED"
        async with postgres.transaction() as connection:
            savepoint = connection.transaction()
            await savepoint.start()
            try:
                await connection.execute("SET LOCAL session_replication_role = replica")
                await connection.execute(
                    f"UPDATE {HANDOFF_TABLE} SET strategy_lifecycle_id=$2 WHERE tradeplan_id=$1",
                    seeded.candidate.tradeplan_id,
                    f"forged-lifecycle:{uuid4().hex}",
                )
                local = _FixedClockRepository(cast(Any, _SingleConnectionPostgres(connection)))
                with pytest.raises(
                    CandidateC2ShadowV2IntegrityError,
                    match=rf"C2_DURABLE_DRIFT:{HANDOFF_TABLE}\.strategy_lifecycle_id",
                ):
                    await local.load_authority(seeded.candidate.tradeplan_id)
            finally:
                await savepoint.rollback()


async def test_durable_campaign_execution_mode_corruption_fails_closed(
    postgres: PoolBackedPostgres,
) -> None:
    async with _seeded(postgres) as seeded:
        approved = await _repository(postgres).process_evidence(seeded.evidence)
        assert approved.status == "APPROVED"
        async with postgres.transaction() as connection:
            savepoint = connection.transaction()
            await savepoint.start()
            try:
                await connection.execute("SET LOCAL session_replication_role = replica")
                await connection.execute(
                    f"ALTER TABLE {CAMPAIGN_TABLE} DROP CONSTRAINT ck_5scr_execution_campaign_v2_state"
                )
                await connection.execute(
                    f"UPDATE {CAMPAIGN_TABLE} SET execution_mode='DEMO' WHERE tradeplan_id=$1",
                    seeded.candidate.tradeplan_id,
                )
                local = _FixedClockRepository(cast(Any, _SingleConnectionPostgres(connection)))
                with pytest.raises(
                    CandidateC2ShadowV2IntegrityError,
                    match=rf"C2_DURABLE_DRIFT:{CAMPAIGN_TABLE}\.execution_mode",
                ):
                    await local.load_authority(seeded.candidate.tradeplan_id)
            finally:
                await savepoint.rollback()


async def test_durable_evaluation_candidate_scope_corruption_fails_closed(
    postgres: PoolBackedPostgres,
) -> None:
    async with _seeded(postgres) as seeded:
        approved = await _repository(postgres).process_evidence(seeded.evidence)
        assert approved.status == "APPROVED"
        async with postgres.transaction() as connection:
            savepoint = connection.transaction()
            await savepoint.start()
            try:
                await connection.execute("SET LOCAL session_replication_role = replica")
                await connection.execute(
                    f"UPDATE {EVALUATION_TABLE} SET strategy_lifecycle_id=$2 WHERE tradeplan_id=$1",
                    seeded.candidate.tradeplan_id,
                    f"forged-lifecycle:{uuid4().hex}",
                )
                local = _FixedClockRepository(cast(Any, _SingleConnectionPostgres(connection)))
                with pytest.raises(
                    CandidateC2ShadowV2IntegrityError,
                    match="C2_EVALUATION_DURABLE_DRIFT:strategy_lifecycle_id",
                ):
                    await local.load_evaluations(seeded.candidate.tradeplan_id)
            finally:
                await savepoint.rollback()


async def test_durable_snapshot_nullable_column_corruption_fails_closed(
    postgres: PoolBackedPostgres,
) -> None:
    async with _seeded(postgres) as seeded:
        approved = await _repository(postgres).process_evidence(seeded.evidence)
        assert approved.status == "APPROVED"
        async with postgres.transaction() as connection:
            savepoint = connection.transaction()
            await savepoint.start()
            try:
                await connection.execute("SET LOCAL session_replication_role = replica")
                await connection.execute(
                    "UPDATE executor_account_snapshots SET margin_level_pct=123.45 WHERE snapshot_id=$1",
                    seeded.evidence.account_snapshot.snapshot_id,
                )
                local = _FixedClockRepository(cast(Any, _SingleConnectionPostgres(connection)))
                with pytest.raises(
                    CandidateC2ShadowV2IntegrityError,
                    match="C2_ACCOUNT_SNAPSHOT_COLUMN_DRIFT:margin_level_pct",
                ):
                    await local.load_authority(seeded.candidate.tradeplan_id)
            finally:
                await savepoint.rollback()


async def test_full_p3_p4_p5_parent_corruption_rejects_before_reservation(
    postgres: PoolBackedPostgres,
) -> None:
    async with _seeded(postgres) as seeded:
        repository = _repository(postgres)
        thesis_row = await postgres.fetchrow(
            "SELECT h1_proof_id FROM strategy_5scr_directional_theses_v1 WHERE strategy_thesis_id=$1",
            seeded.candidate.strategy_thesis_id,
        )
        assert thesis_row is not None
        cases = (
            (
                "strategy_5scr_context_epochs_v1",
                "context_epoch_id",
                seeded.candidate.context_epoch_id,
                "evidence_payload",
                "daily_bias",
                None,
            ),
            (
                "strategy_5scr_h1_structure_proofs_v1",
                "h1_proof_id",
                str(thesis_row["h1_proof_id"]),
                "evidence_payload",
                "reference_level",
                "trg_strategy_5scr_h1_structure_proofs_v1_immutable",
            ),
            (
                "strategy_5scr_execution_boxes_v1",
                "execution_box_id",
                seeded.candidate.execution_box_id,
                "freeze_evidence_payload",
                "freeze_authority_hash",
                "trg_strategy_5scr_execution_boxes_v1_guard",
            ),
        )
        for table, id_column, identity, payload_column, payload_key, trigger in cases:
            row = await postgres.fetchrow(
                f"SELECT {payload_column} original FROM {table} WHERE {id_column}=$1",
                identity,
            )
            assert row is not None
            if trigger is not None:
                await postgres.execute(f"ALTER TABLE {table} DISABLE TRIGGER {trigger}")
            try:
                forged = '"FORGED"' if payload_key == "daily_bias" else '"sha256:' + "f" * 64 + '"'
                await postgres.execute(
                    f"UPDATE {table} SET {payload_column}=jsonb_set({payload_column},$2::text[],$3::jsonb) "
                    f"WHERE {id_column}=$1",
                    identity,
                    [payload_key],
                    forged,
                )
                with pytest.raises(CandidateC2ShadowV2IntegrityError, match="C2_PARENT_.*DRIFT"):
                    await repository.process_evidence(seeded.evidence)
                assert await _p7_counts(postgres, seeded.candidate.tradeplan_id) == {item: 0 for item in _P7_TABLES}
            finally:
                await postgres.execute(
                    f"UPDATE {table} SET {payload_column}=$2::jsonb WHERE {id_column}=$1",
                    identity,
                    json.dumps(row["original"]) if not isinstance(row["original"], str) else row["original"],
                )
                if trigger is not None:
                    await postgres.execute(f"ALTER TABLE {table} ENABLE TRIGGER {trigger}")


async def test_box_v3_rejects_coherently_invalidated_v1_predecessor(
    postgres: PoolBackedPostgres,
) -> None:
    context = await _seed_box_v3(postgres)
    seeded = context.seeded
    trigger = "trg_strategy_5scr_execution_boxes_v1_guard"
    try:
        row = await postgres.fetchrow(
            f"SELECT payload,superseded_at FROM {P5_BOX_TABLE} WHERE execution_box_id=$1",
            context.predecessor_v1_id,
        )
        assert row is not None and row["superseded_at"] is not None
        original_payload = row["payload"]
        payload = dict(original_payload) if not isinstance(original_payload, str) else json.loads(original_payload)
        payload.update(
            {
                "state": "INVALIDATED",
                "superseded_at_utc": None,
                "invalidated_at_utc": row["superseded_at"].isoformat(),
            }
        )
        await postgres.execute(f"ALTER TABLE {P5_BOX_TABLE} DISABLE TRIGGER {trigger}")
        try:
            await postgres.execute(
                f"""UPDATE {P5_BOX_TABLE}
                    SET state='INVALIDATED',superseded_at=NULL,invalidated_at=$2,payload=$3::jsonb
                    WHERE execution_box_id=$1""",
                context.predecessor_v1_id,
                row["superseded_at"],
                json.dumps(payload, sort_keys=True, separators=(",", ":")),
            )
            with pytest.raises(
                CandidateC2ShadowV2IntegrityError,
                match="C2_PARENT_BOX_PREDECESSOR_SCOPE_DRIFT",
            ):
                await _repository(postgres).process_evidence(seeded.evidence)
            assert await _p7_counts(postgres, seeded.candidate.tradeplan_id) == {table: 0 for table in _P7_TABLES}
        finally:
            await postgres.execute(f"ALTER TABLE {P5_BOX_TABLE} ENABLE TRIGGER {trigger}")
    finally:
        # P6 cleanup removes the full P5 chain, including the deliberately
        # corrupted predecessor, under its disposable-test trigger discipline.
        await _cleanup_p7(postgres, seeded)


async def test_snapshot_table_fence_prevents_latest_snapshot_phantom(
    postgres: PoolBackedPostgres,
) -> None:
    async with _seeded(postgres) as seeded:
        barrier = _SnapshotFencePostgres(postgres)
        repository = _FixedClockRepository(cast(Any, barrier))
        pending = asyncio.create_task(repository.process_evidence(seeded.evidence))
        await asyncio.wait_for(barrier.reached.wait(), timeout=5)
        newer = _snapshot(
            seeded.candidate,
            seeded.executor_id,
            seeded.account_id,
            captured_at=_P7_DECISION + timedelta(seconds=1),
        ).model_copy(update={"snapshot_id": f"p7-snapshot-newer-{seeded.executor_id.hex}"})
        writer = asyncio.create_task(_insert_snapshot_row(postgres, newer))
        try:
            await asyncio.sleep(0.1)
            assert not writer.done(), "snapshot INSERT crossed the repository's SHARE fence"
        finally:
            barrier.release.set()
        first = await asyncio.wait_for(pending, timeout=10)
        assert first.status == "APPROVED"
        await asyncio.wait_for(writer, timeout=10)

        later_at = _P7_DECISION + timedelta(seconds=2)
        stale = seeded.evidence.model_copy(
            update={
                "source_request_id": "p7-stale-snapshot-after-fence",
                "decision_at_utc": later_at,
                "expires_at_utc": later_at + timedelta(seconds=60),
                "governance": _governance(
                    seeded.executor_id,
                    seeded.account_id,
                    kill_switch_active=False,
                    verified_at=later_at,
                ),
                "existing_risk": c2_shadow_existing_risk_evidence_v2(
                    account_id=seeded.account_id,
                    tradeplan_id=seeded.candidate.tradeplan_id,
                    captured_at_utc=later_at,
                ),
            }
        )
        changed = await _repository(postgres).process_evidence(stale)
        assert (changed.status, changed.reason_code) == (
            "QUARANTINED",
            "C2_ACCOUNT_SNAPSHOT_CHANGED_DURING_READ",
        )
        assert await _p7_counts(postgres, seeded.candidate.tradeplan_id) == {table: 1 for table in _P7_TABLES}


async def test_command_insert_cannot_cross_risk_snapshot_and_remain_live(
    postgres: PoolBackedPostgres,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _seeded(postgres) as seeded:
        monkeypatch.setenv("EXECUTOR_COMMAND_SIGNING_SECRET", _COMMAND_SIGNING_SECRET)
        monkeypatch.setenv("EXECUTOR_COMMAND_SIGNING_KEY_ID", _COMMAND_SIGNING_KEY_ID)
        command = _pending_command(seeded)
        barrier = _DerivedRiskFencePostgres(postgres)
        repository = _FixedClockRepository(cast(Any, barrier))
        process = asyncio.create_task(repository.process_evidence(seeded.evidence))
        writer: asyncio.Task[ExecutionCommandV1] | None = None
        try:
            await asyncio.wait_for(barrier.reached.wait(), timeout=5)
            writer = asyncio.create_task(MT5CommandRepository(pg=cast(Any, postgres)).enqueue_command(command))
            waiting = False
            for _ in range(50):
                row = await postgres.fetchrow(
                    """SELECT EXISTS (
                           SELECT 1 FROM pg_locks
                           WHERE relation='execution_commands'::regclass
                             AND mode='RowExclusiveLock' AND NOT granted
                       ) AS waiting"""
                )
                waiting = bool(row and row["waiting"])
                if waiting or writer.done():
                    break
                await asyncio.sleep(0.05)
            assert not writer.done(), "execution command INSERT crossed P7's derived-risk fence"
            assert waiting, "command writer never reached the execution_commands table lock"
            barrier.release.set()
            approved = await asyncio.wait_for(process, timeout=10)
            assert approved.status == "APPROVED" and approved.authority_bundle is not None
            with pytest.raises(postgres.check_violation_error) as raised:
                await asyncio.wait_for(writer, timeout=10)
            assert getattr(raised.value, "constraint_name", None) == "ck_execution_command_no_live_c2_shadow_v2"
            command_count = await postgres.fetchrow(
                "SELECT count(*) AS n FROM execution_commands WHERE account_id=$1",
                seeded.account_id,
            )
            assert command_count is not None and int(command_count["n"]) == 0
            assert (
                await _repository(postgres).load_authority(seeded.candidate.tradeplan_id) == approved.authority_bundle
            )
            states = await postgres.fetchrow(
                f"""SELECT
                    (SELECT state FROM {RISK_LOCK_TABLE} WHERE tradeplan_id=$1) risk_lock,
                    (SELECT state FROM {RESERVATION_TABLE} WHERE tradeplan_id=$1) reservation,
                    (SELECT state FROM {CAMPAIGN_TABLE} WHERE tradeplan_id=$1) campaign,
                    (SELECT status FROM {OUTBOX_TABLE} WHERE tradeplan_id=$1) outbox""",
                seeded.candidate.tradeplan_id,
            )
            assert states is not None
            assert tuple(states) == (
                "ACTIVE",
                "RESERVED",
                "PARENT_PENDING",
                "PENDING",
            )
        finally:
            barrier.release.set()
            if not process.done():
                with suppress(Exception):
                    await asyncio.wait_for(process, timeout=10)
            if writer is not None and not writer.done():
                with suppress(Exception):
                    await asyncio.wait_for(writer, timeout=10)
            await postgres.execute(
                "DELETE FROM execution_commands WHERE command_id=$1::uuid",
                str(command.command_id),
            )


async def test_every_p7_foreign_key_has_a_valid_left_prefix_index(
    postgres: PoolBackedPostgres,
) -> None:
    rows = await postgres.fetch(
        """SELECT con.conname,child.relname table_name,
                  EXISTS (
                      SELECT 1 FROM pg_index idx
                      WHERE idx.indrelid=con.conrelid
                        AND idx.indisvalid AND idx.indisready
                        AND idx.indpred IS NULL
                        AND idx.indexprs IS NULL
                        AND (
                            (
                                idx.indnkeyatts >= cardinality(con.conkey)
                                AND NOT EXISTS (
                                    SELECT 1
                                    FROM unnest(con.conkey) WITH ORDINALITY AS key(attnum,ord)
                                    WHERE (string_to_array(idx.indkey::text,' ')::smallint[])
                                              [key.ord::integer] IS DISTINCT FROM key.attnum
                                )
                            )
                            OR (
                                idx.indisunique
                                AND idx.indnkeyatts BETWEEN 1 AND cardinality(con.conkey)
                                AND NOT EXISTS (
                                    SELECT 1
                                    FROM generate_series(1,idx.indnkeyatts::integer) AS key(ord)
                                    WHERE (string_to_array(idx.indkey::text,' ')::smallint[])[key.ord]
                                          IS DISTINCT FROM con.conkey[key.ord]
                                )
                            )
                        )
                  ) covered
           FROM pg_constraint con
           JOIN pg_class child ON child.oid=con.conrelid
           JOIN pg_namespace ns ON ns.oid=child.relnamespace
           WHERE ns.nspname=current_schema() AND con.contype='f'
             AND child.relname=ANY($1::text[])
           ORDER BY con.conname""",
        list(_P7_TABLES),
    )
    expected = {name for name, table in _CONSTRAINT_TABLES.items() if name.startswith("fk_") and table in _P7_TABLES}
    assert {str(row["conname"]) for row in rows} == expected
    assert all(bool(row["covered"]) for row in rows), [
        (row["conname"], row["table_name"]) for row in rows if not row["covered"]
    ]


async def test_readiness_fails_on_weakened_constraint_index_trigger_and_parent(
    postgres: PoolBackedPostgres,
) -> None:
    repository = _repository(postgres)
    assert (await repository.schema_status()).ready is True

    async with postgres.transaction() as connection:
        savepoint = connection.transaction()
        await savepoint.start()
        try:
            await connection.execute(
                "ALTER TABLE execution_commands ALTER COLUMN terminal_at TYPE timestamp(0) with time zone"
            )
            altered = await Strategy5SCRCandidateC2ShadowV2Repository(
                cast(Any, _SingleConnectionPostgres(connection))
            ).schema_status()
            assert "execution_commands.terminal_at" in altered.invalid_columns
        finally:
            await savepoint.rollback()
    assert (await repository.schema_status()).ready is True

    constraint = "ck_5scr_risk_reservation_v2_authority"
    definition_row = await postgres.fetchrow(
        "SELECT pg_get_constraintdef(oid) definition FROM pg_constraint WHERE conname=$1",
        constraint,
    )
    assert definition_row is not None
    definition = str(definition_row["definition"])
    await postgres.execute(f"ALTER TABLE {RESERVATION_TABLE} DROP CONSTRAINT {constraint}")
    try:
        await postgres.execute(f"ALTER TABLE {RESERVATION_TABLE} ADD CONSTRAINT {constraint} CHECK (true)")
        assert constraint in (await repository.schema_status()).invalid_constraints
    finally:
        await postgres.execute(f"ALTER TABLE {RESERVATION_TABLE} DROP CONSTRAINT {constraint}")
        await postgres.execute(f"ALTER TABLE {RESERVATION_TABLE} ADD CONSTRAINT {constraint} {definition}")

    index = "ix_5scr_final_signal_outbox_v2_status"
    index_row = await postgres.fetchrow(
        "SELECT pg_get_indexdef(indexrelid) definition FROM pg_index WHERE indexrelid=$1::regclass",
        index,
    )
    assert index_row is not None
    index_definition = str(index_row["definition"])
    await postgres.execute(f"DROP INDEX {index}")
    try:
        await postgres.execute(f"CREATE INDEX {index} ON {OUTBOX_TABLE}(tradeplan_id)")
        assert index in (await repository.schema_status()).invalid_indexes
    finally:
        await postgres.execute(f"DROP INDEX {index}")
        await postgres.execute(index_definition)

    trigger = f"trg_5scr_guard_{OUTBOX_TABLE}_transition"
    await postgres.execute(f"ALTER TABLE {OUTBOX_TABLE} DISABLE TRIGGER {trigger}")
    try:
        assert trigger in (await repository.schema_status()).invalid_triggers
    finally:
        await postgres.execute(f"ALTER TABLE {OUTBOX_TABLE} ENABLE TRIGGER {trigger}")

    parent_trigger = "trg_strategy_5scr_execution_boxes_v1_guard"
    await postgres.execute(f"ALTER TABLE strategy_5scr_execution_boxes_v1 DISABLE TRIGGER {parent_trigger}")
    try:
        parent_drift = await repository.schema_status()
        assert parent_drift.ready is False
        assert any(parent_trigger in item for item in parent_drift.invalid_triggers)
    finally:
        await postgres.execute(f"ALTER TABLE strategy_5scr_execution_boxes_v1 ENABLE TRIGGER {parent_trigger}")


@pytest.mark.parametrize(
    ("table", "trigger"),
    [
        ("execution_commands", "trg_5scr_guard_execution_command_against_c2_v2"),
        ("executor_instances", "trg_5scr_guard_executor_identity_against_c2_v2"),
        (
            "strategy_5scr_campaign_risk_locks",
            "trg_5scr_guard_legacy_campaign_risk_against_c2_v2",
        ),
        (
            "strategy_5scr_risk_reservations",
            "trg_5scr_guard_legacy_reservation_against_c2_v2",
        ),
        (
            "strategy_5scr_campaign_risk_locks",
            "trg_5scr_campaign_risk_lock_update_v1",
        ),
        (
            "strategy_5scr_risk_reservations",
            "trg_5scr_risk_reservation_update_v1",
        ),
    ],
)
async def test_readiness_requires_cross_authority_and_legacy_lifecycle_triggers(
    postgres: PoolBackedPostgres,
    table: str,
    trigger: str,
) -> None:
    repository = _repository(postgres)
    assert (await repository.schema_status()).ready is True
    await postgres.execute(f"ALTER TABLE {table} DISABLE TRIGGER {trigger}")
    try:
        status = await repository.schema_status()
        assert status.ready is False
        assert trigger in status.invalid_triggers
    finally:
        await postgres.execute(f"ALTER TABLE {table} ENABLE TRIGGER {trigger}")
    assert (await repository.schema_status()).ready is True


@pytest.mark.parametrize(
    "constraint",
    ["executor_bridge_governance_pkey", "ck_executor_governance_singleton"],
)
async def test_readiness_requires_governance_cardinality_constraints(
    postgres: PoolBackedPostgres,
    constraint: str,
) -> None:
    async with postgres.transaction() as connection:
        savepoint = connection.transaction()
        await savepoint.start()
        try:
            await connection.execute(f"ALTER TABLE executor_bridge_governance DROP CONSTRAINT {constraint}")
            status = await Strategy5SCRCandidateC2ShadowV2Repository(
                cast(Any, _SingleConnectionPostgres(connection))
            ).schema_status()
            assert status.ready is False
            assert constraint in status.missing_constraints
        finally:
            await savepoint.rollback()


async def test_readiness_fingerprints_preserve_quoted_literal_case(
    postgres: PoolBackedPostgres,
) -> None:
    trigger = "trg_5scr_guard_legacy_campaign_risk_against_c2_v2"
    function = "strategy_5scr_guard_legacy_campaign_risk_against_c2_v2"
    async with postgres.transaction() as connection:
        savepoint = connection.transaction()
        await savepoint.start()
        try:
            definition = await connection.fetchval(
                "SELECT pg_get_functiondef($1::regproc)",
                function,
            )
            assert isinstance(definition, str)
            weakened = definition.replace("'ACTIVE'", "'active'", 1)
            assert weakened != definition
            await connection.execute(weakened)
            status = await Strategy5SCRCandidateC2ShadowV2Repository(
                cast(Any, _SingleConnectionPostgres(connection))
            ).schema_status()
            assert status.ready is False
            assert trigger in status.invalid_triggers
        finally:
            await savepoint.rollback()


async def test_readiness_fingerprints_preserve_line_comment_boundaries(
    postgres: PoolBackedPostgres,
) -> None:
    trigger = "trg_5scr_guard_execution_command_against_c2_v2"
    function = "strategy_5scr_guard_execution_command_against_c2_v2"
    async with postgres.transaction() as connection:
        savepoint = connection.transaction()
        await savepoint.start()
        try:
            definition = await connection.fetchval(
                "SELECT pg_get_functiondef($1::regproc)",
                function,
            )
            assert isinstance(definition, str)
            boundary = (
                "-- Binding fields are command identity, not lifecycle metadata.\n"
                "                -- Terminal cleanup may advance state/report fields only."
            )
            weakened = definition.replace(
                boundary,
                boundary.replace("\n", ""),
                1,
            )
            assert weakened != definition
            await connection.execute(weakened)
            status = await Strategy5SCRCandidateC2ShadowV2Repository(
                cast(Any, _SingleConnectionPostgres(connection))
            ).schema_status()
            assert status.ready is False
            assert trigger in status.invalid_triggers
        finally:
            await savepoint.rollback()


async def test_p6_guard_literal_case_drift_invalidates_p6_and_delegated_p7_readiness(
    postgres: PoolBackedPostgres,
) -> None:
    trigger = "trg_strategy_5scr_tradeplan_candidates_v2_guard"
    function = "strategy_5scr_guard_tradeplan_candidate_v2"
    async with postgres.transaction() as connection:
        savepoint = connection.transaction()
        await savepoint.start()
        try:
            definition = await connection.fetchval(
                "SELECT pg_get_functiondef($1::regproc)",
                function,
            )
            assert isinstance(definition, str)
            weakened = definition.replace("'ACTIVE'", "'active'", 1)
            assert weakened != definition
            await connection.execute(weakened)
            single = cast(Any, _SingleConnectionPostgres(connection))
            p6_status = await Strategy5SCRTradePlanCandidateV2Repository(single).schema_status()
            p7_status = await Strategy5SCRCandidateC2ShadowV2Repository(single).schema_status()
            assert p6_status.ready is False
            assert trigger in p6_status.invalid_triggers
            assert p7_status.ready is False
            assert f"p6:invalid:{trigger}" in p7_status.invalid_triggers
        finally:
            await savepoint.rollback()


@pytest.mark.parametrize(
    ("stage", "function", "literal"),
    [
        ("p4", "strategy_5scr_guard_thesis_update_v1", "ACTIVE"),
        ("p5", "strategy_5scr_guard_execution_box_v1", "FROZEN"),
    ],
)
async def test_upstream_guard_literal_case_drift_invalidates_delegated_chain_readiness(
    postgres: PoolBackedPostgres,
    stage: Literal["p4", "p5"],
    function: str,
    literal: str,
) -> None:
    async with postgres.transaction() as connection:
        savepoint = connection.transaction()
        await savepoint.start()
        try:
            definition = await connection.fetchval("SELECT pg_get_functiondef($1::regproc)", function)
            assert isinstance(definition, str)
            weakened = definition.replace(f"'{literal}'", f"'{literal.lower()}'", 1)
            assert weakened != definition
            await connection.execute(weakened)
            single = cast(Any, _SingleConnectionPostgres(connection))
            p4_status = await Strategy5SCRDirectionalThesisV1Repository(single).schema_status()
            p5_status = await Strategy5SCRExecutionBoxV1Repository(single).schema_status()
            p6_status = await Strategy5SCRTradePlanCandidateV2Repository(single).schema_status()
            p7_status = await Strategy5SCRCandidateC2ShadowV2Repository(single).schema_status()
            if stage == "p4":
                assert p4_status.ready is False
            else:
                assert p4_status.ready is True and p5_status.ready is False
            assert p6_status.ready is False
            assert p7_status.ready is False
        finally:
            await savepoint.rollback()


async def test_readiness_requires_permanent_authority_tables(
    postgres: PoolBackedPostgres,
) -> None:
    async with postgres.transaction() as connection:
        savepoint = connection.transaction()
        await savepoint.start()
        try:
            await connection.execute(f"ALTER TABLE {OUTBOX_TABLE} SET UNLOGGED")
            status = await Strategy5SCRCandidateC2ShadowV2Repository(
                cast(Any, _SingleConnectionPostgres(connection))
            ).schema_status()
            assert status.ready is False
            assert OUTBOX_TABLE in status.invalid_tables
        finally:
            await savepoint.rollback()


async def test_p6_evaluation_must_be_permanent_for_p6_and_delegated_p7_readiness(
    postgres: PoolBackedPostgres,
) -> None:
    p6_evaluation_table = "strategy_5scr_tradeplan_candidate_evaluations_v2"
    async with postgres.transaction() as connection:
        savepoint = connection.transaction()
        await savepoint.start()
        try:
            await connection.execute(f"ALTER TABLE {p6_evaluation_table} SET UNLOGGED")
            single = cast(Any, _SingleConnectionPostgres(connection))
            p6_status = await Strategy5SCRTradePlanCandidateV2Repository(single).schema_status()
            p7_status = await Strategy5SCRCandidateC2ShadowV2Repository(single).schema_status()
            assert p6_status.ready is False
            assert p6_evaluation_table in p6_status.invalid_tables
            assert p7_status.ready is False
            assert f"p6:{p6_evaluation_table}" in p7_status.invalid_tables
        finally:
            await savepoint.rollback()


async def test_forged_frozen_build_evidence_fails_load_and_exact_replay(
    postgres: PoolBackedPostgres,
) -> None:
    async with _seeded(postgres) as seeded:
        repository = _repository(postgres)
        approved = await repository.process_evidence(seeded.evidence)
        assert approved.status == "APPROVED"
        row = await postgres.fetchrow(
            f"SELECT build_evidence_payload FROM {EVALUATION_TABLE} WHERE tradeplan_id=$1",
            seeded.candidate.tradeplan_id,
        )
        assert row is not None
        await postgres.execute(f"ALTER TABLE {EVALUATION_TABLE} DISABLE TRIGGER USER")
        try:
            await postgres.execute(
                f"UPDATE {EVALUATION_TABLE} SET build_evidence_payload="
                "jsonb_set(build_evidence_payload,'{broker_symbol}','\"GBPUSD\"'::jsonb) "
                "WHERE tradeplan_id=$1",
                seeded.candidate.tradeplan_id,
            )
            with pytest.raises(CandidateC2ShadowV2IntegrityError, match="C2_.*EVIDENCE|C2_.*DRIFT"):
                await repository.load_evaluations(seeded.candidate.tradeplan_id)
            with pytest.raises(CandidateC2ShadowV2IntegrityError, match="C2_.*EVIDENCE|C2_.*DRIFT"):
                await repository.process_evidence(seeded.evidence)
        finally:
            await postgres.execute(
                f"UPDATE {EVALUATION_TABLE} SET build_evidence_payload=$2::jsonb WHERE tradeplan_id=$1",
                seeded.candidate.tradeplan_id,
                json.dumps(row["build_evidence_payload"])
                if not isinstance(row["build_evidence_payload"], str)
                else row["build_evidence_payload"],
            )
            await postgres.execute(f"ALTER TABLE {EVALUATION_TABLE} ENABLE TRIGGER USER")


async def test_snapshot_update_is_allowed_before_admission_but_frozen_after_handoff(
    postgres: PoolBackedPostgres,
) -> None:
    async with _seeded(postgres) as seeded:
        changed_snapshot = seeded.evidence.account_snapshot.model_copy(
            update={"balance": 1001.0, "equity": 1001.0, "free_margin": 1001.0}
        )
        await postgres.execute(
            """UPDATE executor_account_snapshots SET balance=$2,equity=$2,free_margin=$2,
                   payload=$3::jsonb WHERE snapshot_id=$1""",
            changed_snapshot.snapshot_id,
            changed_snapshot.balance,
            json.dumps(changed_snapshot.model_dump(mode="json"), sort_keys=True, separators=(",", ":")),
        )
        changed_evidence = seeded.evidence.model_copy(
            update={
                "account_snapshot": changed_snapshot,
                "account_snapshot_hash": account_snapshot_authority_hash_v2(changed_snapshot),
            }
        )
        approved = await _repository(postgres).process_evidence(changed_evidence)
        assert approved.status == "APPROVED"

        unbound = _snapshot(
            seeded.candidate,
            seeded.executor_id,
            seeded.account_id,
            captured_at=_P7_DECISION + timedelta(seconds=1),
        ).model_copy(update={"snapshot_id": f"p7-unbound-{seeded.executor_id.hex}"})
        await _insert_snapshot_row(postgres, unbound)
        changed_unbound = unbound.model_copy(update={"balance": 1003.0, "equity": 1003.0, "free_margin": 1003.0})
        await postgres.execute(
            """UPDATE executor_account_snapshots SET balance=$2,equity=$2,free_margin=$2,
                   payload=$3::jsonb WHERE snapshot_id=$1""",
            changed_unbound.snapshot_id,
            changed_unbound.balance,
            json.dumps(changed_unbound.model_dump(mode="json"), sort_keys=True, separators=(",", ":")),
        )
        mutable = await postgres.fetchrow(
            "SELECT balance FROM executor_account_snapshots WHERE snapshot_id=$1",
            changed_unbound.snapshot_id,
        )
        assert mutable is not None and Decimal(str(mutable["balance"])) == Decimal("1003")

        with pytest.raises(postgres.check_violation_error):
            await postgres.execute(
                "UPDATE executor_account_snapshots SET balance=1002 WHERE snapshot_id=$1",
                changed_snapshot.snapshot_id,
            )


async def test_numeric_alias_drift_cannot_hide_behind_string_normalization(
    postgres: PoolBackedPostgres,
) -> None:
    async with _seeded(postgres) as seeded:
        repository = _repository(postgres)
        approved = await repository.process_evidence(seeded.evidence)
        assert approved.status == "APPROVED"
        async with postgres.transaction() as connection:
            savepoint = connection.transaction()
            await savepoint.start()
            try:
                # The production amount CHECK correctly blocks this direct
                # corruption.  Remove it only inside a rolled-back savepoint
                # so the loader's exact numeric comparison is exercised
                # without weakening the durable schema after the test.
                await connection.execute(f"ALTER TABLE {RISK_LOCK_TABLE} DISABLE TRIGGER USER")
                await connection.execute(
                    f"ALTER TABLE {RISK_LOCK_TABLE} DROP CONSTRAINT ck_5scr_campaign_risk_lock_v2_amounts"
                )
                # The historical string-rstrip comparator aliased 10000 and 1.
                await connection.execute(
                    f"UPDATE {RISK_LOCK_TABLE} SET balance_base=1 WHERE tradeplan_id=$1",
                    seeded.candidate.tradeplan_id,
                )
                single = cast(Any, _SingleConnectionPostgres(connection))
                with pytest.raises(CandidateC2ShadowV2IntegrityError, match="C2_DURABLE_DRIFT"):
                    await Strategy5SCRCandidateC2ShadowV2Repository(single).load_authority(
                        seeded.candidate.tradeplan_id
                    )
            finally:
                await savepoint.rollback()


async def test_kill_switch_after_reservation_revokes_active_authority(
    postgres: PoolBackedPostgres,
) -> None:
    async with _seeded(postgres) as seeded:
        repository = _repository(postgres)
        approved = await repository.process_evidence(seeded.evidence)
        assert approved.status == "APPROVED"
        revoked_at = _P7_DECISION + timedelta(seconds=1)
        await postgres.execute(
            """UPDATE executor_bridge_governance SET kill_switch_active=true,
                   kill_switch_reason='P7_TEST_REVOKE',governance_version=governance_version+1,
                   updated_by='P7_POSTGRES_TEST',updated_at=$1 WHERE singleton_id=1""",
            revoked_at,
        )
        revoked = seeded.evidence.model_copy(
            update={
                "source_request_id": "p7-governance-revoked",
                "decision_at_utc": revoked_at,
                "expires_at_utc": revoked_at + timedelta(seconds=60),
                "governance": _governance(
                    seeded.executor_id,
                    seeded.account_id,
                    kill_switch_active=True,
                    verified_at=revoked_at,
                ),
            }
        )
        result = await repository.process_evidence(revoked)
        assert (result.status, result.reason_code) == ("INVALIDATED", "C2_KILL_SWITCH_ENGAGED")
        assert await repository.load_authority(seeded.candidate.tradeplan_id) is None
        states = await postgres.fetchrow(
            f"""SELECT
                (SELECT state FROM {RISK_LOCK_TABLE} WHERE tradeplan_id=$1) risk_lock,
                (SELECT state FROM {RESERVATION_TABLE} WHERE tradeplan_id=$1) reservation,
                (SELECT state FROM {CAMPAIGN_TABLE} WHERE tradeplan_id=$1) campaign,
                (SELECT status FROM {OUTBOX_TABLE} WHERE tradeplan_id=$1) outbox""",
            seeded.candidate.tradeplan_id,
        )
        assert states is not None
        assert tuple(states) == ("CLOSED", "INVALIDATED", "INVALIDATED", "CANCELLED")


async def test_durable_executor_broker_server_drift_terminalizes_authority(
    postgres: PoolBackedPostgres,
) -> None:
    async with _seeded(postgres) as seeded:
        repository = _repository(postgres)
        approved = await repository.process_evidence(seeded.evidence)
        assert approved.status == "APPROVED"
        changed_at = _P7_DECISION + timedelta(seconds=1)
        trigger = "trg_5scr_guard_executor_identity_against_c2_v2"
        await postgres.execute(f"ALTER TABLE executor_instances DISABLE TRIGGER {trigger}")
        try:
            # The live DB guard is covered independently above. Bypass it
            # only for this injection so repository restart/reconciliation
            # still proves its own fail-closed defense in depth.
            await postgres.execute(
                """UPDATE executor_instances SET broker_server='FORGED-DURABLE-SERVER',
                       updated_at=$2 WHERE executor_id=$1::uuid""",
                str(seeded.executor_id),
                changed_at,
            )
        finally:
            await postgres.execute(f"ALTER TABLE executor_instances ENABLE TRIGGER {trigger}")
        replay = seeded.evidence.model_copy(
            update={
                "source_request_id": "p7-durable-broker-server-drift",
                "decision_at_utc": changed_at,
                "expires_at_utc": changed_at + timedelta(seconds=60),
                "existing_risk": c2_shadow_existing_risk_evidence_v2(
                    account_id=seeded.account_id,
                    tradeplan_id=seeded.candidate.tradeplan_id,
                    captured_at_utc=changed_at,
                ),
            }
        )
        invalidated = await repository.process_evidence(replay)
        assert (invalidated.status, invalidated.reason_code) == (
            "INVALIDATED",
            "C2_BROKER_BINDING_MISMATCH",
        )
        assert await repository.load_authority(seeded.candidate.tradeplan_id) is None
        states = await postgres.fetchrow(
            f"""SELECT
                (SELECT state FROM {RISK_LOCK_TABLE} WHERE tradeplan_id=$1) risk_lock,
                (SELECT state FROM {RESERVATION_TABLE} WHERE tradeplan_id=$1) reservation,
                (SELECT state FROM {CAMPAIGN_TABLE} WHERE tradeplan_id=$1) campaign,
                (SELECT status FROM {OUTBOX_TABLE} WHERE tradeplan_id=$1) outbox""",
            seeded.candidate.tradeplan_id,
        )
        assert states is not None
        assert tuple(states) == ("CLOSED", "INVALIDATED", "INVALIDATED", "CANCELLED")


async def test_expiry_is_atomic_and_cannot_resurrect_on_retry(postgres: PoolBackedPostgres) -> None:
    async with _seeded(postgres) as seeded:
        repository = _repository(postgres)
        approved = await repository.process_evidence(seeded.evidence)
        assert approved.status == "APPROVED" and approved.authority_bundle is not None
        expires_at = approved.authority_bundle.reservation.expires_at_utc
        premature = await repository.reconcile_expired(
            seeded.candidate.tradeplan_id,
            expires_at + timedelta(days=1),
        )
        assert (premature.status, premature.reason_code) == ("REJECTED", "C2_AUTHORITY_NOT_EXPIRED")
        assert await repository.load_authority(seeded.candidate.tradeplan_id) is not None

        expiry_repository = _repository(postgres, now=expires_at)
        expired = await expiry_repository.reconcile_expired(seeded.candidate.tradeplan_id, expires_at)
        assert (expired.status, expired.reason_code) == ("INVALIDATED", "C2_AUTHORITY_EXPIRED")
        assert await repository.load_authority(seeded.candidate.tradeplan_id) is None
        retry = await _repository(postgres).reconcile_expired(
            seeded.candidate.tradeplan_id,
            expires_at + timedelta(seconds=1),
        )
        assert (retry.status, retry.reason_code) == ("DUPLICATE", "C2_AUTHORITY_ALREADY_TERMINAL")
        states = await postgres.fetchrow(
            f"""SELECT
                (SELECT state FROM {RISK_LOCK_TABLE} WHERE tradeplan_id=$1) risk_lock,
                (SELECT state FROM {RESERVATION_TABLE} WHERE tradeplan_id=$1) reservation,
                (SELECT state FROM {CAMPAIGN_TABLE} WHERE tradeplan_id=$1) campaign,
                (SELECT status FROM {OUTBOX_TABLE} WHERE tradeplan_id=$1) outbox""",
            seeded.candidate.tradeplan_id,
        )
        assert states is not None
        assert tuple(states) == ("CLOSED", "EXPIRED", "EXPIRED", "CANCELLED")


async def test_stale_latest_snapshot_terminalizes_active_authority(
    postgres: PoolBackedPostgres,
) -> None:
    async with _seeded(postgres) as seeded:
        repository = _repository(postgres)
        approved = await repository.process_evidence(seeded.evidence)
        assert approved.status == "APPROVED"

        stale_repository = _repository(
            postgres,
            now=seeded.evidence.account_snapshot.captured_at_utc + timedelta(seconds=31),
        )
        assert await stale_repository.load_authority(seeded.candidate.tradeplan_id) is None
        states = await postgres.fetchrow(
            f"""SELECT
                (SELECT state FROM {RISK_LOCK_TABLE} WHERE tradeplan_id=$1) risk_lock,
                (SELECT state FROM {RESERVATION_TABLE} WHERE tradeplan_id=$1) reservation,
                (SELECT state FROM {CAMPAIGN_TABLE} WHERE tradeplan_id=$1) campaign,
                (SELECT status FROM {OUTBOX_TABLE} WHERE tradeplan_id=$1) outbox""",
            seeded.candidate.tradeplan_id,
        )
        assert states is not None
        assert tuple(states) == (
            "CLOSED",
            "RECONCILIATION_REQUIRED",
            "RECONCILIATION_REQUIRED",
            "CANCELLED",
        )


@pytest.mark.parametrize("new_snapshot_kind", ["unreconciled", "pending", "open"])
async def test_newer_adverse_snapshot_revokes_existing_reserved_authority(
    postgres: PoolBackedPostgres,
    new_snapshot_kind: str,
) -> None:
    async with _seeded(postgres) as seeded:
        repository = _repository(postgres)
        approved = await repository.process_evidence(seeded.evidence)
        assert approved.status == "APPROVED"
        later_at = _P7_DECISION + timedelta(seconds=1)
        kwargs: dict[str, Any] = {}
        if new_snapshot_kind == "unreconciled":
            kwargs["broker_ledger_reconciled"] = False
        elif new_snapshot_kind == "pending":
            kwargs["pending_orders"] = [
                {
                    "order_ticket": 801,
                    "symbol": seeded.candidate.symbol,
                    "order_type": "BUY_LIMIT",
                    "volume": 0.01,
                    "requested_price": float(seeded.candidate.candidate_price),
                    "magic": 150015,
                }
            ]
        else:
            kwargs["open_positions"] = [
                {
                    "position_id": 901,
                    "symbol": seeded.candidate.symbol,
                    "side": seeded.candidate.direction,
                    "volume": 0.01,
                    "entry_price": float(seeded.candidate.candidate_price),
                    "current_price": float(seeded.candidate.candidate_price),
                    "magic": 150015,
                    "floating_pnl": 0.0,
                }
            ]
        newer = _snapshot(
            seeded.candidate,
            seeded.executor_id,
            seeded.account_id,
            captured_at=later_at,
            **kwargs,
        ).model_copy(update={"snapshot_id": f"p7-{new_snapshot_kind}-{seeded.executor_id.hex}"})
        await _insert_snapshot_row(postgres, newer)
        next_evidence = _build_p7_evidence(
            seeded.candidate,
            seeded.executor_id,
            seeded.account_id,
            newer,
            request=f"p7-newer-{new_snapshot_kind}",
            decision_at=later_at,
        )
        result = await repository.process_evidence(next_evidence)
        assert (result.status, result.reason_code) == (
            "INVALIDATED",
            "C2_BROKER_RECONCILIATION_REQUIRED",
        )
        assert await repository.load_authority(seeded.candidate.tradeplan_id) is None
        reservation = await postgres.fetchrow(
            f"SELECT state FROM {RESERVATION_TABLE} WHERE tradeplan_id=$1",
            seeded.candidate.tradeplan_id,
        )
        assert reservation is not None and reservation["state"] == "RECONCILIATION_REQUIRED"
