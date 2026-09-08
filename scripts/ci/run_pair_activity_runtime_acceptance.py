"""Require actual, non-skipped PostgreSQL acceptance with source-bound receipts."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEST = "tests/integration/test_pair_activity_runtime_postgres.py"
SOURCES = (
    TEST,
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
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCES}


def main() -> int:
    out = ROOT / "artifacts/pair-activity-runtime"
    out.mkdir(parents=True, exist_ok=True)
    before = source_hashes()
    base = [sys.executable, "-m", "pytest", TEST, "-o", "addopts=", "-p", "no:cacheprovider"]
    collection = subprocess.run(
        [*base, "--collect-only", "-q"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=180
    )
    (out / "collection.log").write_text(collection.stdout + collection.stderr, encoding="utf-8")
    expected = [line for line in collection.stdout.splitlines() if line.startswith(TEST + "::")]
    if collection.returncode or not expected or len(set(expected)) != len(expected):
        print("PostgreSQL acceptance collection failed")
        return 1
    result = subprocess.run(
        [*base, "-q", "--timeout=60", "--junitxml", str(out / "tests.xml")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
    )
    (out / "pytest.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    after = source_hashes()
    receipt = {
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "expected_tests": len(expected),
        "expected_ids": expected,
        "pytest_exit": result.returncode,
        "source_before": before,
        "source_after": after,
        "source_unchanged": before == after,
        "scope": "DISPOSABLE_POSTGRES_ONLY",
        "execution_authority": False,
    }
    try:
        receipt["counts"] = validate_junit(out / "tests.xml", expected)
        receipt["accepted"] = result.returncode == 0 and before == after
    except (OSError, ValueError, ET.ParseError):
        receipt["accepted"] = False
    (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                key: receipt.get(key)
                for key in ("head", "expected_tests", "pytest_exit", "counts", "source_unchanged", "accepted")
            }
        )
    )
    return 0 if receipt["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
