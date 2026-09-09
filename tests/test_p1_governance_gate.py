"""Negative C05 receipts use fixtures only, never a live provider or credentials."""

from copy import deepcopy

import pytest

from scripts.ci import p1_governance_gate as gate

SHA = "a" * 40
REPO = "owner/repo"


@pytest.fixture
def protection():
    return {
        "required_status_checks": {
            "strict": True,
            "checks": [{"context": name, "app_id": gate.GITHUB_ACTIONS_APP_ID} for name in gate.REQUIRED_CONTEXTS],
        },
        "enforce_admins": {"enabled": True},
        "required_pull_request_reviews": {
            "required_approving_review_count": 1,
            "dismiss_stale_reviews": True,
            "require_last_push_approval": True,
            "bypass_pull_request_allowances": {"users": [], "teams": [], "apps": []},
        },
        "allow_force_pushes": {"enabled": False},
        "required_conversation_resolution": {"enabled": True},
        "allow_deletions": {"enabled": False},
    }


@pytest.fixture
def environment():
    return {
        "name": "Production",
        "can_admins_bypass": False,
        "protection_rules": [
            {
                "type": "required_reviewers",
                "prevent_self_review": True,
                "reviewers": [{"type": "User", "reviewer": {"id": 123}}],
            }
        ],
        "deployment_branch_policy": {"protected_branches": True, "custom_branch_policies": False},
    }


@pytest.fixture
def receipt():
    def make(path):
        jobs = []
        checks = {}
        for job_id, (name, steps) in enumerate(gate.REQUIRED_WORKFLOWS[path].items(), 100):
            jobs.append(
                {
                    "id": job_id,
                    "check_run_url": f"https://api.github.com/repos/{REPO}/check-runs/{job_id}",
                    "name": name,
                    "head_sha": SHA,
                    "run_id": 42,
                    "run_attempt": 1,
                    "status": "completed",
                    "conclusion": "success",
                    "runner_id": 123,
                    "steps": [{"name": step, "status": "completed", "conclusion": "success"} for step in steps],
                }
            )
            checks[job_id] = {
                "id": job_id,
                "name": name,
                "head_sha": SHA,
                "status": "completed",
                "conclusion": "success",
                "app": {"id": gate.GITHUB_ACTIONS_APP_ID, "slug": "github-actions"},
                "check_suite": {"id": 7},
            }
        return {
            "repository": REPO,
            "release_sha": SHA,
            "path": path,
            "workflow": {"id": 9, "path": path, "state": "active"},
            "run": {
                "id": 42,
                "workflow_id": 9,
                "path": path,
                "head_sha": SHA,
                "head_branch": "main",
                "repository": {"full_name": REPO},
                "head_repository": {"full_name": REPO},
                "event": "push",
                "status": "completed",
                "conclusion": "success",
                "run_attempt": 1,
                "check_suite_id": 7,
            },
            "jobs": jobs,
            "checks": checks,
        }

    return make


def test_active_protection_and_environment_pass(protection, environment):
    gate.validate_branch_protection(protection)
    gate.validate_environment(environment)


def test_owner_operated_policy_without_independent_review_rejects(protection, environment):
    protection["required_pull_request_reviews"]["required_approving_review_count"] = 0
    protection["required_pull_request_reviews"]["require_last_push_approval"] = False
    environment["protection_rules"] = [{"type": "branch_policy"}]
    with pytest.raises(gate.GovernanceGateError):
        gate.validate_branch_protection(protection)
    with pytest.raises(gate.GovernanceGateError):
        gate.validate_environment(environment)


@pytest.mark.parametrize(
    "field",
    [
        "required_status_checks",
        "enforce_admins",
        "required_pull_request_reviews",
        "allow_force_pushes",
        "allow_deletions",
        "required_conversation_resolution",
    ],
)
def test_missing_protection_field_rejects(protection, field):
    del protection[field]
    with pytest.raises(gate.GovernanceGateError):
        gate.validate_branch_protection(protection)


@pytest.mark.parametrize(
    "case",
    [
        "loose",
        "missing_context",
        "unbound_app",
        "wrong_app",
        "duplicate_context",
        "admins",
        "negative_reviews",
        "bool_reviews",
        "stale",
        "last_push",
        "unresolved_conversations",
        "bypass_user",
        "bypass_team",
        "bypass_app",
        "force",
        "delete",
    ],
)
def test_weakened_protection_rejects(protection, case):
    status = protection["required_status_checks"]
    reviews = protection["required_pull_request_reviews"]
    if case == "loose":
        status["strict"] = False
    elif case == "missing_context":
        status["checks"].pop()
    elif case == "unbound_app":
        status["checks"][0]["app_id"] = None
    elif case == "wrong_app":
        status["checks"][0]["app_id"] = 1
    elif case == "duplicate_context":
        status["checks"].append(deepcopy(status["checks"][0]))
    elif case == "admins":
        protection["enforce_admins"]["enabled"] = False
    elif case == "negative_reviews":
        reviews["required_approving_review_count"] = -1
    elif case == "bool_reviews":
        reviews["required_approving_review_count"] = True
    elif case == "stale":
        reviews["dismiss_stale_reviews"] = False
    elif case == "last_push":
        reviews["require_last_push_approval"] = False
    elif case == "unresolved_conversations":
        protection["required_conversation_resolution"]["enabled"] = False
    elif case.startswith("bypass_"):
        reviews["bypass_pull_request_allowances"][
            {"bypass_user": "users", "bypass_team": "teams", "bypass_app": "apps"}[case]
        ] = [{"id": 1}]
    elif case == "force":
        protection["allow_force_pushes"]["enabled"] = True
    else:
        protection["allow_deletions"]["enabled"] = True
    with pytest.raises(gate.GovernanceGateError):
        gate.validate_branch_protection(protection)


@pytest.mark.parametrize(
    "case", ["wrong_env", "admin_bypass", "missing_rule", "empty_reviewers", "self_review", "unrestricted_branch"]
)
def test_weak_environment_rejects(environment, case):
    if case == "wrong_env":
        environment["name"] = "staging"
    elif case == "admin_bypass":
        environment["can_admins_bypass"] = True
    elif case == "missing_rule":
        del environment["protection_rules"]
    elif case == "empty_reviewers":
        environment["protection_rules"][0]["reviewers"] = []
    elif case == "self_review":
        environment["protection_rules"][0]["prevent_self_review"] = False
    else:
        environment["deployment_branch_policy"] = None
    with pytest.raises(gate.GovernanceGateError):
        gate.validate_environment(environment)


@pytest.mark.parametrize("path", gate.REQUIRED_WORKFLOWS)
def test_complete_workflow_receipt_passes(receipt, path):
    gate.validate_workflow_receipt(**receipt(path))


@pytest.mark.parametrize("path", gate.REQUIRED_WORKFLOWS)
@pytest.mark.parametrize(
    "case",
    [
        "foreign_sha",
        "missing_job",
        "duplicate_job",
        "missing_step",
        "skipped_step",
        "missing_runner",
        "wrong_run",
        "wrong_attempt",
        "failed_job",
        "untrusted_app",
        "wrong_slug",
        "wrong_suite",
        "missing_check",
        "wrong_check_sha",
        "disabled_workflow",
        "untrusted_event",
        "fork_source",
    ],
)
def test_incomplete_or_substituted_receipt_rejects(receipt, path, case):
    value = receipt(path)
    job = value["jobs"][0]
    check = value["checks"][job["id"]]
    if case == "foreign_sha":
        value["run"]["head_sha"] = "b" * 40
    elif case == "missing_job":
        value["jobs"].pop()
    elif case == "duplicate_job":
        value["jobs"].append(deepcopy(job))
    elif case == "missing_step":
        job["steps"].pop()
    elif case == "skipped_step":
        job["steps"][0]["conclusion"] = "skipped"
    elif case == "missing_runner":
        job["runner_id"] = 0
    elif case == "wrong_run":
        job["run_id"] = 43
    elif case == "wrong_attempt":
        job["run_attempt"] = 2
    elif case == "failed_job":
        job["conclusion"] = "failure"
    elif case == "untrusted_app":
        check["app"]["id"] = 1
    elif case == "wrong_slug":
        check["app"]["slug"] = "spoof"
    elif case == "wrong_suite":
        check["check_suite"]["id"] = 8
    elif case == "missing_check":
        value["checks"].clear()
    elif case == "wrong_check_sha":
        check["head_sha"] = "b" * 40
    elif case == "disabled_workflow":
        value["workflow"]["state"] = "disabled_manually"
    elif case == "untrusted_event":
        value["run"]["event"] = "pull_request_target"
    else:
        value["run"]["head_repository"]["full_name"] = "foreign/repo"
    with pytest.raises(gate.GovernanceGateError):
        gate.validate_workflow_receipt(**value)


def test_missing_runtime_acceptance_job_cannot_hide_behind_ci_gate(receipt):
    value = receipt(".github/workflows/ci.yml")
    value["jobs"] = [job for job in value["jobs"] if job["name"] != "P1 built runtime acceptance"]
    with pytest.raises(gate.GovernanceGateError, match="missing required job"):
        gate.validate_workflow_receipt(**value)


def test_unprotected_main_rejects_before_observing_runs(monkeypatch):
    calls = []

    def read(endpoint):
        calls.append(endpoint)
        if endpoint.endswith("/branches/main"):
            return {"commit": {"sha": SHA}}
        if endpoint.endswith("/protection"):
            return {"message": "Branch not protected", "status": "404"}
        pytest.fail("must reject before any run or environment observation")

    monkeypatch.setattr(gate, "github_json", read)
    with pytest.raises(gate.GovernanceGateError):
        gate.validate_live_governance(REPO, SHA, "42")
    assert len(calls) == 2


def test_truncated_job_observation_fails_closed(monkeypatch):
    monkeypatch.setattr(gate, "github_json", lambda _: {"total_count": 2, "jobs": []})
    with pytest.raises(gate.GovernanceGateError, match="incomplete"):
        gate.paginated("/fixture", "jobs")


@pytest.mark.parametrize(
    "url",
    [
        "",
        "https://api.github.com/repos/foreign/repo/check-runs/100",
        "https://example.com/repos/owner/repo/check-runs/100",
        "https://api.github.com/repos/owner/repo/check-runs/0",
    ],
)
def test_check_endpoint_must_bind_expected_repository(receipt, url):
    value = receipt(".github/workflows/ci.yml")
    value["jobs"][0]["check_run_url"] = url
    with pytest.raises(gate.GovernanceGateError):
        gate.validate_workflow_receipt(**value)


def test_actions_job_and_check_ids_need_not_be_equal(receipt):
    value = receipt(".github/workflows/ci.yml")
    job = value["jobs"][0]
    job["check_run_url"] = f"https://api.github.com/repos/{REPO}/check-runs/999"
    value["checks"][job["id"]]["id"] = 999
    gate.validate_workflow_receipt(**value)


@pytest.mark.parametrize("case", ["success", "missing_docs", "ci_not_latest", "attempt_changed"])
def test_live_receipts_are_collected_read_only(monkeypatch, receipt, protection, environment, case):
    values = {path: receipt(path) for path in gate.REQUIRED_WORKFLOWS}
    active = None
    observations = 0

    def read(endpoint):
        nonlocal active, observations
        if endpoint.endswith("/branches/main"):
            return {"commit": {"sha": SHA}}
        if endpoint.endswith("/protection"):
            return protection
        if endpoint.endswith("/environments/production"):
            return environment
        if "/actions/workflows/" in endpoint:
            path = ".github/workflows/" + endpoint.split("/actions/workflows/")[1].split("/")[0]
            active = values[path]
            observations = 0
            if "/runs?" in endpoint:
                if case == "missing_docs" and path.endswith("docs-hygiene.yml"):
                    return {"total_count": 0, "workflow_runs": []}
                return {"total_count": 1, "workflow_runs": [active["run"]]}
            return active["workflow"]
        if "/check-runs/" in endpoint:
            return active["checks"][int(endpoint.rsplit("/", 1)[-1])]
        if "/jobs?" in endpoint:
            return {"total_count": len(active["jobs"]), "jobs": active["jobs"]}
        if "/actions/runs/" in endpoint:
            observations += 1
            result = deepcopy(active["run"])
            if case == "attempt_changed" and observations > 1:
                result["run_attempt"] = 2
            return result
        pytest.fail("unexpected endpoint: " + endpoint)

    monkeypatch.setattr(gate, "github_json", read)
    if case == "success":
        assert gate.validate_live_governance(REPO, SHA, "42") == dict.fromkeys(gate.REQUIRED_WORKFLOWS, 42)
    else:
        with pytest.raises(gate.GovernanceGateError):
            gate.validate_live_governance(REPO, SHA, "43" if case == "ci_not_latest" else "42")
