"""Exercise the aggregate query locally; PostgreSQL ACLs have a separate test."""

import sqlite3
from importlib import import_module

import pytest

migration = import_module("storage.migrations.versions.20260915_02_d0_window_audit_view")


@pytest.mark.parametrize(
    ("states", "expected"),
    [
        ([], (0, 0, 0, 0)),
        (["QUEUED"], (1, 1, 0, 0)),
        (["ARMED"], (1, 0, 1, 0)),
        (["RECONCILIATION_REQUIRED"], (1, 0, 0, 1)),
        (["COMPLETED", "EXPIRED", "CANCELLED", "ABORTED", None], (0, 0, 0, 0)),
        # A broken upstream uniqueness invariant must remain visible, not clamp to one.
        (["QUEUED", "QUEUED", "ARMED", "RECONCILIATION_REQUIRED", "COMPLETED"], (4, 2, 1, 1)),
    ],
)
def test_exact_open_states_and_empty_aggregate(states, expected):
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("ATTACH DATABASE ':memory:' AS public")
        connection.execute("CREATE TABLE public.engineering_demo_canary_windows (state TEXT)")
        connection.executemany(
            "INSERT INTO public.engineering_demo_canary_windows VALUES (?)",
            [(state,) for state in states],
        )
        cursor = connection.execute(migration.WINDOW_COUNTS_SQL)
        assert [column[0] for column in cursor.description] == [
            "open_window_count", "queued_count", "armed_count", "reconciliation_required_count"
        ]
        assert cursor.fetchall() == [expected]
        assert expected[0] == sum(expected[1:])
    finally:
        connection.close()


def test_upgrade_does_not_grant_source_table_or_writer_access(monkeypatch):
    statements = []
    monkeypatch.setattr(migration.op, "execute", statements.append)
    migration.upgrade()
    sql = "\n".join(statements)
    assert "security_barrier=true" in sql
    assert "REVOKE ALL ON wolf15_audit.d0_window_counts_v1 FROM PUBLIC" in sql
    assert "GRANT SELECT ON wolf15_audit.d0_window_counts_v1 TO wolf15_auditor" in sql
    assert "GRANT SELECT ON public.engineering_demo_canary_windows" not in sql
    assert "GRANT ALL" not in sql
    statements.clear()
    migration.downgrade()
    assert statements == ["DROP VIEW wolf15_audit.d0_window_counts_v1"]
