"""Behavioral regressions for fail-closed performance evidence."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.ci import perf_guard


def junit(path: Path, *, duration: str = "0.2", outcome: str = "") -> None:
    path.write_text(
        f'<testsuites><testsuite tests="1"><testcase name="sample" time="{duration}">{outcome}'
        "</testcase></testsuite></testsuites>",
        encoding="utf-8",
    )


@pytest.mark.parametrize("returncode", [1, 2, 3, 4, 5, -9])
def test_pytest_errors_cannot_pass(tmp_path, monkeypatch, returncode):
    junit(tmp_path / "tests.xml")
    monkeypatch.setattr(perf_guard.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=returncode))
    assert perf_guard.run_tests(tmp_path)["passed"] is False
    assert not (tmp_path / "tests.xml").exists()


def test_success_requires_fresh_report(tmp_path, monkeypatch):
    junit(tmp_path / "tests.xml")
    monkeypatch.setattr(perf_guard.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0))
    with pytest.raises(FileNotFoundError):
        perf_guard.run_tests(tmp_path)


def test_success_with_report(tmp_path, monkeypatch):
    def run(argv, **kwargs):
        assert "junit_duration_report=call" in argv
        assert kwargs["timeout"] == 1500
        junit(tmp_path / "tests.xml")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(perf_guard.subprocess, "run", run)
    assert perf_guard.run_tests(tmp_path)["tests"] == 1


@pytest.mark.parametrize("outcome", ["<failure/>", "<error/>", "<skipped/>"])
def test_incomplete_cases_rejected(tmp_path, outcome):
    path = tmp_path / "tests.xml"
    junit(path, outcome=outcome)
    with pytest.raises(ValueError):
        perf_guard.validate_durations(path)


@pytest.mark.parametrize("content", ["", "<testsuites/>", '<testsuite tests="0"/>'])
def test_empty_or_malformed_report_rejected(tmp_path, content):
    path = tmp_path / "tests.xml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises((ValueError, perf_guard.ET.ParseError)):
        perf_guard.validate_durations(path)


@pytest.mark.parametrize("duration", ["nan", "inf", "-1", "invalid"])
def test_invalid_duration_rejected(tmp_path, duration):
    path = tmp_path / "tests.xml"
    junit(path, duration=duration)
    with pytest.raises(ValueError):
        perf_guard.validate_durations(path)


@pytest.mark.parametrize("duration,passed", [("5.0", True), ("5.001", False)])
def test_call_budget_boundary(tmp_path, duration, passed):
    path = tmp_path / "tests.xml"
    junit(path, duration=duration)
    assert perf_guard.validate_durations(path)["passed"] is passed


@pytest.mark.parametrize("returncode,passed", [(0, True), (1, False)])
def test_import_failure_cannot_pass(tmp_path, monkeypatch, returncode, passed):
    monkeypatch.setattr(perf_guard.time, "perf_counter", lambda: 0.0)
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        assert kwargs["timeout"] == 30
        return SimpleNamespace(returncode=returncode)

    monkeypatch.setattr(perf_guard.subprocess, "run", run)
    assert perf_guard.run_imports(tmp_path)["passed"] is passed
    assert len(calls) == 1


def test_import_budget_exceeded(tmp_path, monkeypatch):
    ticks = iter(range(100))
    monkeypatch.setattr(perf_guard.time, "perf_counter", lambda: next(ticks) * 11.0)
    monkeypatch.setattr(perf_guard.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0))
    assert perf_guard.run_imports(tmp_path)["passed"] is False


def test_timeout_writes_failure_receipt(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(perf_guard.sys, "argv", ["perf_guard", "imports"])

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("synthetic", 30)

    monkeypatch.setattr(perf_guard.subprocess, "run", timeout)
    assert perf_guard.main() == 1
    result = json.loads((tmp_path / "artifacts/perf-guard/imports/result.json").read_text())
    assert result["error_type"] == "TimeoutExpired"


@pytest.mark.parametrize("lines,passed", [(500, True), (501, False)])
def test_size_boundary(tmp_path, lines, passed):
    for name in perf_guard.TICK_FILES:
        path = tmp_path / name
        path.parent.mkdir(exist_ok=True)
        path.write_text("x\n" * lines)
    assert perf_guard.check_size(tmp_path)["passed"] is passed


def test_missing_tick_module_rejected(tmp_path):
    with pytest.raises(FileNotFoundError):
        perf_guard.check_size(tmp_path)


@pytest.mark.parametrize(
    "source,expected",
    [
        ("def test_example(): assert True", True),
        ("def test_example(): assert False", False),
        ("def test_broken(:", False),
        ("# no tests", False),
    ],
)
def test_real_pytest_outcomes(tmp_path, monkeypatch, source, expected):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    (tmp_path / "pytest.ini").write_text("[pytest]\naddopts = -p pytest_timeout\nmarkers = slow: slow test\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_example.py").write_text(source, encoding="utf-8")
    output = tmp_path / "evidence"
    output.mkdir()
    assert perf_guard.run_tests(output)["passed"] is expected
