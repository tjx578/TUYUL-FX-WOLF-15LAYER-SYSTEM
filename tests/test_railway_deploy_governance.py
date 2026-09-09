"""Provider-free checks for the approved four-service release workflow policy."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "railway-deploy.yml"
ALLOWED_TARGETS = {
    "wolf15-api": "d3f53524-4571-496f-8008-b3f98fedc5b9",
    "wolf15-engine": "43bc213a-96af-4ed5-b679-691534fad4b4",
    "wolf15-ingest": "e7fb1aa7-2ca0-4287-bd53-35d82181c890",
    "wolf15-orchestrator": "4492195c-81cd-4e7d-88e8-bf6e380bbcc2",
}


def _workflow() -> dict[str, Any]:
    # BaseLoader preserves GitHub's `on` key instead of treating it as a YAML 1.1 boolean.
    return yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def _assert_allowed_targets(workflow: dict[str, Any]) -> None:
    assert set(workflow["jobs"]) == {"deploy"}
    matrix = workflow["jobs"]["deploy"]["strategy"]["matrix"]
    assert set(matrix) == {"include"}
    targets = matrix["include"]
    assert len(targets) == len(ALLOWED_TARGETS)
    assert all(set(target) == {"service", "service_id"} for target in targets)
    assert {target["service"]: target["service_id"] for target in targets} == ALLOWED_TARGETS


def test_automatic_and_manual_releases_keep_exact_four_service_policy() -> None:
    workflow = _workflow()
    _assert_allowed_targets(workflow)
    assert set(workflow["on"]) == {"workflow_run", "workflow_dispatch"}
    assert workflow["on"]["workflow_run"] == {"workflows": ["CI"], "types": ["completed"]}
    inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"release_sha", "ci_run_id"}
    assert all(value["required"] == "true" and value["type"] == "string" for value in inputs.values())
    condition = workflow["jobs"]["deploy"]["if"]
    assert "github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/main'" in condition
    assert "github.event.workflow_run.conclusion == 'success'" in condition
    assert "github.event.workflow_run.head_branch == 'main'" in condition
    assert workflow["concurrency"]["cancel-in-progress"] == "false"
    assert workflow["jobs"]["deploy"]["environment"] == "production"


@pytest.mark.parametrize(
    "service",
    ["wolf15-pressure-outbox", "wolf15-migrator", "wolf15-execution", "wolf15-ea-bridge", "wolf15-worker"],
)
def test_target_policy_rejects_service_outside_approved_list(service: str) -> None:
    workflow = deepcopy(_workflow())
    workflow["jobs"]["deploy"]["strategy"]["matrix"]["include"][0]["service"] = service
    with pytest.raises(AssertionError):
        _assert_allowed_targets(workflow)


@pytest.mark.parametrize("mutation", ["wrong_id", "additional_target", "duplicate_target", "additional_job"])
def test_target_policy_rejects_selector_substitution_or_expansion(mutation: str) -> None:
    workflow = deepcopy(_workflow())
    targets = workflow["jobs"]["deploy"]["strategy"]["matrix"]["include"]
    if mutation == "wrong_id":
        targets[0]["service_id"] = "unapproved-service-id"
    elif mutation == "additional_target":
        targets.append({"service": "wolf15-ea-bridge", "service_id": "unapproved-service-id"})
    elif mutation == "duplicate_target":
        targets[0] = deepcopy(targets[1])
    else:
        workflow["jobs"]["extra-deploy"] = deepcopy(workflow["jobs"]["deploy"])
    with pytest.raises(AssertionError):
        _assert_allowed_targets(workflow)


def test_both_release_paths_use_main_exact_source_gate_before_credentials_and_deploy() -> None:
    workflow = _workflow()
    job = workflow["jobs"]["deploy"]
    assert job["env"]["RELEASE_SHA"] == "${{ github.event.workflow_run.head_sha || inputs.release_sha }}"
    steps = job["steps"]
    checkout = steps[0]
    assert checkout["uses"] == "actions/checkout@v4"
    assert checkout["with"] == {"ref": "${{ env.RELEASE_SHA }}", "fetch-depth": "0"}
    gate_indices = [
        index
        for index, step in enumerate(steps)
        if step.get("run") == "python scripts/ci/railway_release_source_gate.py"
    ]
    assert len(gate_indices) == 2
    credential_indices = [index for index, step in enumerate(steps) if "RAILWAY_TOKEN" in step.get("env", {})]
    assert credential_indices and gate_indices[0] < min(credential_indices)
    assert gate_indices[1] == len(steps) - 2
    assert all("if" not in steps[index] for index in gate_indices)
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "continue-on-error" not in source
    assert "|| true" not in source


def test_pinned_cli_and_exact_production_selectors_are_used_by_deployment() -> None:
    job = _workflow()["jobs"]["deploy"]
    assert job["env"]["RAILWAY_PROJECT_ID"] == "af4d15d8-d4cb-44b7-80e7-d99a37ca0045"
    assert job["env"]["RAILWAY_ENVIRONMENT_ID"] == "5838964d-8c76-42b3-b0b9-18f2d1e4d5c2"
    commands = [step.get("run", "") for step in job["steps"]]
    assert "npm install -g @railway/cli@5.41.0" in commands
    assert 'test "$(railway --version)" = "railway 5.41.0"' in commands
    deploy = commands[-1]
    assert "set -euo pipefail" in deploy
    assert deploy.count("railway up") == 1
    assert '--project "$RAILWAY_PROJECT_ID"' in deploy
    assert '--environment "$RAILWAY_ENVIRONMENT_ID"' in deploy
    assert '--service "${{ matrix.service_id }}"' in deploy
    assert '--message "release_sha=${RELEASE_SHA}"' in deploy
    assert "--ci" in deploy
