"""T09/T11: real process restart against a newly created disposable Redis.

Opt in with WOLF15_RUN_PROCESS_RECOVERY=1. No existing Redis URL is accepted.
The two child processes use production StateManager and RedisFencedOwnership;
the on_started boundary pauses before compliance evaluation for deterministic
commit/interruption control. This does not prove production durability or replay
behavior of downstream execution services.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import sysconfig
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import redis

ROOT = Path(__file__).resolve().parents[2]
REDIS_IMAGE = "redis@sha256:e7723ff73d963f5cc6d9c4643ea3d989527a402a319239054e9472a7fb9219a2"


def _write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _wait(predicate: Any, *, seconds: float = 15) -> Any:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("bounded process-recovery observation timed out")


@pytest.fixture
def disposable_redis(tmp_path: Path) -> Iterator[tuple[Any, int, Path, dict[str, Any]]]:
    if os.getenv("WOLF15_RUN_PROCESS_RECOVERY") != "1":
        pytest.skip("set WOLF15_RUN_PROCESS_RECOVERY=1 for disposable process acceptance")
    docker = os.getenv("WOLF15_TEST_DOCKER") or shutil.which("docker")
    assert docker, "Docker is required for explicitly requested process acceptance"
    root = Path(os.getenv("WOLF15_PROCESS_RECOVERY_EVIDENCE", str(tmp_path))) / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=False)
    name = "wolf15-process-recovery-" + uuid.uuid4().hex[:12]
    network = name + "-net"
    meta: dict[str, Any] = {
        "container_name": name,
        "network_name": network,
        "redis_image": REDIS_IMAGE,
        "cleanup": "NOT_EXECUTED",
        "phase": "RESERVED",
        "campaign_id": os.getenv("WOLF15_DISPOSABLE_CAMPAIGN_ID", "standalone"),
    }
    _write_json(root / "redis.json", meta)  # Reserved names survive an outer supervisor interruption.

    def cli(*args: str) -> str:
        result = subprocess.run([docker, *args], capture_output=True, text=True, timeout=30, check=True)
        return result.stdout.strip()

    client = None
    try:
        meta["phase"] = "NETWORK_CREATE_REQUESTED"
        _write_json(root / "redis.json", meta)
        meta["network_id"] = cli(
            "network",
            "create",
            "--label",
            "wolf15.test=process-recovery",
            "--label",
            "wolf15.campaign=" + meta["campaign_id"],
            network,
        )
        meta["phase"] = "NETWORK_CREATED"
        _write_json(root / "redis.json", meta)
        meta["phase"] = "CONTAINER_RUN_REQUESTED"
        _write_json(root / "redis.json", meta)
        meta["container_id"] = cli(
            "run",
            "-d",
            "--name",
            name,
            "--label",
            "wolf15.test=process-recovery",
            "--label",
            "wolf15.campaign=" + meta["campaign_id"],
            "--network",
            network,
            "--memory",
            "128m",
            "--memory-swap",
            "128m",
            "--cpus",
            "0.5",
            "--pids-limit",
            "64",
            "--tmpfs",
            "/data:rw,noexec,nosuid,size=16777216",
            "--publish",
            "127.0.0.1::6379",
            "--pull",
            "never",
            REDIS_IMAGE,
            "redis-server",
            "--save",
            "",
            "--appendonly",
            "no",
        )
        meta["phase"] = "CONTAINER_CREATED"
        _write_json(root / "redis.json", meta)
        info = json.loads(cli("inspect", name))[0]
        meta["image_id"] = info["Image"]
        meta["resource_limits"] = {
            key: info["HostConfig"][key] for key in ("Memory", "MemorySwap", "NanoCpus", "PidsLimit")
        }
        meta["tmpfs"] = info["HostConfig"]["Tmpfs"]
        assert meta["tmpfs"] == {"/data": "rw,noexec,nosuid,size=16777216"}
        assert meta["resource_limits"]["Memory"] == meta["resource_limits"]["MemorySwap"] == 128 * 1024 * 1024
        assert meta["resource_limits"]["NanoCpus"] == 500_000_000
        assert meta["resource_limits"]["PidsLimit"] == 64
        binding = info["NetworkSettings"]["Ports"]["6379/tcp"][0]
        assert binding["HostIp"] == "127.0.0.1"
        port = int(binding["HostPort"])
        meta["loopback_port"] = port
        client = redis.Redis(host="127.0.0.1", port=port, decode_responses=True, socket_timeout=2)

        def ping() -> bool:
            try:
                return bool(client.ping())
            except redis.ConnectionError:
                return False

        _wait(ping)
        assert client.dbsize() == 0, "test must start with its own empty Redis"
        meta["redis_version"] = client.info("server")["redis_version"]
        meta["phase"] = "READY"
        _write_json(root / "redis.json", meta)
        yield client, port, root, meta
        meta["phase"] = "CASE_COMPLETED"
    finally:
        try:
            if client is not None:
                client.close()
            if "container_id" in meta:
                try:
                    (root / "redis.log").write_text(cli("logs", name), encoding="utf-8")
                finally:
                    # An observation error must not leave the owned test service running.
                    cli("rm", "-f", name)
                    remaining = cli("ps", "-aq", "--filter", "name=^/" + name + "$")
                    assert not remaining, "disposable Redis cleanup must be proven"
                    meta["cleanup"] = "PASS_REMOVED"
        finally:
            if "network_id" in meta:
                cli("network", "rm", network)
                meta["network_cleanup"] = "PASS_REMOVED"
            _write_json(root / "redis.json", meta)


def _child_environment(port: int) -> dict[str, str]:
    # Do not inherit Railway, database, broker, or credential environment values.
    env = {key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP") if key in os.environ}
    env.update(
        {
            "ENV": "test",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": os.pathsep.join([str(ROOT), sysconfig.get_paths()["purelib"]]),
            "REDIS_URL": f"redis://127.0.0.1:{port}/0",
            "ORCHESTRATOR_LEASE_TTL_SEC": "3",
            "ORCHESTRATOR_LEASE_RENEW_INTERVAL_SEC": "1",
            "EXECUTION_ENABLED": "false",
            "ALLOW_MARKET_EXECUTION": "false",
            "MT5_ORDER_SEND_ENABLED": "false",
            "EA_COMMAND_DELIVERY_ENABLED": "false",
            "RISK_RESERVATION_ENABLED": "false",
            "STRATEGY_5SCR_EXECUTION_ENABLED": "false",
            "CANARY_ISSUANCE_ENABLED": "false",
        }
    )
    return env


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.parametrize("stop_mode", ["graceful", "abrupt"])
def test_separate_process_restores_committed_state_and_watermark(
    disposable_redis: tuple[Any, int, Path, dict[str, Any]],
    stop_mode: str,
) -> None:
    client, port, root, meta = disposable_redis
    processes: list[subprocess.Popen[str]] = []
    handles: list[Any] = []
    receipt: dict[str, Any] = {"stop_mode": stop_mode, "verdict": "NOT_COMPLETED", "source_root": str(ROOT)}

    def spawn(role: str) -> subprocess.Popen[str]:
        stdout = (root / f"{role}.stdout.log").open("w", encoding="utf-8")
        stderr = (root / f"{role}.stderr.log").open("w", encoding="utf-8")
        handles.extend([stdout, stderr])
        # Windows venv python.exe is a launcher that creates another process.
        # Invoke its actual interpreter with the same site-packages explicitly,
        # so Popen's PID and termination handle belong to the tested process.
        executable = getattr(sys, "_base_executable", sys.executable) if os.name == "nt" else sys.executable
        process = subprocess.Popen(
            [executable, "-B", str(Path(__file__).resolve()), "--worker", role, stop_mode, str(root), str(port)],
            cwd=ROOT,
            env=_child_environment(port),
            stdin=subprocess.PIPE,
            stdout=stdout,
            stderr=stderr,
            text=True,
        )
        processes.append(process)
        return process

    try:
        first = spawn("A")
        _wait(lambda: (root / "A.ready.json").exists() or first.poll() is not None)
        assert first.poll() is None, "process A exited before committing; inspect A.stderr.log"
        a = json.loads((root / "A.ready.json").read_text(encoding="utf-8"))
        assert a["pid"] == first.pid
        assert a["boot"]["details"]["hydrated"] is False
        assert a["committed"]["mode"] == "SAFE"
        assert a["committed"]["commit_marker"] == "COMMITTED"
        assert first.stdin is not None
        first.stdin.write("stop\n")
        first.stdin.flush()
        first.stdin.close()
        assert first.wait(timeout=15) == (0 if stop_mode == "graceful" else 73)
        persisted_a = json.loads(client.get("wolf15:orchestrator:state"))
        assert persisted_a["mode"] == "SAFE", "uncommitted KILL_SWITCH must not survive abrupt exit"
        assert persisted_a["event"] == ("SHUTDOWN" if stop_mode == "graceful" else "TEST_COMMITTED")
        assert persisted_a["state_revision"] == a["committed"]["state_revision"] + (stop_mode == "graceful")
        _wait(lambda: client.get("wolf15:orchestrator:owner") is None, seconds=6)

        second = spawn("B")
        assert second.wait(timeout=15) == 0, "process B recovery failed; inspect B.stderr.log"
        b = json.loads((root / "B.ready.json").read_text(encoding="utf-8"))
        assert a["pid"] != b["pid"] == second.pid
        assert b["boot"]["owner_id"] != persisted_a["owner_id"]
        assert b["boot"]["fence_generation"] > persisted_a["fence_generation"]
        assert b["boot"]["details"]["hydrated"] is True
        assert b["boot"]["details"]["prior_state_revision"] == persisted_a["state_revision"]
        assert b["boot"]["state_revision"] == persisted_a["state_revision"] + 1
        for field in ("mode", "reason", "compliance_code", "updated_at"):
            assert b["boot"][field] == persisted_a[field]
        assert b["recovery_count"] == 0
        settled = json.loads(client.get("wolf15:orchestrator:state"))
        assert settled["event"] == "SHUTDOWN"
        assert settled["state_revision"] == b["boot"]["state_revision"] + 1
        assert settled["mode"] == "SAFE"
        assert "recovery_count" not in settled
        assert client.get("wolf15:orchestrator:owner") is None
        receipt.update(
            {
                "verdict": "PASS_LOCAL_REAL_PROCESS_RECOVERY",
                "producer": a,
                "producer_terminal": persisted_a,
                "consumer": b,
                "consumer_terminal": settled,
                "exit_codes": [first.returncode, second.returncode],
                "redis": meta,
                "production_or_broker_calls": "NOT_EXECUTED",
                "source_sha256": {
                    path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                    for path in (
                        "services/orchestrator/state_manager.py",
                        "services/orchestrator/ownership.py",
                        "tests/integration/test_orchestrator_process_recovery.py",
                    )
                },
            }
        )
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
        for handle in handles:
            handle.close()
        receipt["all_children_stopped"] = all(process.poll() is not None for process in processes)
        _write_json(root / "receipt.json", receipt)


def _worker(role: str, stop_mode: str, root: Path, port: int) -> None:
    sys.path.insert(0, str(ROOT))
    from services.orchestrator.execution_mode import ExecutionMode
    from services.orchestrator.state_manager import StateManager

    client = redis.Redis(host="127.0.0.1", port=port, decode_responses=True, socket_timeout=2)
    manager = StateManager(redis_client=client)  # type: ignore[arg-type]

    def on_started() -> None:
        data = {"pid": os.getpid(), "boot": json.loads(client.get(manager._state_key))}  # noqa: SLF001
        if role == "A":
            manager.set_mode(ExecutionMode.SAFE, reason="process-recovery-committed", compliance_code="TEST_HOLD")
            manager.publish_state("TEST_COMMITTED")
            manager._recovery_count = 2  # noqa: SLF001
            data["committed"] = json.loads(client.get(manager._state_key))  # noqa: SLF001
            data["recovery_count"] = manager._recovery_count  # noqa: SLF001
            _write_json(root / "A.ready.json", data)
            assert sys.stdin.readline().strip() == "stop"
            if stop_mode == "abrupt":
                manager.set_mode(ExecutionMode.KILL_SWITCH, reason="uncommitted-interrupted-work")
                os._exit(73)
        else:
            data["recovery_count"] = manager._recovery_count  # noqa: SLF001
            _write_json(root / "B.ready.json", data)
        raise KeyboardInterrupt

    try:
        manager.run_forever(on_started=on_started)
    except KeyboardInterrupt:
        pass
    finally:
        client.close()


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.parametrize("shape", ["legacy", "malformed"])
def test_rejected_process_startup_preserves_redis_bytes_and_releases_lease(
    disposable_redis: tuple[Any, int, Path, dict[str, Any]], shape: str
) -> None:
    client, port, root, meta = disposable_redis
    state_key = "wolf15:orchestrator:state"
    payload = (
        json.dumps(
            {
                "source": "wolf15-orchestrator",
                "channel": "wolf15:orchestrator:commands",
                "mode": "KILL_SWITCH",
                "reason": "synthetic-account-state-missing",
                "compliance_code": "ACCOUNT_STATE_MISSING",
                "updated_at": "2026-09-05T13:48:10+00:00",
                "timestamp": 1,
                "event": "HEARTBEAT",
            }
        )
        if shape == "legacy"
        else "{malformed"
    )
    before = {
        state_key: payload,
        "wolf15:heartbeat:orchestrator": "existing-heartbeat-bytes",
        "wolf15:system:kill_switch": '{"active":true}',
    }
    for key, value in before.items():
        client.set(key, value)
    previous_generation = 0  # The task-owned fixture starts with an empty Redis.
    receipt: dict[str, Any] = {
        "verdict": "NOT_COMPLETED",
        "shape": shape,
        "fixture": "SYNTHETIC_NOT_PRODUCTION_DATA",
        "source_root": str(ROOT),
        "attempts": [],
    }
    process = None
    try:
        for attempt in (1, 2):
            role = f"failure-{attempt}"
            executable = getattr(sys, "_base_executable", sys.executable) if os.name == "nt" else sys.executable
            with (
                (root / f"{role}.stdout.log").open("w", encoding="utf-8") as stdout,
                (root / f"{role}.stderr.log").open("w", encoding="utf-8") as stderr,
            ):
                process = subprocess.Popen(
                    [
                        executable,
                        "-B",
                        str(Path(__file__).resolve()),
                        "--rejected-start",
                        role,
                        str(root),
                        str(port),
                    ],
                    cwd=ROOT,
                    env=_child_environment(port),
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    text=True,
                )
                assert process.wait(timeout=15) == 0, "rejected-start worker failed; inspect its stderr"
            observed = json.loads((root / f"{role}.json").read_text(encoding="utf-8"))
            assert observed["pid"] == process.pid
            assert observed["error_type"] == "StateHydrationError"
            assert observed["supervisor_state"] == "FATAL"
            assert observed["ready"] is False
            assert {key: client.get(key) for key in before} == before
            assert client.get("wolf15:orchestrator:owner") is None
            generation = int(client.get("wolf15:orchestrator:fence_generation"))
            assert generation > previous_generation
            previous_generation = generation
            receipt["attempts"].append(
                {
                    **observed,
                    "generation_after_exit": generation,
                    "state_and_heartbeat_bytes_preserved": True,
                    "lease_released": True,
                }
            )
        receipt.update(
            {
                "verdict": "PASS_LOCAL_REAL_REDIS_REJECTED_STARTUP",
                "redis": meta,
                "production_or_broker_calls": "NOT_EXECUTED",
                "source_sha256": {
                    path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                    for path in (
                        "services/orchestrator/state_manager.py",
                        "services/orchestrator/ownership.py",
                        "tests/integration/test_orchestrator_process_recovery.py",
                    )
                },
            }
        )
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        receipt["all_children_stopped"] = process is None or process.poll() is not None
        _write_json(root / "receipt.json", receipt)


def _rejected_start_worker(role: str, root: Path, port: int) -> None:
    sys.path.insert(0, str(ROOT))
    from services.orchestrator.state_manager import StateHydrationError, StateManager

    client = redis.Redis(host="127.0.0.1", port=port, decode_responses=True, socket_timeout=2)
    manager = StateManager(redis_client=client)  # type: ignore[arg-type]
    try:
        manager.run_forever()
    except StateHydrationError:
        _write_json(
            root / f"{role}.json",
            {
                "pid": os.getpid(),
                "error_type": "StateHydrationError",
                "supervisor_state": manager._supervisor.state,
                "ready": manager._supervisor.is_ready(),
            },  # noqa: SLF001
        )
    else:
        raise AssertionError("legacy/malformed startup unexpectedly accepted")
    finally:
        client.close()


if __name__ == "__main__":
    if sys.argv[1] == "--rejected-start":
        _rejected_start_worker(sys.argv[2], Path(sys.argv[3]), int(sys.argv[4]))
    else:
        assert sys.argv[1] == "--worker"
        _worker(sys.argv[2], sys.argv[3], Path(sys.argv[4]), int(sys.argv[5]))
