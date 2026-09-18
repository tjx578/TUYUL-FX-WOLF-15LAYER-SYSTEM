"""Auditor-only projections for the two D0 canary predicates, on guarded disposable PostgreSQL.

Seeds an executor, two snapshots (S and a newer S+1) and one direct reconciliation receipt for S inside a
transaction that is always rolled back, then reads the views as wolf15_auditor.
"""

import json
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from tests.integration.postgres_test_guard import require_disposable_postgres_target

pytestmark = pytest.mark.integration

VIEW_SYMBOL = "wolf15_audit.executor_snapshot_symbol_capability_v1"
VIEW_RECEIPT = "wolf15_audit.direct_reconciliation_receipt_v1"
BASE_TABLES = (
    "public.executor_account_snapshots",
    "public.executor_instances",
    "public.direct_broker_reconciliation_receipts",
)


class _RollbackError(Exception):
    pass


async def _seed(connection, executor_id, account_id):
    from tests.test_mt5_engineering_demo_canary import _snapshot

    now = datetime.now(UTC)
    await connection.execute(
        """INSERT INTO executor_instances (
               executor_id,account_id,login_hash,broker_server,terminal_build,ea_version,protocol_version,
               execution_mode,status,last_heartbeat_at)
           VALUES ($1::uuid,$2,$3,'Broker-Demo',5000,'SYNTHETIC','wolf15.mt5.exec.v1','DEMO','ONLINE',$4)""",
        str(executor_id),
        account_id,
        "sha256:" + "a" * 64,
        now,
    )
    snapshots = {}
    for snapshot_id, age, volume_min in (("snapshot-S", 12, 0.01), ("snapshot-S1", 1, 0.02)):
        snapshot = _snapshot(
            snapshot_id=snapshot_id,
            executor_id=executor_id,
            account_id=account_id,
            captured_at_utc=now - timedelta(seconds=age),
            autotrading_enabled=False,
        )
        payload = snapshot.model_dump(mode="json")
        payload["symbols"][0]["volume_min"] = volume_min
        await connection.execute(
            """INSERT INTO executor_account_snapshots (
                   snapshot_id,executor_id,account_id,captured_at,balance,equity,floating_pnl,used_margin,free_margin,
                   margin_level_pct,margin_mode,trade_allowed,autotrading_enabled,payload)
               VALUES ($1,$2::uuid,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14::jsonb)""",
            snapshot_id,
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
            json.dumps(payload),
        )
        snapshots[snapshot_id] = payload
    counts = {
        "positions": 0,
        "pending_orders": 0,
        "orders": 0,
        "deals": 0,
        "matched_wolf15": 0,
        "manual_external": 0,
        "preexisting": 0,
        "orphan_wolf15": 0,
        "unattributed": 0,
        "ambiguous": 0,
        "ledger_mismatch": 0,
    }
    reconciliation_id = uuid4()
    await connection.execute(
        """INSERT INTO direct_broker_reconciliation_receipts (
               reconciliation_id,executor_id,account_reference,broker_server_sha256,source_snapshot_id,
               source_snapshot_sha256,command_id,observed_at,counts,broker_ledger_reconciled,terminal_reason,
               receipt_sha256,payload,created_at)
           VALUES ($1::uuid,$2::uuid,$3,$4,'snapshot-S',$5,NULL,$6,$7::jsonb,true,'FLAT_RECONCILED',$8,$9::jsonb,$6)""",
        str(reconciliation_id),
        str(executor_id),
        "sha256:" + "b" * 64,
        "sha256:" + "c" * 64,
        "sha256:" + "d" * 64,
        now,
        json.dumps(counts),
        "sha256:" + "e" * 64,
        json.dumps({"secret_like": "never exposed"}),
    )
    return snapshots, reconciliation_id


async def test_auditor_measures_exact_snapshot_capability_and_receipt_without_base_access():
    if os.getenv("WOLF15_RUN_POSTGRES_INTEGRATION") != "1":
        pytest.skip("requires migrated disposable PostgreSQL")
    import asyncpg

    dsn = os.environ["DATABASE_URL"]
    database = os.getenv("WOLF15_POSTGRES_TEST_DATABASE", "wolf15_ci_test")
    require_disposable_postgres_target(dsn, expected_database=database)
    connection = await asyncpg.connect(dsn, timeout=10, command_timeout=10)
    executor_id, account_id = uuid4(), f"acct-{uuid4().hex[:10]}"
    try:
        assert await connection.fetchval("SELECT current_database()") == database
        with pytest.raises(_RollbackError):
            async with connection.transaction():
                snapshots, reconciliation_id = await _seed(connection, executor_id, account_id)
                await connection.execute("SET LOCAL ROLE wolf15_auditor")

                capability = await connection.fetch(
                    f"SELECT * FROM {VIEW_SYMBOL} WHERE executor_id=$1::uuid AND snapshot_id='snapshot-S'",
                    str(executor_id),
                )
                assert len(capability) == len(snapshots["snapshot-S"]["symbols"])
                first = dict(capability[0])
                expected = snapshots["snapshot-S"]["symbols"][0]
                assert first["canonical_symbol"] == expected["canonical_symbol"]
                assert first["broker_symbol"] == expected["broker_symbol"]
                assert first["volume_min"] == 0.01  # exact S, not the newer S+1 (0.02)
                assert first["volume_step"] == expected["volume_step"]
                assert first["digits"] == expected["digits"]
                assert first["account_matches_executor"] is True
                assert first["autotrading_enabled"] is False
                assert set(first) == {
                    "executor_id",
                    "snapshot_id",
                    "account_matches_executor",
                    "captured_at",
                    "trade_allowed",
                    "autotrading_enabled",
                    "margin_mode",
                    "canonical_symbol",
                    "broker_symbol",
                    "digits",
                    "point",
                    "tick_size",
                    "volume_min",
                    "volume_max",
                    "volume_step",
                    "stops_level_points",
                    "freeze_level_points",
                }

                receipts = await connection.fetch(
                    f"SELECT * FROM {VIEW_RECEIPT} WHERE executor_id=$1::uuid AND source_snapshot_id='snapshot-S'",
                    str(executor_id),
                )
                assert len(receipts) == 1
                receipt = dict(receipts[0])
                assert receipt["reconciliation_id"] == reconciliation_id
                assert receipt["broker_ledger_reconciled"] is True
                assert receipt["source_snapshot_exists"] is True
                assert (receipt["positions_count"], receipt["pending_orders_count"]) == (0, 0)
                assert "payload" not in receipt and "counts" not in receipt
                assert not await connection.fetchval(
                    f"SELECT count(*) FROM {VIEW_RECEIPT} WHERE executor_id=$1::uuid AND source_snapshot_id='snapshot-S1'",
                    str(executor_id),
                )

                for table in BASE_TABLES:
                    for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                        assert not await connection.fetchval(
                            "SELECT has_table_privilege(current_user, $1, $2)", table, privilege
                        ), (table, privilege)
                for view in (VIEW_SYMBOL, VIEW_RECEIPT):
                    assert await connection.fetchval("SELECT has_table_privilege(current_user, $1, 'SELECT')", view)
                    for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                        assert not await connection.fetchval(
                            "SELECT has_table_privilege(current_user, $1, $2)", view, privilege
                        ), (view, privilege)
                raise _RollbackError
    finally:
        await connection.close()
