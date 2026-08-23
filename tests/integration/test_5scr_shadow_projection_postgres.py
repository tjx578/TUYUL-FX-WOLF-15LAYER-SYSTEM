"""Disposable-PostgreSQL gates for atomic C2 projection -> C3 issuance."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

import pytest

from analysis.strategy_5scr_shadow_risk_projection import (
    Strategy5SCRShadowRiskProjectionEvaluatorV1,
    _build_projection,
)
from contracts.mt5_shadow_projection_command import C3ShadowProjectionCommandRequest
from contracts.strategy_5scr_shadow_risk_projection import (
    C2_SHADOW_SOURCE_ADMISSION_CLASS,
    C2ShadowRiskProjectionDecision,
    C2ShadowRiskProjectionV1,
)
from execution.execution_plane_flags import ExecutionPlaneFlags
from execution.mt5_shadow_projection_operator_wiring import (
    ISSUANCE_TABLE,
    C3ShadowProjectionOperatorAuthorityV1,
)
from storage.strategy_5scr_shadow_risk_projection_repository import (
    SHADOW_RISK_PROJECTION_TABLE,
    Strategy5SCRShadowRiskProjectionRepository,
)
from tests.integration.test_5scr_candidate_c2_shadow_v2_postgres import (
    _build_p7_evidence,
    _seeded,
    _snapshot,
)

if TYPE_CHECKING:
    from tests.integration.lifecycle_v2_postgres_plugin import PoolBackedPostgres

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
pytest_plugins = ("tests.integration.lifecycle_v2_postgres_plugin",)

_SIGNING_SECRET = "shadow-projection-postgres-signing-secret-0123456789"
_SIGNING_KEY_ID = "shadow-projection-postgres.v1"


def _flags() -> ExecutionPlaneFlags:
    return ExecutionPlaneFlags(
        execution_enabled=True,
        signed_command_bridge_enabled=True,
        execution_command_producer_enabled=True,
        risk_reservation_enabled=False,
        trade_outbox_write_enabled=False,
        ea_command_delivery_enabled=True,
        mt5_order_send_enabled=False,
    )


async def _fresh_projection(
    postgres: PoolBackedPostgres,
    seeded: Any,
) -> C2ShadowRiskProjectionV1:
    """Rebind the seeded historical candidate to a fresh disposable snapshot."""

    baseline = Strategy5SCRShadowRiskProjectionEvaluatorV1().evaluate(
        seeded.evidence,
        source_admission_class=C2_SHADOW_SOURCE_ADMISSION_CLASS,
    )
    assert baseline.projection is not None
    assert baseline.projection.decision is C2ShadowRiskProjectionDecision.WOULD_RESERVE
    now = datetime.now(UTC)
    snapshot = _snapshot(
        seeded.candidate,
        seeded.executor_id,
        seeded.account_id,
        captured_at=now,
    )
    await postgres.execute(
        """
        UPDATE executor_account_snapshots
        SET captured_at=$2,balance=$3,equity=$4,floating_pnl=$5,used_margin=$6,
            free_margin=$7,margin_level_pct=$8,margin_mode=$9,trade_allowed=$10,
            autotrading_enabled=$11,payload=$12::jsonb
        WHERE snapshot_id=$1
        """,
        snapshot.snapshot_id,
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
    evidence = _build_p7_evidence(
        seeded.candidate,
        seeded.executor_id,
        seeded.account_id,
        snapshot,
        kill_switch_active=True,
        decision_at=now,
    )
    return _build_projection(
        evidence,
        decision=C2ShadowRiskProjectionDecision.WOULD_RESERVE,
        reason_code="C2_SHADOW_WOULD_RESERVE",
        would_volume=baseline.projection.would_volume,
        would_risk_usd=baseline.projection.would_risk_usd,
        would_open_risk_after_usd=baseline.projection.would_open_risk_after_usd,
    )


def _request(projection: C2ShadowRiskProjectionV1, governance_version: int) -> C3ShadowProjectionCommandRequest:
    requested_at = datetime.now(UTC)
    return C3ShadowProjectionCommandRequest(
        operator_run_id="c3-shadow-postgres-001",
        confirm_run_id="c3-shadow-postgres-001",
        actor="operator:postgres-test",
        reason="atomic natural strategy SHADOW issuance",
        shadow_authority_id=projection.shadow_authority_id,
        source_candidate_id=projection.tradeplan_id,
        source_candidate_revision=projection.candidate_revision,
        executor_id=projection.executor_id,
        account_id=projection.account_id,
        broker_symbol=projection.broker_symbol,
        expected_governance_version=governance_version,
        max_spread_points=100,
        max_price_drift_points=50,
        magic=150015,
        requested_at_utc=requested_at,
        expires_at_utc=min(requested_at + timedelta(seconds=30), projection.expires_at_utc),
    )


async def _purge_projection_rows(
    postgres: PoolBackedPostgres,
    projection: C2ShadowRiskProjectionV1,
) -> None:
    async with postgres.transaction() as connection:
        await connection.execute("SET LOCAL session_replication_role = replica")
        await connection.execute(
            f"DELETE FROM {ISSUANCE_TABLE} WHERE source_shadow_authority_id=$1",
            projection.shadow_authority_id,
        )
        await connection.execute(
            "DELETE FROM execution_reports WHERE command_id IN "
            "(SELECT command_id FROM execution_commands WHERE source_shadow_authority_id=$1)",
            projection.shadow_authority_id,
        )
        await connection.execute(
            "DELETE FROM execution_commands WHERE source_shadow_authority_id=$1",
            projection.shadow_authority_id,
        )
        await connection.execute(
            f"DELETE FROM {SHADOW_RISK_PROJECTION_TABLE} WHERE shadow_authority_id=$1",
            projection.shadow_authority_id,
        )


@asynccontextmanager
async def _persisted_projection(
    postgres: PoolBackedPostgres,
) -> AsyncIterator[tuple[Any, C2ShadowRiskProjectionV1]]:
    async with _seeded(postgres, kill_switch_active=True) as seeded:
        projection = await _fresh_projection(postgres, seeded)
        repository = Strategy5SCRShadowRiskProjectionRepository(cast(Any, postgres))
        first, replay = await asyncio.gather(
            repository.persist_projection(projection),
            repository.persist_projection(projection),
        )
        assert first == replay == projection
        try:
            yield seeded, projection
        finally:
            await _purge_projection_rows(postgres, projection)


async def test_concurrent_manual_issuance_creates_exactly_one_inert_command(
    postgres: PoolBackedPostgres,
) -> None:
    async with _persisted_projection(postgres) as (seeded, projection):
        governance = await postgres.fetchrow(
            "SELECT governance_version FROM executor_bridge_governance WHERE singleton_id=1"
        )
        assert governance is not None
        request = _request(projection, int(governance["governance_version"]))
        authority = C3ShadowProjectionOperatorAuthorityV1(
            pg=cast(Any, postgres),
            flags=_flags(),
            environ={
                "EXECUTOR_COMMAND_SIGNING_SECRET": _SIGNING_SECRET,
                "EXECUTOR_COMMAND_SIGNING_KEY_ID": _SIGNING_KEY_ID,
            },
        )

        first, replay = await asyncio.gather(authority.issue(request), authority.issue(request))

        assert first == replay
        counts = await postgres.fetchrow(
            f"""
            SELECT
              (SELECT count(*) FROM {ISSUANCE_TABLE} WHERE source_shadow_authority_id=$1) AS issuances,
              (SELECT count(*) FROM execution_commands WHERE source_shadow_authority_id=$1) AS commands,
              (SELECT count(*) FROM strategy_5scr_risk_reservations WHERE account_id=$2) AS legacy_reservations,
              (SELECT count(*) FROM strategy_5scr_risk_reservations_v2 WHERE account_id=$2) AS v2_reservations,
              (SELECT count(*) FROM strategy_5scr_campaign_risk_locks WHERE account_id=$2) AS legacy_locks,
              (SELECT count(*) FROM strategy_5scr_campaign_risk_locks_v2 WHERE account_id=$2) AS v2_locks
            """,
            projection.shadow_authority_id,
            seeded.account_id,
        )
        assert counts is not None
        assert dict(counts) == {
            "issuances": 1,
            "commands": 1,
            "legacy_reservations": 0,
            "v2_reservations": 0,
            "legacy_locks": 0,
            "v2_locks": 0,
        }
        command = await postgres.fetchrow(
            """
            SELECT execution_authority,capital_reserved,broker_side_effect_allowed,
                   order_send_eligible,risk_reservation_id,risk_snapshot_id
            FROM execution_commands WHERE source_shadow_authority_id=$1
            """,
            projection.shadow_authority_id,
        )
        assert command is not None
        assert dict(command) == {
            "execution_authority": False,
            "capital_reserved": False,
            "broker_side_effect_allowed": False,
            "order_send_eligible": False,
            "risk_reservation_id": None,
            "risk_snapshot_id": None,
        }


async def test_command_insert_failure_rolls_back_projection_consumption(
    postgres: PoolBackedPostgres,
) -> None:
    constraint = "ck_test_shadow_projection_force_command_rollback"
    async with _persisted_projection(postgres) as (_, projection):
        governance = await postgres.fetchrow(
            "SELECT governance_version FROM executor_bridge_governance WHERE singleton_id=1"
        )
        assert governance is not None
        request = _request(projection, int(governance["governance_version"]))
        authority = C3ShadowProjectionOperatorAuthorityV1(
            pg=cast(Any, postgres),
            flags=_flags(),
            environ={
                "EXECUTOR_COMMAND_SIGNING_SECRET": _SIGNING_SECRET,
                "EXECUTOR_COMMAND_SIGNING_KEY_ID": _SIGNING_KEY_ID,
            },
        )
        await postgres.execute(
            f"ALTER TABLE execution_commands ADD CONSTRAINT {constraint} "
            "CHECK (source_shadow_authority_id IS NULL) NOT VALID"
        )
        try:
            with pytest.raises(postgres.check_violation_error):
                await authority.issue(request)
            row = await postgres.fetchrow(
                f"""
                SELECT state,state_version,
                  (SELECT count(*) FROM execution_commands WHERE source_shadow_authority_id=$1) AS commands,
                  (SELECT count(*) FROM {ISSUANCE_TABLE} WHERE source_shadow_authority_id=$1) AS issuances
                FROM {SHADOW_RISK_PROJECTION_TABLE} WHERE shadow_authority_id=$1
                """,
                projection.shadow_authority_id,
            )
            assert row is not None
            assert dict(row) == {"state": "AVAILABLE", "state_version": 1, "commands": 0, "issuances": 0}
        finally:
            await postgres.execute(f"ALTER TABLE execution_commands DROP CONSTRAINT {constraint}")


async def test_database_rejects_projection_authority_escalation(postgres: PoolBackedPostgres) -> None:
    async with _persisted_projection(postgres) as (_, projection):
        with pytest.raises(postgres.check_violation_error):
            await postgres.execute(
                f"UPDATE {SHADOW_RISK_PROJECTION_TABLE} SET execution_authority=true WHERE shadow_authority_id=$1",
                projection.shadow_authority_id,
            )
