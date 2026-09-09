"""Actual ingest entrypoint with local synthetic REST/WS providers and real Redis.

The outer harness uses a fresh internal Docker network. Provider transport alone
is redirected; the ingest runner, warmup, parsing, readiness and shutdown are real.
This proves fixture infrastructure behavior, not production market-data quality.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SOURCE_PATHS = (
    "ingest_service.py",
    "ingest/service_runner.py",
    "ingest/finnhub_ws.py",
    "services/ingest/ingest_worker.py",
    "deploy/railway/start_ingest.sh",
    "scripts/ci/ingest_process_acceptance.py",
)


async def child():
    import psycopg
    import redis
    from websockets.asyncio.server import serve

    assert os.environ.get("WOLF15_INGEST_DISPOSABLE_CHILD") == "YES_I_UNDERSTAND"
    assert Path("/.dockerenv").is_file(), "child must run in the isolated container"
    assert urlsplit(os.environ["REDIS_URL"]).hostname == "cache"
    db_url = urlsplit(os.environ["DATABASE_URL"])
    assert db_url.hostname == "database" and db_url.path == "/ingest_disposable_test"
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        assert connection.execute(
            "SELECT current_database(), current_setting('wolf15.environment_class',true)"
        ).fetchone() == ("ingest_disposable_test", "DISPOSABLE_TEST")

    provider_counts = {"rest": 0, "ticks": 0}

    class Provider(BaseHTTPRequestHandler):
        def do_GET(self):
            query = parse_qs(urlsplit(self.path).query)
            resolution = query.get("resolution", ["60"])[0]
            seconds = {"D": 86400, "W": 604800, "M": 2592000}.get(resolution)
            if seconds is None:
                seconds = max(60, int(resolution) * 60)
            end = int(time.time()) // seconds * seconds
            count = 400
            body = json.dumps(
                {
                    "s": "ok",
                    "t": [end - (count - i) * seconds for i in range(count)],
                    "o": [1.2] * count,
                    "c": [1.2001] * count,
                    "h": [1.2002] * count,
                    "l": [1.1999] * count,
                    "v": [100] * count,
                }
            ).encode()
            provider_counts["rest"] += 1
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    async def websocket(ws):
        async for message in ws:
            item = json.loads(message)
            if item.get("type") == "subscribe":
                while True:
                    await ws.send(
                        json.dumps(
                            {
                                "type": "trade",
                                "data": [
                                    {
                                        "s": item["symbol"],
                                        "p": 1.2001,
                                        "t": int(time.time() * 1000),
                                        "v": 1,
                                    }
                                ],
                            }
                        )
                    )
                    provider_counts["ticks"] += 1
                    await asyncio.sleep(0.2)

    http = ThreadingHTTPServer(("127.0.0.1", 19091), Provider)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    cache = redis.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    case = os.environ["WOLF15_INGEST_CASE"]
    assert case in {"graceful", "required_fault"}
    receipt = {"accepted": False, "scope": "ACTUAL_INGEST_SYNTHETIC_PROVIDER_REAL_REDIS", "case": case}
    if case == "required_fault":
        receipt["fault_scope"] = "INJECTED_REQUIRED_ACTOR_FAILURE"
    receipt["source_hashes"] = {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in SOURCE_PATHS}
    try:
        async with serve(websocket, "127.0.0.1", 19090):
            with tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary)
                # Redirect provider transport; retain actual provider implementations.
                (folder / "sitecustomize.py").write_text(
                    "import config_loader\n"
                    "config_loader.get_enabled_symbols=lambda:['EURUSD']\n"
                    "import ingest.finnhub_ws as ws\n"
                    "ws.FINNHUB_WS_URL='ws://127.0.0.1:19090'\n"
                    "import ingest.dependencies as dep\n"
                    "dep._enabled_symbols=lambda:['EURUSD']\n"
                    "from ingest.finnhub_candles import FinnhubCandleFetcher\n"
                    "original=FinnhubCandleFetcher.__init__\n"
                    "def init(self):\n"
                    " original(self)\n self.base_url='http://127.0.0.1:19091'\n self.request_delay=0\n"
                    "FinnhubCandleFetcher.__init__=init\n"
                )
                trigger = folder / "required-fault"
                if case == "required_fault":
                    with (folder / "sitecustomize.py").open("a") as fixture:
                        fixture.write(
                            "import asyncio,os\nfrom pathlib import Path\n"
                            "import ingest.service_runner as role\n"
                            "healthy=role._HealthCheckRunner.run\n"
                            "async def injected(self):\n"
                            " task=asyncio.create_task(healthy(self))\n"
                            " try:\n"
                            "  while not Path(os.environ['INGEST_FAULT_TRIGGER']).exists():\n"
                            "   if task.done(): return await task\n"
                            "   await asyncio.sleep(0.02)\n"
                            "  raise RuntimeError('DISPOSABLE_REQUIRED_INGEST_FAULT')\n"
                            " finally:\n"
                            "  task.cancel()\n  await asyncio.gather(task,return_exceptions=True)\n"
                            "role._HealthCheckRunner.run=injected\n"
                        )
                env = dict(os.environ, PYTHONPATH=str(folder) + os.pathsep + "/app", INGEST_FAULT_TRIGGER=str(trigger))
                log_path = Path("/tmp/ingest-role.log")
                with log_path.open("w") as log:
                    process = await asyncio.create_subprocess_exec(
                        "bash",
                        "deploy/railway/start_ingest.sh",
                        env=env,
                        stdout=log,
                        stderr=log,
                    )
                    try:
                        import urllib.error
                        import urllib.request

                        def status():
                            try:
                                with urllib.request.urlopen("http://127.0.0.1:18084/readyz", timeout=2) as response:
                                    return response.status
                            except urllib.error.HTTPError as error:
                                return error.code
                            except OSError:
                                return None

                        deadline = time.monotonic() + 150
                        while time.monotonic() < deadline:
                            assert process.returncode is None, "ingest exited before readiness"
                            if await asyncio.to_thread(status) == 200 and provider_counts["ticks"] > 2:
                                break
                            await asyncio.sleep(0.2)
                        else:
                            raise AssertionError("ingest real-provider fixture readiness did not arrive")
                        from core.redis_keys import HEARTBEAT_INGEST, latest_tick

                        assert cache.get(HEARTBEAT_INGEST), "actual ingest did not publish producer heartbeat"
                        assert cache.hget(latest_tick("EURUSD"), "data"), (
                            "actual parser did not persist the fixture tick"
                        )
                        assert provider_counts["rest"] > 0 and provider_counts["ticks"] > 2
                        with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
                            assert (
                                connection.execute(
                                    "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                                    "AND pid<>pg_backend_pid()"
                                ).fetchone()[0]
                                > 0
                            ), "ingest pool did not connect to real PostgreSQL"
                        if case == "graceful":
                            process.terminate()
                            code = await asyncio.wait_for(process.wait(), 30)
                            assert code == 0, "ingest did not drain on SIGTERM"
                        else:
                            trigger.write_text("DISPOSABLE_REQUIRED_INGEST_FAULT")
                            deadline = time.monotonic() + 10
                            while time.monotonic() < deadline:
                                if await asyncio.to_thread(status) == 503:
                                    receipt["ready_after_required_fault"] = 503
                                    break
                                await asyncio.sleep(0.02)
                            else:
                                raise AssertionError("required ingest fault did not clear readiness")
                            code = await asyncio.wait_for(process.wait(), 100)
                            assert code not in (0, -9), "required ingest failure did not exit nonzero"
                        with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
                            assert (
                                connection.execute(
                                    "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                                    "AND pid<>pg_backend_pid()"
                                ).fetchone()[0]
                                == 0
                            ), "ingest PostgreSQL pool survived shutdown"
                        receipt.update(accepted=True, readyz=200, exit_code=code, provider_counts=provider_counts)
                    finally:
                        if process.returncode is None:
                            process.kill()
                            await process.wait()
                        if not receipt["accepted"]:
                            receipt["diagnostic"] = log_path.read_text()[-6000:]
    finally:
        cache.close()
        http.shutdown()
        http.server_close()
        print("INGEST_ROLE_RECEIPT " + json.dumps(receipt), flush=True)


def run_case(image, output, case):
    from api.owner_dashboard_release import DISABLED_FLAGS
    from scripts.ci.orchestrator_process_acceptance import docker, until

    name = "wolf15-ingest-" + uuid4().hex[:12]
    resources = []
    network_created = False
    receipt = {"accepted": False, "scope": "INTERNAL_DOCKER_INGEST", "execution_enabled": False}
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
            "POSTGRES_DB=ingest_disposable_test",
            "postgres:16-alpine",
        )
        resources.append(database)
        until(lambda: "accepting connections" in docker("exec", database, "pg_isready", "-U", "fixture"))
        docker(
            "exec",
            database,
            "psql",
            "-U",
            "fixture",
            "-d",
            "ingest_disposable_test",
            "-c",
            "ALTER DATABASE ingest_disposable_test SET wolf15.environment_class = 'DISPOSABLE_TEST'",
        )
        dsn = f"postgresql://fixture:{password}@database:5432/ingest_disposable_test"
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
            WOLF15_INGEST_DISPOSABLE_CHILD="YES_I_UNDERSTAND",
            WOLF15_INGEST_CASE=case,
            REDIS_URL="redis://cache:6379/0",
            DATABASE_URL=dsn,
            RUN_MODE="SHADOW",
            PORT="18084",
            FINNHUB_API_KEY="synthetic-local-provider-fixture",
            ALPHAVANTAGE_ENABLED="false",
            JWT_SECRET="synthetic-local-provider-jwt-fixture-minimum-32",
            FORCE_HTTPS="false",
        )
        args = ["create", "--network", name, "--entrypoint", "python"]
        for key, value in env.items():
            args += ["-e", f"{key}={value}"]
        args += [image, "scripts/ci/ingest_process_acceptance.py", "--child"]
        app = docker(*args)
        resources.append(app)
        container = json.loads(docker("inspect", app))[0]
        assert not container["Mounts"] and not container["HostConfig"]["PortBindings"]
        docker("start", app)
        until(lambda: not json.loads(docker("inspect", app))[0]["State"]["Running"], timeout=300)
        logs = docker("logs", app)
        rows = [
            line.removeprefix("INGEST_ROLE_RECEIPT ")
            for line in logs.splitlines()
            if line.startswith("INGEST_ROLE_RECEIPT ")
        ]
        assert len(rows) == 1, "missing ingest receipt"
        result = json.loads(rows[0])
        receipt.update(result)
        receipt["image_id"] = json.loads(docker("image", "inspect", image))[0]["Id"]
        assert json.loads(docker("inspect", app))[0]["Image"] == receipt["image_id"]
        assert receipt["source_hashes"] == {
            path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in SOURCE_PATHS
        }, "actual container source differs from candidate"
        assert json.loads(docker("inspect", app))[0]["State"]["ExitCode"] == 0
        assert receipt["accepted"]
    except Exception as error:
        receipt.update(accepted=False, failure_class=type(error).__name__, diagnostic=str(error)[-1000:])
        receipt["owned_container_logs"] = {}
        for resource in resources:
            with contextlib.suppress(Exception):
                receipt["owned_container_logs"][resource] = docker("logs", resource)[-8000:]
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


def run(image, output):
    results = []
    for case in ("graceful", "required_fault"):
        case_output = output.with_name(output.stem + "-" + case + ".json")
        run_case(image, case_output, case)
        results.append(json.loads(case_output.read_text()))
    receipt = {"accepted": all(result["accepted"] for result in results), "cases": results}
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
