"""Bounded, fail-closed checks for Perf Guard; no production authority."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path
from xml.etree import ElementTree as ET

from scripts.ci.validate_suite_junit import validate

MODULES = (
    "analysis.tick_pipeline",
    "analysis.tick_filter",
    "analysis.price_analysis",
    "pipeline.wolf_constitutional_pipeline",
)
TICK_FILES = ("analysis/tick_pipeline.py", "analysis/tick_filter.py")


def validate_durations(path: Path, threshold: float = 5.0) -> dict:
    """JUnit must use junit_duration_report=call; reject incomplete evidence."""
    count = validate(path)
    violations = []
    for case in ET.parse(path).getroot().iter("testcase"):
        duration = float(case.attrib["time"])
        if not math.isfinite(duration) or duration < 0:
            raise ValueError("INVALID_TEST_DURATION")
        if duration > threshold:
            violations.append({"test": case.get("name"), "seconds": duration})
    return {"passed": not violations, "tests": count, "call_budget_seconds": threshold, "violations": violations}


def check_size(root: Path) -> dict:
    files = {}
    for name in TICK_FILES:
        files[name] = len((root / name).read_text(encoding="utf-8").splitlines())
    return {"passed": all(size <= 500 for size in files.values()), "max_lines": 500, "files": files}


def run_imports(output: Path) -> dict:
    # Preserve the aggregate import-chain budget in one fresh interpreter.
    # The parent timeout also bounds an import that never returns.
    code = (
        "import importlib, time\n"
        f"for module in {MODULES!r}:\n"
        "    before = time.perf_counter()\n"
        "    importlib.import_module(module)\n"
        "    print(f'{module}: {time.perf_counter() - before:.3f}s', flush=True)\n"
    )
    start = time.perf_counter()
    with (output / "imports.log").open("w", encoding="utf-8") as log:
        process = subprocess.run(
            [sys.executable, "-B", "-c", code],
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=30,
            check=False,
        )
    elapsed = time.perf_counter() - start
    return {
        "passed": process.returncode == 0 and elapsed <= 10.0,
        "returncode": process.returncode,
        "measurement": "aggregate import chain in one fresh interpreter, including interpreter startup",
        "budget_seconds": 10.0,
        "seconds": elapsed,
        "modules": list(MODULES),
    }


def run_tests(output: Path) -> dict:
    report = output / "tests.xml"
    # Never accept an artifact left by an earlier invocation.
    report.unlink(missing_ok=True)
    with (output / "pytest.log").open("w", encoding="utf-8") as log:
        process = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/",
                "--timeout=30",
                "-q",
                "--tb=short",
                "-m",
                "not slow",
                "--ignore=tests/integration",
                "--ignore=tests/test_native_mt5_readonly_mcp.py",
                "-o",
                "junit_duration_report=call",
                f"--junitxml={report}",
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=1500,
            check=False,
        )
    if process.returncode != 0:
        return {"passed": False, "pytest_returncode": process.returncode}
    return validate_durations(report)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("check", choices=("imports", "tests", "size"))
    args = parser.parse_args()
    output = Path("artifacts/perf-guard") / args.check
    output.mkdir(parents=True, exist_ok=True)
    try:
        if args.check == "imports":
            result = run_imports(output)
        elif args.check == "tests":
            result = run_tests(output)
        else:
            result = check_size(Path.cwd())
    except (OSError, ValueError, KeyError, ET.ParseError, subprocess.TimeoutExpired) as error:
        result = {"passed": False, "error_type": type(error).__name__}
    result["check"] = args.check
    payload = json.dumps(result, indent=2)
    (output / "result.json").write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
