"""Run the reviewed performance inventory without coverage; require every identity."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import yaml


def entries(manifest: dict) -> list[dict]:
    rows = [*manifest["definitions"], *manifest["additional_preserved_definitions"]]
    if (
        len(rows) != 23
        or sum(row["instance_count"] for row in rows) != 29
        or manifest["candidate_counts"]["benchmark_instances"] != 29
    ):
        raise ValueError("PERFORMANCE_INVENTORY_CHANGED_WITHOUT_RECONCILIATION")
    return rows


def validate_results(path: Path, rows: list[dict]) -> list[str]:
    cases = ET.parse(path).getroot().findall(".//testcase")
    identities = [(case.get("classname"), case.get("name")) for case in cases]
    if len(identities) != len(set(identities)):
        raise ValueError("DUPLICATE_PERFORMANCE_IDENTITY")
    if any(case.find(tag) is not None for case in cases for tag in ("failure", "error", "skipped")):
        raise ValueError("PERFORMANCE_CASE_NOT_PASSED")
    matched = set()
    for row in rows:
        pattern = row["node_pattern"]
        parts = pattern.removesuffix("[*]").split("::")
        classname = ".".join([parts[0][:-3].replace("/", "."), *parts[1:-1]])
        name = parts[-1]
        expected_names = row["expected_names"] if pattern.endswith("[*]") else [name]
        expected = {(classname, expected_name) for expected_name in expected_names}
        if len(expected) != row["instance_count"]:
            raise ValueError("INVALID_EXPECTED_PERFORMANCE_IDENTITIES")
        selected = {identity for identity in identities if identity in expected}
        if selected != expected or matched.intersection(selected):
            raise ValueError("PERFORMANCE_IDENTITY_MISSING_OR_OVERLAPPING")
        matched.update(selected)
    if matched != set(identities):
        raise ValueError("UNREVIEWED_PERFORMANCE_IDENTITY")
    return sorted("::".join(identity) for identity in identities)


def main() -> int:
    root = Path.cwd()
    out = root / "artifacts/python-suite"
    out.mkdir(parents=True, exist_ok=True)
    receipt = {"accepted": False, "scope": "REVIEWED_UNINSTRUMENTED_TEST_WORKLOADS_ONLY"}
    try:
        manifest_path = root / "tests/performance_gate_manifest.yaml"
        manifest = yaml.safe_load(manifest_path.read_text())
        rows = entries(manifest)
        files = sorted({row["source_file"] for row in rows})
        bound = [
            *files,
            "tests/performance_gate_manifest.yaml",
            "scripts/ci/performance_acceptance.py",
            "pytest.ini",
            "requirements.txt",
            ".github/workflows/ci.yml",
        ]

        def hashes():
            return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in bound}

        receipt["source_before"] = hashes()
        receipt["source_commit"] = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        receipt["run_id"] = os.environ.get("GITHUB_RUN_ID")
        receipt["runner_os"] = os.environ.get("RUNNER_OS")
        receipt["coverage_enabled"] = False
        # Disable both inherited pytest options and coverage auto-start. Timing
        # assertions remain unchanged; 300 seconds is only a process safety cap.
        env = dict(os.environ)
        env.pop("COVERAGE_PROCESS_START", None)
        env.pop("COVERAGE_RCFILE", None)
        env["PYTEST_ADDOPTS"] = ""
        command = [
            sys.executable,
            "-m",
            "pytest",
            *files,
            "-m",
            "benchmark",
            "-o",
            "addopts=",
            "-o",
            "junit_family=xunit1",
            "-p",
            "no:cov",
            "-q",
            "--timeout=300",
            f"--junitxml={out / 'benchmark.xml'}",
        ]
        receipt["command"] = command
        (out / "benchmark.xml").unlink(missing_ok=True)
        result = subprocess.run(command, env=env, timeout=600)
        receipt["pytest_exit"] = result.returncode
        receipt["source_after"] = hashes()
        receipt["source_unchanged"] = receipt["source_before"] == receipt["source_after"]
        receipt["identities"] = validate_results(out / "benchmark.xml", rows)
        receipt["junit_sha256"] = hashlib.sha256((out / "benchmark.xml").read_bytes()).hexdigest()
        receipt["accepted"] = result.returncode == 0 and receipt["source_unchanged"]
    except Exception as error:
        receipt["failure_class"] = type(error).__name__
    (out / "performance-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return 0 if receipt["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
