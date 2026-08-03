"""Unit tests for the destructive-integration database provenance guard."""

from __future__ import annotations

import pytest

from tests.integration.postgres_test_guard import require_disposable_postgres_target, verify_connected_database


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
        async def fetchval(self, _query: str) -> str:
            return "wrong_test"

    with pytest.raises(RuntimeError):
        await verify_connected_database(Connection(), expected_database="wolf15_matrix_audit")
