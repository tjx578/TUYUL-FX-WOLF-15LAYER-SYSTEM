"""Measure C04 bootstrap on the existing CI services without production access."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import psycopg  # noqa: E402
import redis  # noqa: E402

from scripts.ci.pair_activity_run_evidence import host_snapshot, migration_graph, observe_postgres  # noqa: E402
from tests.integration.postgres_test_guard import (  # noqa: E402
    require_destructive_postgres_opt_in,
    require_disposable_postgres_target,
)


def main():
    if os.environ.get("WOLF15_RUN_POSTGRES_INTEGRATION") != "1":
        raise ValueError("EXPLICIT_DISPOSABLE_RUN_REQUIRED")
    require_destructive_postgres_opt_in(os.environ.get("WOLF15_ALLOW_DESTRUCTIVE_PG_TESTS", ""))
    dsn = os.environ["WOLF15_PAIR_ACTIVITY_TEST_DATABASE_URL"]
    database = os.environ["WOLF15_POSTGRES_TEST_DATABASE"]
    require_disposable_postgres_target(dsn, expected_database=database)
    from urllib.parse import urlsplit

    if urlsplit(dsn).query or urlsplit(dsn).fragment:
        raise ValueError("DSN_OVERRIDE_FORBIDDEN")
    redis_url = urlsplit(os.environ["REDIS_URL"])
    if redis_url.scheme != "redis" or redis_url.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("LOOPBACK_REDIS_REQUIRED")
    host = host_snapshot(True)
    if host["os"] != "Linux" or host["capacity"].get("below_90_percent") is not True:
        raise ValueError("LINUX_CAPACITY_NOT_QUALIFIED")
    with psycopg.connect(dsn, connect_timeout=3) as connection:
        pg = observe_postgres(connection, database, migration_graph(ROOT)["repository_heads"][0], 16)
        privileges = connection.execute(
            "SELECT rolsuper, rolcreatedb FROM pg_roles WHERE rolname=current_user"
        ).fetchone()
    client = redis.Redis.from_url(os.environ["REDIS_URL"], socket_connect_timeout=3, socket_timeout=3)
    try:
        assert client.ping() is True
        version = client.info("server")["redis_version"]
        assert version.split(".")[0] == "7"
    finally:
        client.close()
    receipt = {
        "scope": "C04_CI_BOOTSTRAP_ONLY_NOT_VPS_OR_APPLICATION_ROLE_ACCEPTANCE",
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "clean_checkout": not subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip(),
        "host": host,
        "postgres": pg,
        "postgres_bootstrap_role": {"superuser": privileges[0], "createdb": privileges[1]},
        "redis": {"loopback_connected": True, "ping": True, "version": version},
        "historical_vps_or_windows_workload_mutated": False,
    }
    assert receipt["clean_checkout"]
    destination = ROOT / "artifacts/pair-activity-runtime/runner-qualification.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"qualification": "PASS_C04_BOOTSTRAP_SCOPE", "source_commit": receipt["source_commit"]}))


if __name__ == "__main__":
    main()
