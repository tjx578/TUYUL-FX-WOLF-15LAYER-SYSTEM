"""Unit tests for the destructive-integration database provenance guard."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.integration.postgres_test_guard import (
    DESTRUCTIVE_TEST_OPT_IN,
    require_destructive_postgres_opt_in,
    require_disposable_postgres_target,
    verify_connected_database,
    verify_operational_tables_empty,
)


def test_destructive_opt_in_requires_the_exact_phrase() -> None:
    require_destructive_postgres_opt_in(DESTRUCTIVE_TEST_OPT_IN)

    for invalid in ("", "yes", "YES_I_UNDERSTAND ", "yes_i_understand"):
        with pytest.raises(ValueError):
            require_destructive_postgres_opt_in(invalid)


def test_ci_provisions_every_disposable_database_proof() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert 'WOLF15_RUN_POSTGRES_INTEGRATION: "1"' in workflow
    assert "WOLF15_POSTGRES_TEST_DATABASE: wolf15_ci_test" in workflow
    assert "WOLF15_ALLOW_DESTRUCTIVE_PG_TESTS: YES_I_UNDERSTAND" in workflow
    assert "SET wolf15.environment_class = 'DISPOSABLE_TEST'" in workflow
    assert "SET wolf15.destructive_tests_allowed = 'true'" in workflow
    assert "current_setting('wolf15.environment_class', true)" in workflow
    assert "current_setting('wolf15.destructive_tests_allowed', true)" in workflow


def test_disposable_guard_accepts_exact_loopback_audit_database() -> None:
    target = require_disposable_postgres_target(
        "postgresql://postgres:secret@127.0.0.1:55433/wolf15_matrix_audit",
        expected_database="wolf15_matrix_audit",
    )

    assert target.host == "127.0.0.1"
    assert target.port == 55433
    assert target.database == "wolf15_matrix_audit"


@pytest.mark.parametrize(
    ("dsn", "expected"),
    [
        ("postgresql://postgres:secret@railway.internal/prod", "prod"),
        ("postgresql://postgres:secret@db.example.com/wolf15_test", "wolf15_test"),
        ("postgresql://postgres:secret@127.0.0.1/prod", "prod"),
        ("postgresql://postgres:secret@127.0.0.1/wolf15_test", "another_test"),
        ("mysql://root@127.0.0.1/wolf15_test", "wolf15_test"),
    ],
)
def test_disposable_guard_rejects_remote_production_or_mismatched_targets(dsn: str, expected: str) -> None:
    with pytest.raises(ValueError):
        require_disposable_postgres_target(dsn, expected_database=expected)


@pytest.mark.asyncio
async def test_connected_database_identity_is_verified_server_side() -> None:
    class Connection:
        async def fetchval(self, query: str) -> str:
            if "current_database" in query:
                return "wrong_test"
            if "environment_class" in query:
                return "DISPOSABLE_TEST"
            return "true"

    with pytest.raises(RuntimeError):
        await verify_connected_database(Connection(), expected_database="wolf15_matrix_audit")


@pytest.mark.parametrize(
    ("environment_class", "destructive_allowed"),
    [("PRODUCTION", "true"), ("DISPOSABLE_TEST", "false"), ("", "true")],
)
@pytest.mark.asyncio
async def test_connected_database_requires_server_side_disposable_markers(
    environment_class: str,
    destructive_allowed: str,
) -> None:
    class Connection:
        async def fetchval(self, query: str) -> str:
            if "current_database" in query:
                return "wolf15_matrix_audit"
            if "environment_class" in query:
                return environment_class
            return destructive_allowed

    with pytest.raises(RuntimeError):
        await verify_connected_database(Connection(), expected_database="wolf15_matrix_audit")


@pytest.mark.asyncio
async def test_connected_database_accepts_complete_server_side_provenance() -> None:
    class Connection:
        async def fetchval(self, query: str) -> str:
            if "current_database" in query:
                return "wolf15_matrix_audit"
            if "environment_class" in query:
                return "DISPOSABLE_TEST"
            return "true"

    await verify_connected_database(Connection(), expected_database="wolf15_matrix_audit")


@pytest.mark.asyncio
async def test_operational_table_guard_rejects_preexisting_rows() -> None:
    class Connection:
        async def fetchrow(self, _query: str) -> dict[str, int]:
            return {
                "ea_agents": 1,
                "executor_instances": 0,
                "executor_account_snapshots": 0,
                "execution_commands": 2,
                "execution_reports": 0,
                "broker_entities": 0,
                "executor_governance_audit": 0,
            }

    with pytest.raises(RuntimeError, match=r"ea_agents=1.*execution_commands=2"):
        await verify_operational_tables_empty(Connection())


@pytest.mark.asyncio
async def test_operational_table_guard_accepts_an_empty_target() -> None:
    class Connection:
        async def fetchrow(self, _query: str) -> dict[str, int]:
            return {
                "ea_agents": 0,
                "executor_instances": 0,
                "executor_account_snapshots": 0,
                "execution_commands": 0,
                "execution_reports": 0,
                "broker_entities": 0,
                "executor_governance_audit": 0,
            }

    await verify_operational_tables_empty(Connection())
