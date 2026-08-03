"""Real-PostgreSQL gate for atomic Strategy 5S-CR risk authority V1."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from importlib import import_module
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
import pytest_asyncio

import execution.mt5_risk_command_producer as producer_module
from contracts.mt5_execution_protocol import (
    AccountSnapshotV1,
    CommandGuards,
    ExecutionAction,
    MarginMode,
    SignedExecutionEnvelopeV2,
    SymbolCapability,
    canonical_json_bytes,
    verify_signed_execution_envelope_with_root,
)
from contracts.strategy_5scr_risk_reservation import RiskReservationRequest
from execution.execution_plane_flags import ExecutionPlaneFlags
from execution.mt5_risk_command_producer import (
    MT5RiskCommandProducer,
    RiskCommandProducerRejectedError,
)
from storage.strategy_5scr_risk_reservation_repository import (
    RiskReservationRejectedError,
    Strategy5SCRRiskReservationRepository,
)
from tests.integration.postgres_test_guard import (
    require_destructive_postgres_opt_in,
    require_disposable_postgres_target,
    verify_connected_database,
)
from tests.test_strategy_5scr_pressure_to_tradeplan import _evidence, _legacy_builder, _lifecycle

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_RUN_FLAG = "WOLF15_RUN_POSTGRES_INTEGRATION"
_DATABASE_GUARD = "WOLF15_POSTGRES_TEST_DATABASE"
_DESTRUCTIVE_FLAG = "WOLF15_ALLOW_DESTRUCTIVE_PG_TESTS"
_LOCK_KEY = 0x5701_1505
_LOCK_TIMEOUT_SECONDS = 120
_AUTHORITY_NOW = datetime(2026, 7, 17, 13, 15, 1, tzinfo=UTC)
_COMMAND_SECRET = "postgres-command-signing-secret-v1"
_COMMAND_KEY_ID = "postgres-command-key-v1"


class _PoolBackedPostgres:
    def __init__(
        self,
        pool: Any,
        check_violation_error: type[Exception],
        foreign_key_violation_error: type[Exception],
    ) -> None:
        self._pool = pool
        self.check_violation_error = check_violation_error
        self.foreign_key_violation_error = foreign_key_violation_error

    @property
    def is_available(self) -> bool:
        return True

    async def execute(self, query: str, *args: Any) -> str:
        async with self._pool.acquire() as connection:
            return str(await connection.execute(query, *args))

    async def fetch(self, query: str, *args: Any) -> list[Any]:
        async with self._pool.acquire() as connection:
            return list(await connection.fetch(query, *args))

    async def fetchrow(self, query: str, *args: Any) -> Any | None:
        async with self._pool.acquire() as connection:
            return await connection.fetchrow(query, *args)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Any]:
        async with self._pool.acquire() as connection, connection.transaction():
            yield connection


@pytest_asyncio.fixture
async def postgres() -> AsyncIterator[_PoolBackedPostgres]:
    if os.getenv(_RUN_FLAG) != "1":
        pytest.skip(f"set {_RUN_FLAG}=1 for disposable PostgreSQL integration tests")
    try:
        require_destructive_postgres_opt_in(os.getenv(_DESTRUCTIVE_FLAG, ""))
    except ValueError as exc:
        pytest.fail(str(exc))
    dsn = os.getenv("DATABASE_URL", "")
    expected_database = os.getenv(_DATABASE_GUARD, "")
    if not dsn or not expected_database:
        pytest.fail(f"{_RUN_FLAG}=1 requires DATABASE_URL and {_DATABASE_GUARD}")
    try:
        require_disposable_postgres_target(dsn, expected_database=expected_database)
    except ValueError as exc:
        pytest.fail(str(exc))
    try:
        asyncpg = import_module("asyncpg")
    except ModuleNotFoundError:
        pytest.fail(f"{_RUN_FLAG}=1 requires asyncpg")

    pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=4, command_timeout=10)
    lock_connection = await pool.acquire()
    lock_acquired = False
    try:
        await verify_connected_database(lock_connection, expected_database=expected_database)
        deadline = asyncio.get_running_loop().time() + _LOCK_TIMEOUT_SECONDS
        while not await lock_connection.fetchval("SELECT pg_try_advisory_lock($1)", _LOCK_KEY):
            if asyncio.get_running_loop().time() >= deadline:
                pytest.fail("timed out waiting for the risk-authority PostgreSQL lock")
            await asyncio.sleep(0.25)
        lock_acquired = True
        governance = await lock_connection.fetchrow(
            """
            SELECT kill_switch_active, kill_switch_reason, governance_version, updated_by, updated_at
            FROM executor_bridge_governance WHERE singleton_id = 1
            """
        )
        if governance is None or not bool(governance["kill_switch_active"]):
            pytest.fail("disposable governance must exist with the kill switch engaged")
        yield _PoolBackedPostgres(
            pool,
            asyncpg.CheckViolationError,
            asyncpg.ForeignKeyViolationError,
        )
        restored = await lock_connection.fetchrow(
            """
            SELECT kill_switch_active, kill_switch_reason, governance_version, updated_by, updated_at
            FROM executor_bridge_governance WHERE singleton_id = 1
            """
        )
        if restored is None or dict(restored) != dict(governance):
            pytest.fail("risk authority changed executor governance")
    finally:
        if lock_acquired:
            await lock_connection.execute("SELECT pg_advisory_unlock($1)", _LOCK_KEY)
        await pool.release(lock_connection)
        await pool.close()


@dataclass(frozen=True, slots=True)
class _SeededAuthority:
    executor_id: UUID
    account_id: str
    tradeplan_id: str
    campaign_id: str
    broker_symbol: str
    request: RiskReservationRequest


def _snapshot(
    executor_id: UUID,
    account_id: str,
    *,
    open_positions: list[dict[str, object]] | None = None,
) -> AccountSnapshotV1:
    return AccountSnapshotV1.model_validate(
        {
            "snapshot_id": f"risk-snapshot-{executor_id}",
            "captured_at_utc": _AUTHORITY_NOW,
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
            "symbols": [
                SymbolCapability(
                    canonical_symbol="CHFJPY",
                    broker_symbol="CHFJPY",
                    digits=3,
                    point=0.001,
                    tick_size=0.001,
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


async def _cleanup(postgres: _PoolBackedPostgres, seeded: _SeededAuthority) -> None:
    async with postgres.transaction() as connection:
        await connection.execute("SET CONSTRAINTS ALL DEFERRED")
        await connection.execute(
            """
            DELETE FROM broker_entities WHERE command_id IN (
                SELECT command_id FROM execution_commands WHERE account_id = $1
            )
            """,
            seeded.account_id,
        )
        await connection.execute(
            "DELETE FROM execution_reports WHERE executor_id = $1::uuid",
            str(seeded.executor_id),
        )
        await connection.execute(
            "DELETE FROM strategy_5scr_final_signal_outbox WHERE tradeplan_id = $1",
            seeded.tradeplan_id,
        )
        await connection.execute(
            "DELETE FROM strategy_5scr_risk_reservations WHERE tradeplan_id = $1",
            seeded.tradeplan_id,
        )
        await connection.execute(
            "DELETE FROM execution_commands WHERE account_id = $1",
            seeded.account_id,
        )
    await postgres.execute(
        "DELETE FROM strategy_5scr_campaign_risk_locks WHERE campaign_id = $1 AND account_id = $2",
        seeded.campaign_id,
        seeded.account_id,
    )
    await postgres.execute(
        "DELETE FROM strategy_5scr_tradeplan_candidates WHERE tradeplan_id = $1", seeded.tradeplan_id
    )
    await postgres.execute("DELETE FROM strategy_5scr_evidence_snapshots WHERE lifecycle_id = $1", seeded.campaign_id)
    await postgres.execute("DELETE FROM strategy_5scr_lifecycles WHERE lifecycle_id = $1", seeded.campaign_id)
    await postgres.execute(
        "DELETE FROM executor_account_snapshots WHERE executor_id = $1::uuid",
        str(seeded.executor_id),
    )
    await postgres.execute("DELETE FROM executor_instances WHERE executor_id = $1::uuid", str(seeded.executor_id))
    await postgres.execute("DELETE FROM ea_agents WHERE id = $1::uuid", str(seeded.executor_id))


@pytest_asyncio.fixture
async def seeded(postgres: _PoolBackedPostgres) -> AsyncIterator[_SeededAuthority]:
    executor_id = uuid4()
    account_id = f"risk-test-{executor_id.hex[:12]}"
    built = _legacy_builder().build(_lifecycle(), _evidence())
    assert built.tradeplan is not None and built.candidate_payload is not None
    plan = built.tradeplan
    candidate = built.candidate_payload
    anchor_event_id = uuid4()
    evidence_event_id = uuid4()
    candidate_event_id = uuid4()
    evidence_snapshot_id = f"evidence-{executor_id.hex[:24]}"
    snapshot = _snapshot(executor_id, account_id)

    await postgres.execute(
        """
        INSERT INTO ea_agents (
            id, agent_name, ea_class, ea_subtype, execution_mode, reporter_mode, status, locked
        ) VALUES ($1::uuid,$2,'PRIMARY','EDUMB','SHADOW','FULL','OFFLINE',false)
        """,
        str(executor_id),
        f"Risk Authority Test {executor_id}",
    )
    await postgres.execute(
        """
        INSERT INTO executor_instances (
            executor_id, account_id, login_hash, broker_server, terminal_build,
            ea_version, protocol_version, execution_mode, status, last_heartbeat_at
        ) VALUES ($1::uuid,$2,$3,'XMGlobal-MT5 10',5000,'0.22-shadow-acceptance-v1',
                  'wolf15.mt5.exec.v1','SHADOW','ONLINE',$4)
        """,
        str(executor_id),
        account_id,
        "sha256:" + "a" * 64,
        _AUTHORITY_NOW,
    )
    await postgres.execute(
        """
        INSERT INTO executor_account_snapshots (
            snapshot_id, executor_id, account_id, captured_at, balance, equity,
            floating_pnl, used_margin, free_margin, margin_level_pct, margin_mode,
            trade_allowed, autotrading_enabled, payload
        ) VALUES ($1,$2::uuid,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14::jsonb)
        """,
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
        """
        INSERT INTO strategy_5scr_lifecycles (
            lifecycle_id, symbol, anchor_at, anchor_event_id, anchor_sequence,
            latest_event_at, last_sequence
        ) VALUES ($1,$2,$3,$4::uuid,1,$3,1)
        """,
        plan.campaign_id,
        plan.symbol,
        plan.decision_at_utc - timedelta(minutes=1),
        str(anchor_event_id),
    )
    await postgres.execute(
        """
        INSERT INTO strategy_5scr_evidence_snapshots (
            snapshot_id, lifecycle_id, event_id, decision_at, lifecycle_anchor_at,
            payload, payload_hash
        ) VALUES ($1,$2,$3::uuid,$4,$5,'{}'::jsonb,$6)
        """,
        evidence_snapshot_id,
        plan.campaign_id,
        str(evidence_event_id),
        plan.decision_at_utc,
        plan.decision_at_utc - timedelta(minutes=1),
        hashlib.sha256(b"{}").hexdigest(),
    )
    candidate_hash = hashlib.sha256(canonical_json_bytes(candidate)).hexdigest()
    await postgres.execute(
        """
        INSERT INTO strategy_5scr_tradeplan_candidates (
            tradeplan_id, lifecycle_id, event_id, evidence_snapshot_id, symbol,
            direction, decision_at, payload, payload_hash
        ) VALUES ($1,$2,$3::uuid,$4,$5,$6,$7,$8::jsonb,$9)
        """,
        plan.tradeplan_id,
        plan.campaign_id,
        str(candidate_event_id),
        evidence_snapshot_id,
        plan.symbol,
        plan.direction,
        plan.decision_at_utc,
        json.dumps(candidate, sort_keys=True, separators=(",", ":")),
        candidate_hash,
    )
    context = _SeededAuthority(
        executor_id=executor_id,
        account_id=account_id,
        tradeplan_id=plan.tradeplan_id,
        campaign_id=plan.campaign_id,
        broker_symbol="CHFJPY",
        request=RiskReservationRequest(
            tradeplan_id=plan.tradeplan_id,
            executor_id=executor_id,
            broker_symbol="CHFJPY",
            requested_at_utc=_AUTHORITY_NOW,
            expires_at_utc=_AUTHORITY_NOW + timedelta(minutes=5),
        ),
    )
    try:
        yield context
    finally:
        await _cleanup(postgres, context)


def _repository(postgres: _PoolBackedPostgres) -> Strategy5SCRRiskReservationRepository:
    return Strategy5SCRRiskReservationRepository(
        pg=cast(Any, postgres),
        clock=lambda: _AUTHORITY_NOW,
    )


def _command_producer(
    postgres: _PoolBackedPostgres,
    *,
    now: datetime = _AUTHORITY_NOW,
) -> MT5RiskCommandProducer:
    return MT5RiskCommandProducer(
        pg=cast(Any, postgres),
        flags=ExecutionPlaneFlags(
            execution_enabled=True,
            signed_command_bridge_enabled=True,
            execution_command_producer_enabled=True,
            risk_reservation_enabled=True,
            trade_outbox_write_enabled=True,
        ),
        environ={
            "EXECUTOR_COMMAND_SIGNING_SECRET": _COMMAND_SECRET,
            "EXECUTOR_COMMAND_SIGNING_KEY_ID": _COMMAND_KEY_ID,
        },
        clock=lambda: now,
    )


async def test_reservation_and_final_signal_outbox_are_atomic_and_idempotent(
    postgres: _PoolBackedPostgres,
    seeded: _SeededAuthority,
) -> None:
    repository = _repository(postgres)
    assert (await repository.schema_status())["ready"] is True

    first = await repository.reserve_parent(seeded.request)
    second = await repository.reserve_parent(seeded.request)

    assert second == first
    assert first.reservation.state == "HELD"
    assert first.reservation.entry_role == "PARENT"
    assert first.signal_payload["valid_for_execution"] is True
    assert first.signal_payload["risk_reservation_id"] == str(first.reservation.reservation_id)
    assert seeded.account_id not in json.dumps(first.signal_payload, sort_keys=True)
    counts = await postgres.fetchrow(
        """
        SELECT
          (SELECT count(*) FROM strategy_5scr_campaign_risk_locks WHERE account_id = $1) AS locks,
          (SELECT count(*) FROM strategy_5scr_risk_reservations WHERE account_id = $1) AS reservations,
          (SELECT count(*) FROM strategy_5scr_final_signal_outbox WHERE account_id = $1) AS outbox
        """,
        seeded.account_id,
    )
    assert counts is not None and dict(counts) == {"locks": 1, "reservations": 1, "outbox": 1}


async def test_database_immutability_rejects_final_signal_tamper(
    postgres: _PoolBackedPostgres,
    seeded: _SeededAuthority,
) -> None:
    result = await _repository(postgres).reserve_parent(seeded.request)

    with pytest.raises(postgres.check_violation_error) as caught:
        await postgres.execute(
            """
            UPDATE strategy_5scr_final_signal_outbox
            SET payload = jsonb_set(payload, '{valid_for_execution}', 'false'::jsonb)
            WHERE outbox_id = $1::uuid
            """,
            str(result.outbox_id),
        )
    assert cast(Any, caught.value).constraint_name == "ck_5scr_final_signal_outbox_immutable_v1"


@pytest.mark.parametrize("tamper", ["credential_leak", "missing_reservation_proof"])
async def test_outbox_constraint_failure_rolls_back_lock_and_reservation(
    postgres: _PoolBackedPostgres,
    seeded: _SeededAuthority,
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
) -> None:
    import storage.strategy_5scr_risk_reservation_repository as module

    original = module.build_final_signal_payload

    def _leaking_payload(**kwargs: Any) -> dict[str, Any]:
        payload = original(**kwargs)
        if tamper == "credential_leak":
            payload["account_id"] = seeded.account_id
        else:
            payload.pop("risk_reservation")
        return payload

    monkeypatch.setattr(module, "build_final_signal_payload", _leaking_payload)
    with pytest.raises(postgres.check_violation_error) as caught:
        await _repository(postgres).reserve_parent(seeded.request)
    assert cast(Any, caught.value).constraint_name == "ck_5scr_final_signal_outbox_payload_v1"
    counts = await postgres.fetchrow(
        """
        SELECT
          (SELECT count(*) FROM strategy_5scr_campaign_risk_locks WHERE account_id = $1) AS locks,
          (SELECT count(*) FROM strategy_5scr_risk_reservations WHERE account_id = $1) AS reservations,
          (SELECT count(*) FROM strategy_5scr_final_signal_outbox WHERE account_id = $1) AS outbox
        """,
        seeded.account_id,
    )
    assert counts is not None and dict(counts) == {"locks": 0, "reservations": 0, "outbox": 0}


async def test_parent_reservation_fails_closed_when_account_has_a_broker_position(
    postgres: _PoolBackedPostgres,
    seeded: _SeededAuthority,
) -> None:
    snapshot = _snapshot(
        seeded.executor_id,
        seeded.account_id,
        open_positions=[
            {
                "position_id": 12345,
                "symbol": "CHFJPY",
                "side": "SELL",
                "volume": 0.1,
                "entry_price": 190.0,
                "current_price": 189.99,
                "stop_loss": 190.05,
                "take_profit": 189.908,
                "magic": 150015,
                "comment": "existing",
                "floating_pnl": 1.0,
            }
        ],
    )
    await postgres.execute(
        "UPDATE executor_account_snapshots SET payload = $2::jsonb WHERE snapshot_id = $1",
        snapshot.snapshot_id,
        json.dumps(snapshot.model_dump(mode="json"), sort_keys=True, separators=(",", ":")),
    )

    with pytest.raises(RiskReservationRejectedError) as caught:
        await _repository(postgres).reserve_parent(seeded.request)
    assert caught.value.reason_code == "RISK_PARENT_REQUIRES_FLAT_ACCOUNT"
    row = await postgres.fetchrow(
        "SELECT count(*) AS reservations FROM strategy_5scr_risk_reservations WHERE account_id = $1",
        seeded.account_id,
    )
    assert row is not None and int(row["reservations"]) == 0


async def test_concurrent_retry_creates_exactly_one_authority_chain(
    postgres: _PoolBackedPostgres,
    seeded: _SeededAuthority,
) -> None:
    first, second = await asyncio.gather(
        _repository(postgres).reserve_parent(seeded.request),
        _repository(postgres).reserve_parent(seeded.request),
    )

    assert first == second
    row = await postgres.fetchrow(
        """
        SELECT
          (SELECT count(*) FROM strategy_5scr_risk_reservations WHERE account_id = $1) AS reservations,
          (SELECT count(*) FROM strategy_5scr_final_signal_outbox WHERE account_id = $1) AS outbox
        """,
        seeded.account_id,
    )
    assert row is not None and dict(row) == {"reservations": 1, "outbox": 1}


async def test_stale_account_snapshot_creates_no_authority_rows(
    postgres: _PoolBackedPostgres,
    seeded: _SeededAuthority,
) -> None:
    later = _AUTHORITY_NOW + timedelta(seconds=31)
    request = seeded.request.model_copy(
        update={
            "requested_at_utc": later,
            "expires_at_utc": later + timedelta(minutes=5),
        }
    )
    repository = Strategy5SCRRiskReservationRepository(
        pg=cast(Any, postgres),
        clock=lambda: later,
    )

    with pytest.raises(RiskReservationRejectedError) as caught:
        await repository.reserve_parent(request)
    assert caught.value.reason_code == "RISK_SNAPSHOT_STALE"
    row = await postgres.fetchrow(
        "SELECT count(*) AS reservations FROM strategy_5scr_risk_reservations WHERE account_id = $1",
        seeded.account_id,
    )
    assert row is not None and int(row["reservations"]) == 0


async def test_disengaged_kill_switch_creates_no_authority_rows_and_is_restored(
    postgres: _PoolBackedPostgres,
    seeded: _SeededAuthority,
) -> None:
    original = await postgres.fetchrow(
        """
        SELECT kill_switch_active, kill_switch_reason, governance_version, updated_by, updated_at
        FROM executor_bridge_governance WHERE singleton_id = 1
        """
    )
    assert original is not None
    try:
        await postgres.execute(
            "UPDATE executor_bridge_governance SET kill_switch_active = false WHERE singleton_id = 1"
        )
        with pytest.raises(RiskReservationRejectedError) as caught:
            await _repository(postgres).reserve_parent(seeded.request)
        assert caught.value.reason_code == "RISK_KILL_SWITCH_DISENGAGED"
    finally:
        await postgres.execute(
            """
            UPDATE executor_bridge_governance
            SET kill_switch_active=$1, kill_switch_reason=$2, governance_version=$3,
                updated_by=$4, updated_at=$5
            WHERE singleton_id = 1
            """,
            original["kill_switch_active"],
            original["kill_switch_reason"],
            original["governance_version"],
            original["updated_by"],
            original["updated_at"],
        )
    row = await postgres.fetchrow(
        "SELECT count(*) AS reservations FROM strategy_5scr_risk_reservations WHERE account_id = $1",
        seeded.account_id,
    )
    assert row is not None and int(row["reservations"]) == 0


async def test_risk_command_production_is_atomic_signed_shadow_and_idempotent(
    postgres: _PoolBackedPostgres,
    seeded: _SeededAuthority,
) -> None:
    reservation = await _repository(postgres).reserve_parent(seeded.request)
    producer = _command_producer(postgres)
    assert (await producer.schema_status())["ready"] is True

    produced = await producer.produce_next()
    assert produced is not None
    assert produced.reservation_id == reservation.reservation.reservation_id
    assert produced.outbox_id == reservation.outbox_id
    assert produced.command.action is ExecutionAction.PLACE_MARKET
    assert produced.command.executor_binding.execution_mode.value == "SHADOW"
    guards = cast(CommandGuards, produced.command.guards)
    assert guards.risk_reservation_id == str(produced.reservation_id)
    assert await producer.produce_next() is None

    row = await postgres.fetchrow(
        """
        SELECT c.*, r.state AS reservation_state, r.command_id AS reservation_command_id,
               o.status AS outbox_status, o.published_at
        FROM execution_commands c
        JOIN strategy_5scr_risk_reservations r ON r.reservation_id = c.risk_reservation_id
        JOIN strategy_5scr_final_signal_outbox o ON o.reservation_id = r.reservation_id
        WHERE c.command_id = $1::uuid
        """,
        str(produced.command.command_id),
    )
    assert row is not None
    assert row["state"] == "QUEUED"
    assert row["reservation_state"] == "CONSUMED"
    assert str(row["reservation_command_id"]) == str(produced.command.command_id)
    assert row["outbox_status"] == "PUBLISHED" and row["published_at"] is not None
    envelope = SignedExecutionEnvelopeV2.model_validate(
        {
            "wire_version": row["wire_format"],
            "payload_encoding": row["payload_encoding"],
            "payload_b64": row["signed_payload_b64"],
            "payload_sha256": row["signed_payload_sha256"],
            "algorithm": row["signature_algorithm"],
            "key_id": row["signature_key_id"],
            "executor_id": row["executor_id"],
            "signature": row["signature_value"],
        }
    )
    verified = verify_signed_execution_envelope_with_root(envelope, root_secret=_COMMAND_SECRET)
    assert verified == produced.command

    tampered_payload = produced.command.model_dump(mode="json")
    tampered_payload["guards"]["risk_snapshot_id"] = "different-risk-snapshot"
    with pytest.raises(postgres.foreign_key_violation_error):
        async with postgres.transaction() as connection:
            await connection.execute("SET CONSTRAINTS fk_execution_command_risk_reservation_v1 DEFERRED")
            await connection.execute(
                """
                UPDATE execution_commands
                SET risk_snapshot_id = $2, payload = $3::jsonb
                WHERE command_id = $1::uuid
                """,
                str(produced.command.command_id),
                "different-risk-snapshot",
                json.dumps(tampered_payload, sort_keys=True, separators=(",", ":")),
            )
    unchanged = await postgres.fetchrow(
        "SELECT risk_snapshot_id FROM execution_commands WHERE command_id = $1::uuid",
        str(produced.command.command_id),
    )
    assert unchanged is not None and unchanged["risk_snapshot_id"] == reservation.reservation.account_snapshot_id


async def test_command_producer_readiness_fails_closed_without_relational_binding(
    postgres: _PoolBackedPostgres,
    seeded: _SeededAuthority,
) -> None:
    del seeded
    producer = _command_producer(postgres)
    assert (await producer.schema_status())["ready"] is True
    await postgres.execute("ALTER TABLE execution_commands DROP CONSTRAINT fk_execution_command_risk_reservation_v1")
    try:
        status = await producer.schema_status()
        assert status["ready"] is False
        assert "fk_execution_command_risk_reservation_v1" in status["missing_constraints"]
    finally:
        await postgres.execute(
            """
            ALTER TABLE execution_commands
            ADD CONSTRAINT fk_execution_command_risk_reservation_v1
            FOREIGN KEY (
                risk_reservation_id, command_id, executor_id, account_id,
                source_signal_id, source_signal_hash, risk_snapshot_id
            ) REFERENCES strategy_5scr_risk_reservations (
                reservation_id, command_id, executor_id, account_id,
                signal_id, signal_hash, account_snapshot_id
            ) DEFERRABLE INITIALLY DEFERRED
            """
        )


async def test_concurrent_risk_command_producers_create_exactly_one_command(
    postgres: _PoolBackedPostgres,
    seeded: _SeededAuthority,
) -> None:
    await _repository(postgres).reserve_parent(seeded.request)
    first, second = await asyncio.gather(
        _command_producer(postgres).produce_next(),
        _command_producer(postgres).produce_next(),
    )
    assert sum(result is not None for result in (first, second)) == 1
    count = await postgres.fetchrow(
        "SELECT count(*) AS commands FROM execution_commands WHERE account_id = $1",
        seeded.account_id,
    )
    assert count is not None and int(count["commands"]) == 1


async def test_command_producer_rejects_disengaged_kill_switch_without_mutation(
    postgres: _PoolBackedPostgres,
    seeded: _SeededAuthority,
) -> None:
    authority = await _repository(postgres).reserve_parent(seeded.request)
    original = await postgres.fetchrow(
        """
        SELECT kill_switch_active, kill_switch_reason, governance_version, updated_by, updated_at
        FROM executor_bridge_governance WHERE singleton_id = 1
        """
    )
    assert original is not None
    try:
        await postgres.execute(
            "UPDATE executor_bridge_governance SET kill_switch_active = false WHERE singleton_id = 1"
        )
        with pytest.raises(RiskCommandProducerRejectedError) as caught:
            await _command_producer(postgres).produce_next()
        assert caught.value.reason_code == "COMMAND_KILL_SWITCH_DISENGAGED"
    finally:
        await postgres.execute(
            """
            UPDATE executor_bridge_governance
            SET kill_switch_active=$1, kill_switch_reason=$2, governance_version=$3,
                updated_by=$4, updated_at=$5
            WHERE singleton_id = 1
            """,
            original["kill_switch_active"],
            original["kill_switch_reason"],
            original["governance_version"],
            original["updated_by"],
            original["updated_at"],
        )
    state = await postgres.fetchrow(
        """
        SELECT r.state AS reservation_state, r.command_id, o.status AS outbox_status,
               (SELECT count(*) FROM execution_commands WHERE account_id = $2) AS commands
        FROM strategy_5scr_risk_reservations r
        JOIN strategy_5scr_final_signal_outbox o ON o.reservation_id = r.reservation_id
        WHERE r.reservation_id = $1::uuid
        """,
        str(authority.reservation.reservation_id),
        seeded.account_id,
    )
    assert state is not None
    assert dict(state) == {
        "reservation_state": "HELD",
        "command_id": None,
        "outbox_status": "PENDING",
        "commands": 0,
    }


async def test_command_producer_rejects_a_superseded_risk_snapshot(
    postgres: _PoolBackedPostgres,
    seeded: _SeededAuthority,
) -> None:
    authority = await _repository(postgres).reserve_parent(seeded.request)
    later = _AUTHORITY_NOW + timedelta(seconds=1)
    snapshot = _snapshot(seeded.executor_id, seeded.account_id).model_copy(
        update={
            "snapshot_id": f"later-{seeded.executor_id}",
            "captured_at_utc": later,
        }
    )
    await postgres.execute(
        """
        INSERT INTO executor_account_snapshots (
            snapshot_id, executor_id, account_id, captured_at, balance, equity,
            floating_pnl, used_margin, free_margin, margin_level_pct, margin_mode,
            trade_allowed, autotrading_enabled, payload
        ) VALUES ($1,$2::uuid,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14::jsonb)
        """,
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
    with pytest.raises(RiskCommandProducerRejectedError) as caught:
        await _command_producer(postgres, now=later).produce_next()
    assert caught.value.reason_code == "COMMAND_RISK_SNAPSHOT_SUPERSEDED"
    state = await postgres.fetchrow(
        """
        SELECT r.state AS reservation_state, o.status AS outbox_status
        FROM strategy_5scr_risk_reservations r
        JOIN strategy_5scr_final_signal_outbox o ON o.reservation_id = r.reservation_id
        WHERE r.reservation_id = $1::uuid
        """,
        str(authority.reservation.reservation_id),
    )
    assert state is not None and dict(state) == {
        "reservation_state": "HELD",
        "outbox_status": "PENDING",
    }


async def test_database_failure_rolls_back_command_reservation_and_outbox(
    postgres: _PoolBackedPostgres,
    seeded: _SeededAuthority,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = await _repository(postgres).reserve_parent(seeded.request)
    real_promote = producer_module.promote_final_signal_to_command

    def _invalid_action(*args: Any, **kwargs: Any) -> Any:
        command = real_promote(*args, **kwargs)
        return command.model_copy(update={"action": ExecutionAction.PLACE_PENDING})

    monkeypatch.setattr(producer_module, "promote_final_signal_to_command", _invalid_action)
    with pytest.raises(postgres.check_violation_error):
        await _command_producer(postgres).produce_next()
    state = await postgres.fetchrow(
        """
        SELECT r.state AS reservation_state, r.command_id, o.status AS outbox_status,
               o.attempts, (SELECT count(*) FROM execution_commands WHERE account_id = $2) AS commands
        FROM strategy_5scr_risk_reservations r
        JOIN strategy_5scr_final_signal_outbox o ON o.reservation_id = r.reservation_id
        WHERE r.reservation_id = $1::uuid
        """,
        str(authority.reservation.reservation_id),
        seeded.account_id,
    )
    assert state is not None
    assert dict(state) == {
        "reservation_state": "HELD",
        "command_id": None,
        "outbox_status": "PENDING",
        "attempts": 0,
        "commands": 0,
    }


async def test_shadow_command_database_guards_forbid_broker_effects(
    postgres: _PoolBackedPostgres,
    seeded: _SeededAuthority,
) -> None:
    await _repository(postgres).reserve_parent(seeded.request)
    produced = await _command_producer(postgres).produce_next()
    assert produced is not None
    invalid_report = {
        "state": "FILLED",
        "broker": {"order_ticket": None, "deal_ticket": None, "position_id": None},
        "execution": {"filled_volume": 0},
    }
    with pytest.raises(postgres.check_violation_error) as report_error:
        await postgres.execute(
            """
            INSERT INTO execution_reports (
                report_id, command_id, executor_id, sequence, state, payload, payload_hash, event_time
            ) VALUES ($1::uuid,$2::uuid,$3::uuid,1,'FILLED',$4::jsonb,$5,$6)
            """,
            str(uuid4()),
            str(produced.command.command_id),
            str(seeded.executor_id),
            json.dumps(invalid_report, sort_keys=True, separators=(",", ":")),
            "sha256:" + "b" * 64,
            _AUTHORITY_NOW,
        )
    assert getattr(report_error.value, "constraint_name", None) == "ck_shadow_report_broker_forbidden_v2"

    with pytest.raises(postgres.check_violation_error) as broker_error:
        await postgres.execute(
            """
            INSERT INTO broker_entities (command_id, entity_type, broker_ticket, symbol)
            VALUES ($1::uuid,'ORDER',123456,'CHFJPY')
            """,
            str(produced.command.command_id),
        )
    assert getattr(broker_error.value, "constraint_name", None) == "ck_shadow_broker_entity_forbidden_v2"
