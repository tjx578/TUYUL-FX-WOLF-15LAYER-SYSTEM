"""Require actual, non-skipped PostgreSQL acceptance with source-bound receipts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.ci.pair_activity_run_evidence import (  # noqa: E402 - direct script entrypoint binds repository imports
    digest,
    host_snapshot,
    migration_graph,
    now,
    redact,
    validate_fixture_receipts,
    write_json,
)

TEST = "tests/integration/test_pair_activity_runtime_postgres.py"
SOURCES = (
    TEST,
    "scripts/ci/pair_activity_run_evidence.py",
    "tests/conftest.py",
    "conftest.py",
    "requirements.txt",
    "pyproject.toml",
    "alembic.ini",
    ".github/workflows/ci.yml",
    "storage/migrations/env.py",
    "docs/remediation/2026-09-09/source-binding/selected-ssot-v3.1.md",
    "scripts/ci/run_pair_activity_runtime_acceptance.py",
    "analysis/strategy_5scr_raw_admission_blocks.py",
    "analysis/signal_throttle_log_analyzer.py",
    "analysis/strategy_5scr_pair_activity.py",
    "analysis/strategy_5scr_pair_activity_report.py",
    "analysis/strategy_5scr_activity_service.py",
    "contracts/strategy_5scr_pair_activity.py",
    "contracts/strategy_5scr_activity_runtime.py",
    "storage/strategy_5scr_activity_runtime.py",
    "storage/strategy_5scr_activity_schema.py",
    "storage/migrations/versions/20260909_01_pair_activity_runtime.py",
    "pipeline/wolf_constitutional_pipeline.py",
    "tests/integration/postgres_test_guard.py",
)


def validate_junit(path: Path, expected_ids: list[str]) -> dict[str, int]:
    root = ET.parse(path).getroot()
    cases = root.findall(".//testcase")
    counts = {
        "tests": len(cases),
        "failures": len(root.findall(".//failure")),
        "errors": len(root.findall(".//error")),
        "skipped": len(root.findall(".//skipped")),
    }
    identities = {(case.get("classname"), case.get("name")) for case in cases}
    expected = len(expected_ids)
    expected_identities = set()
    for node_id in expected_ids:
        parts = node_id.split("::")
        if len(parts) < 2 or not parts[0].endswith(".py"):
            raise ValueError("invalid collected test identity")
        classname = ".".join([parts[0][:-3].replace("/", "."), *parts[1:-1]])
        expected_identities.add((classname, parts[-1]))
    if (
        expected <= 0
        or counts["tests"] != expected
        or len(identities) != expected
        or identities != expected_identities
        or any(counts[key] for key in ("failures", "errors", "skipped"))
    ):
        raise ValueError(
            "PostgreSQL acceptance must execute every collected case exactly once with no failure/error/skip"
        )
    return counts


def source_hashes() -> dict[str, str]:
    names = set(SOURCES) | {p.relative_to(ROOT).as_posix() for p in (ROOT / "storage/migrations/versions").glob("*.py")}
    return {name: digest(ROOT / name) for name in sorted(names)}


def main() -> int:
    run_id = uuid4().hex
    out = ROOT / "artifacts/pair-activity-runtime" / run_id
    out.mkdir(parents=True, exist_ok=False)
    receipt = {
        "run_id": run_id,
        "started_at_utc": now(),
        "accepted": False,
        "scope": "DISPOSABLE_POSTGRES_ONLY",
        "execution_authority": False,
        "migration_upgrade_execution": "NOT_BOUND",
        "linux_acceptance": "NOT_EXECUTED",
    }
    write_json(out / "receipt.json", receipt)
    env = dict(os.environ)
    # Each child belongs to this invocation; an old directory cannot be reused.
    env.update(
        WOLF15_PAIR_ACTIVITY_RUN_ID=run_id,
        WOLF15_PAIR_ACTIVITY_EVIDENCE_DIR=str(out),
        WOLF15_LOAD_DOTENV="false",
        PYTHONDONTWRITEBYTECODE="1",
    )
    try:
        receipt["head"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        receipt["tree"] = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True).strip()
        receipt["working_tree_clean"] = not subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=normal"], cwd=ROOT, text=True
        ).strip()
        receipt["source_before"] = source_hashes()
        graph = migration_graph(ROOT)
        receipt["migration_graph"] = graph
        expected_head = graph["repository_heads"][0]
        env["WOLF15_PAIR_ACTIVITY_EXPECTED_MIGRATION_HEAD"] = expected_head
        enabled = env.get("WOLF15_RUN_POSTGRES_INTEGRATION") == "1"
        if enabled:
            from urllib.parse import urlsplit

            from tests.integration.postgres_test_guard import (
                require_destructive_postgres_opt_in,
                require_disposable_postgres_target,
            )

            require_destructive_postgres_opt_in(env.get("WOLF15_ALLOW_DESTRUCTIVE_PG_TESTS", ""))
            dsn = env["WOLF15_PAIR_ACTIVITY_TEST_DATABASE_URL"]
            require_disposable_postgres_target(dsn, expected_database=env["WOLF15_POSTGRES_TEST_DATABASE"])
            if urlsplit(dsn).query or urlsplit(dsn).fragment:
                raise ValueError("DSN_OVERRIDE_FORBIDDEN")
            if int(env["WOLF15_PAIR_ACTIVITY_EXPECTED_PG_MAJOR"]) not in {16, 17}:
                raise ValueError("UNSUPPORTED_EXPECTED_POSTGRES_MAJOR")
        receipt["host"] = host_snapshot(enabled)
        if enabled:
            capacity = receipt["host"]["capacity"]
            if (
                capacity.get("below_90_percent") is not True
                or capacity.get("cgroup", {}).get("below_90_percent") is False
            ):
                raise ValueError("RUNNER_CAPACITY_NOT_ADMITTED")
        base = [sys.executable, "-m", "pytest", TEST, "-o", "addopts=", "-p", "no:cacheprovider"]
        collection = subprocess.run(
            [*base, "--collect-only", "-q"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=180,
        )
        (out / "collection.log").write_text(redact(collection.stdout + collection.stderr, env), encoding="utf-8")
        expected = [line for line in collection.stdout.splitlines() if line.startswith(TEST + "::")]
        receipt.update(collection_exit=collection.returncode, expected_tests=len(expected), expected_ids=expected)
        if collection.returncode or not expected or len(set(expected)) != len(expected):
            raise ValueError("ACCEPTANCE_COLLECTION_FAILED")
        result = subprocess.run(
            [*base, "-q", "--timeout=60", "--junitxml", str(out / "tests.xml")],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=300,
        )
        (out / "pytest.log").write_text(redact(result.stdout + result.stderr, env), encoding="utf-8")
        receipt["pytest_exit"] = result.returncode
        if (out / "tests.xml").is_file():
            xml = (out / "tests.xml").read_text(encoding="utf-8")
            (out / "tests.xml").write_text(redact(xml, env), encoding="utf-8")
        if (out / "tests.xml").is_file():
            xml_root = ET.parse(out / "tests.xml").getroot()
            receipt["observed_counts"] = {
                key: len(xml_root.findall(".//" + tag))
                for key, tag in (
                    ("tests", "testcase"),
                    ("failures", "failure"),
                    ("errors", "error"),
                    ("skipped", "skipped"),
                )
            }
        receipt["counts"] = validate_junit(out / "tests.xml", expected)
        receipt["postgres"] = validate_fixture_receipts(
            out,
            run_id,
            env["WOLF15_POSTGRES_TEST_DATABASE"],
            expected_head,
            int(env["WOLF15_PAIR_ACTIVITY_EXPECTED_PG_MAJOR"]),
        )
        receipt["accepted"] = enabled and result.returncode == 0 and receipt["working_tree_clean"]
    except Exception as error:
        # Exception text and subprocess output may contain a DSN. Only classify it here.
        receipt["failure_class"] = type(error).__name__
        receipt["accepted"] = False
    finally:
        try:
            receipt["source_after"] = source_hashes()
            receipt["source_unchanged"] = receipt.get("source_before") == receipt["source_after"]
            receipt["accepted"] = receipt["accepted"] and receipt["source_unchanged"]
            receipt["artifacts"] = {
                p.name: digest(p)
                for p in sorted(out.iterdir())
                if p.is_file() and p.name not in {"receipt.json", "receipt.tmp"}
            }
        except Exception as error:
            receipt["finalization_failure_class"] = type(error).__name__
            receipt["accepted"] = False
        receipt["completed_at_utc"] = now()
        if receipt["accepted"] and receipt.get("host", {}).get("os") == "Linux":
            receipt["linux_acceptance"] = "EXECUTED_POSTGRES_SUBSET_ONLY"
        write_json(out / "receipt.json", receipt)
    print(
        json.dumps(
            {
                key: receipt.get(key)
                for key in (
                    "run_id",
                    "head",
                    "expected_tests",
                    "pytest_exit",
                    "counts",
                    "source_unchanged",
                    "accepted",
                    "failure_class",
                )
            }
        )
    )
    return 0 if receipt["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
