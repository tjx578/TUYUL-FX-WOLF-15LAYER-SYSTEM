"""Offline built-image API and supervisor-component acceptance; never deploys.

Docker network=none, no source mounts and no inherited application environment.
This does not certify all service roles, database ownership or broker dispatch.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import hashlib
import json
import os
import secrets
import signal
import subprocess
import time
import uuid
from pathlib import Path


def child(mode: str) -> None:
    from core.health_probe import HealthProbe
    from startup.graceful_shutdown import GracefulShutdown
    from startup.task_supervisor import supervised_task

    async def run() -> None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGTERM, stop.set)
        probe = HealthProbe(port=8111, service_name="acceptance-component")
        tasks = [asyncio.create_task(probe.start())]

        async def worker() -> None:
            try:
                if mode == "fault":
                    await asyncio.sleep(2)
                    raise RuntimeError("acceptance_fault")
                await stop.wait()
            finally:
                print("WORKER_DRAINED", flush=True)

        tasks.append(
            asyncio.create_task(
                supervised_task(
                    "AcceptanceWorker",
                    worker,
                    stop,
                    probe,
                    max_restarts=1,
                    cooldown=3,
                    required=True,
                )
            )
        )
        gs = GracefulShutdown(drain_timeout=3)
        gs.register_cleanup("probe", probe.stop)

        async def close_pool() -> None:
            if not tasks[1].done():
                raise AssertionError("worker still active")
            print("POOL_CLOSED", flush=True)

        gs.register_cleanup("recording pool", close_pool)
        stopper = asyncio.create_task(stop.wait())
        try:
            done, _ = await asyncio.wait([*tasks, stopper], return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if task is not stopper:
                    task.result()
        finally:
            stop.set()
            stopper.cancel()
            await gs.shutdown(tasks)

    asyncio.run(run())


def legacy_recording_sink() -> None:
    """Send synthetic requests through the real disabled executor, never a broker."""
    import threading
    import urllib.request
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from execution.broker_executor import BrokerExecutor, ExecutionRequest, OrderAction

    calls = []

    class Sink(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append(("GET", self.path))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        def do_POST(self):
            calls.append(("POST", self.path))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args):
            pass

    os.environ["EXECUTION_ENABLED"] = "false"
    os.environ["LEGACY_PUSH_EXECUTION_ENABLED"] = "false"
    sink = HTTPServer(("127.0.0.1", 0), Sink)
    thread = threading.Thread(target=sink.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{sink.server_port}"
    try:
        with urllib.request.urlopen(base + "/recording-sink-control", timeout=2) as response:
            assert response.status == 200
        executor = BrokerExecutor(ea_url=base)
        outcomes = []
        for action in OrderAction:
            request = ExecutionRequest(
                action=action,
                account_id="disposable-recording-fixture",
                symbol="EURUSD",
                lot_size=0.01,
                order_type="BUY_LIMIT",
                entry_price=1.0,
                stop_loss=0.99,
                take_profit=1.01,
                request_id="offline-" + action.value,
            )
            result = executor.execute(request)
            assert result.success is False and result.raw["sent"] is False
            assert result.error_msg == "execution_disabled"
            outcomes.append(action.value)
        assert calls == [("GET", "/recording-sink-control")]
        print(
            "WOLF15_LEGACY_SINK_RECEIPT "
            + json.dumps(
                {
                    "actual_executor_inputs": outcomes,
                    "control_requests": 1,
                    "dispatch_requests": 0,
                    "execution_enabled": False,
                    "scope": "direct-legacy-executor-disabled-plane",
                }
            ),
            flush=True,
        )
    finally:
        sink.shutdown()
        sink.server_close()
        thread.join(timeout=2)


def docker(*args: str, timeout: int = 180) -> str:
    result = subprocess.run(["docker", *args], text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        # Never include docker invocation/env or raw container log in exceptions.
        raise RuntimeError(f"docker {args[0]} failed (exit {result.returncode})")
    return result.stdout.strip()


def main(image: str, output: Path) -> None:
    receipt: dict = {
        "scope": "built-image-api-and-supervisor-component",
        "checks": {},
        "not_executed": [
            "all-required-role-entrypoints",
            "dedicated-owner-fencing",
            "application-role-PostgreSQL",
            "legacy-path-recording-broker-sink",
            "production-runtime",
            "actual-inflight-database-drain",
        ],
    }
    ids: list[str] = []
    # Ephemeral credentials exist only inside network-isolated disposable containers.
    token = secrets.token_urlsafe(40)
    env = {
        "DASHBOARD_OWNER_USERNAME": "disposable-acceptance",
        "DASHBOARD_JWT_SECRET": token,
        "OBSERVABILITY_MACHINE_KEY": token,
        "OBSERVABILITY_AUTH_MODE": "required",
        "DASHBOARD_OWNER_PASSWORD_HASH": "pbkdf2_sha256$210000$"
        + base64.urlsafe_b64encode(os.urandom(16)).decode()
        + "$"
        + base64.urlsafe_b64encode(os.urandom(32)).decode(),
        "REDIS_URL": "redis://127.0.0.1:6399/0",
        "API_STARTUP_REDIS_TIMEOUT_SEC": "0.1",
        "PYTHONPATH": "/app",
        "GUNICORN_WORKERS": "1",
        "FORCE_HTTPS": "false",
        "PORT": "8000",
    }

    def launch(command: list[str], overrides: dict | None = None) -> str:
        name = "wolf15-acceptance-" + uuid.uuid4().hex[:12]
        args = [
            "run",
            "-d",
            "--name",
            name,
            "--network",
            "none",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--memory",
            "2g",
            "--cpus",
            "2",
        ]
        for key, value in (env | (overrides or {})).items():
            args.extend(["-e", f"{key}={value}"])
        cid = docker(*args, image, *command)
        ids.append(cid)
        assert json.loads(docker("inspect", cid))[0]["Mounts"] == []
        return cid

    def request(cid: str, port: int, path: str) -> dict:
        code = """import urllib.request,urllib.error,json,os
r=urllib.request.Request('http://127.0.0.1:%d%s',headers={'X-Machine-Key':os.environ['OBSERVABILITY_MACHINE_KEY']})
try:
 s=urllib.request.urlopen(r,timeout=2); status=s.status
except urllib.error.HTTPError as e:
 s=e; status=e.code
print(json.dumps({'status':status,'body':json.loads(s.read())}))
""" % (port, path)  # noqa: UP031
        return json.loads(docker("exec", cid, "python", "-c", code, timeout=10))

    def until(fn, seconds: int = 90):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            try:
                value = fn()
                if value:
                    return value
            except (RuntimeError, ValueError):
                pass
            time.sleep(0.4)
        raise AssertionError("acceptance condition timed out")

    def exited(cid: str) -> bool:
        return not json.loads(docker("inspect", cid))[0]["State"]["Running"]

    try:
        receipt["image_id"] = json.loads(docker("image", "inspect", image))[0]["Id"]
        receipt["source_files_sha256"] = {
            str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in map(
                Path,
                [
                    "api/app_factory.py",
                    "startup/task_supervisor.py",
                    "main.py",
                    "core/health_probe.py",
                    "services/orchestrator/state_manager.py",
                    "services/pressure_outbox/runner.py",
                    "startup/graceful_shutdown.py",
                    __file__,
                ],
            )
        }
        api = launch(["python", "-m", "api.owner_dashboard_release"])
        until(lambda: request(api, 8000, "/healthz")["status"] == 200)
        listening = json.loads(
            docker(
                "exec",
                api,
                "python",
                "-c",
                "import json;from pathlib import Path;print(json.dumps([r.split()[1] for f in ['/proc/net/tcp','/proc/net/tcp6'] for r in Path(f).read_text().splitlines()[1:] if r.split()[3]=='0A']))",
            )
        )
        assert len(listening) == 1 and listening[0].endswith(":1F40")
        receipt["checks"]["one_configured_listener"] = "PASS"
        readiness = request(api, 8000, "/readyz")
        assert readiness["status"] == 503 and readiness["body"]["ready"] is False
        assert readiness["body"].get("reasons")
        lines = docker("logs", api).splitlines()
        attest = [
            json.loads(line.split("WOLF15_OWNER_STARTUP_ATTESTATION ")[1])
            for line in lines
            if "WOLF15_OWNER_STARTUP_ATTESTATION " in line
        ]
        assert len(attest) == 1 and not any(attest[0]["background_started"].values())
        receipt["checks"]["api"] = {"liveness": 200, "dependency_readiness": readiness, "worker_attestation": attest[0]}
        docker("stop", "--time", "35", api, timeout=45)
        assert json.loads(docker("inspect", api))[0]["State"]["ExitCode"] == 0
        receipt["checks"]["api_graceful_shutdown"] = "PASS"
        rejected = launch(["python", "-m", "api.owner_dashboard_release"], {"WOLF15_EMBED_ORCHESTRATOR": "true"})
        until(lambda: exited(rejected))
        assert json.loads(docker("inspect", rejected))[0]["State"]["ExitCode"] == 78
        receipt["checks"]["embedded_owner_bootstrap_rejection"] = "PASS"
        # Deliberately remove one required router only in a disposable container's
        # writable layer. This is a fault injection, not the unmodified-image run.
        fault_command = [
            "python",
            "-c",
            "from pathlib import Path;import os;Path('api/allocation_router.py').rename('api/allocation_router.injected-missing');os.execvp('python',['python','-m','api.owner_dashboard_release'])",
        ]
        for strict in [False, True]:
            failed_router = launch(
                fault_command,
                {
                    "ROUTER_BOOT_FAIL_OPEN": "false" if strict else "true",
                    "API_BOOT_FAIL_OPEN": "false" if strict else "true",
                },
            )
            if strict:
                until(lambda cid=failed_router: exited(cid))
                assert json.loads(docker("inspect", failed_router))[0]["State"]["ExitCode"] != 0
                receipt["checks"]["required_router_strict_process_failure"] = "PASS"
            else:
                response = until(lambda cid=failed_router: request(cid, 8000, "/readyz"))
                assert response["status"] == 503
                assert response["body"]["ready"] is False
                assert response["body"]["reasons"] in [["router_boot_failed"], ["api_bootstrap_failed"]]
                receipt["checks"]["required_router_diagnostic_readiness"] = response
                docker("stop", "--time", "35", failed_router, timeout=45)
        orchestrator = launch(
            ["bash", "deploy/railway/start_orchestrator.sh"],
            {
                "DEGRADED_HOLD_TIMEOUT_SEC": "8",
                "REDIS_RETRY_ATTEMPTS": "0",
            },
        )
        response = until(lambda: request(orchestrator, 8000, "/readyz"))
        assert response["status"] == 503 and response["body"]["status"] == "not_ready"
        until(lambda: exited(orchestrator), seconds=45)
        assert json.loads(docker("inspect", orchestrator))[0]["State"]["ExitCode"] != 0
        receipt["checks"]["orchestrator_actual_entrypoint_dependency_failure"] = response
        legacy = launch(["python", "scripts/ci/p1_runtime_acceptance.py", "--child", "legacy-sink"])
        until(lambda: exited(legacy), seconds=30)
        assert json.loads(docker("inspect", legacy))[0]["State"]["ExitCode"] == 0
        sink_receipts = [
            json.loads(line.split("WOLF15_LEGACY_SINK_RECEIPT ")[1])
            for line in docker("logs", legacy).splitlines()
            if "WOLF15_LEGACY_SINK_RECEIPT " in line
        ]
        assert len(sink_receipts) == 1 and sink_receipts[0]["dispatch_requests"] == 0
        receipt["checks"]["direct_legacy_executor_disabled_sink"] = sink_receipts[0]
        for mode in ["fault", "graceful"]:
            cid = launch(["python", "scripts/ci/p1_runtime_acceptance.py", "--child", mode])
            until(lambda cid=cid: request(cid, 8111, "/readyz")["status"] == 200)
            if mode == "fault":
                until(lambda cid=cid: request(cid, 8111, "/readyz")["status"] == 503, seconds=10)
                until(lambda cid=cid: exited(cid), seconds=15)
                assert json.loads(docker("inspect", cid))[0]["State"]["ExitCode"] != 0
            else:
                docker("stop", "--time", "10", cid)
                assert json.loads(docker("inspect", cid))[0]["State"]["ExitCode"] == 0
            logs = docker("logs", cid)
            assert logs.rfind("WORKER_DRAINED") < logs.rfind("POOL_CLOSED")
            assert "WORKER_DRAINED" in logs and "POOL_CLOSED" in logs
            receipt["checks"]["supervisor_component_" + mode] = "PASS"
        receipt["status"] = "PASS_BOUNDED_C02_C06_REMAIN_OPEN"
    except Exception as exc:
        receipt["status"] = "FAIL"
        receipt["failure_class"] = type(exc).__name__
        raise
    finally:
        for cid in ids:
            with contextlib.suppress(Exception):
                docker("rm", "-f", cid)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", choices=["fault", "graceful", "legacy-sink"])
    parser.add_argument("--image")
    parser.add_argument("--output", type=Path, default=Path("artifacts/p1-runtime.json"))
    args = parser.parse_args()
    if args.child == "legacy-sink":
        legacy_recording_sink()
    elif args.child:
        child(args.child)
    elif args.image:
        main(args.image, args.output)
    else:
        parser.error("--image is required outside component child")
