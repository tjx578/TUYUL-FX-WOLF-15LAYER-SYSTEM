"""Prove the required replay launcher uses its child DB and rejects incomplete evidence."""

import json
import os
from contextlib import contextmanager
from pathlib import Path

import pytest

from scripts.ci import run_canonical_v1_replay_acceptance as runner


@pytest.mark.parametrize("fault", [None, "skip", "count", "lineage"])
def test_required_replay_uses_child_and_checks_both_receipts(tmp_path, monkeypatch, fault):
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setenv("DATABASE_URL", "baseline-must-not-be-used")
    monkeypatch.setenv("WOLF15_PAIR_ACTIVITY_TEST_DATABASE_URL", "baseline")
    monkeypatch.setenv("WOLF15_POSTGRES_TEST_DATABASE", "baseline")

    @contextmanager
    def child():
        with monkeypatch.context() as scope:
            scope.setenv("WOLF15_PAIR_ACTIVITY_TEST_DATABASE_URL", "child-disposable")
            scope.setenv("WOLF15_POSTGRES_TEST_DATABASE", "child")
            yield "child"

    monkeypatch.setattr(runner, "isolated_domain_database", child)
    monkeypatch.setattr(runner.subprocess, "check_output", lambda *_args, **_kwargs: "a" * 40)

    def run(command, *, cwd, env, check, timeout):
        assert env["DATABASE_URL"] == "child-disposable"
        assert env["WOLF15_POSTGRES_TEST_DATABASE"] == "child"
        assert env["WOLF15_P5_REPLAY_SOURCE_COMMIT"] == "a" * 40
        assert check is True and timeout == 240
        assert runner.TEST in command
        count = 2 if fault == "count" else 3
        cases = "".join("<testcase><skipped/></testcase>" if fault == "skip" else "<testcase/>" for _ in range(count))
        junit = Path(next(value.removeprefix("--junitxml=") for value in command if value.startswith("--junitxml=")))
        junit.write_text(f'<testsuites><testsuite tests="{count}">{cases}</testsuite></testsuites>')
        counts = {"commands": 1, "reservations": 1, "final_signals": 1, "execution_reports": 0, "broker_entities": 0}
        if fault == "lineage":
            counts["commands"] = 2
        Path(env["WOLF15_P5_REPLAY_RECEIPT"]).write_text(json.dumps({"counts": counts}))

    monkeypatch.setattr(runner.subprocess, "run", run)
    if fault is None:
        assert runner.main() == 0
    else:
        with pytest.raises(ValueError):
            runner.main()
    assert os.environ["WOLF15_PAIR_ACTIVITY_TEST_DATABASE_URL"] == "baseline"
    assert os.environ["DATABASE_URL"] == "baseline-must-not-be-used"


def test_existing_replay_receipt_prevents_reexecution(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    output = tmp_path / "artifacts/python-suite"
    output.mkdir(parents=True)
    (output / "canonical-v1-lineage.json").write_text("existing evidence")
    monkeypatch.setattr(runner.subprocess, "check_output", lambda *_a, **_k: pytest.fail("unexpected dispatch"))
    with pytest.raises(ValueError, match="RECEIPT_ALREADY_EXISTS"):
        runner.main()
