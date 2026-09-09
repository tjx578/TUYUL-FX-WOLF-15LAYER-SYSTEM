"""Real locked outbox UPDATE cancellation against explicitly disposable PostgreSQL."""

import asyncio
import os
from uuid import uuid4

import asyncpg
import pytest

from scripts.ci.postgres_server_binding import require_server_address
from startup.graceful_shutdown import GracefulShutdown
from startup.required_tasks import RequiredTaskSupervisor
from storage.postgres_client import PostgresClient
from storage.trade_outbox_worker import OutboxEvent, TradeOutboxWorker
from tests.integration.postgres_test_guard import (
    require_destructive_postgres_opt_in,
    require_disposable_postgres_target,
    verify_connected_database,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("owner", ["api_required", "pressure_graceful"])
async def test_actual_outbox_update_cancelled_before_pool_close(monkeypatch, owner):
    if os.environ.get("WOLF15_RUN_POSTGRES_INTEGRATION") != "1":
        pytest.skip("requires explicitly enabled disposable PostgreSQL")
    require_destructive_postgres_opt_in(os.environ.get("WOLF15_ALLOW_DESTRUCTIVE_PG_TESTS", ""))
    dsn = os.environ["WOLF15_PAIR_ACTIVITY_TEST_DATABASE_URL"]
    expected = os.environ["WOLF15_POSTGRES_TEST_DATABASE"]
    require_disposable_postgres_target(dsn, expected_database=expected)
    control = await asyncpg.connect(dsn)
    schema = "drain_test_" + uuid4().hex
    pool = None
    task = None
    lock = None
    created = False
    try:
        await verify_connected_database(control, expected_database=expected)
        require_server_address(
            await control.fetchval("SELECT inet_server_addr()::text"),
            os.environ.get("WOLF15_POSTGRES_TEST_SERVER_ADDRESS", ""),
        )
        await control.execute(f'CREATE SCHEMA "{schema}"')
        created = True
        await control.execute(
            f'CREATE TABLE "{schema}".trade_outbox '
            "(outbox_id text PRIMARY KEY, status text, published_at timestamptz, "
            "updated_at timestamptz, last_error text)"
        )
        await control.execute(
            f'INSERT INTO "{schema}".trade_outbox VALUES ($1,$2,NULL,NULL,NULL)', "fixture", "PENDING"
        )
        pool = await asyncpg.create_pool(
            dsn, min_size=1, max_size=1, server_settings={"search_path": schema, "application_name": schema}
        )
        # Real PostgresClient query methods and real asyncpg pool; no query/pool stub.
        monkeypatch.setattr(PostgresClient, "_instance", None)
        pg = PostgresClient()
        pg._pool = pool
        worker = TradeOutboxWorker(pg=pg)
        lock = control.transaction()
        await lock.start()
        await control.execute(f'SELECT 1 FROM "{schema}".trade_outbox WHERE outbox_id=$1 FOR UPDATE', "fixture")
        supervisor = RequiredTaskSupervisor({"trade_outbox": True})
        task = supervisor.start("trade_outbox", worker._mark_db_published(OutboxEvent("fixture", "", "", "", {})))
        deadline = asyncio.get_running_loop().time() + 5
        while True:
            blocked = await control.fetchval(
                "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                "AND application_name=$1 AND wait_event_type='Lock' AND query LIKE '%UPDATE trade_outbox%'",
                schema,
            )
            if blocked:
                break
            assert asyncio.get_running_loop().time() < deadline, "actual DB update never reached lock wait"
            await asyncio.sleep(0.02)

        async def close_real_pool():
            assert task.done(), "pool close attempted before required operation drained"
            assert pool.get_idle_size() == pool.get_size(), "transaction connection was not released"
            assert (
                await control.fetchval(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                    "AND application_name=$1 AND wait_event_type='Lock' AND query LIKE '%UPDATE trade_outbox%'",
                    schema,
                )
                == 0
            )
            await pg.close()

        if owner == "api_required":
            await supervisor.stop(timeout=5)
            await close_real_pool()
        else:
            shutdown = GracefulShutdown(drain_timeout=5)
            shutdown.register_cleanup("real PostgreSQL pool", close_real_pool)
            await shutdown.shutdown([task])
        assert task.cancelled()
        assert pg._pool is None
        await lock.rollback()
        lock = None
        assert await control.fetchval(f'SELECT status FROM "{schema}".trade_outbox') == "PENDING"
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=5)
        if lock is not None:
            await lock.rollback()
        if pool is not None:
            await asyncio.wait_for(pool.close(), timeout=5)
        if created:
            await control.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        await control.close()
