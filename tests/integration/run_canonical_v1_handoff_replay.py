"""One invocation, one disposable PostgreSQL V1 engineering replay.

Run with the project's Python environment after host coordination. This runner
never reads a production credential or .env, pulls/builds images, starts an EA,
or contacts Railway. Failure is terminal for this invocation; artifacts remain.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import sysconfig
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

IMAGE = "postgres@sha256:67f41722b7a8cbdb868a44a4995c846eddfdc2973bccb291ce937dce88ad5675"
DATABASE = "p5_canonical_v1_replay_test"
TEST = "tests/integration/test_5scr_canonical_v1_handoff_replay.py"
TOTAL_SECONDS = 300
SAFE_ENV_NAMES = (
    "SYSTEMROOT",
    "WINDIR",
    "PATH",
    "TEMP",
    "TMP",
    "APPDATA",
    "LOCALAPPDATA",
    "USERPROFILE",
    "COMSPEC",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "PROGRAMDATA",
    "SYSTEMDRIVE",
)
OFF_FLAGS = (
    "EXECUTION_ENABLED",
    "ALLOW_MARKET_EXECUTION",
    "MT5_ORDER_SEND_ENABLED",
    "EA_COMMAND_DELIVERY_ENABLED",
    "RISK_RESERVATION_ENABLED",
    "STRATEGY_5SCR_EXECUTION_ENABLED",
    "CANARY_ISSUANCE_ENABLED",
    "SIGNED_COMMAND_BRIDGE_ENABLED",
    "EXECUTION_COMMAND_PRODUCER_ENABLED",
    "TRADE_OUTBOX_WRITE_ENABLED",
    "LEGACY_PUSH_EXECUTION_ENABLED",
    "STRATEGY_5SCR_ANALYSIS_ADMISSION_V1_ENABLED",
)


def now() -> str:
    return datetime.now(UTC).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--docker", required=True, type=Path)
    args = parser.parse_args()
    if re.fullmatch(r"[0-9a-f]{40}", args.expected_commit) is None:
        parser.error("expected commit must be a full Git SHA")
    root = args.source_root.resolve(strict=True)
    output = args.output_dir.resolve()
    if not (root / TEST).is_file() or not args.docker.is_file():
        parser.error("bound test or Docker executable is missing")
    if output.is_relative_to(root):
        parser.error("receipt directory must be outside the Git source")
    if (root / ".env").exists():
        parser.error("source must not contain an ambient .env")
    output.mkdir(parents=True, exist_ok=False)
    temporary_root = output / "tmp"
    temporary_root.mkdir()
    claim = uuid.uuid4().hex
    name = f"wolf15-p5-v1-replay-{claim[:12]}"
    env = {key: os.environ[key] for key in SAFE_ENV_NAMES if key in os.environ}
    env.update({key: "false" for key in OFF_FLAGS})
    env.update(ENV="test", PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1", REDIS_URL="redis://127.0.0.1:1/0")
    env.update(TEMP=str(temporary_root), TMP=str(temporary_root))
    # Avoid Windows venv launcher indirection while retaining this venv's exact libraries.
    libraries = tuple(dict.fromkeys((str(root), sysconfig.get_path("purelib"), sysconfig.get_path("platlib"))))
    env["PYTHONPATH"] = os.pathsep.join(libraries)
    python = getattr(sys, "_base_executable", sys.executable)
    receipt: dict[str, Any] = {
        "schema": "wolf15.synthetic-canonical-v1-handoff-run/v1",
        "started_at": now(),
        "expected_commit": args.expected_commit,
        "source_root": str(root),
        "claim": claim,
        "container_name": name,
        "image": IMAGE,
        "database": DATABASE,
        "total_seconds": TOTAL_SECONDS,
        "attempts": 0,
        "verdict": "NOT_EXECUTED",
        "cleanup": "NOT_EXECUTED",
        "steps": [],
        "resource_caps": {
            "container_memory_bytes": 536870912,
            "container_memory_swap_bytes": 536870912,
            "pgdata_tmpfs_bytes": 268435456,
            "work_deadline_seconds": TOTAL_SECONDS,
            "cleanup_commands_max_seconds_each": 40,
            "temporary_root": str(temporary_root),
        },
        "natural_runtime": "NOT_PROVEN",
        "strategy_validation": "NOT_PROVEN",
        "demo_authority": "NOT_GRANTED",
    }
    deadline = time.monotonic() + TOTAL_SECONDS

    def save() -> None:
        temporary = output / "supervision-receipt.tmp"
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(receipt, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(output / "supervision-receipt.json")

    def invoke(label: str, command: list[str], *, cap: float = 90, cleanup: bool = False) -> str:
        remaining = 40 if cleanup else min(cap, deadline - time.monotonic())
        if remaining <= 0:
            raise TimeoutError("REPLAY_TOTAL_DEADLINE")
        step: dict[str, Any] = {"label": label, "started_at": now(), "status": "DISPATCHING"}
        receipt["steps"].append(step)
        save()
        try:
            completed = subprocess.run(
                command,
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                timeout=remaining,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            (output / f"{label}.log").write_text(completed.stdout + completed.stderr, encoding="utf-8")
            step.update(
                exit=completed.returncode, status="PASS" if completed.returncode == 0 else "FAIL", finished_at=now()
            )
            if completed.returncode:
                raise RuntimeError(f"REPLAY_STAGE_FAILED:{label}")
            return completed.stdout.strip()
        except subprocess.TimeoutExpired:
            step.update(status="TIMEOUT", finished_at=now())
            raise TimeoutError(f"REPLAY_STAGE_TIMEOUT:{label}") from None
        finally:
            save()

    def docker(label: str, *arguments: str, cap: float = 40, cleanup: bool = False) -> str:
        return invoke(label, [str(args.docker), *arguments], cap=cap, cleanup=cleanup)

    creation_attempted = False
    try:
        if shutil.disk_usage(output).free < 128 * 1024 * 1024:
            raise RuntimeError("ARTIFACT_DRIVE_CAPACITY_BELOW_128_MIB")
        commit = invoke("source-commit", ["git", "rev-parse", "HEAD"])
        if commit != args.expected_commit or invoke("source-clean", ["git", "status", "--porcelain"]):
            raise RuntimeError("SOURCE_BINDING_MISMATCH_OR_DIRTY")
        receipt["source_tree"] = invoke("source-tree", ["git", "rev-parse", "HEAD^{tree}"])
        receipt["test_sha256"] = hashlib.sha256((root / TEST).read_bytes()).hexdigest()
        receipt["runner_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        receipt["python"] = {"executable": python, "libraries": libraries, "version": sys.version}
        docker("cached-image", "image", "inspect", IMAGE, "--format", "{{.Id}}")
        creation_attempted = True
        receipt.update(attempts=1, verdict="RUNNING")
        save()
        receipt["container_id"] = docker(
            "create-postgres",
            "run",
            "-d",
            "--name",
            name,
            "--label",
            f"wolf15.p5-replay-claim={claim}",
            "--memory",
            "512m",
            "--memory-swap",
            "512m",
            "--publish",
            "127.0.0.1::5432",
            "--mount",
            "type=tmpfs,destination=/var/lib/postgresql/data,tmpfs-size=268435456",
            "--env",
            "POSTGRES_HOST_AUTH_METHOD=trust",
            "--pull",
            "never",
            IMAGE,
            "-c",
            "wolf15.environment_class=DISPOSABLE_TEST",
            "-c",
            "wolf15.destructive_tests_allowed=true",
            "-c",
            "shared_buffers=64MB",
            "-c",
            "maintenance_work_mem=32MB",
            "-c",
            "max_connections=20",
            "-c",
            "temp_file_limit=65536",
            "-c",
            "max_wal_size=128MB",
        )
        info = json.loads(docker("postgres-binding", "inspect", name))[0]
        ports = info["NetworkSettings"]["Ports"]["5432/tcp"]
        if len(ports) != 1 or ports[0]["HostIp"] != "127.0.0.1":
            raise RuntimeError("NON_LOOPBACK_BINDING")
        port = int(ports[0]["HostPort"])
        receipt["target"] = {"host": "127.0.0.1", "port": port, "database": DATABASE, "class": "DISPOSABLE_TEST"}
        # Only readiness probes repeat; the replay itself is dispatched exactly once.
        docker(
            "postgres-ready",
            "exec",
            name,
            "sh",
            "-c",
            "for i in $(seq 1 30); do pg_isready -U postgres >/dev/null 2>&1 && exit 0; sleep 1; done; exit 1",
        )
        import psycopg
        from psycopg import sql

        with psycopg.connect(
            host="127.0.0.1",
            port=port,
            user="postgres",
            dbname="postgres",
            connect_timeout=5,
            autocommit=True,
            options="-c statement_timeout=10000",
        ) as connection:
            connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DATABASE)))
        env.update(
            DATABASE_URL=f"postgresql://postgres@127.0.0.1:{port}/{DATABASE}",
            WOLF15_RUN_POSTGRES_INTEGRATION="1",
            WOLF15_ALLOW_DESTRUCTIVE_PG_TESTS="YES_I_UNDERSTAND",
            WOLF15_POSTGRES_TEST_DATABASE=DATABASE,
            WOLF15_P5_REPLAY_RECEIPT=str(output / "lineage-receipt.json"),
            WOLF15_P5_REPLAY_SOURCE_COMMIT=commit,
        )
        invoke("migrate", [python, "-B", "-m", "alembic", "upgrade", "head"], cap=120)
        invoke(
            "replay",
            [
                python,
                "-B",
                "-m",
                "pytest",
                TEST,
                "-q",
                "-o",
                "addopts=",
                "-p",
                "no:cacheprovider",
                "--junitxml=" + str(output / "replay.xml"),
            ],
            cap=120,
        )
        suites = ET.parse(output / "replay.xml").getroot()
        cases = list(suites.iter("testcase"))
        if len(cases) != 3 or any(
            case.find(tag) is not None for case in cases for tag in ("failure", "error", "skipped")
        ):
            raise RuntimeError("REPLAY_REQUIRED_CASES_NOT_ALL_PASSED")
        lineage = json.loads((output / "lineage-receipt.json").read_text(encoding="utf-8"))
        if lineage["counts"] != {
            "commands": 1,
            "reservations": 1,
            "final_signals": 1,
            "execution_reports": 0,
            "broker_entities": 0,
        }:
            raise RuntimeError("REPLAY_EFFECT_COUNTS_MISMATCH")
        receipt["lineage_sha256"] = hashlib.sha256((output / "lineage-receipt.json").read_bytes()).hexdigest()
        receipt["verdict"] = "PASS_ISOLATED_V1_ENGINEERING_HANDOFF"
    except Exception as exc:
        receipt.update(verdict="HOLD", error_type=type(exc).__name__, error=str(exc)[:300])
    finally:
        if creation_attempted:
            try:
                owned = json.loads(docker("cleanup-inspect", "inspect", name, cleanup=True))[0]
                if owned["Config"]["Labels"].get("wolf15.p5-replay-claim") != claim:
                    raise RuntimeError("CLEANUP_OWNERSHIP_MISMATCH")
                docker("cleanup-remove", "rm", "-f", name, cleanup=True)
                remaining = docker(
                    "cleanup-verify", "ps", "-aq", "--filter", f"label=wolf15.p5-replay-claim={claim}", cleanup=True
                )
                if remaining:
                    raise RuntimeError("CLEANUP_RESOURCE_REMAINS")
                receipt["cleanup"] = "PASS_OWN_DISPOSABLE_CONTAINER_REMOVED"
            except Exception as exc:
                receipt.update(verdict="HOLD", cleanup="NOT_PROVEN", cleanup_error_type=type(exc).__name__)
        receipt.update(finished_at=now(), elapsed_seconds=round(time.monotonic() - (deadline - TOTAL_SECONDS), 3))
        save()
    print(json.dumps({"verdict": receipt["verdict"], "receipt": str(output / "supervision-receipt.json")}))
    return 0 if receipt["verdict"] == "PASS_ISOLATED_V1_ENGINEERING_HANDOFF" else 3


if __name__ == "__main__":
    raise SystemExit(main())
