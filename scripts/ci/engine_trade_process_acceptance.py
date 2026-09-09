"""Real ENGINE/TRADE role processes with disposable PostgreSQL and Redis.

No runtime functions are patched. Empty fixture streams intentionally provide no
trade intent; readiness proves process/dependency startup, not market readiness.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


async def child():
    import urllib.error
    import urllib.request

    import psycopg
    import redis

    assert os.environ.get("WOLF15_ROLES_DISPOSABLE_CHILD") == "YES_I_UNDERSTAND"
    assert Path("/.dockerenv").is_file(), "child requires an isolated container"
    assert urlsplit(os.environ["REDIS_URL"]).hostname == "cache"
    db_url = urlsplit(os.environ["DATABASE_URL"])
    assert db_url.hostname == "database" and db_url.path == "/roles_disposable_test"
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        assert connection.execute(
            "SELECT current_database(), current_setting('wolf15.environment_class',true)"
        ).fetchone() == ("roles_disposable_test", "DISPOSABLE_TEST")

    receipt = {
        "accepted": False,
        "roles": [],
        "fixture_scope": "empty streams, migrated disposable database; no strategy or broker acceptance",
    }
    cache = redis.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    try:
        # Run before the positive roles create any consumer groups. These flags
        # must be rejected by the real trade entrypoint before worker imports.
        receipt["invalid_dual_plane"] = await invalid_dual_plane(cache)
        for role, command in (
            ("engine", ["bash", "deploy/railway/start_engine.sh"]),
            ("trade", [sys.executable, "-m", "services.trade.runner"]),
        ):
            env = dict(
                os.environ,
                PORT="18084",
                TRADE_HEALTH_PORT="18084",
                ALLOC_HEALTH_PORT="18085",
                ALLOC_METRICS_PORT="19102",
            )
            path = Path("/tmp") / (role + "-role.log")
            row = {"role": role, "accepted": False}
            receipt["roles"].append(row)
            with path.open("w") as log:
                process = await asyncio.create_subprocess_exec(*command, env=env, stdout=log, stderr=log)
                try:

                    def status():
                        try:
                            with urllib.request.urlopen("http://127.0.0.1:18084/readyz", timeout=2) as response:
                                return response.status
                        except urllib.error.HTTPError as error:
                            return error.code
                        except OSError:
                            return None

                    deadline = time.monotonic() + 150
                    observed = []
                    while time.monotonic() < deadline:
                        assert process.returncode is None, role + " exited before readiness"
                        value = await asyncio.to_thread(status)
                        if value is not None:
                            observed.append(value)
                        if value == 200:
                            break
                        await asyncio.sleep(0.25)
                    else:
                        raise AssertionError(role + " readiness timeout")
                    assert cache.ping()
                    if role == "trade":
                        assert cache.xinfo_groups("allocation:request"), "allocation group not created"
                    else:
                        with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
                            assert (
                                connection.execute(
                                    "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid()"
                                ).fetchone()[0]
                                > 0
                            )
                    for key in ("execution:queue", "trade:commands"):
                        assert not cache.exists(key), "unexpected execution output"
                    process.terminate()
                    code = await asyncio.wait_for(process.wait(), 35)
                    assert code == 0, role + " did not gracefully exit on SIGTERM"
                    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
                        assert (
                            connection.execute(
                                "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid()"
                            ).fetchone()[0]
                            == 0
                        ), "role database connections survived shutdown"
                    row.update(accepted=True, readyz=200, observed_statuses=sorted(set(observed)), exit_code=code)
                finally:
                    if process.returncode is None:
                        process.kill()
                        await process.wait()
                    if not row["accepted"]:
                        row["diagnostic"] = path.read_text()[-7000:]
        receipt["accepted"] = True
    finally:
        cache.close()
        print("ENGINE_TRADE_RECEIPT " + json.dumps(receipt), flush=True)


async def invalid_dual_plane(cache):
    """Actual role startup rejection; a loopback recording sink is never a broker."""
    import threading
    import urllib.request
    from http.server import BaseHTTPRequestHandler, HTTPServer

    import psycopg
    from psycopg import sql

    calls = []

    class Sink(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append(("GET", self.path))
            self.send_response(200)
            self.end_headers()

        def do_POST(self):
            calls.append(("POST", self.path))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    def snapshot():
        redis_state = {key: hashlib.sha256(cache.dump(key)).hexdigest() for key in sorted(cache.scan_iter())}
        database_state = {}
        with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            tables = connection.execute(
                "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname='public' ORDER BY tablename"
            ).fetchall()
            for (table,) in tables:
                digest = hashlib.sha256()
                count = 0
                rows = connection.execute(
                    sql.SQL("SELECT row_to_json(t)::text FROM public.{} t ORDER BY row_to_json(t)::text").format(
                        sql.Identifier(table)
                    )
                )
                for (row,) in rows:
                    digest.update(row.encode() + b"\n")
                    count += 1
                database_state[table] = {"rows": count, "sha256": digest.hexdigest()}
        return {"redis": redis_state, "public_tables": database_state}

    assert not cache.exists("allocation:request"), "negative case must precede consumer creation"
    before = snapshot()
    sink = HTTPServer(("127.0.0.1", 0), Sink)
    thread = threading.Thread(target=sink.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{sink.server_port}"
    path = Path("/tmp/trade-invalid-dual-plane.log")
    process = None
    try:
        with urllib.request.urlopen(base + "/recording-control", timeout=2) as response:
            assert response.status == 200
        env = dict(
            os.environ,
            PORT="18084",
            TRADE_HEALTH_PORT="18084",
            EXECUTION_ENABLED="true",
            LEGACY_PUSH_EXECUTION_ENABLED="true",
            SIGNED_COMMAND_BRIDGE_ENABLED="true",
            EA_BRIDGE_URL=base,
        )
        with path.open("w") as log:
            process = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "services.trade.runner", env=env, stdout=log, stderr=log
            )
            code = await asyncio.wait_for(process.wait(), timeout=30)
        assert code != 0, "invalid dual plane was not rejected"
        assert "EXECUTION_PLANE_CONFLICT" in path.read_text(), "exit was not the required preflight rejection"
        assert not cache.exists("allocation:request"), "invalid role created an allocation consumer stream/group"
        assert snapshot() == before, "invalid role changed Redis or persistent public-table rows"
        assert calls == [("GET", "/recording-control")], "invalid role contacted the recording sink"
        return {
            "accepted": True,
            "scope": "ACTUAL_TRADE_ROLE_INVALID_DUAL_PLANE_BEFORE_CONSUMERS",
            "exit_code": code,
            "reason": "EXECUTION_PLANE_CONFLICT",
            "allocation_stream_or_group_created": False,
            "redis_state_unchanged": True,
            "public_table_rows_unchanged": True,
            "before_state": before,
            "sink_control_requests": 1,
            "sink_dispatch_requests": 0,
            "broker_acceptance": "NOT_EXECUTED",
            "all_legacy_paths_coverage": False,
        }
    finally:
        if process is not None and process.returncode is None:
            process.kill()
            await process.wait()
        sink.shutdown()
        sink.server_close()
        thread.join(timeout=2)


def run(image, output):
    from api.owner_dashboard_release import DISABLED_FLAGS
    from scripts.ci.orchestrator_process_acceptance import docker, until

    name = "wolf15-engine-trade-" + uuid4().hex[:12]
    resources = []
    network_created = False
    receipt = {"accepted": False, "scope": "INTERNAL_DOCKER_ENGINE_TRADE", "execution_enabled": False}
    try:
        docker("network", "create", "--internal", name)
        network_created = True
        assert json.loads(docker("network", "inspect", name))[0]["Internal"] is True
        cache = docker("run", "-d", "--network", name, "--network-alias", "cache", "redis:7-alpine")
        resources.append(cache)
        until(lambda: docker("exec", cache, "redis-cli", "ping") == "PONG")
        password = uuid4().hex
        database = docker(
            "run",
            "-d",
            "--network",
            name,
            "--network-alias",
            "database",
            "-e",
            "POSTGRES_USER=fixture",
            "-e",
            f"POSTGRES_PASSWORD={password}",
            "-e",
            "POSTGRES_DB=roles_disposable_test",
            "postgres:16-alpine",
        )
        resources.append(database)
        # Require the final TCP server and the intended initialized database.
        until(
            lambda: (
                docker(
                    "exec",
                    "-e",
                    "PGPASSWORD=" + password,
                    database,
                    "psql",
                    "-h",
                    "127.0.0.1",
                    "-U",
                    "fixture",
                    "-d",
                    "roles_disposable_test",
                    "-Atc",
                    "SELECT current_database()",
                )
                == "roles_disposable_test"
            )
        )
        docker(
            "exec",
            database,
            "psql",
            "-U",
            "fixture",
            "-d",
            "roles_disposable_test",
            "-c",
            "ALTER DATABASE roles_disposable_test SET wolf15.environment_class = 'DISPOSABLE_TEST'",
        )
        docker(
            "exec",
            database,
            "psql",
            "-U",
            "fixture",
            "-d",
            "roles_disposable_test",
            "-c",
            "ALTER DATABASE roles_disposable_test SET wolf15.environment_class = 'DISPOSABLE_TEST'",
        )
        dsn = f"postgresql://fixture:{password}@database:5432/roles_disposable_test"
        docker(
            "run",
            "--rm",
            "--network",
            name,
            "--entrypoint",
            "python",
            "-e",
            f"DATABASE_URL={dsn}",
            image,
            "-m",
            "alembic",
            "upgrade",
            "head",
            timeout=120,
        )
        env = {flag: "false" for flag in DISABLED_FLAGS}
        env.update(
            ENV="test",
            APP_ENV="test",
            RAILWAY_ENVIRONMENT="CI_DISPOSABLE",
            WOLF15_LOAD_DOTENV="false",
            WOLF15_ROLES_DISPOSABLE_CHILD="YES_I_UNDERSTAND",
            WOLF15_INGEST_DISPOSABLE_CHILD="YES_I_UNDERSTAND",
            REDIS_URL="redis://cache:6379/0",
            DATABASE_URL=dsn,
            RUN_MODE="engine-only",
            CONTEXT_MODE="redis",
            WOLF15_PAIRS="EURUSD",
            ENGINE_WARMUP_MAX_RETRIES="1",
            ENGINE_WARMUP_RETRY_DELAY_SEC="0.1",
            ENGINE_WARMUP_REST_TOPUP="false",
            ANALYSIS_LOOP_INTERVAL_SEC="1",
            PORT="18084",
            FINNHUB_API_KEY="synthetic-local-provider-fixture",
            ALPHAVANTAGE_ENABLED="false",
            JWT_SECRET="synthetic-local-provider-jwt-fixture-minimum-32",
            FORCE_HTTPS="false",
        )
        args = ["create", "--network", name, "--entrypoint", "python"]
        for key, value in env.items():
            args += ["-e", f"{key}={value}"]
        args += [image, "scripts/ci/engine_trade_process_acceptance.py", "--child"]
        app = docker(*args)
        resources.append(app)
        docker("start", app)
        until(lambda: not json.loads(docker("inspect", app))[0]["State"]["Running"], timeout=360)
        logs = docker("logs", app)
        rows = [
            line.removeprefix("ENGINE_TRADE_RECEIPT ")
            for line in logs.splitlines()
            if line.startswith("ENGINE_TRADE_RECEIPT ")
        ]
        assert len(rows) == 1, "missing engine/trade receipt"
        result = json.loads(rows[0])
        receipt.update(result)
        receipt["image_id"] = json.loads(docker("image", "inspect", image))[0]["Id"]
        receipt["source_hashes"] = {
            path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
            for path in (
                "main.py",
                "services/engine/runner.py",
                "services/trade/runner.py",
                "services/trade/preflight.py",
                "execution/execution_plane_flags.py",
                "allocation/async_worker.py",
                "startup/graceful_shutdown.py",
                "deploy/railway/start_engine.sh",
                "scripts/ci/engine_trade_process_acceptance.py",
            )
        }
        assert json.loads(docker("inspect", app))[0]["State"]["ExitCode"] == 0
        assert receipt["accepted"]
    except Exception as error:
        receipt.update(accepted=False, failure_class=type(error).__name__, diagnostic=str(error)[-1000:])
    finally:
        for resource in reversed(resources):
            with contextlib.suppress(Exception):
                docker("rm", "-f", "-v", resource)
        if network_created:
            with contextlib.suppress(Exception):
                docker("network", "rm", name)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(receipt, indent=2) + "\n")
    return 0 if receipt["accepted"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--image")
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    if arguments.child:
        asyncio.run(child())
    else:
        raise SystemExit(run(arguments.image, arguments.output))
