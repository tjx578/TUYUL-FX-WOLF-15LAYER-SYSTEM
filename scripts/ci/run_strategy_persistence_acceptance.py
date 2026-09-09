"""Execute candidate, capacity and TEST_ONLY Transaction A as distinct PG gates."""

import os
import sys
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ci.postgres_server_binding import require_server_address  # noqa: E402
from scripts.ci.run_pair_activity_runtime_acceptance import DOMAIN_TESTS, main  # noqa: E402
from tests.integration.postgres_test_guard import (  # noqa: E402
    require_destructive_postgres_opt_in,
    require_disposable_postgres_target,
)


@contextmanager
def isolated_domain_database():
    """Clone only an explicitly guarded disposable CI database.

    Domain owner rows must not fence unrelated legacy fixtures in the baseline
    database. Child databases remain available for evidence until CI destroys
    its service container; this helper never drops a database.
    """
    import psycopg
    from psycopg import sql

    if os.environ.get("WOLF15_RUN_POSTGRES_INTEGRATION") != "1":
        raise ValueError("DISPOSABLE_INTEGRATION_REQUIRED")
    require_destructive_postgres_opt_in(os.environ.get("WOLF15_ALLOW_DESTRUCTIVE_PG_TESTS", ""))
    dsn = os.environ["WOLF15_PAIR_ACTIVITY_TEST_DATABASE_URL"]
    expected = os.environ["WOLF15_POSTGRES_TEST_DATABASE"]
    require_disposable_postgres_target(dsn, expected_database=expected)
    parsed = urlsplit(dsn)
    if parsed.query or parsed.fragment:
        raise ValueError("DSN_OVERRIDE_FORBIDDEN")
    child = expected + "_domain_" + uuid4().hex[:12]
    if len(child) > 63:
        raise ValueError("DISPOSABLE_DATABASE_NAME_TOO_LONG")
    with psycopg.connect(dsn, autocommit=True, connect_timeout=3) as connection:
        identity = connection.execute(
            "SELECT current_database(), inet_server_addr()::text, "
            "current_setting('wolf15.environment_class', true), "
            "current_setting('wolf15.destructive_tests_allowed', true)"
        ).fetchone()
        require_server_address(identity[1], os.environ.get("WOLF15_POSTGRES_TEST_SERVER_ADDRESS", ""))
        if identity[0] != expected or identity[2:] != ("DISPOSABLE_TEST", "true"):
            raise ValueError("DISPOSABLE_TEMPLATE_IDENTITY_REJECTED")
    # Connect to the maintenance database only after validating the template.
    maintenance = urlunsplit(parsed._replace(path="/postgres"))
    with psycopg.connect(maintenance, autocommit=True, connect_timeout=3) as connection:
        connection.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(sql.Identifier(child), sql.Identifier(expected))
        )
        connection.execute(
            sql.SQL("ALTER DATABASE {} SET wolf15.environment_class='DISPOSABLE_TEST'").format(sql.Identifier(child))
        )
        connection.execute(
            sql.SQL("ALTER DATABASE {} SET wolf15.destructive_tests_allowed='true'").format(sql.Identifier(child))
        )
    os.environ["WOLF15_PAIR_ACTIVITY_TEST_DATABASE_URL"] = urlunsplit(parsed._replace(path="/" + child))
    os.environ["WOLF15_POSTGRES_TEST_DATABASE"] = child
    try:
        yield child
    finally:
        os.environ["WOLF15_PAIR_ACTIVITY_TEST_DATABASE_URL"] = dsn
        os.environ["WOLF15_POSTGRES_TEST_DATABASE"] = expected


def run_domains():
    outcomes = []
    for module in DOMAIN_TESTS:
        with isolated_domain_database():
            outcomes.append(main(test_module=module))
    return 1 if any(outcomes) else 0


if __name__ == "__main__":
    raise SystemExit(run_domains())
