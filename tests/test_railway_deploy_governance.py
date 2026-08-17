from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "railway-deploy.yml"


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_railway_deploy_is_manual_single_service_only() -> None:
    workflow = _workflow_text()

    assert "workflow_dispatch:" in workflow
    assert "workflow_run:" not in workflow
    assert "matrix:" not in workflow
    assert "cancel-in-progress: false" in workflow
    assert "environment: production" in workflow
    assert "if: github.ref == 'refs/heads/main'" in workflow
    assert workflow.count("wolf15-pressure-outbox") == 2

    for forbidden_target in (
        "wolf15-api",
        "wolf15-engine",
        "wolf15-execution",
        "wolf15-ea-bridge",
        "wolf15-migrator",
        "wolf15-ingest",
        "wolf15-orchestrator",
        "wolf15-worker",
    ):
        assert forbidden_target not in workflow


def test_railway_deploy_binds_reviewed_main_sha_and_successful_ci() -> None:
    workflow = _workflow_text()

    assert "release_sha:" in workflow
    assert "ref: ${{ inputs.release_sha }}" in workflow
    assert "fetch-depth: 0" in workflow
    assert "^[0-9a-f]{40}$" in workflow
    assert "git rev-parse HEAD" in workflow
    assert workflow.count("git ls-remote --exit-code origin refs/heads/main") == 2
    assert "head_sha=${RELEASE_SHA}" in workflow
    assert "select(.head_sha == env.RELEASE_SHA" in workflow
    assert '.conclusion == "success"' in workflow


def test_railway_deploy_pins_cli_and_exact_production_selectors() -> None:
    workflow = _workflow_text()

    assert "npm install -g @railway/cli@5.41.0" in workflow
    assert 'test "$(railway --version)" = "railway 5.41.0"' in workflow
    assert "RAILWAY_PROJECT_ID: af4d15d8-d4cb-44b7-80e7-d99a37ca0045" in workflow
    assert "RAILWAY_ENVIRONMENT_ID: 5838964d-8c76-42b3-b0b9-18f2d1e4d5c2" in workflow
    assert "RAILWAY_SERVICE_ID: e555dbb1-76ea-4300-8244-80747cfc9786" in workflow
    assert '--project "$RAILWAY_PROJECT_ID"' in workflow
    assert '--environment "$RAILWAY_ENVIRONMENT_ID"' in workflow
    assert '--service "$RAILWAY_SERVICE_ID"' in workflow
    assert '--message "release_sha=${RELEASE_SHA} service=${RAILWAY_SERVICE_NAME}"' in workflow
    assert "Remote main changed after release validation; aborting deploy" in workflow
