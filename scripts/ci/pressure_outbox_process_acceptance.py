"""Disposable built pressure role: dispatcher readiness, database loss and drain."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import secrets
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from api.owner_dashboard_release import DISABLED_FLAGS  # noqa: E402
from scripts.ci.orchestrator_process_acceptance import docker, until  # noqa: E402

SOURCES = [
    "services/pressure_outbox/runner.py",
    "storage/pressure_outbox_worker.py",
    "services/pressure_outbox/preflight.py",
    "deploy/railway/start_pressure_outbox.sh",
    "startup/required_tasks.py",
    "startup/graceful_shutdown.py",
    "core/health_probe.py",
]


def run(image, output):
    receipt = dict(
        scope="ACTUAL_PRESSURE_DISPATCHER_DISPOSABLE_POSTGRES",
        accepted=False,
        production="NOT_EXECUTED",
        execution_enabled=False,
        strategy_consumer_enabled=False,
        cases=[],
    )
    network = "wolf15-pressure-" + uuid4().hex[:12]
    resources = []
    created = False
    try:
        receipt["image_id"] = json.loads(docker("image", "inspect", image))[0]["Id"]
        receipt["files"] = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in SOURCES}
        docker("network", "create", "--internal", network)
        created = True
        assert json.loads(docker("network", "inspect", network))[0]["Internal"]
        for case in ["graceful", "database_failure", "dark"]:
            receipt["current_case"] = case
            password = secrets.token_hex(20)
            db_name = network + "-" + case
            db = docker(
                "run",
                "-d",
                "--network",
                network,
                "--network-alias",
                db_name,
                "-e",
                "POSTGRES_USER=fixture",
                "-e",
                "POSTGRES_PASSWORD=" + password,
                "-e",
                "POSTGRES_DB=pressure_disposable_test",
                "postgres:16",
            )
            resources.append(db)
            until(lambda db=db: "accepting connections" in docker("exec", db, "pg_isready", "-U", "fixture"))

            def sql(query, db=db):
                return docker("exec", db, "psql", "-U", "fixture", "-d", "pressure_disposable_test", "-Atc", query)

            sql("ALTER DATABASE pressure_disposable_test SET wolf15.environment_class = 'DISPOSABLE_TEST'")
            dsn = f"postgresql://fixture:{password}@{db_name}:5432/pressure_disposable_test"
            docker(
                "run",
                "--rm",
                "--network",
                network,
                "--entrypoint",
                "python",
                "-e",
                "DATABASE_URL=" + dsn,
                image,
                "-m",
                "alembic",
                "upgrade",
                "head",
                timeout=180,
            )
            token = secrets.token_hex(20)
            env = {key: "false" for key in DISABLED_FLAGS}
            env.update(
                ENV="test",
                APP_ENV="test",
                WOLF15_LOAD_DOTENV="false",
                DATABASE_URL=dsn,
                PORT="18085",
                HEALTH_PROBE_TOKEN=token,
                PRESSURE_OUTBOX_POLL_SECONDS="0.1",
                PRESSURE_OUTBOX_EXPECTED_PHASE="dark" if case == "dark" else "dispatcher",
                SIGNAL_PRESSURE_OUTBOX_ENABLED="false" if case == "dark" else "true",
                SIGNAL_PRESSURE_OUTBOX_DISPATCH_ENABLED="false" if case == "dark" else "true",
                SIGNAL_PRESSURE_OUTBOX_WRITE_ENABLED="false",
                STRATEGY_5SCR_PRESSURE_CONSUMER_ENABLED="false",
                STRATEGY_5SCR_EVIDENCE_ENABLED="false",
                STRATEGY_5SCR_OUTCOME_ENABLED="false",
                STRATEGY_5SCR_LIFECYCLE_V2_ENABLED="false",
                STRATEGY_5SCR_SHADOW_EVIDENCE_V2_ENABLED="false",
            )
            args = []
            for key, value in env.items():
                args.extend(["-e", key + "=" + value])
            app = docker(
                "run",
                "-d",
                "--network",
                network,
                "--entrypoint",
                "bash",
                *args,
                image,
                "deploy/railway/start_pressure_outbox.sh",
            )
            resources.append(app)
            config = json.loads(docker("inspect", app))[0]
            assert (
                config["Image"] == receipt["image_id"]
                and not config["Mounts"]
                and not config["HostConfig"]["PortBindings"]
            )
            actual = json.loads(
                docker(
                    "exec",
                    app,
                    "python",
                    "-c",
                    'import hashlib,json; print(json.dumps({p:hashlib.sha256(open(p,"rb").read()).hexdigest() for p in '
                    + repr(SOURCES)
                    + "}))",
                )
            )
            assert actual == receipt["files"]

            def http(path, app=app, token=token):
                code = (
                    "import urllib.request,urllib.error,json; "
                    'r=urllib.request.Request("http://127.0.0.1:18085/'
                    + path
                    + '",headers={"Authorization":"Bearer '
                    + token
                    + '"}); '
                    "\ntry:\n with urllib.request.urlopen(r,timeout=1) as v: print(json.dumps([v.status,v.read().decode()]))"
                    "\nexcept urllib.error.HTTPError as e: print(json.dumps([e.code,e.read().decode()]))"
                )
                return json.loads(docker("exec", app, "python", "-c", code))

            until(lambda http=http: http("healthz")[0] == 200)
            expected = 503 if case == "dark" else 200
            until(lambda http=http, expected=expected: http("readyz")[0] == expected)
            status = http("status")[1]
            assert ("pressure-outbox:DISABLED" if case == "dark" else "pressure-outbox:REQUIRED") in status
            assert "evidence_worker:DISABLED" in status and "outcome_worker:DISABLED" in status
            connections = int(
                sql("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid()")
            )
            assert connections > 0
            if case == "database_failure":
                docker("stop", "-t", "1", db)
                until(lambda http=http: http("readyz")[0] == 503, timeout=60)
                until(lambda app=app: not json.loads(docker("inspect", app))[0]["State"]["Running"], timeout=60)
            else:
                docker("stop", "-t", "20", app)
                assert (
                    sql(
                        "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid()"
                    )
                    == "0"
                )
            state = json.loads(docker("inspect", app))[0]["State"]
            assert state["ExitCode"] not in [137, 143]
            assert (state["ExitCode"] != 0) if case == "database_failure" else (state["ExitCode"] == 0)
            receipt["cases"].append(
                dict(case=case, ready_status=expected, exit_code=state["ExitCode"], real_pool_connections=connections)
            )
        receipt["accepted"] = True
    finally:
        output.parent.mkdir(parents=True, exist_ok=True)
        if not receipt["accepted"]:
            for resource in resources:
                with contextlib.suppress(Exception):
                    (output.parent / (resource[:12] + ".log")).write_text(docker("logs", resource), encoding="utf-8")
        for resource in reversed(resources):
            with contextlib.suppress(Exception):
                docker("rm", "-fv", resource)
        if created:
            with contextlib.suppress(Exception):
                docker("network", "rm", network)
        output.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.image, args.output)
