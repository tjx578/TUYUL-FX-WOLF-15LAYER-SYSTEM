"""Fail-closed provenance guard for destructive PostgreSQL integration tests."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit


@dataclass(frozen=True)
class DisposablePostgresTarget:
    host: str
    port: int
    database: str


_DISPOSABLE_NAME = re.compile(r"^[a-z0-9_]*(?:test|audit)[a-z0-9_]*$")
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
DESTRUCTIVE_TEST_OPT_IN = "YES_I_UNDERSTAND"
DISPOSABLE_ENVIRONMENT_CLASS = "DISPOSABLE_TEST"
_OPERATIONAL_TABLES = (
    "ea_agents",
    "executor_instances",
    "executor_account_snapshots",
    "execution_commands",
    "execution_reports",
    "broker_entities",
    "executor_governance_audit",
)


def require_destructive_postgres_opt_in(value: str) -> None:
    """Require an exact, deliberate opt-in before destructive tests may connect."""

    if value != DESTRUCTIVE_TEST_OPT_IN:
        raise ValueError(f"destructive PostgreSQL tests require exact opt-in {DESTRUCTIVE_TEST_OPT_IN}")


def require_disposable_postgres_target(dsn: str, *, expected_database: str) -> DisposablePostgresTarget:
    """Reject a DSN unless both operator intent and target identity are local/test-only."""

    if not expected_database or _DISPOSABLE_NAME.fullmatch(expected_database) is None:
        raise ValueError("expected disposable database name must contain test or audit")
    parsed = urlsplit(dsn)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ValueError("integration DATABASE_URL must use postgres or postgresql")
    host = (parsed.hostname or "").lower()
    if host not in _LOOPBACK_HOSTS:
        raise ValueError("integration DATABASE_URL must target a loopback PostgreSQL server")
    database = unquote(parsed.path.lstrip("/"))
    if database != expected_database:
        raise ValueError("integration DATABASE_URL database does not match the explicit test guard")
    try:
        port = parsed.port or 5432
    except ValueError as exc:
        raise ValueError("integration DATABASE_URL has an invalid port") from exc
    return DisposablePostgresTarget(host=host, port=port, database=database)


async def verify_connected_database(connection: object, *, expected_database: str) -> None:
    """Prove server-side identity and disposable provenance after connecting."""

    fetchval = getattr(connection, "fetchval", None)
    if fetchval is None:
        raise TypeError("PostgreSQL connection does not expose fetchval")
    actual = await fetchval("SELECT current_database()")
    if str(actual) != expected_database:
        raise RuntimeError("connected PostgreSQL database differs from the explicit test guard")
    environment_class = await fetchval("SELECT current_setting('wolf15.environment_class', true)")
    if str(environment_class) != DISPOSABLE_ENVIRONMENT_CLASS:
        raise RuntimeError("connected PostgreSQL database is not marked DISPOSABLE_TEST")
    destructive_allowed = await fetchval("SELECT current_setting('wolf15.destructive_tests_allowed', true)")
    if str(destructive_allowed).lower() != "true":
        raise RuntimeError("connected PostgreSQL database does not allow destructive tests")


async def verify_operational_tables_empty(connection: object) -> None:
    """Reject a target that contains any pre-existing bridge operational state."""

    fetchrow = getattr(connection, "fetchrow", None)
    if fetchrow is None:
        raise TypeError("PostgreSQL connection does not expose fetchrow")
    counts = await fetchrow(
        """
        SELECT
            (SELECT count(*) FROM ea_agents) AS ea_agents,
            (SELECT count(*) FROM executor_instances) AS executor_instances,
            (SELECT count(*) FROM executor_account_snapshots) AS executor_account_snapshots,
            (SELECT count(*) FROM execution_commands) AS execution_commands,
            (SELECT count(*) FROM execution_reports) AS execution_reports,
            (SELECT count(*) FROM broker_entities) AS broker_entities,
            (SELECT count(*) FROM executor_governance_audit) AS executor_governance_audit
        """
    )
    if counts is None:
        raise RuntimeError("operational table count query returned no row")
    nonempty = {table: int(counts[table]) for table in _OPERATIONAL_TABLES if int(counts[table]) != 0}
    if nonempty:
        details = ", ".join(f"{table}={count}" for table, count in sorted(nonempty.items()))
        raise RuntimeError(f"disposable PostgreSQL target contains operational rows: {details}")
