"""Fault receipts for exact-source deployment authorization, without provider calls."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from scripts.ci import railway_release_source_gate as gate

SHA = "a" * 40
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def receipt():
    run = {
        "id": 42,
        "workflow_id": 9,
        "path": gate.CI_PATH,
        "repository": {"full_name": "owner/repo"},
        "head_repository": {"full_name": "owner/repo"},
        "head_sha": SHA,
        "head_branch": "main",
        "event": "push",
        "status": "completed",
        "conclusion": "success",
        "run_attempt": 1,
    }
    jobs = [
        {
            "name": name,
            "head_sha": SHA,
            "run_id": 42,
            "run_attempt": 1,
            "status": "completed",
            "conclusion": "success",
            "runner_id": 123,
            "steps": [{"name": step, "status": "completed", "conclusion": "success"} for step in steps],
        }
        for name, steps in gate.REQUIRED_STEPS.items()
    ]
    return {
        "release_sha": SHA,
        "checkout_sha": SHA,
        "remote_main_sha": SHA,
        "repository": "owner/repo",
        "ci_run_id": "42",
        "workflow": {"id": 9, "path": gate.CI_PATH, "state": "active"},
        "run": run,
        "jobs": jobs,
    }


def test_complete_exact_source_receipt_passes(receipt):
    gate.validate_receipt(**receipt)


@pytest.mark.parametrize("field", ["release_sha", "checkout_sha", "remote_main_sha"])
def test_source_a_ci_cannot_deploy_source_b(receipt, field):
    receipt[field] = "b" * 40
    with pytest.raises(gate.ReleaseGateError):
        gate.validate_receipt(**receipt)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", 43),
        ("workflow_id", 10),
        ("path", ".github/workflows/spoof.yml"),
        ("head_sha", "b" * 40),
        ("head_branch", "feature"),
        ("repository", {"full_name": "other/repo"}),
        ("head_repository", {"full_name": "fork/repo"}),
        ("event", "pull_request"),
        ("event", "pull_request_target"),
        ("status", "queued"),
        ("conclusion", "failure"),
        ("conclusion", "skipped"),
        ("run_attempt", None),
    ],
)
def test_untrusted_or_incomplete_run_rejected(receipt, field, value):
    receipt["run"][field] = value
    with pytest.raises(gate.ReleaseGateError):
        gate.validate_receipt(**receipt)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("head_sha", "b" * 40),
        ("run_id", 43),
        ("run_attempt", 2),
        ("status", "queued"),
        ("conclusion", "skipped"),
        ("conclusion", "failure"),
        ("runner_id", 0),
        ("runner_id", None),
        ("steps", []),
    ],
)
def test_skipped_missing_runner_or_wrong_job_rejected(receipt, field, value):
    receipt["jobs"][0][field] = value
    with pytest.raises(gate.ReleaseGateError):
        gate.validate_receipt(**receipt)


@pytest.mark.parametrize("conclusion", ["failure", "skipped", "cancelled", None])
def test_failed_step_cannot_hide_behind_successful_job(receipt, conclusion):
    receipt["jobs"][0]["steps"][0]["conclusion"] = conclusion
    with pytest.raises(gate.ReleaseGateError):
        gate.validate_receipt(**receipt)


@pytest.mark.parametrize("case", ["missing_job", "duplicate_job", "missing_migration", "wrong_workflow", "disabled_ci"])
def test_required_evidence_cannot_be_removed(receipt, case):
    if case == "missing_job":
        receipt["jobs"].pop()
    elif case == "duplicate_job":
        receipt["jobs"].append(deepcopy(receipt["jobs"][0]))
    elif case == "missing_migration":
        receipt["jobs"][1]["steps"] = [
            step for step in receipt["jobs"][1]["steps"] if step["name"] != "Apply database migrations"
        ]
    elif case == "wrong_workflow":
        receipt["workflow"]["path"] = ".github/workflows/spoof.yml"
    else:
        receipt["workflow"]["state"] = "disabled_manually"
    with pytest.raises(gate.ReleaseGateError):
        gate.validate_receipt(**receipt)


def test_manual_dispatch_requires_explicit_sha_and_run_id(tmp_path, monkeypatch):
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps({"inputs": {}}), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setattr(gate, "github_json", lambda _: pytest.fail("must reject before API query"))
    assert gate.main() == 1


@pytest.mark.parametrize("event_name", ["workflow_dispatch", "workflow_run"])
@pytest.mark.parametrize("rerun", [False, True])
def test_cli_event_binding_and_rerun_race(receipt, tmp_path, monkeypatch, event_name, rerun):
    event = {"inputs": {"release_sha": SHA, "ci_run_id": "42"}, "workflow_run": {"head_sha": SHA, "id": 42}}
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event), encoding="utf-8")
    for key, value in {
        "GITHUB_EVENT_PATH": str(event_path),
        "GITHUB_REPOSITORY": "owner/repo",
        "GITHUB_EVENT_NAME": event_name,
        "GITHUB_REF": "refs/heads/main",
    }.items():
        monkeypatch.setenv(key, value)
    calls = []

    def github_json(endpoint):
        calls.append(endpoint)
        if endpoint.endswith("/ci.yml"):
            return receipt["workflow"]
        if "/jobs?" in endpoint:
            return {"jobs": receipt["jobs"], "total_count": len(receipt["jobs"])}
        result = deepcopy(receipt["run"])
        if rerun and calls.count(endpoint) > 1:
            result["run_attempt"] = 2
        return result

    monkeypatch.setattr(gate, "github_json", github_json)
    monkeypatch.setattr(gate, "command", lambda args: "" if "status" in args else SHA)
    assert gate.main() == int(rerun)
    assert all("railway" not in endpoint for endpoint in calls)


def test_real_cli_rejects_before_provider_when_dispatch_missing_evidence(tmp_path):
    event_path = tmp_path / "event.json"
    event_path.write_text('{"inputs": {}}', encoding="utf-8")
    env = dict(
        os.environ,
        GITHUB_EVENT_PATH=str(event_path),
        GITHUB_REPOSITORY="owner/repo",
        GITHUB_EVENT_NAME="workflow_dispatch",
        GITHUB_REF="refs/heads/main",
    )
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/ci/railway_release_source_gate.py")],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 1
    assert "Exact-source CI gate rejected" in result.stderr


def test_workflow_binds_checkout_and_never_swallows_provider_failure():
    source = (ROOT / ".github/workflows/railway-deploy.yml").read_text(encoding="utf-8")
    assert "ref: ${{ env.RELEASE_SHA }}" in source
    assert "fetch-depth: 0" in source
    assert "cancel-in-progress: false" in source
    assert "environment: production" in source
    assert "@railway/cli@5.41.0" in source
    assert "          - wolf15-worker\n" not in source
    assert source.index("python scripts/ci/railway_release_source_gate.py") < source.index("secrets['RAILWAY_TOKEN']")
    assert "set -euo pipefail" in source
    assert "continue-on-error" not in source
    assert "|| true" not in source
