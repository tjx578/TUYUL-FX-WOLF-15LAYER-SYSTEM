"""Negative controls for the CI report gate; no application services are used."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from scripts.ci.typecheck_evidence import prepare, summarize, validate_report

VERSION = "1.1.414"


def report(*, severity: str | None = None) -> dict[str, Any]:
    diagnostics = []
    if severity:
        diagnostics.append(
            {
                "file": "/repo/example.py",
                "message": "diagnostic",
                "severity": severity,
                "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 1}},
            }
        )
    return {
        "version": VERSION,
        "summary": {
            "filesAnalyzed": 1,
            "errorCount": int(severity == "error"),
            "warningCount": int(severity == "warning"),
            "informationCount": int(severity == "information"),
        },
        "generalDiagnostics": diagnostics,
    }


@pytest.mark.parametrize("severity", [None, "warning", "information"])
def test_non_error_report_can_pass(severity: str | None) -> None:
    assert (
        validate_report(report(severity=severity), version=VERSION, exit_code=0, outcome="success")["errorCount"] == 0
    )


@pytest.mark.parametrize(
    "exit_code,outcome", [(0, "success"), (0, "failure"), (1, "success"), (2, "failure"), (1, "skipped")]
)
def test_errors_cannot_be_overridden_by_step_status(exit_code: int, outcome: str) -> None:
    with pytest.raises(ValueError):
        validate_report(report(severity="error"), version=VERSION, exit_code=exit_code, outcome=outcome)


@pytest.mark.parametrize(
    "exit_code,outcome", [(1, "failure"), (2, "failure"), (0, "failure"), (0, "cancelled"), (0, "skipped")]
)
def test_clean_report_cannot_hide_runner_failure(exit_code: int, outcome: str) -> None:
    with pytest.raises(ValueError):
        validate_report(report(), version=VERSION, exit_code=exit_code, outcome=outcome)


@pytest.mark.parametrize("value", [0, -1, True, None, "1", 1.0])
def test_empty_or_invalid_file_count_rejected(value: Any) -> None:
    data = report()
    data["summary"]["filesAnalyzed"] = value
    with pytest.raises(ValueError):
        validate_report(data, version=VERSION, exit_code=0, outcome="success")


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", "1.1.408"),
        ("summary", []),
        ("generalDiagnostics", {}),
    ],
)
def test_invalid_report_structure_rejected(field: str, value: Any) -> None:
    data = report()
    data[field] = value
    with pytest.raises(ValueError):
        validate_report(data, version=VERSION, exit_code=0, outcome="success")


@pytest.mark.parametrize(
    "field,value",
    [
        ("severity", []),
        ("severity", "fatal"),
        ("file", ""),
        ("message", None),
        ("range", {}),
        ("range", {"start": {"line": True, "character": 0}, "end": {"line": 0, "character": 1}}),
        ("range", {"start": {"line": 1, "character": 0}, "end": {"line": 0, "character": 1}}),
    ],
)
def test_malformed_diagnostic_rejected(field: str, value: Any) -> None:
    data = report(severity="error")
    data["generalDiagnostics"][0][field] = value
    with pytest.raises(ValueError):
        validate_report(data, version=VERSION, exit_code=1, outcome="failure")


def test_summary_must_match_diagnostics() -> None:
    data = report()
    data["summary"]["warningCount"] = 1
    with pytest.raises(ValueError, match="count mismatch"):
        validate_report(data, version=VERSION, exit_code=0, outcome="success")


def test_summarizer_fails_on_type_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sha = "a" * 40
    (tmp_path / "pyright.json").write_text(json.dumps(report(severity="error")), encoding="utf-8")
    (tmp_path / "source.json").write_text(json.dumps({"checked_sha": sha, "scope": "core"}), encoding="utf-8")
    (tmp_path / "checked-sha.txt").write_text(sha, encoding="utf-8")
    (tmp_path / "pyright-exit-code.txt").write_text("1", encoding="utf-8")
    monkeypatch.setenv("PYRIGHT_VERSION", VERSION)
    monkeypatch.setenv("TYPECHECK_OUTCOME", "failure")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "summary.md"))
    with pytest.raises(ValueError, match="reported 1 errors"):
        summarize(tmp_path)
    assert "Errors: 1" in (tmp_path / "summary.md").read_text(encoding="utf-8")


def test_prepare_preserves_canonical_scope_and_splits_mcp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    canonical = {"include": ["**/*.py"], "exclude": ["scripts", "ops", "docs"], "typeCheckingMode": "standard"}
    fixture_files = {
        "pyrightconfig.json": json.dumps(canonical),
        "pyproject.toml": "",
        "requirements.txt": "pytest==9.0.3\npytest-asyncio==1.3.0\nredis>=5.0\n",
        "ops/mt5_mcp/requirements.txt": "MetaTrader5==5.0.6090\nmcp==2.0.0\npsutil==7.2.2\n",
        "tests/test_native_mt5_readonly_mcp.py": "",
        ".github/workflows/lint.yml": "",
        "scripts/ci/typecheck_evidence.py": "",
    }
    for name, content in fixture_files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    monkeypatch.setattr("scripts.ci.typecheck_evidence.subprocess.check_output", lambda *a, **kw: "a" * 40)
    prepare(tmp_path, "core")
    core = json.loads((tmp_path / ".pyright-ci.json").read_text())
    assert core["extends"] == "./pyrightconfig.json"
    assert core["exclude"] == [*canonical["exclude"], "tests/test_native_mt5_readonly_mcp.py"]
    assert json.loads((tmp_path / "pyrightconfig.json").read_text()) == canonical
    original = copy.deepcopy(core)
    prepare(tmp_path, "native-mcp")
    native = json.loads((tmp_path / ".pyright-ci.json").read_text())
    assert native["include"] == ["ops/mt5_mcp", "tests/test_native_mt5_readonly_mcp.py"]
    assert native["pythonPlatform"] == "Windows"
    requirements = (tmp_path / "artifacts/typecheck/requirements-input.txt").read_text()
    assert "MetaTrader5==5.0.6090" in requirements and "pytest==9.0.3" in requirements
    assert "redis" not in requirements
    assert original["exclude"][-1] in native["include"]
