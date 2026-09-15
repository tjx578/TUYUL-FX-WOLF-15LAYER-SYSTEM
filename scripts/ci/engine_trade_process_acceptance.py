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
        "fixture_scope": "empty-stream role startup then synthetic legacy queue-to-loopback acceptance; no strategy or broker acceptance",
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
        legacy_url = urlsplit(os.environ["REDIS_URL"])._replace(path="/1", query="", fragment="").geturl()
        legacy_cache = redis.Redis.from_url(legacy_url, decode_responses=True)
        try:
            assert legacy_cache.dbsize() == 0, "legacy fixture requires an empty disposable logical database"
            legacy_receipt = {"accepted": False, "cases": [], "current_case": "initialization"}
            receipt["legacy_queue_recording_sink"] = legacy_receipt
            await legacy_queue_recording_sink(legacy_cache, legacy_url, legacy_receipt)
        finally:
            legacy_cache.close()
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


async def legacy_queue_recording_sink(cache, legacy_url, report):
    """Real legacy worker processes, synthetic queue, and loopback-only transport."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    import psycopg
    from psycopg import sql

    from contracts.execution_queue_contract import ExecutionQueuePayload
    from execution.execution_plane_flags import EXECUTION_PLANE_FLAGS

    assert Path("/.dockerenv").is_file()
    assert os.environ.get("WOLF15_ROLES_DISPOSABLE_CHILD") == "YES_I_UNDERSTAND"
    assert os.environ.get("WOLF15_INTERNAL_NETWORK_FIXTURE") == "YES"
    assert urlsplit(os.environ["REDIS_URL"]).hostname == "cache"
    db = urlsplit(os.environ["DATABASE_URL"])
    assert db.hostname == "database" and db.path == "/roles_disposable_test"

    def database_snapshot():
        with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            assert connection.execute(
                "SELECT current_database(), current_setting('wolf15.environment_class',true)"
            ).fetchone() == ("roles_disposable_test", "DISPOSABLE_TEST")
            result = {}
            for (table,) in connection.execute(
                "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname='public' ORDER BY tablename"
            ).fetchall():
                rows = connection.execute(
                    sql.SQL("SELECT row_to_json(t)::text FROM public.{} t ORDER BY row_to_json(t)::text").format(
                        sql.Identifier(table)
                    )
                ).fetchall()
                result[table] = {
                    "rows": len(rows),
                    "sha256": hashlib.sha256("".join(row[0] + "\n" for row in rows).encode()).hexdigest(),
                }
            return result

    def redis_snapshot():
        return {key: hashlib.sha256(cache.dump(key)).hexdigest() for key in sorted(cache.scan_iter())}

    assert urlsplit(legacy_url).hostname == "cache" and urlsplit(legacy_url).path == "/1"
    stream, group = "execution:queue", "exec-group"
    assert not cache.exists(stream), "fixture cannot replace an existing execution queue"
    original_redis, original_database = redis_snapshot(), database_snapshot()
    fixture_id = "disposable-legacy-" + uuid4().hex
    payload = ExecutionQueuePayload(
        request_id=fixture_id,
        signal_id=fixture_id + "-signal",
        account_id="disposable-recording-account",
        symbol="EURUSD",
        verdict="EXECUTE",
        direction="BUY",
        entry_price=1.0,
        stop_loss=0.99,
        take_profit_1=1.01,
        lot_size=0.01,
        order_type="BUY_LIMIT",
        execution_mode="TP1_ONLY",
        operator="disposable-fixture",
    )
    calls = []

    class Sink(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(min(int(self.headers.get("Content-Length", "0")), 16384))
            calls.append({"method": "POST", "path": self.path, "payload": json.loads(body)})
            response = json.dumps({"success": True, "ticket": 12345, "error_code": 0}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def do_GET(self):
            calls.append({"method": "GET", "path": self.path})
            self.send_response(405)
            self.end_headers()

        def log_message(self, *args):
            pass

    sink = HTTPServer(("127.0.0.1", 0), Sink)
    thread = threading.Thread(target=sink.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{sink.server_port}"
    assert urlsplit(base).hostname == "127.0.0.1"
    env = {
        key: value
        for key, value in os.environ.items()
        if key.lower() not in {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}
    }
    for key in (
        "REDIS_HOST",
        "REDISHOST",
        "REDIS_PORT",
        "REDISPORT",
        "REDIS_PASSWORD",
        "REDISPASSWORD",
        "REDIS_PRIVATE_URL",
    ):
        env.pop(key, None)
    env.update({flag: "false" for flag in EXECUTION_PLANE_FLAGS})
    env.update(
        EA_BRIDGE_URL=base,
        NO_PROXY="*",
        no_proxy="*",
        WOLF15_LOAD_DOTENV="false",
        REDIS_URL=legacy_url,
        REDIS_DB="1",
        EXEC_METRICS_PORT="19113",
        PORT="18094",
        EXEC_MAX_RESTARTS="0",
    )
    process = None
    seeded = False
    rows = report["cases"]
    try:
        message_id = cache.xadd(stream, payload.to_stream_fields())
        seeded = True
        seeded_state = redis_snapshot()
        cases = (
            ("disabled_module", {}, None, "execution:queue not consumed"),
            (
                "incoherent_module",
                {"LEGACY_PUSH_EXECUTION_ENABLED": "true"},
                None,
                "EXECUTION_PLANE_INCOHERENT:legacy_push_without_execution_enabled",
            ),
            (
                "dual_plane_module",
                {
                    "EXECUTION_ENABLED": "true",
                    "LEGACY_PUSH_EXECUTION_ENABLED": "true",
                    "SIGNED_COMMAND_BRIDGE_ENABLED": "true",
                },
                None,
                "EXECUTION_PLANE_CONFLICT:legacy_push+signed_command_bridge",
            ),
            (
                "disabled_constructor",
                {},
                "from execution.async_worker import AsyncExecutionWorker; AsyncExecutionWorker()",
                "LEGACY_PUSH_EXECUTION_DISABLED:worker_not_permitted",
            ),
        )
        for name, overrides, command, reason in cases:
            report["current_case"] = name
            report["stage"] = "launch_and_wait"
            path = Path("/tmp") / ("legacy-" + name + ".log")
            args = [sys.executable, "-c", command] if command else [sys.executable, "-m", "execution.async_worker"]
            with path.open("w") as log:
                process = await asyncio.create_subprocess_exec(*args, env=env | overrides, stdout=log, stderr=log)
                code = await asyncio.wait_for(process.wait(), 30)
            assert (code == 0) if name == "disabled_module" else (code != 0), name + " exit contract"
            assert reason in path.read_text(), name + " rejection reason"
            assert cache.xinfo_groups(stream) == [], name + " created a consumer group"
            assert redis_snapshot() == seeded_state, name + " changed Redis"
            assert database_snapshot() == original_database, name + " changed public tables"
            assert calls == [], name + " contacted recording sink"
            rows.append(
                {
                    "case": name,
                    "accepted": True,
                    "exit_code": code,
                    "reason": reason,
                    "dispatch_requests": 0,
                    "redis_unchanged": True,
                    "public_tables_unchanged": True,
                }
            )

        # This subprocess alone enables the synthetic legacy path, with no external route.
        report["current_case"] = "positive_queue_to_recording_sink"
        report["stage"] = "launch_and_await_dispatch_ack"
        path = Path("/tmp/legacy-positive-control.log")
        with path.open("w") as log:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "execution.async_worker",
                env=env | {"EXECUTION_ENABLED": "true", "LEGACY_PUSH_EXECUTION_ENABLED": "true"},
                stdout=log,
                stderr=log,
            )
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline:
                assert process.returncode is None, "positive queue control exited before consumption"
                groups = cache.xinfo_groups(stream)
                if calls and groups and groups[0]["last-delivered-id"] == message_id and groups[0]["pending"] == 0:
                    break
                await asyncio.sleep(0.1)
            else:
                raise AssertionError("positive queue-to-sink/ACK control timed out")
            process.terminate()
            await asyncio.wait_for(process.wait(), 10)
        assert len(calls) == 1, "queue positive control must dispatch exactly once"
        assert calls[0]["method"] == "POST" and calls[0]["path"] == "/execute"
        assert calls[0]["payload"] == {
            "action": "PLACE",
            "account_id": payload.account_id,
            "symbol": payload.symbol,
            "lot_size": payload.lot_size,
            "order_type": payload.order_type,
            "entry_price": payload.entry_price,
            "stop_loss": payload.stop_loss,
            "take_profit": payload.take_profit_1,
            "ticket": None,
            "request_id": fixture_id,
            "meta": {"signal_id": payload.signal_id, "execution_mode": payload.execution_mode},
        }
        assert cache.xrange(stream) == [(message_id, payload.to_stream_fields())]
        assert len(cache.xinfo_groups(stream)) == 1 and cache.xinfo_groups(stream)[0]["name"] == group
        assert cache.xpending(stream, group)["pending"] == 0
        assert database_snapshot() == original_database
        other_redis = redis_snapshot()
        del other_redis[stream]
        assert other_redis == original_redis, "legacy worker changed unrelated Redis state"
        rows.append(
            {
                "case": "positive_queue_to_recording_sink",
                "accepted": True,
                "dispatch_requests": 1,
                "pending": 0,
                "request_id": fixture_id,
                "public_tables_unchanged": True,
                "scope": "SYNTHETIC_LOOPBACK_ONLY",
            }
        )
    finally:
        if process is not None and process.returncode is None:
            process.kill()
            await process.wait()
        sink.shutdown()
        sink.server_close()
        thread.join(timeout=2)
        if seeded:
            cache.delete(stream)
    report["stage"] = "verify_cleanup"
    assert not thread.is_alive(), "recording sink thread survived cleanup"
    assert redis_snapshot() == original_redis and database_snapshot() == original_database
    result = {
        "accepted": True,
        "scope": "ACTUAL_LEGACY_MODULE_REDIS_QUEUE_LOOPBACK_RECORDING_SINK",
        "cases": rows,
        "fixture_cleanup_verified": True,
        "broker_acceptance": "NOT_EXECUTED",
        "all_legacy_paths_coverage": False,
        "source_hashes": {
            relative: hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
            for relative in (
                "execution/async_worker.py",
                "execution/broker_executor.py",
                "execution/execution_plane_flags.py",
                "contracts/execution_queue_contract.py",
                "scripts/ci/engine_trade_process_acceptance.py",
            )
        },
    }

    report.update(result)
    report["stage"] = "complete"


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
            WOLF15_INTERNAL_NETWORK_FIXTURE="YES",
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
        until(lambda: not json.loads(docker("inspect", app))[0]["State"]["Running"], timeout=660)
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
                "execution/async_worker.py",
                "execution/broker_executor.py",
                "contracts/execution_queue_contract.py",
                "allocation/async_worker.py",
                "startup/graceful_shutdown.py",
                "deploy/railway/start_engine.sh",
                "scripts/ci/engine_trade_process_acceptance.py",
            )
        }
        legacy = receipt["legacy_queue_recording_sink"]
        assert legacy["accepted"] and legacy["fixture_cleanup_verified"]
        assert [row["case"] for row in legacy["cases"]] == [
            "disabled_module",
            "incoherent_module",
            "dual_plane_module",
            "disabled_constructor",
            "positive_queue_to_recording_sink",
        ]
        assert all(row["accepted"] for row in legacy["cases"])
        assert legacy["source_hashes"] and all(
            receipt["source_hashes"][path] == digest for path, digest in legacy["source_hashes"].items()
        ), "legacy image and candidate source mismatch"
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
