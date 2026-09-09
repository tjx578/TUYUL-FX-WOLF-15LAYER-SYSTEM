"""Disposable real-dependency acceptance of Railway's Gunicorn entrypoint.

Synthetic Redis heartbeat/tick timestamps exercise infrastructure readiness only;
these fixtures do not prove healthy market producers or trading readiness.
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ci.built_api_acceptance import environment, request  # noqa: E402
from tests.integration.postgres_test_guard import (  # noqa: E402
    require_destructive_postgres_opt_in,
    require_disposable_postgres_target,
)


def main():
    import psycopg
    import redis

    require_destructive_postgres_opt_in(os.environ.get("WOLF15_ALLOW_DESTRUCTIVE_PG_TESTS", ""))
    dsn = os.environ["WOLF15_PAIR_ACTIVITY_TEST_DATABASE_URL"]
    database = os.environ["WOLF15_POSTGRES_TEST_DATABASE"]
    require_disposable_postgres_target(dsn, expected_database=database)
    assert not urlsplit(dsn).query and not urlsplit(dsn).fragment
    redis_url = os.environ["WOLF15_C06_TEST_REDIS_URL"]
    target = urlsplit(redis_url)
    assert target.scheme == "redis" and target.hostname in {"localhost", "127.0.0.1", "::1"}
    assert target.path == "/14" and not target.username and not target.password
    assert not target.query and not target.fragment
    assert os.environ["WOLF15_C06_DISPOSABLE_REDIS"] == "YES_I_UNDERSTAND"
    with psycopg.connect(dsn) as connection:
        identity = connection.execute(
            "SELECT current_database(), current_setting('wolf15.environment_class',true), "
            "current_setting('wolf15.destructive_tests_allowed',true)"
        ).fetchone()
        assert identity == (database, "DISPOSABLE_TEST", "true")
    client = redis.Redis.from_url(redis_url)
    assert client.ping()
    # The harness owns an empty disposable Redis database, never flushes it.
    assert client.dbsize() == 0, "effective-role Redis database must be empty"
    env = environment()
    application_name = "c06_api_" + uuid4().hex
    env.update(DATABASE_URL=dsn + "?application_name=" + application_name, REDIS_URL=redis_url, GUNICORN_WORKERS="1")
    with tempfile.TemporaryDirectory() as folder:
        folder = Path(folder)
        trigger = folder / "fault"
        # Inject a separate faulting required task; actual outbox is retained.
        (folder / "sitecustomize.py").write_text(
            "import asyncio,os\nfrom pathlib import Path\n"
            "from startup.required_tasks import RequiredTaskSupervisor\n"
            "original=RequiredTaskSupervisor.start\n"
            "def start(self,name,coro):\n"
            " task=original(self,name,coro)\n"
            " if name=='trade_outbox':\n"
            "  self.states['ci_fault']='STARTING'\n"
            "  async def fault():\n"
            "   while not Path(os.environ['C06_FAULT_TRIGGER']).exists(): await asyncio.sleep(0.02)\n"
            "   raise RuntimeError('C06_REQUIRED_TASK_FAULT')\n"
            "  original(self,'ci_fault',fault())\n"
            " return task\n"
            "RequiredTaskSupervisor.start=start\n"
        )
        env.update(PYTHONPATH=str(folder) + os.pathsep + str(ROOT), C06_FAULT_TRIGGER=str(trigger))
        output = Path(os.environ.get("WOLF15_C06_OUTPUT", "artifacts/c06-effective-api"))
        output.mkdir(parents=True, exist_ok=True)
        receipt = {
            "scope": "DISPOSABLE_API_ROLE_REAL_DB_REDIS_SYNTHETIC_FEED",
            "accepted": False,
            "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "source_sha256": {
                name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                for name in (
                    "deploy/railway/start_api.sh",
                    "deploy/uvicorn_worker.py",
                    "startup/required_task_server.py",
                    "startup/required_tasks.py",
                    "api/app_factory.py",
                    "scripts/ci/effective_api_role_acceptance.py",
                )
            },
        }
        with (output / "gunicorn.log").open("w") as log:
            process = subprocess.Popen(
                ["bash", "deploy/railway/start_api.sh"], cwd=ROOT, env=env, stdout=log, stderr=log
            )
            try:
                # Match canonical key functions/config, without replacing server dependencies.
                from api.allocation_router import _latest_tick_key, load_pairs
                from state.redis_keys import HEARTBEAT_ENGINE, HEARTBEAT_INGEST, HEARTBEAT_ORCHESTRATOR

                deadline = time.monotonic() + 90
                body = {}
                while time.monotonic() < deadline:
                    assert process.poll() is None, "effective API exited before readiness"
                    for key in (HEARTBEAT_ENGINE, HEARTBEAT_INGEST, HEARTBEAT_ORCHESTRATOR):
                        client.set(key, json.dumps({"ts": time.time()}), ex=60)
                    for pair in load_pairs():
                        client.hset(_latest_tick_key(pair["symbol"]), mapping={"last_seen_ts": str(time.time())})
                    try:
                        status, body = request("/readyz")
                        if status == 200:
                            break
                    except (OSError, ValueError):
                        pass
                    time.sleep(0.2)
                else:
                    raise AssertionError("effective API did not become ready")
                assert body["runtime"]["states"]["trade_outbox"] == "RUNNING"
                # Independently require actual server connections from the API pool.
                with psycopg.connect(dsn) as connection:
                    assert (
                        connection.execute(
                            "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                            "AND pid<>pg_backend_pid()"
                        ).fetchone()[0]
                        > 0
                    )
                receipt["healthy_dependencies_readyz"] = 200
                receipt["actual_outbox_retained"] = True
                trigger.write_text("DISPOSABLE_FAULT")
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    status, body = request("/readyz")
                    if "required_task_ci_fault_exception" in body.get("reasons", []):
                        assert status == 503
                        break
                    time.sleep(0.02)
                else:
                    raise AssertionError("required loss did not expose causal 503")
                code = process.wait(timeout=35)
                assert code != 0, "Gunicorn master must fail after required task loss"
                receipt.update(causal_readyz=503, master_exit=code, accepted=True)
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=35)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
                client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
