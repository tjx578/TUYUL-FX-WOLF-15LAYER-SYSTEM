"""Actual orchestrator process on a fresh internal Docker network and Redis.

No host ports, source mounts, production credentials or trading activation.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.owner_dashboard_release import DISABLED_FLAGS  # noqa: E402


def docker(*args, timeout=90):
    result = subprocess.run(["docker", *args], text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"docker {args[0]} failed: {result.stderr[-1000:]}")
    return result.stdout.strip()


def until(check, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = check()
            if result:
                return result
        except (RuntimeError, ValueError, KeyError):
            pass
        time.sleep(0.1)
    raise AssertionError("process acceptance condition timed out")


def run(image, redis_image, output):
    receipt = {
        "scope": "ACTUAL_ORCHESTRATOR_INTERNAL_NETWORK",
        "accepted": False,
        "cases": [],
        "production": "NOT_EXECUTED",
        "trading_enabled": False,
    }
    resources = []
    network = "wolf15-orch-" + uuid4().hex[:12]
    network_created = False
    files = [
        "services/orchestrator/state_manager.py",
        "services/orchestrator/mode_owner.py",
        "deploy/railway/start_orchestrator.sh",
        "core/health_probe.py",
        "services/shared/diagnostics.py",
        "scripts/ci/orchestrator_process_acceptance.py",
    ]
    try:
        receipt["image_id"] = json.loads(docker("image", "inspect", image))[0]["Id"]
        receipt["files"] = {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in files}
        docker("network", "create", "--internal", network)
        network_created = True
        assert json.loads(docker("network", "inspect", network))[0]["Internal"] is True
        for case in ["graceful", "dependency_failure"]:
            receipt["current_case"] = case
            redis_name = network + "-redis-" + case
            cache = docker(
                "run",
                "-d",
                "--name",
                redis_name,
                "--network",
                network,
                "--network-alias",
                redis_name,
                redis_image,
                "redis-server",
                "--save",
                "",
                "--appendonly",
                "no",
            )
            resources.append(cache)
            until(lambda cache=cache: docker("exec", cache, "redis-cli", "ping") == "PONG")
            env = {name: "false" for name in DISABLED_FLAGS}
            env.update(
                ENV="test",
                APP_ENV="test",
                WOLF15_LOAD_DOTENV="false",
                REDIS_URL=f"redis://{redis_name}:6379/0",
                PORT="18083",
                REDIS_RETRY_ATTEMPTS="0",
                REDIS_SOCKET_TIMEOUT_SEC="1",
                REDIS_SOCKET_CONNECT_TIMEOUT_SEC="1",
                REDIS_POOL_TIMEOUT_SEC="1",
                DEGRADED_HOLD_TIMEOUT_SEC="8",
                ORCHESTRATOR_FATAL_DIAGNOSTIC_HOLD_SEC="8",
            )
            command = [
                "run",
                "-d",
                "--name",
                network + "-app-" + case,
                "--network",
                network,
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--memory",
                "2g",
                "--cpus",
                "2",
            ]
            for name, value in env.items():
                command.extend(["-e", f"{name}={value}"])
            app = docker(*command, image, "bash", "deploy/railway/start_orchestrator.sh")
            resources.append(app)
            inspected = json.loads(docker("inspect", app))[0]
            assert inspected["Mounts"] == [] and not inspected["HostConfig"]["PortBindings"]
            copied = json.loads(
                docker(
                    "exec",
                    app,
                    "python",
                    "-c",
                    "import hashlib,json;from pathlib import Path;print(json.dumps({p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in "
                    + repr(files)
                    + "}))",
                )
            )
            assert copied == receipt["files"]

            def request(app=app):
                return json.loads(
                    docker(
                        "exec",
                        app,
                        "python",
                        "-c",
                        """import json,urllib.request,urllib.error
try:
 r=urllib.request.urlopen('http://127.0.0.1:18083/readyz',timeout=3);status=r.status
except urllib.error.HTTPError as e:
 r=e;status=e.code
print(json.dumps({'status':status,'body':json.loads(r.read())}))
""",
                        timeout=10,
                    )
                )

            def read(key, cache=cache):
                value = docker("exec", cache, "redis-cli", "--raw", "GET", key)
                return json.loads(value) if value else None

            until(lambda: request()["status"] == 200)
            keys = json.loads(
                docker(
                    "exec",
                    app,
                    "python",
                    "-c",
                    "import json;from core.redis_keys import ORCHESTRATOR_STATE,HEARTBEAT_ORCHESTRATOR,KILL_SWITCH;print(json.dumps({'state':ORCHESTRATOR_STATE,'heartbeat':HEARTBEAT_ORCHESTRATOR,'kill':KILL_SWITCH,'lease':KILL_SWITCH+':mode-owner'}))",
                )
            )
            state = until(lambda key=keys["state"]: (value := read(key)) and value["mode"] == "KILL_SWITCH" and value)
            assert state["compliance_code"] == "ACCOUNT_STATE_MISSING"
            assert read(keys["kill"])["active"] is True
            assert docker("exec", cache, "redis-cli", "EXISTS", keys["lease"]) == "1"
            # Count only sockets owned by the actual role PID1, excluding Docker DNS.
            listeners = json.loads(
                docker(
                    "exec",
                    app,
                    "python",
                    "-c",
                    """import os,json
from pathlib import Path
inodes=set()
for p in Path('/proc/1/fd').iterdir():
 try: target=os.readlink(p)
 except FileNotFoundError: continue
 if target.startswith('socket:['): inodes.add(target[8:-1])
print(json.dumps([int(r.split()[1].split(':')[1],16) for f in ['tcp','tcp6'] for r in Path('/proc/1/net/'+f).read_text().splitlines()[1:] if r.split()[3]=='0A' and r.split()[9] in inodes]))
""",
                )
            )
            assert listeners == [18083]
            if case == "graceful":
                docker("stop", "--time", "20", app, timeout=30)
                exit_code = json.loads(docker("inspect", app))[0]["State"]["ExitCode"]
                assert exit_code == 0
                final = read(keys["state"])
                assert final["event"] == "SHUTDOWN" and final["mode"] == "KILL_SWITCH"
                assert docker("exec", cache, "redis-cli", "EXISTS", keys["lease"]) == "0"
                # Redis reports no remaining subscriptions after role shutdown.
                assert docker("exec", cache, "redis-cli", "PUBSUB", "NUMPAT") == "0"
                subscribed = docker("exec", cache, "redis-cli", "PUBSUB", "CHANNELS")
                assert not subscribed
            else:
                docker("stop", "--time", "5", cache, timeout=15)
                receipt["fault_stage"] = "awaiting_dependency_readiness_rejection"
                until(lambda: request()["status"] == 503, timeout=10)
                receipt["fault_stage"] = "awaiting_nonzero_exit_after_bounded_diagnostics"
                until(lambda app=app: not json.loads(docker("inspect", app))[0]["State"]["Running"], timeout=25)
                exit_code = json.loads(docker("inspect", app))[0]["State"]["ExitCode"]
                assert exit_code not in (0, 137)
            receipt["cases"].append(
                {
                    "case": case,
                    "ready_before_fault": 200,
                    "missing_account_mode": "KILL_SWITCH",
                    "listener_ports": listeners,
                    "exit_code": exit_code,
                    "passed": True,
                }
            )
        receipt["accepted"] = True
    except Exception as exc:
        receipt["failure_class"] = type(exc).__name__
        receipt["diagnostic"] = str(exc)[-1500:]
    finally:
        output.parent.mkdir(parents=True, exist_ok=True)
        if not receipt["accepted"]:
            for index, resource in enumerate(resources):
                with contextlib.suppress(Exception):
                    result = subprocess.run(["docker", "logs", resource], capture_output=True, text=True, timeout=15)
                    (output.parent / f"orchestrator-container-{index}.log").write_text(result.stdout + result.stderr)
        for resource in reversed(resources):
            with contextlib.suppress(Exception):
                docker("rm", "-f", "-v", resource)
        if network_created:
            with contextlib.suppress(Exception):
                docker("network", "rm", network)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(receipt, indent=2) + "\n")
    return 0 if receipt["accepted"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--redis-image", default="redis:7-alpine")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(run(args.image, args.redis_image, args.output))
