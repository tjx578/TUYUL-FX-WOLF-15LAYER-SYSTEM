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


def for_workflow(receipt, path):
    result = deepcopy(receipt)
    index = list(gate.RELEASE_WORKFLOWS).index(path)
    result["expected_path"] = path
    result["workflow"].update(path=path, id=9 + index)
    result["run"].update(path=path, workflow_id=9 + index, id=42 + index)
    result["ci_run_id"] = str(42 + index)
    result["jobs"] = []
    for name, steps in gate.RELEASE_WORKFLOWS[path].items():
        job = deepcopy(receipt["jobs"][0])
        job.update(name=name, run_id=42 + index)
        job["steps"] = [
            {"name": step, "status": "completed", "conclusion": "success"} for step in steps or {"Executed check"}
        ]
        result["jobs"].append(job)
    return result


@pytest.mark.parametrize("path", list(gate.RELEASE_WORKFLOWS)[1:])
@pytest.mark.parametrize("fault", [None, "missing_job", "skipped_step", "source_mismatch", "spoof_workflow", "pending"])
def test_security_and_docs_are_bound_executed_workflows(receipt, path, fault):
    result = for_workflow(receipt, path)
    if fault == "missing_job":
        result["jobs"].pop()
    elif fault == "skipped_step":
        result["jobs"][0]["steps"][0]["conclusion"] = "skipped"
    elif fault == "source_mismatch":
        result["run"]["head_sha"] = "b" * 40
    elif fault == "spoof_workflow":
        result["run"]["workflow_id"] = 999
    elif fault == "pending":
        result["run"].update(status="in_progress", conclusion=None)
    if fault:
        with pytest.raises(gate.ReleaseGateError):
            gate.validate_receipt(**result)
    else:
        gate.validate_receipt(**result)


def test_latest_required_run_does_not_select_older_green(receipt):
    older = deepcopy(receipt["run"])
    latest = dict(older, id=43, status="in_progress", conclusion=None)
    assert gate.latest_required_run({"workflow_runs": [older, latest], "total_count": 2}, SHA) == latest
    with pytest.raises(gate.ReleaseGateError):
        gate.latest_required_run({"workflow_runs": [older], "total_count": 2}, SHA)
    with pytest.raises(gate.ReleaseGateError):
        gate.latest_required_run({"workflow_runs": [], "total_count": 0}, SHA)


@pytest.mark.parametrize("missing", sorted(gate.REQUIRED_STEPS["Python tests (pytest)"]))
def test_release_rejects_missing_postgres_or_runner_step(receipt, missing):
    job = next(job for job in receipt["jobs"] if job["name"] == "Python tests (pytest)")
    job["steps"] = [step for step in job["steps"] if step["name"] != missing]
    with pytest.raises(gate.ReleaseGateError, match="required CI step absent"):
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
@pytest.mark.parametrize("new_run", [False, True])
def test_cli_event_binding_and_rerun_race(receipt, tmp_path, monkeypatch, event_name, rerun, new_run):
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
    fixtures = {path: for_workflow(receipt, path) for path in gate.RELEASE_WORKFLOWS}

    def github_json(endpoint):
        calls.append(endpoint)
        for path, fixture in fixtures.items():
            name = path.rsplit("/", 1)[1]
            if endpoint.endswith("/" + name):
                return fixture["workflow"]
            if "/" + name + "/runs?" in endpoint:
                result = deepcopy(fixture["run"])
                if new_run and calls.count(endpoint) > 1:
                    result.update(id=result["id"] + 100, status="queued", conclusion=None)
                return {"workflow_runs": [result], "total_count": 1}
        fixture = next(f for f in fixtures.values() if f"/runs/{f['run']['id']}" in endpoint)
        if "/jobs?" in endpoint:
            return {"jobs": fixture["jobs"], "total_count": len(fixture["jobs"])}
        result = deepcopy(fixture["run"])
        if rerun and calls.count(endpoint) > 1:
            result["run_attempt"] = 2
        return result

    monkeypatch.setattr(gate, "github_json", github_json)
    monkeypatch.setattr(gate, "command", lambda args: "" if "status" in args else SHA)
    assert gate.main() == int(rerun or new_run)
    assert all("railway" not in endpoint for endpoint in calls)


def test_required_workflow_names_and_steps_match_repository():
    import yaml

    for path, required_jobs in gate.RELEASE_WORKFLOWS.items():
        workflow = yaml.safe_load((ROOT / path).read_text())
        jobs = {job.get("name", key): job for key, job in workflow["jobs"].items()}
        assert set(required_jobs).issubset(jobs)
        for name, required_steps in required_jobs.items():
            assert required_steps.issubset({step.get("name") for step in jobs[name]["steps"]})


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
