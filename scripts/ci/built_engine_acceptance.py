"""Built root-image engine lifecycle proof; injected dependencies confer no authority."""

import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Reuse only the network-isolated environment and independent HTTP/socket observers.
from scripts.ci.built_api_acceptance import environment, listener_ports, request

SOURCES = (
    "Dockerfile",
    "main.py",
    "services/engine/runner.py",
    "services/engine/runtime_state.py",
    "startup/task_supervisor.py",
    "startup/graceful_shutdown.py",
    "startup/signal_handlers.py",
    "core/health_probe.py",
    "services/shared/health_probe_launcher.py",
    "services/shared/diagnostics.py",
    "deploy/railway/start_engine.sh",
    "deploy/railway/start_engine_consolidated.sh",
    "scripts/ci/built_engine_acceptance.py",
    "scripts/ci/built_api_acceptance.py",
)

CHILD = r"""
import asyncio, sys
from pathlib import Path
from types import SimpleNamespace
from services.engine import runner
mode, folder = sys.argv[1], Path(sys.argv[2])
async def wait_marker(name):
    while not (folder / name).exists(): await asyncio.sleep(0.02)
async def preflight():
    if mode == 'bootstrap_failure':
        await wait_marker('trigger')
        raise RuntimeError('TEST_ONLY_PREFLIGHT_FAILURE')
runner._preflight_checks = preflight
original_import = runner._import_main

def import_main():
    real_main = original_import()
    import main as app
    from infrastructure import redis_health, redis_client
    async def validate(): return SimpleNamespace(ok=True)
    async def noop(*args, **kwargs): pass
    async def health(): return {'healthy': True}
    async def storage_close(): print('CI_STORAGE_CLOSE', flush=True)
    async def pool_close(): print('CI_POOL_CLOSE', flush=True)
    app.validate_engine_startup_async = validate
    app.init_persistent_storage = noop
    app.shutdown_persistent_storage = storage_close
    app.seed_candles_on_startup = noop
    app._validate_api_key = lambda: False
    redis_health.check_redis_pool_health = health
    redis_client.close_pool = pool_close
    async def redis():
        try:
            while True:
                try: await asyncio.Event().wait()
                except asyncio.CancelledError:
                    if mode != 'resistant': raise
                    print('CI_CANCEL_RESISTED', flush=True)
        finally: print('CI_REDIS_DRAINED', flush=True)
    app.run_redis_consumer = redis
    attempts = 0
    async def analysis(*, pairs, pipeline, shutdown_event, on_first_cycle):
        nonlocal attempts
        attempts += 1
        print('CI_ANALYSIS_ATTEMPT_' + str(attempts), flush=True)
        try:
            if mode == 'restart' and attempts == 2:
                (folder / 'restarted').write_text('TEST_ONLY')
                await wait_marker('resume')
            on_first_cycle.set()
            if mode == 'graceful' or (mode == 'restart' and attempts == 2):
                await shutdown_event.wait()
                return
            await wait_marker('trigger')
            if mode == 'returned': return
            if mode == 'cancelled':
                asyncio.current_task().cancel()
                await asyncio.sleep(0)
            raise RuntimeError('TEST_ONLY_ANALYSIS_FAILURE')
        finally: print('CI_ANALYSIS_DRAINED', flush=True)
    app.analysis_loop = analysis
    return real_main
runner._import_main = import_main
runner.run()
"""


def wait_ready(process, expected, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        assert process.poll() is None, "engine exited before expected readiness"
        try:
            status, body = request("/readyz")
            if status == expected:
                assert body.get("status") == ("ready" if expected == 200 else "not_ready")
                return
        except (OSError, ValueError):
            pass
        time.sleep(0.03)
    raise AssertionError("engine readiness deadline expired")


def case(mode):
    env = environment()
    env.update(
        WOLF15_SERVICE_ROLE="engine",
        RUN_MODE="engine-only",
        CONTEXT_MODE="redis",
        ENGINE_HEALTH_PORT="18080",
        MAX_TASK_RESTARTS="1" if mode == "restart" else "0",
        RESTART_COOLDOWN_SEC="0.2",
        DEGRADED_HOLD_TIMEOUT_SEC="2",
        SHUTDOWN_DRAIN_SEC="0.2",
    )
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        log_path = folder / "engine.log"
        with log_path.open("w+") as log:
            process = subprocess.Popen([sys.executable, "-c", CHILD, mode, directory], env=env, stdout=log, stderr=log)
            try:
                wait_ready(process, 503 if mode == "bootstrap_failure" else 200)
                assert listener_ports(process.pid) == [18080], "engine must own one probe listener"
                if mode != "graceful":
                    (folder / "trigger").write_text("TEST_ONLY")
                started = time.monotonic()
                if mode == "restart":
                    deadline = time.monotonic() + 10
                    while not (folder / "restarted").exists():
                        assert process.poll() is None and time.monotonic() < deadline
                        time.sleep(0.02)
                    wait_ready(process, 503, timeout=5)
                    # The first attempt's completed cycle must not make attempt two ready.
                    for _ in range(5):
                        assert request("/readyz")[0] == 503
                        time.sleep(0.04)
                    (folder / "resume").write_text("TEST_ONLY")
                    wait_ready(process, 200, timeout=5)
                normal = mode in {"graceful", "restart"}
                if normal:
                    process.send_signal(signal.SIGTERM)
                else:
                    wait_ready(process, 503, timeout=8)
                code = process.wait(timeout=55 if mode == "resistant" else 15)
                elapsed = time.monotonic() - started
                output = log_path.read_text()
                assert code == (0 if normal else 1), "engine exit does not match lifecycle outcome"
                if mode == "resistant":
                    assert 44 <= elapsed < 55
                    assert "CI_CANCEL_RESISTED" in output
                    assert "CI_POOL_CLOSE" not in output and "CI_STORAGE_CLOSE" not in output
                elif mode != "bootstrap_failure":
                    assert output.index("CI_REDIS_DRAINED") < output.index("CI_STORAGE_CLOSE")
                    assert output.index("CI_ANALYSIS_DRAINED") < output.index("CI_POOL_CLOSE")
                    if normal:
                        assert "holding alive" not in output
                return {
                    "case": mode,
                    "passed": True,
                    "exit_code": code,
                    "listener_ports": [18080],
                    "elapsed_seconds": round(elapsed, 3),
                    "readiness_scope": "FIXTURE_ANALYSIS_CYCLE_AND_REQUIRED_TASK_LIFECYCLE_ONLY",
                    "pool_closed_while_writer_alive": False,
                }
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)


def main():
    receipt = {
        "scope": "BUILT_ENGINE_PROCESS_WITH_INJECTED_DEPENDENCIES_TEST_ONLY",
        "accepted": False,
        "execution_authority": False,
        "broker_acceptance": "NOT_EXECUTED",
        "cases": [],
    }
    try:
        expected = json.loads(os.environ["WOLF15_TEST_ENGINE_SOURCES_JSON"])
        actual = {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in SOURCES}
        assert set(expected) == set(SOURCES) and expected == actual, "built engine source binding differs"
        receipt["source_hashes"] = actual
        for mode in ("bootstrap_failure", "graceful", "exception", "returned", "cancelled", "restart", "resistant"):
            receipt["cases"].append(case(mode))
        receipt["accepted"] = True
    except Exception as error:
        receipt["failure_class"] = type(error).__name__
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
