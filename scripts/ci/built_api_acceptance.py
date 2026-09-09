"""Exercise the built API entrypoint inside a network-isolated CI container."""

import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


def environment():
    env = {key: value for key, value in os.environ.items() if key in {"PATH", "LANG", "PYTHONPATH"}}
    env.update(
        ENV="test",
        APP_ENV="test",
        WOLF15_SERVICE_ROLE="api",
        WOLF15_LOAD_DOTENV="false",
        RAILWAY_ENVIRONMENT="CI_DISPOSABLE",
        WOLF15_EMBED_ORCHESTRATOR="false",
        RUN_MODE="SHADOW",
        DATABASE_URL="postgresql://fixture:fixture@127.0.0.1:1/unavailable_test",
        REDIS_URL="redis://127.0.0.1:1/0",
        ENABLE_PEER_HEALTH="false",
        ENABLE_WS_RELAY="false",
        FORCE_HTTPS="false",
        PORT="18080",
        OBSERVABILITY_AUTH_MODE="required",
        OBSERVABILITY_MACHINE_KEY="ci-built-runtime-fixture-key",
        PYTHONDONTWRITEBYTECODE="1",
        JWT_SECRET="ci-built-runtime-fixture-jwt-at-least-32-characters",
        DASHBOARD_JWT_SECRET="ci-built-runtime-fixture-jwt-at-least-32-characters",
        API_STARTUP_REDIS_TIMEOUT_SEC="0.1",
    )
    for name in (
        "ALLOW_MARKET_EXECUTION",
        "EXECUTION_ENABLED",
        "CANARY_ISSUANCE_ENABLED",
        "EA_COMMAND_DELIVERY_ENABLED",
        "MT5_ORDER_SEND_ENABLED",
        "RISK_RESERVATION_ENABLED",
        "STRATEGY_5SCR_EXECUTION_ENABLED",
        "LEGACY_PUSH_EXECUTION_ENABLED",
    ):
        env[name] = "false"
    return env


def request(path):
    req = urllib.request.Request(
        "http://127.0.0.1:18080" + path, headers={"X-Machine-Key": "ci-built-runtime-fixture-key"}
    )
    try:
        response = urllib.request.urlopen(req, timeout=3)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        return response.status, json.loads(response.read())


def listener_ports(pid):
    """Read the tested Linux process's socket inodes without another listener."""
    inodes = set()
    for descriptor in Path(f"/proc/{pid}/fd").iterdir():
        try:
            target = os.readlink(descriptor)
        except FileNotFoundError:
            continue
        if target.startswith("socket:["):
            inodes.add(target[8:-1])
    ports = []
    for protocol in ("tcp", "tcp6"):
        for line in Path(f"/proc/{pid}/net/{protocol}").read_text().splitlines()[1:]:
            fields = line.split()
            if fields[3] == "0A" and fields[9] in inodes:
                ports.append(int(fields[1].split(":")[1], 16))
    return sorted(ports)


def worker_failure_case(env):
    """Fault the real built API worker after the HTTP listener is available."""
    code = """
import asyncio, sys
from pathlib import Path
from storage import trade_outbox_worker
from storage.postgres_client import pg_client
class FaultWorker:
    def __init__(self, **kwargs): pass
    async def run(self):
        try:
            while not Path(sys.argv[1]).exists(): await asyncio.sleep(0.02)
            raise RuntimeError('CI_REQUIRED_WORKER_FAULT')
        finally: print('CI_WORKER_DRAINED', flush=True)
    async def stop(self): pass
trade_outbox_worker.TradeOutboxWorker = FaultWorker
original_close = pg_client.close
async def close():
    print('CI_POOL_CLOSE', flush=True)
    await original_close()
pg_client.close = close
import api_server
raise SystemExit(api_server.run_api())
"""
    with tempfile.TemporaryDirectory() as folder:
        trigger = Path(folder) / "fail"
        log_path = Path(folder) / "worker.log"
        with log_path.open("w+") as log:
            process = subprocess.Popen([sys.executable, "-c", code, str(trigger)], env=env, stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    assert process.poll() is None, "worker fault fixture exited before serving"
                    try:
                        if request("/healthz")[0] == 200:
                            break
                    except (OSError, ValueError):
                        pass
                    time.sleep(0.05)
                else:
                    raise AssertionError("worker fault fixture listener timeout")
                assert listener_ports(process.pid) == [18080]
                trigger.write_text("TEST_ONLY_FAULT")
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    status, body = request("/readyz")
                    if "required_task_trade_outbox_exception" in body.get("reasons", []):
                        assert status == 503 and body["ready"] is False
                        break
                    time.sleep(0.02)
                else:
                    raise AssertionError("required worker loss was not served as causal 503")
                assert process.wait(timeout=15) == 1, "required worker loss must exit nonzero"
                output = log_path.read_text()
                assert output.index("CI_WORKER_DRAINED") < output.index("CI_POOL_CLOSE")
                return {
                    "case": "required_worker_late_failure",
                    "readyz": 503,
                    "exit_code": 1,
                    "listener_ports": [18080],
                    "drain_before_pool": True,
                    "passed": True,
                }
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)


def main():
    receipt = {"scope": "BUILT_API_BOOTSTRAP_LIFESPAN_AND_HTTP_ONLY", "accepted": False, "cases": []}
    try:
        for path, variable in (
            ("api/app_factory.py", "WOLF15_TEST_APP_SHA256"),
            ("api/router_registry.py", "WOLF15_TEST_REGISTRY_SHA256"),
            ("api_server.py", "WOLF15_TEST_ENTRYPOINT_SHA256"),
            ("startup/required_tasks.py", "WOLF15_TEST_SUPERVISOR_SHA256"),
        ):
            actual = hashlib.sha256(Path(path).read_bytes()).hexdigest()
            assert actual == os.environ[variable], "built source bytes differ"
        env = environment()
        registry = subprocess.run(
            [
                sys.executable,
                "-c",
                "from api.router_registry import ROUTER_ENTRIES,load_routers; r,e=load_routers(); assert not e,e; assert len(r)==len(ROUTER_ENTRIES)>0; print('FULL_REGISTRY_OK')",
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert registry.returncode == 0 and "FULL_REGISTRY_OK" in registry.stdout, registry.stderr[-3000:]
        receipt["cases"].append({"case": "full_built_registry", "passed": True})
        with tempfile.TemporaryDirectory() as folder:
            log_path = Path(folder) / "api.log"
            with log_path.open("w+") as log:
                process = subprocess.Popen([sys.executable, "api_server.py"], env=env, stdout=log, stderr=log)
                try:
                    deadline = time.monotonic() + 60
                    while time.monotonic() < deadline:
                        if process.poll() is not None:
                            raise AssertionError("built API exited before listener: " + log_path.read_text()[-3000:])
                        try:
                            status, _ = request("/healthz")
                            if status == 200:
                                break
                        except (OSError, ValueError):
                            pass
                        time.sleep(0.1)
                    else:
                        raise AssertionError("built API listener startup timed out")
                    status, body = request("/readyz")
                    assert status == 503 and body["ready"] is False and body["router_boot_ok"] is True, body
                    receipt["cases"].append(
                        {"case": "served_dependency_failure", "healthz": 200, "readyz": status, "passed": True}
                    )
                    assert listener_ports(process.pid) == [18080]
                    receipt["cases"].append({"case": "single_configured_listener", "ports": [18080], "passed": True})
                finally:
                    process.terminate()
                    try:
                        code = process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                        raise AssertionError("built API graceful shutdown timed out") from None
                # Uvicorn 0.30.6 re-raises the received signal after lifespan
                # shutdown. A SIGTERM exit alone is not proof of cleanup.
                assert code in {0, -signal.SIGTERM}, f"built API shutdown returned {code}"
                assert "Application shutdown complete" in log_path.read_text(), "lifespan shutdown was not confirmed"
                receipt["cases"].append({"case": "graceful_shutdown", "exit_code": code, "passed": True})
        receipt["cases"].append(worker_failure_case(env))
        faults = (
            (
                "mandatory_router",
                "import api.router_registry as r; r.ROUTER_ENTRIES.append(r.RouterEntry('ci_missing_mandatory_router','router','fixture fault')); import api_server",
                "Mandatory API router import failed",
            ),
            (
                "bootstrap",
                "import api.app_factory as f\ndef fail(): raise RuntimeError('CI_FATAL_BOOTSTRAP_FIXTURE')\nf._create_app_inner=fail\nimport api_server",
                "CI_FATAL_BOOTSTRAP_FIXTURE",
            ),
            (
                "required_worker_bootstrap",
                "from storage import trade_outbox_worker as w\ndef fail(**kwargs): raise RuntimeError('fixture')\nw.TradeOutboxWorker=fail\nimport api_server\nraise SystemExit(api_server.run_api())",
                "REQUIRED_TRADE_OUTBOX_BOOTSTRAP_FAILED",
            ),
        )
        for case, code, reason in faults:
            result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=60)
            assert result.returncode != 0 and reason in result.stderr, result.stderr[-3000:]
            receipt["cases"].append({"case": case, "exit_code": result.returncode, "passed": True})
        receipt["accepted"] = True
    except Exception as exc:
        receipt["failure_class"] = type(exc).__name__
        receipt["diagnostic"] = str(exc)[-3000:]
    print(json.dumps(receipt))
    return 0 if receipt["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
