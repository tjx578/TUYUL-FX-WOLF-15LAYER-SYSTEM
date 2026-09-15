"""Read the migrated projection as auditor on guarded disposable PostgreSQL."""

import os

import pytest

from tests.integration.postgres_test_guard import require_disposable_postgres_target

pytestmark = pytest.mark.integration


async def test_auditor_reads_only_aggregate_and_cannot_read_base_table():
    if os.getenv("WOLF15_RUN_POSTGRES_INTEGRATION") != "1":
        pytest.skip("requires migrated disposable PostgreSQL")
    import asyncpg

    dsn = os.environ["DATABASE_URL"]
    database = os.getenv("WOLF15_POSTGRES_TEST_DATABASE", "wolf15_ci_test")
    require_disposable_postgres_target(dsn, expected_database=database)
    connection = await asyncpg.connect(dsn, timeout=10, command_timeout=10)
    try:
        assert await connection.fetchval("SELECT current_database()") == database
        async with connection.transaction(isolation="repeatable_read", readonly=True):
            expected = await connection.fetchrow("""
                SELECT count(*) AS open_window_count,
                       count(*) FILTER (WHERE state='QUEUED') AS queued_count,
                       count(*) FILTER (WHERE state='ARMED') AS armed_count,
                       count(*) FILTER (WHERE state='RECONCILIATION_REQUIRED')
                           AS reconciliation_required_count
                  FROM public.engineering_demo_canary_windows
                 WHERE state IN ('QUEUED','ARMED','RECONCILIATION_REQUIRED')
            """)
            await connection.execute("SET LOCAL ROLE wolf15_auditor")
            rows = await connection.fetch("SELECT * FROM wolf15_audit.d0_window_counts_v1")
            assert len(rows) == 1
            assert dict(rows[0]) == dict(expected)
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                assert not await connection.fetchval(
                    "SELECT has_table_privilege(current_user, 'public.engineering_demo_canary_windows', $1)",
                    privilege,
                )
            for privilege in ("INSERT", "UPDATE", "DELETE"):
                assert not await connection.fetchval(
                    "SELECT has_table_privilege(current_user, 'wolf15_audit.d0_window_counts_v1', $1)",
                    privilege,
                )
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                async with connection.transaction():
                    await connection.fetch("SELECT state FROM public.engineering_demo_canary_windows")
    finally:
        await connection.close()
