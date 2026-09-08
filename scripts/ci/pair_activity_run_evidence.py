"""Allowlisted evidence for an explicitly enabled disposable PostgreSQL run.

No helper launches PostgreSQL, performs migrations, or opens a connection.
Database observations are supplied by the already guarded acceptance fixture.
"""

from __future__ import annotations

import ast
import ctypes
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import threading
from datetime import UTC, datetime
from pathlib import Path

LOCK = threading.Lock()
PG_SETTINGS = (
    "fsync",
    "synchronous_commit",
    "shared_buffers",
    "max_connections",
    "TimeZone",
    "default_transaction_isolation",
    "wolf15.environment_class",
    "wolf15.destructive_tests_allowed",
)
PG_TABLES = ("ledgers", "raw", "observations", "evaluations", "attachments", "snapshots")


def now() -> str:
    return datetime.now(UTC).isoformat()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def migration_graph(root: Path) -> dict:
    graph = {}
    for path in sorted((root / "storage/migrations/versions").glob("*.py")):
        assignments = {}
        for node in ast.parse(path.read_text(encoding="utf-8-sig")).body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in {"revision", "down_revision"}:
                        assignments[target.id] = ast.literal_eval(node.value)
        if "revision" in assignments:
            revision = assignments["revision"]
            if revision in graph:
                raise ValueError("DUPLICATE_MIGRATION_REVISION")
            graph[revision] = assignments.get("down_revision")
    parents = {
        parent for value in graph.values() for parent in (value if isinstance(value, tuple) else (value,)) if parent
    }
    heads = sorted(set(graph) - parents)
    if len(heads) != 1 or not parents <= set(graph):
        raise ValueError("MIGRATION_GRAPH_NOT_SINGLE_COMPLETE_HEAD")
    return {"repository_heads": heads, "revision_parents": graph, "migration_upgrade_execution": "NOT_BOUND"}


def capacity_snapshot() -> dict:
    """Measure only on an explicitly enabled run, never in disabled controls."""
    try:
        if platform.system() == "Windows":

            class Performance(ctypes.Structure):
                _fields_ = (
                    [("cb", ctypes.c_ulong)]
                    + [
                        (name, ctypes.c_size_t)
                        for name in (
                            "CommitTotal",
                            "CommitLimit",
                            "CommitPeak",
                            "PhysicalTotal",
                            "PhysicalAvailable",
                            "SystemCache",
                            "KernelTotal",
                            "KernelPaged",
                            "KernelNonpaged",
                            "PageSize",
                        )
                    ]
                    + [(name, ctypes.c_ulong) for name in ("HandleCount", "ProcessCount", "ThreadCount")]
                )

            data = Performance()
            data.cb = ctypes.sizeof(data)
            if not ctypes.windll.psapi.GetPerformanceInfo(ctypes.byref(data), data.cb):
                raise OSError("CAPACITY_UNAVAILABLE")
            used, limit = data.CommitTotal * data.PageSize, data.CommitLimit * data.PageSize
            return {
                "status": "MEASURED",
                "scope": "WINDOWS_HOST",
                "metric": "COMMITTED_BYTES",
                "used_bytes": used,
                "limit_bytes": limit,
                "below_90_percent": used / limit < 0.9,
            }
        if platform.system() == "Linux":
            memory = {}
            for line in Path("/proc/meminfo").read_text().splitlines():
                key, value = line.split(":", 1)
                memory[key] = int(value.strip().split()[0]) * 1024
            result = {
                "status": "MEASURED",
                "scope": "PROC_MEMINFO_VISIBLE_TO_RUNNER",
                "metric": "PHYSICAL_AVAILABLE_BYTES",
                "total_bytes": memory["MemTotal"],
                "available_bytes": memory["MemAvailable"],
                "below_90_percent": 1 - memory["MemAvailable"] / memory["MemTotal"] < 0.9,
                "cgroup": {"status": "NOT_MEASURED"},
            }
            for used_path, limit_path, kind in (
                ("/sys/fs/cgroup/memory.current", "/sys/fs/cgroup/memory.max", "CGROUP_V2"),
                (
                    "/sys/fs/cgroup/memory/memory.usage_in_bytes",
                    "/sys/fs/cgroup/memory/memory.limit_in_bytes",
                    "CGROUP_V1",
                ),
            ):
                if Path(used_path).is_file() and Path(limit_path).is_file():
                    used, limit_text = int(Path(used_path).read_text()), Path(limit_path).read_text().strip()
                    limit = None if limit_text == "max" else int(limit_text)
                    result["cgroup"] = {
                        "status": "MEASURED",
                        "scope": kind,
                        "used_bytes": used,
                        "limit_bytes": limit,
                        "below_90_percent": None if limit is None else used / limit < 0.9,
                    }
                    break
            return result
    except (OSError, ValueError, KeyError, ZeroDivisionError, AttributeError):
        pass
    return {"status": "NOT_MEASURED", "scope": "UNKNOWN", "metric": "UNKNOWN"}


def host_snapshot(enabled: bool) -> dict:
    if not enabled:
        return {"status": "NOT_MEASURED_DISABLED_CONTROL", "capacity": {"status": "NOT_MEASURED"}}
    packages = {}
    for package in importlib.metadata.distributions():
        packages[package.metadata["Name"]] = package.version
    return {
        "status": "MEASURED",
        "hostname": platform.node(),
        "os": platform.system(),
        "os_release": platform.release(),
        "architecture": platform.machine(),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "packages": dict(sorted(packages.items())),
        "capacity": capacity_snapshot(),
        "ci": {
            key: os.environ[key]
            for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB", "RUNNER_OS", "RUNNER_ARCH")
            if key in os.environ
        },
    }


def redact(text: str, environment: dict[str, str]) -> str:
    for key, value in environment.items():
        if value and any(word in key.upper() for word in ("DATABASE_URL", "PASSWORD", "SECRET", "TOKEN", "DSN")):
            text = text.replace(value, "[REDACTED]")
    from urllib.parse import unquote, urlsplit

    for key, value in environment.items():
        if "DATABASE_URL" in key.upper() or "DSN" in key.upper():
            try:
                password = urlsplit(value).password
                if password:
                    text = text.replace(password, "[REDACTED]").replace(unquote(password), "[REDACTED]")
            except ValueError:
                pass
    return re.sub(r"postgres(?:ql)?(?:\+\w+)?://[^\s\"'<>]+", "[REDACTED_DSN]", text)


def evidence_directory() -> tuple[Path, str] | None:
    run_id = os.environ.get("WOLF15_PAIR_ACTIVITY_RUN_ID", "")
    folder = os.environ.get("WOLF15_PAIR_ACTIVITY_EVIDENCE_DIR", "")
    if not run_id and not folder:
        return None  # Broader pytest invocation does not claim a strict receipt.
    if not re.fullmatch(r"[0-9a-f]{32}", run_id) or not folder:
        raise ValueError("INVALID_EVIDENCE_RUN_BINDING")
    path = Path(folder).resolve()
    if path.name != run_id or not path.is_dir():
        raise ValueError("INVALID_EVIDENCE_DIRECTORY")
    return path, run_id


def observe_postgres(connection, expected_database: str, expected_head: str, expected_major: int) -> dict:
    """Fixed read-only queries on the fixture's verified connection."""
    identity = connection.execute(
        "SELECT current_database(), current_user, inet_server_addr()::text, inet_server_port(), "
        "current_setting('server_version_num'), pg_postmaster_start_time()::text, "
        "(SELECT oid::text FROM pg_database WHERE datname=current_database())"
    ).fetchone()
    result = dict(
        zip(
            (
                "database",
                "user",
                "server_address",
                "server_port",
                "server_version_num",
                "postmaster_started_at",
                "database_oid",
            ),
            identity,
            strict=True,
        )
    )
    result["server_version_num"] = int(result["server_version_num"])
    result["migration_heads"] = sorted(
        row[0] for row in connection.execute("SELECT version_num FROM public.alembic_version").fetchall()
    )
    result["settings"] = {
        name: connection.execute("SELECT current_setting(%s, true)", (name,)).fetchone()[0] for name in PG_SETTINGS
    }
    result["tables"] = {
        name: connection.execute("SELECT to_regclass(%s)::text", (f"public.pair_activity_{name}_v31",)).fetchone()[0]
        for name in PG_TABLES
    }
    if (
        expected_major not in {16, 17}
        or result["server_version_num"] // 10000 != expected_major
        or result["database"] != expected_database
        or result["server_address"] not in {"127.0.0.1", "::1"}
        or result["migration_heads"] != [expected_head]
        or result["settings"]["wolf15.environment_class"] != "DISPOSABLE_TEST"
        or result["settings"]["wolf15.destructive_tests_allowed"] != "true"
        or result["settings"]["fsync"] != "on"
        or result["settings"]["synchronous_commit"] != "on"
        or not all(result["tables"].values())
    ):
        raise ValueError("POSTGRES_EVIDENCE_BINDING_REJECTED")
    return result


def write_fixture_phase(phase: str, observation: dict) -> None:
    target = evidence_directory()
    if target is None:
        return
    folder, run_id = target
    path = folder / f"postgres-{phase}.json"
    if path.exists():
        raise ValueError("DUPLICATE_POSTGRES_FIXTURE_EVIDENCE")
    write_json(path, {"run_id": run_id, "phase": phase, "at_utc": now(), "postgres": observation})


def record_runtime_fixture(binding, checkpoint) -> None:
    target = evidence_directory()
    if target is None:
        return
    folder, run_id = target
    entry = {
        "run_id": run_id,
        "test": os.environ.get("PYTEST_CURRENT_TEST", "UNKNOWN"),
        "binding": binding.model_dump(mode="json"),
        "binding_hash": binding.binding_hash,
        "checkpoint": None if checkpoint is None else checkpoint.model_dump(mode="json"),
    }
    with LOCK, (folder / "runtime-fixtures.jsonl").open("a", encoding="utf-8") as output:
        output.write(json.dumps(entry, sort_keys=True) + "\n")


def validate_fixture_receipts(
    folder: Path, run_id: str, expected_database: str, expected_head: str, expected_major: int
) -> dict:
    phases = [
        json.loads((folder / f"postgres-{phase}.json").read_text(encoding="utf-8")) for phase in ("before", "after")
    ]
    for phase, receipt in zip(("before", "after"), phases, strict=True):
        pg = receipt["postgres"]
        if (
            receipt["run_id"] != run_id
            or receipt["phase"] != phase
            or pg["database"] != expected_database
            or pg["migration_heads"] != [expected_head]
            or pg["server_version_num"] // 10000 != expected_major
        ):
            raise ValueError("FIXTURE_RECEIPT_BINDING_MISMATCH")
    if phases[0]["postgres"] != phases[1]["postgres"]:
        raise ValueError("POSTGRES_IDENTITY_OR_CONFIGURATION_CHANGED")
    lines = (folder / "runtime-fixtures.jsonl").read_text(encoding="utf-8").splitlines()
    if not lines or any(json.loads(line)["run_id"] != run_id for line in lines):
        raise ValueError("RUNTIME_FIXTURE_BINDING_MISSING")
    return {"before": phases[0], "after": phases[1], "runtime_fixture_count": len(lines)}
