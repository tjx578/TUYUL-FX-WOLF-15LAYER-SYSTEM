"""Offline stop/ownership checks; no Docker, PostgreSQL or credential-store calls."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.integration import run_canonical_v1_handoff_replay as runner

COMMIT = "1" * 40


def _arguments(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    source = tmp_path / "source"
    test = source / runner.TEST
    test.parent.mkdir(parents=True)
    test.write_text("# offline fixture only\n", encoding="utf-8")
    output = tmp_path / "receipt"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "runner",
            "--source-root",
            str(source),
            "--expected-commit",
            COMMIT,
            "--output-dir",
            str(output),
            "--docker",
            sys.executable,
        ],
    )
    return source, output


def test_wrong_source_commit_cannot_dispatch_container(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, output = _arguments(tmp_path, monkeypatch)
    calls: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        assert command == ["git", "rev-parse", "HEAD"]
        return subprocess.CompletedProcess(command, 0, stdout="2" * 40, stderr="")

    monkeypatch.setattr(runner.subprocess, "run", run)
    assert runner.main() == 3
    receipt = json.loads((output / "supervision-receipt.json").read_text(encoding="utf-8"))
    assert len(calls) == 1 and receipt["attempts"] == 0
    assert receipt["verdict"] == "HOLD" and receipt["cleanup"] == "NOT_EXECUTED"


def test_existing_output_directory_cannot_run_again(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, output = _arguments(tmp_path, monkeypatch)
    output.mkdir()

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("a reused one-shot output directory dispatched a process")

    monkeypatch.setattr(runner.subprocess, "run", forbidden)
    with pytest.raises(FileExistsError):
        runner.main()


def test_create_timeout_never_removes_a_container_without_matching_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, output = _arguments(tmp_path, monkeypatch)
    calls: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if command[:2] == ["git", "rev-parse"]:
            stdout = COMMIT if command[-1] == "HEAD" else "3" * 40
        elif command[:2] == ["git", "status"]:
            stdout = ""
        elif command[1:3] == ["image", "inspect"]:
            stdout = "sha256:" + "4" * 64
        elif command[1] == "run":
            raise subprocess.TimeoutExpired(command, timeout=1)
        elif command[1] == "inspect":
            stdout = json.dumps([{"Config": {"Labels": {"wolf15.p5-replay-claim": "another-invocation"}}}])
        else:
            raise AssertionError(f"unexpected or unsafe subprocess: {command[1:3]}")
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(runner.subprocess, "run", run)
    assert runner.main() == 3
    receipt = json.loads((output / "supervision-receipt.json").read_text(encoding="utf-8"))
    assert receipt["attempts"] == 1 and receipt["verdict"] == "HOLD"
    assert receipt["cleanup"] == "NOT_PROVEN"
    assert sum(command[1] == "run" for command in calls) == 1
    assert all(command[1] != "rm" for command in calls)
