"""Execute the manual workflow's actual summary code with adverse job results."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"
CALLEES = {"ci": "ci.yml", "security": "wolf-security-scan.yml", "docs": "docs-hygiene.yml"}


def _workflow(name):
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _run_summary(raw: str | None) -> subprocess.CompletedProcess:
    workflow = _workflow("wolf-pipeline-ci.yml")
    script = workflow["jobs"]["verification-summary"]["steps"][0]["run"]
    source = script.split("python3 - <<'PY'\n", 1)[1].rsplit("PY", 1)[0]
    env = {key: os.environ[key] for key in ("SystemRoot", "PATH") if key in os.environ}
    env["PYTHONUTF8"] = "1"
    if raw is not None:
        env["NEEDS_JSON"] = raw
    return subprocess.run(
        [sys.executable, "-c", source],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=10,
        env=env,
    )


def _successful_results() -> dict[str, Any]:
    return {name: {"result": "success", "outputs": {}} for name in CALLEES}


def test_manual_summary_accepts_only_complete_success():
    result = _run_summary(json.dumps(_successful_results()))
    assert result.returncode == 0, result.stderr
    assert "Canonical release receipts remain required" in result.stdout


@pytest.mark.parametrize("name", CALLEES)
@pytest.mark.parametrize("status", ["failure", "cancelled", "skipped", "queued", "", None, True])
def test_manual_summary_rejects_every_unsuccessful_callee(name, status):
    results = _successful_results()
    results[name]["result"] = status
    result = _run_summary(json.dumps(results))
    assert result.returncode != 0
    assert name in result.stderr
    assert "All called workflows passed" not in result.stdout


@pytest.mark.parametrize("raw", [None, "", "{", "null", "[]", "false", "{}"])
def test_manual_summary_rejects_missing_or_malformed_results(raw):
    assert _run_summary(raw).returncode != 0


@pytest.mark.parametrize("name", CALLEES)
@pytest.mark.parametrize("fault", ["missing", "non-object", "missing-result"])
def test_manual_summary_rejects_incomplete_job_evidence(name, fault):
    results = _successful_results()
    if fault == "missing":
        del results[name]
    elif fault == "non-object":
        results[name] = "success"
    else:
        results[name] = {"outputs": {}}
    assert _run_summary(json.dumps(results)).returncode != 0


def test_manual_summary_rejects_unexpected_job():
    results = _successful_results()
    results["unreviewed-job"] = {"result": "success"}
    assert _run_summary(json.dumps(results)).returncode != 0


def test_manual_workflow_covers_all_calls_without_secrets_or_privilege_increase():
    workflow = _workflow("wolf-pipeline-ci.yml")
    # PyYAML's YAML 1.1 loader treats the Actions key `on` as boolean True.
    assert set(workflow[True]) == {"workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "read"}
    jobs = workflow["jobs"]
    gate = jobs["verification-summary"]
    assert set(gate["needs"]) == set(jobs) - {"verification-summary"} == set(CALLEES)
    assert gate["if"] == "always()"
    assert gate["timeout-minutes"] <= 5
    assert gate["steps"][0]["env"]["NEEDS_JSON"] == "${{ toJSON(needs) }}"
    assert not gate.get("continue-on-error", False)
    assert not gate["steps"][0].get("continue-on-error", False)
    for name, filename in CALLEES.items():
        call = jobs[name]
        assert call["uses"] == f"./.github/workflows/{filename}"
        assert "secrets" not in call
        assert "if" not in call
        callee = _workflow(filename)
        assert "workflow_call" in callee[True]
        assert {"push", "pull_request"}.issubset(callee[True])
        assert callee["permissions"] == {"contents": "read"}


@pytest.mark.parametrize("ref", ["refs/heads/main", "refs/heads/fixture-feature"])
def test_nested_workflows_do_not_share_a_concurrency_group(ref):
    caller = _workflow("wolf-pipeline-ci.yml")
    substitutions = {
        "${{ github.workflow }}": caller["name"],
        "${{ github.ref }}": ref,
        "${{ github.event_name }}": "workflow_dispatch",
        "${{ github.event.pull_request.number || github.ref }}": ref,
    }
    groups = []
    for filename in ("wolf-pipeline-ci.yml", "ci.yml", "lint.yml"):
        group = _workflow(filename)["concurrency"]["group"]
        for expression, value in substitutions.items():
            group = group.replace(expression, value)
        assert "${{" not in group
        groups.append(group.casefold())
    assert len(set(groups)) == len(groups)


def test_repository_contracts_are_required_before_service_acceptance():
    from scripts.ci.railway_release_source_gate import REQUIRED_STEPS

    steps = _workflow("ci.yml")["jobs"]["tests"]["steps"]
    names = [step.get("name") for step in steps]
    contract = next(step for step in steps if step.get("name") == "Validate repository contracts")
    assert contract["run"] == "python scripts/ci/check_repository_contracts.py"
    assert "if" not in contract
    assert not contract.get("continue-on-error", False)
    assert names.index("Install dependencies") < names.index("Validate repository contracts")
    assert names.index("Validate repository contracts") < names.index("Apply database migrations")
    assert "Validate repository contracts" in REQUIRED_STEPS["Python tests (pytest)"]
