"""Prepare and validate source-bound Pyright evidence without importing the app."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

NATIVE_TEST = "tests/test_native_mt5_readonly_mcp.py"
NATIVE_SOURCE = "ops/mt5_mcp"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def prepare(root: Path, scope: str) -> None:
    require(scope in {"core", "native-mcp"}, "Unsupported typecheck scope")
    folder = root / "artifacts/typecheck"
    folder.mkdir(parents=True, exist_ok=True)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    require(re.fullmatch(r"[0-9a-f]{40}", sha) is not None, "Invalid checked SHA")
    (folder / "checked-sha.txt").write_text(sha + "\n", encoding="utf-8")
    metadata = {
        key.lower(): os.environ.get(key) or None
        for key in (
            "EVENT_NAME",
            "EVENT_SHA",
            "EVENT_REF",
            "PR_NUMBER",
            "PR_HEAD_SHA",
            "PR_BASE_SHA",
            "RUN_ID",
            "RUN_ATTEMPT",
            "REPOSITORY",
            "WORKFLOW_REF",
            "WORKFLOW_SHA",
        )
    }
    write_json(folder / "source.json", {**metadata, "checked_sha": sha, "scope": scope})

    canonical = json.loads((root / "pyrightconfig.json").read_text(encoding="utf-8"))
    require(isinstance(canonical, dict), "Invalid canonical config")
    excluded = canonical.get("exclude", [])
    require(isinstance(excluded, list) and all(isinstance(p, str) for p in excluded), "Invalid exclusions")
    for name in (NATIVE_TEST, NATIVE_SOURCE):
        require((root / name).exists(), f"Missing native MCP scope: {name}")

    if scope == "core":
        config = {"extends": "./pyrightconfig.json", "exclude": list(dict.fromkeys([*excluded, NATIVE_TEST]))}
        requirements = (root / "requirements.txt").read_text(encoding="utf-8")
    else:
        # Windows static analysis needs the real terminal package for import
        # resolution. Installing it does not initialize a terminal or run tests.
        config = {
            "extends": "./pyrightconfig.json",
            "include": [NATIVE_SOURCE, NATIVE_TEST],
            "exclude": ["**/node_modules", "**/__pycache__", ".venv", "**/.*"],
            "pythonPlatform": "Windows",
        }
        requirements = (root / "ops/mt5_mcp/requirements.txt").read_text(encoding="utf-8") + "\n"
        core_lines = (root / "requirements.txt").read_text(encoding="utf-8").splitlines()
        for package in ("pytest", "pytest-asyncio"):
            pins = [line for line in core_lines if line.startswith(package + "==")]
            require(len(pins) == 1, f"Expected one canonical pin for {package}")
            requirements += pins[0] + "\n"

    write_json(root / ".pyright-ci.json", config)
    write_json(folder / "effective-pyright-config.json", config)
    (folder / "requirements-input.txt").write_text(requirements, encoding="utf-8")
    inputs = (
        "requirements.txt",
        "pyproject.toml",
        "pyrightconfig.json",
        "ops/mt5_mcp/requirements.txt",
        ".github/workflows/lint.yml",
        "scripts/ci/typecheck_evidence.py",
        ".pyright-ci.json",
        "artifacts/typecheck/requirements-input.txt",
    )
    write_json(
        folder / "input-sha256.json", {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in inputs}
    )


def validate_report(report: Any, *, version: str, exit_code: int, outcome: str) -> dict[str, int]:
    require(isinstance(report, dict), "Invalid report object")
    require(report.get("version") == version, "Unexpected Pyright version")
    summary = report.get("summary")
    require(isinstance(summary, dict), "Invalid report summary")
    keys = ("filesAnalyzed", "errorCount", "warningCount", "informationCount")
    counts = {key: summary.get(key) for key in keys}
    require(all(type(value) is int and value >= 0 for value in counts.values()), "Invalid report counts")
    require(counts["filesAnalyzed"] > 0, "No files analyzed")
    diagnostics = report.get("generalDiagnostics")
    require(isinstance(diagnostics, list), "Invalid diagnostic collection")
    totals = {"error": 0, "warning": 0, "information": 0}
    for item in diagnostics:
        require(isinstance(item, dict), "Invalid diagnostic")
        severity = item.get("severity")
        require(isinstance(severity, str) and severity in totals, "Invalid diagnostic severity")
        require(isinstance(item.get("file"), str) and bool(item["file"]), "Invalid diagnostic file")
        require(isinstance(item.get("message"), str), "Invalid diagnostic message")
        span = item.get("range")
        require(isinstance(span, dict), "Invalid diagnostic range")
        positions = []
        for endpoint in ("start", "end"):
            point = span.get(endpoint)
            require(isinstance(point, dict), "Invalid diagnostic endpoint")
            require(
                all(type(point.get(key)) is int and point[key] >= 0 for key in ("line", "character")),
                "Invalid diagnostic position",
            )
            positions.append((point["line"], point["character"]))
        require(positions[1] >= positions[0], "Reversed diagnostic range")
        totals[severity] += 1
    for severity, key in (("error", "errorCount"), ("warning", "warningCount"), ("information", "informationCount")):
        require(totals[severity] == counts[key], f"Diagnostic count mismatch: {severity}")
    errors = counts["errorCount"]
    require(exit_code == (1 if errors else 0), "Analyzer exit code disagrees with report")
    require(outcome == ("failure" if errors else "success"), "Step outcome disagrees with report")
    return counts


def summarize(folder: Path) -> None:
    report = json.loads((folder / "pyright.json").read_text(encoding="utf-8"))
    source = json.loads((folder / "source.json").read_text(encoding="utf-8"))
    sha = (folder / "checked-sha.txt").read_text(encoding="utf-8").strip()
    require(re.fullmatch(r"[0-9a-f]{40}", sha) is not None, "Invalid checked SHA")
    require(isinstance(source, dict) and source.get("checked_sha") == sha, "Source SHA mismatch")
    counts = validate_report(
        report,
        version=os.environ["PYRIGHT_VERSION"],
        exit_code=int((folder / "pyright-exit-code.txt").read_text().strip()),
        outcome=os.environ["TYPECHECK_OUTCOME"],
    )
    result = f"Files: {counts['filesAnalyzed']} | Errors: {counts['errorCount']} | Warnings: {counts['warningCount']}"
    print(f"Checked commit: {sha}\n{result}", flush=True)
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as output:
        output.write(f"### Pyright ({source['scope']})\n\nChecked commit: `{sha}`\n\n{result}\n\n")
        output.write("Warnings do not block this gate. Full diagnostics are uploaded by the artifact step.\n")
    errors = [item for item in report["generalDiagnostics"] if item["severity"] == "error"]
    for item in errors[:30]:
        print(json.dumps(item, ensure_ascii=True), flush=True)
    require(not errors, f"Pyright reported {len(errors)} errors; see pyright.json")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "summarize"))
    parser.add_argument("--scope", choices=("core", "native-mcp"), default="core")
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            prepare(Path.cwd(), args.scope)
        else:
            summarize(Path("artifacts/typecheck"))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"Typecheck evidence failed: {exc}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
