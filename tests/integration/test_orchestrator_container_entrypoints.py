"""T14: exact-tree container and effective-entrypoint smoke.

The inexpensive contract tests always run.  The Docker smoke is deliberately
opt-in because it builds the current *committed* tree and creates disposable
local resources.  It never pulls images and it refuses to run unless the caller
binds the expected commit and tree explicitly.

Example (PowerShell)::

    $env:WOLF15_RUN_T14_CONTAINER_SMOKE = "1"
    $env:WOLF15_T14_EXPECTED_COMMIT = git rev-parse HEAD
    $env:WOLF15_T14_EXPECTED_TREE = git rev-parse 'HEAD^{tree}'
    $env:WOLF15_T14_REDIS_IMAGE = "redis@sha256:<locally-present-digest>"
    $env:WOLF15_T14_POSTGRES_IMAGE = "postgres@sha256:<locally-present-digest>"
    pytest -q tests/integration/test_orchestrator_container_entrypoints.py

The test exercises no command, broker, or execution path.  All execution
controls are supplied as literal ``false`` and the orchestrator command secret
is set to a non-production test value.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
API_START = ROOT / "deploy" / "railway" / "start_api.sh"
ORCHESTRATOR_START = ROOT / "deploy" / "railway" / "start_orchestrator.sh"

_FALSE_CONTROLS = (
    "ALLOW_MARKET_EXECUTION",
    "EXECUTION_ENABLED",
    "MT5_ORDER_SEND_ENABLED",
    "EA_COMMAND_DELIVERY_ENABLED",
    "RISK_RESERVATION_ENABLED",
    "STRATEGY_5SCR_EXECUTION_ENABLED",
    "CANARY_ISSUANCE_ENABLED",
)
_DISPOSABLE_REDIS_PASSWORD = "wolf15_t14_disposable_redis"


def _run(*args: str, timeout: float = 120.0, check: bool = True) -> subprocess.CompletedProcess[str]:
    # Docker Desktop on Windows can leave inherited pipe handles open after the
    # CLI process has completed its daemon operation.  ``capture_output=True``
    # then leaves ``subprocess.communicate`` waiting in reader threads even
    # though the container already exists.  Real temporary files preserve the
    # exact output without relying on pipe EOF propagation across that process
    # boundary.
    with (
        tempfile.TemporaryFile(mode="w+", encoding="utf-8") as stdout_file,
        tempfile.TemporaryFile(mode="w+", encoding="utf-8") as stderr_file,
    ):
        completed = subprocess.run(
            args,
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=stdout_file,
            stderr=stderr_file,
            check=False,
            text=True,
            timeout=timeout,
        )
        stdout_file.seek(0)
        stderr_file.seek(0)
        result = subprocess.CompletedProcess(
            completed.args,
            completed.returncode,
            stdout_file.read(),
            stderr_file.read(),
        )
    if check and result.returncode != 0:
        pytest.fail(
            f"command failed ({result.returncode}): {args!r}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        pytest.fail(f"{name} must be bound explicitly for the T14 Docker smoke")
    return value


def _docker_json(*args: str) -> dict[str, Any]:
    value = json.loads(_run("docker", *args).stdout)
    assert isinstance(value, dict)
    return value


def _wait_healthy(container: str, *, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    last = "not attempted"
    while time.monotonic() < deadline:
        result = _run(
            "docker",
            "inspect",
            "--format",
            "{{json .State.Health}}",
            container,
            check=False,
            timeout=10,
        )
        if result.returncode == 0:
            health = json.loads(result.stdout)
            if isinstance(health, dict) and health.get("Status") == "healthy":
                return
            last = json.dumps(health, sort_keys=True)
        else:
            last = f"exit={result.returncode} stdout={result.stdout!r} stderr={result.stderr!r}"
        time.sleep(0.5)
    pytest.fail(f"container {container} did not become healthy: {last}")


def _published_port(container: str, container_port: int) -> int:
    result = _run(
        "docker",
        "inspect",
        "--format",
        f'{{{{(index (index .NetworkSettings.Ports "{container_port}/tcp") 0).HostPort}}}}',
        container,
    )
    return int(result.stdout.strip())


def _wait_http(port: int, path: str, *, timeout: float = 90.0) -> None:
    deadline = time.monotonic() + timeout
    last = "not attempted"
    url = f"http://127.0.0.1:{port}{path}"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:  # noqa: S310 - loopback-only test endpoint
                if response.status == 200:
                    return
                last = f"HTTP {response.status}"
        except Exception as exc:  # noqa: BLE001 - bounded readiness reconciliation
            last = f"{type(exc).__name__}: {exc}"
        time.sleep(0.5)
    pytest.fail(f"endpoint {url} did not become ready: {last}")


def _container_environment(container: dict[str, Any]) -> dict[str, str]:
    values = container.get("Config", {}).get("Env", [])
    assert isinstance(values, list)
    result: dict[str, str] = {}
    for value in values:
        assert isinstance(value, str)
        key, separator, item = value.partition("=")
        if separator:
            result[key] = item
    return result


def _container_processes(container: str) -> str:
    result = _run("docker", "top", container, "-eo", "args", timeout=20)
    if result.returncode == 0:
        return result.stdout
    pytest.fail(f"cannot inspect process table for {container}: {result.stderr}")


def _wait_stopped(container: str, *, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        running = _run("docker", "inspect", "--format", "{{.State.Running}}", container).stdout.strip()
        if running == "false":
            return
        time.sleep(0.25)
    pytest.fail(f"container {container} did not stop within {timeout} seconds")


def _remove_container(name: str) -> None:
    _run("docker", "rm", "-f", name, check=False, timeout=30)


def test_railway_entrypoint_contract_is_split_and_foregrounded() -> None:
    api = API_START.read_text(encoding="utf-8")
    orchestrator = ORCHESTRATOR_START.read_text(encoding="utf-8")
    railway_api = (ROOT / "railway.toml").read_text(encoding="utf-8")
    railway_orchestrator = (ROOT / "railway-orchestrator.toml").read_text(encoding="utf-8")

    assert 'export WOLF15_SERVICE_ROLE="api"' in api
    assert "WOLF15_EMBED_ORCHESTRATOR" in api
    assert "is no longer supported" in api
    assert "StateManager" not in api
    assert "exec gunicorn app:app" in api

    assert 'export WOLF15_SERVICE_ROLE="orchestrator"' in orchestrator
    assert "exec python -m services.orchestrator.state_manager" in orchestrator
    assert "gunicorn" not in orchestrator

    assert 'startCommand = "bash deploy/railway/start_api.sh"' in railway_api
    assert 'startCommand = "bash deploy/railway/start_orchestrator.sh"' in railway_orchestrator
    assert 'healthcheckPath = "/healthz"' in railway_api
    assert 'healthcheckPath = "/healthz"' in railway_orchestrator


def test_runtime_image_contains_both_explicit_start_scripts() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert "FROM python:3.11-slim AS runtime" in dockerfile
    assert "COPY . ." in dockerfile
    assert "USER appuser" in dockerfile
    assert "deploy/" not in {line.strip() for line in dockerignore.splitlines()}
    assert API_START.is_file()
    assert ORCHESTRATOR_START.is_file()


@pytest.mark.skipif(
    os.getenv("WOLF15_RUN_T14_CONTAINER_SMOKE") != "1",
    reason="set WOLF15_RUN_T14_CONTAINER_SMOKE=1 for the bounded Docker smoke",
)
def test_exact_tree_api_and_orchestrator_effective_entrypoints() -> None:
    expected_commit = _required_env("WOLF15_T14_EXPECTED_COMMIT")
    expected_tree = _required_env("WOLF15_T14_EXPECTED_TREE")
    redis_image = _required_env("WOLF15_T14_REDIS_IMAGE")
    postgres_image = _required_env("WOLF15_T14_POSTGRES_IMAGE")
    receipt_path_raw = os.getenv("WOLF15_T14_RECEIPT_PATH", "").strip()

    assert _run("git", "rev-parse", "HEAD").stdout.strip() == expected_commit
    assert _run("git", "rev-parse", "HEAD^{tree}").stdout.strip() == expected_tree
    assert not _run("git", "status", "--porcelain").stdout.strip()

    # Fail before mutation if Docker or either digest-bound dependency is absent.
    _run("docker", "version", "--format", "{{.Server.Version}}", timeout=20)
    _run("docker", "image", "inspect", redis_image, timeout=20)
    _run("docker", "image", "inspect", postgres_image, timeout=20)

    campaign = f"wolf15-t14-{uuid.uuid4().hex[:12]}"
    network = campaign
    redis_name = f"{campaign}-redis"
    postgres_name = f"{campaign}-postgres"
    api_name = f"{campaign}-api"
    orchestrator_name = f"{campaign}-orchestrator"
    image_tag = f"{campaign}:local"
    created_containers: list[str] = []
    network_created = False
    image_created = False
    receipt: dict[str, Any] = {
        "schema": "wolf15.t14.container-entrypoint-smoke/v1",
        "campaign": campaign,
        "source_commit": expected_commit,
        "source_tree": expected_tree,
        "redis_image": redis_image,
        "postgres_image": postgres_image,
        "broker_effects": 0,
        "execution_controls": {key: False for key in _FALSE_CONTROLS},
    }

    try:
        _run("docker", "network", "create", network, timeout=30)
        network_created = True

        _run(
            "docker",
            "run",
            "-d",
            "--pull=never",
            "--name",
            redis_name,
            "--network",
            network,
            "--health-cmd",
            f"redis-cli -a {_DISPOSABLE_REDIS_PASSWORD} ping || exit 1",
            "--health-interval=1s",
            "--health-timeout=3s",
            "--health-retries=30",
            redis_image,
            "redis-server",
            "--requirepass",
            _DISPOSABLE_REDIS_PASSWORD,
        )
        created_containers.append(redis_name)
        _wait_healthy(redis_name)

        _run(
            "docker",
            "run",
            "-d",
            "--pull=never",
            "--name",
            postgres_name,
            "--network",
            network,
            "-e",
            "POSTGRES_USER=wolf15_t14",
            "-e",
            "POSTGRES_PASSWORD=wolf15_t14_disposable",
            "-e",
            "POSTGRES_DB=wolf15_t14",
            "--health-cmd",
            "pg_isready -U wolf15_t14 -d wolf15_t14",
            "--health-interval=1s",
            "--health-timeout=3s",
            "--health-retries=60",
            postgres_image,
        )
        created_containers.append(postgres_name)
        _wait_healthy(postgres_name, timeout=90)

        build = _run(
            "docker",
            "build",
            "--pull=false",
            "--target",
            "runtime",
            "--label",
            f"org.wolf15.source.commit={expected_commit}",
            "--label",
            f"org.wolf15.source.tree={expected_tree}",
            "-t",
            image_tag,
            ".",
            timeout=900,
        )
        image_created = True
        image = _docker_json("image", "inspect", image_tag, "--format", "{{json .}}")
        receipt["image_id"] = image["Id"]
        receipt["build_exit"] = build.returncode

        common = (
            "--network",
            network,
            "-e",
            f"REDIS_URL=redis://:{_DISPOSABLE_REDIS_PASSWORD}@{redis_name}:6379/0",
            "-e",
            f"DATABASE_URL=postgresql://wolf15_t14:wolf15_t14_disposable@{postgres_name}:5432/wolf15_t14",
            "-e",
            "WOLF15_LOAD_DOTENV=false",
            "-e",
            "ORCHESTRATOR_COMMAND_SECRET=t14-non-production-command-secret",
        )
        controls = tuple(item for key in _FALSE_CONTROLS for item in ("-e", f"{key}=false"))

        _run(
            "docker",
            "run",
            "-d",
            "--pull=never",
            "--name",
            api_name,
            "-p",
            "127.0.0.1::8000",
            *common,
            *controls,
            "-e",
            "PORT=8000",
            "-e",
            "WOLF15_EMBED_ORCHESTRATOR=false",
            image_tag,
            "bash",
            "deploy/railway/start_api.sh",
        )
        created_containers.append(api_name)
        api_port = _published_port(api_name, 8000)
        _wait_http(api_port, "/healthz")
        api = _docker_json("container", "inspect", api_name, "--format", "{{json .}}")
        assert api["Path"] == "bash"
        assert api["Args"] == ["deploy/railway/start_api.sh"]
        api_pid = _container_processes(api_name)
        assert "gunicorn" in api_pid
        assert "app:app" in api_pid
        assert "services.orchestrator.state_manager" not in api_pid
        assert _container_environment(api)["WOLF15_SERVICE_ROLE"] == "api"
        api_logs = _run("docker", "logs", api_name, check=False).stdout
        assert "acquired ownership" not in api_logs
        assert "StateManager" not in api_logs

        _run(
            "docker",
            "run",
            "-d",
            "--pull=never",
            "--name",
            orchestrator_name,
            "-p",
            "127.0.0.1::8083",
            *common,
            *controls,
            "-e",
            "PORT=8083",
            "-e",
            "ORCHESTRATOR_LOOP_SLEEP_SEC=0.02",
            "-e",
            "ORCHESTRATOR_COMPLIANCE_INTERVAL_SEC=1",
            "-e",
            "ORCHESTRATOR_HEARTBEAT_INTERVAL_SEC=5",
            image_tag,
            "bash",
            "deploy/railway/start_orchestrator.sh",
        )
        created_containers.append(orchestrator_name)
        orchestrator_port = _published_port(orchestrator_name, 8083)
        _wait_http(orchestrator_port, "/healthz")
        _wait_http(orchestrator_port, "/readyz")
        orchestrator = _docker_json("container", "inspect", orchestrator_name, "--format", "{{json .}}")
        assert orchestrator["Path"] == "bash"
        assert orchestrator["Args"] == ["deploy/railway/start_orchestrator.sh"]
        orchestrator_pid = _container_processes(orchestrator_name)
        assert "python -m services.orchestrator.state_manager" in orchestrator_pid
        assert "gunicorn" not in orchestrator_pid
        assert _container_environment(orchestrator)["WOLF15_SERVICE_ROLE"] == "orchestrator"

        # SIGINT lets Python unwind StateManager.run_forever's finally block.
        _run("docker", "kill", "--signal=INT", orchestrator_name, timeout=20)
        _wait_stopped(orchestrator_name)
        orchestrator_logs = _run("docker", "logs", orchestrator_name, check=False).stdout
        assert "published SHUTDOWN state" in orchestrator_logs

        _run("docker", "stop", "--time=30", api_name, timeout=45)
        receipt.update(
            {
                "api_healthz": "PASS",
                "api_only": True,
                "orchestrator_healthz": "PASS",
                "orchestrator_readyz": "PASS",
                "orchestrator_shutdown": "PASS",
                "verdict": "PASS_EXACT_IMAGE_EFFECTIVE_ENTRYPOINT_SMOKE",
            }
        )
    finally:
        if receipt_path_raw:
            receipt_path = Path(receipt_path_raw)
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        for name in reversed(created_containers):
            _remove_container(name)
        if network_created:
            _run("docker", "network", "rm", network, check=False, timeout=30)
        if image_created:
            _run("docker", "image", "rm", image_tag, check=False, timeout=60)
