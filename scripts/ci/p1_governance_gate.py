"""Read-only P1 governance gate. No provider calls or settings mutations."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from typing import Any

if __package__:
    from .railway_release_source_gate import REQUIRED_STEPS as CI_STEPS
else:
    from railway_release_source_gate import REQUIRED_STEPS as CI_STEPS

# Observed from current repository GitHub Actions check-run receipts, not a user input.
GITHUB_ACTIONS_APP_ID = 15368
REQUIRED_CONTEXTS = frozenset({"CI Gate", "Security Gate", "Docs Gate"})
REQUIRED_WORKFLOWS = {
    ".github/workflows/ci.yml": {
        **CI_STEPS,
    },
    ".github/workflows/wolf-security-scan.yml": {
        "pip-audit (Python deps)": {"Run pip-audit (hard-fail)"},
        "npm audit (Node deps)": {"Validate lockfile sync", "Run npm audit (report)", "Fail on high+"},
        "Secret leak scan": {"Scan for secrets (hard-fail)"},
        "Security Gate": {"Evaluate security results"},
    },
    ".github/workflows/docs-hygiene.yml": {
        "Architecture reading-order integrity": {"Verify every reading-order entry exists"},
        "Legacy docs quarantine": {
            "No production code may import from docs/" + "legacy/",
            "docs/" + "legacy/README.md must exist",
        },
        "Architecture cross-reference check": {"Check internal markdown links"},
        "Docs Gate": {"Evaluate docs hygiene jobs"},
    },
}


class GovernanceGateError(ValueError):
    """Required P1 evidence is missing or fails its contract."""


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise GovernanceGateError(reason)


def validate_branch_protection(protection: dict[str, Any]) -> None:
    """Validate GET main/protection, never a desired-setting request body."""
    status = protection.get("required_status_checks") or {}
    require(status.get("strict") is True, "required checks must be strict")
    checks = status.get("checks") or []
    contexts = [check.get("context") for check in checks]
    require(len(contexts) == len(set(contexts)), "duplicate required check contexts")
    require(REQUIRED_CONTEXTS.issubset(contexts), "required gate contexts absent")
    require(
        all(
            check.get("app_id") == GITHUB_ACTIONS_APP_ID
            for check in checks
            if check.get("context") in REQUIRED_CONTEXTS
        ),
        "required contexts must be bound to observed GitHub Actions app",
    )
    require(protection.get("enforce_admins", {}).get("enabled") is True, "admin enforcement missing")
    reviews = protection.get("required_pull_request_reviews") or {}
    count = reviews.get("required_approving_review_count")
    require(type(count) is int and count >= 1, "at least one approving review required")
    require(reviews.get("dismiss_stale_reviews") is True, "stale approvals must be dismissed")
    require(reviews.get("require_last_push_approval") is True, "latest push must require independent approval")
    require(
        protection.get("required_conversation_resolution", {}).get("enabled") is True,
        "review conversations must be resolved",
    )
    bypass = reviews.get("bypass_pull_request_allowances") or {}
    require(not any(bypass.get(key) for key in ("users", "teams", "apps")), "review bypass allowance present")
    for key in ("allow_force_pushes", "allow_deletions"):
        require(protection.get(key, {}).get("enabled") is False, f"{key} must be explicitly disabled")


def validate_environment(environment: dict[str, Any]) -> None:
    require(str(environment.get("name", "")).lower() == "production", "wrong protected environment")
    require(environment.get("can_admins_bypass") is False, "environment admin bypass enabled or unknown")
    rules = [rule for rule in environment.get("protection_rules", []) if rule.get("type") == "required_reviewers"]
    require(len(rules) == 1, "required environment reviewer rule absent or duplicated")
    require(bool(rules[0].get("reviewers")), "environment reviewer list empty")
    require(rules[0].get("prevent_self_review") is True, "environment self approval not blocked")
    policy = environment.get("deployment_branch_policy") or {}
    require(
        policy.get("protected_branches") is True and policy.get("custom_branch_policies") is False,
        "environment must restrict deployments to protected branches",
    )


def check_id(job: dict[str, Any], repository: str) -> int:
    match = re.fullmatch(
        r"https://api\.github\.com/repos/" + re.escape(repository) + r"/check-runs/([1-9][0-9]*)",
        str(job.get("check_run_url", "")),
    )
    require(match is not None, "job check URL binding absent or foreign")
    return int(match.group(1))


def validate_workflow_receipt(
    *,
    repository: str,
    release_sha: str,
    path: str,
    workflow: dict[str, Any],
    run: dict[str, Any],
    jobs: list[dict[str, Any]],
    checks: dict[int, dict[str, Any]],
) -> None:
    require(bool(re.fullmatch(r"[0-9a-f]{40}", release_sha)), "invalid release SHA")
    require(path in REQUIRED_WORKFLOWS, "workflow outside P1 gate allowlist")
    require(workflow.get("path") == path and workflow.get("state") == "active", "workflow disabled or mismatched")
    require(workflow.get("id") is not None and run.get("workflow_id") == workflow["id"], "workflow id mismatch")
    require(run.get("path") == path, "run workflow path mismatch")
    require(run.get("head_sha") == release_sha and run.get("head_branch") == "main", "run source mismatch")
    for key in ("repository", "head_repository"):
        require(run.get(key, {}).get("full_name") == repository, "foreign repository receipt")
    require(run.get("event") in {"push", "workflow_dispatch"}, "untrusted workflow event")
    require(run.get("status") == "completed" and run.get("conclusion") == "success", "workflow did not succeed")
    require(type(run.get("id")) is int and run["id"] > 0, "missing run id")
    require(type(run.get("run_attempt")) is int and run["run_attempt"] > 0, "missing run attempt")
    require(type(run.get("check_suite_id")) is int and run["check_suite_id"] > 0, "missing check suite binding")
    names = [job.get("name") for job in jobs]
    require(len(names) == len(set(names)), "duplicate jobs")
    require(set(REQUIRED_WORKFLOWS[path]).issubset(names), "missing required job")
    for job in jobs:
        require(job.get("head_sha") == release_sha, "job source mismatch")
        require(job.get("run_id") == run["id"] and job.get("run_attempt") == run["run_attempt"], "job run mismatch")
        require(job.get("status") == "completed" and job.get("conclusion") == "success", "job did not succeed")
        require(type(job.get("runner_id")) is int and job["runner_id"] > 0, "job runner not executed")
        steps = job.get("steps") or []
        require(bool(steps), "job steps absent")
        require(
            all(s.get("status") == "completed" and s.get("conclusion") == "success" for s in steps),
            "failed or skipped step",
        )
        require(
            REQUIRED_WORKFLOWS[path].get(job["name"], set()).issubset({s.get("name") for s in steps}),
            "required step absent",
        )
        check = checks.get(job.get("id"), {})
        require(
            check.get("id") == check_id(job, repository) and check.get("name") == job.get("name"),
            "check identity mismatch",
        )
        require(check.get("head_sha") == release_sha, "check source mismatch")
        require(check.get("check_suite", {}).get("id") == run["check_suite_id"], "check suite mismatch")
        require(check.get("status") == "completed" and check.get("conclusion") == "success", "check did not succeed")
        app = check.get("app") or {}
        require(app.get("id") == GITHUB_ACTIONS_APP_ID and app.get("slug") == "github-actions", "check app mismatch")


def github_json(endpoint: str) -> Any:
    result = subprocess.run(
        ["gh", "api", "-H", "Accept: application/vnd.github+json", endpoint],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    require(result.returncode == 0, "read-only GitHub observation unavailable")
    return json.loads(result.stdout)


def paginated(endpoint: str, key: str) -> list[dict[str, Any]]:
    items = []
    separator = "&" if "?" in endpoint else "?"
    for page in range(1, 101):
        response = github_json(f"{endpoint}{separator}per_page=100&page={page}")
        batch = response.get(key, [])
        items.extend(batch)
        if len(items) == response.get("total_count"):
            return items
        require(bool(batch), "incomplete GitHub pagination")
    raise GovernanceGateError("GitHub pagination limit exceeded")


def validate_live_governance(repository: str, release_sha: str, ci_run_id: str) -> dict[str, int]:
    """Read current controls and exact-source latest CI/security/docs run receipts."""
    require(bool(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)), "invalid repository")
    require(bool(re.fullmatch(r"[0-9a-f]{40}", release_sha)), "invalid release SHA")
    require(bool(re.fullmatch(r"[1-9][0-9]*", ci_run_id)), "invalid CI run id")
    prefix = f"/repos/{repository}"
    require(github_json(prefix + "/branches/main").get("commit", {}).get("sha") == release_sha, "main moved")
    validate_branch_protection(github_json(prefix + "/branches/main/protection"))
    validate_environment(github_json(prefix + "/environments/production"))
    selected = {}
    for path in REQUIRED_WORKFLOWS:
        workflow_endpoint = prefix + "/actions/workflows/" + path.rsplit("/", 1)[1]
        workflow = github_json(workflow_endpoint)
        runs = paginated(workflow_endpoint + f"/runs?head_sha={release_sha}&branch=main", "workflow_runs")
        eligible = [run for run in runs if run.get("event") in {"push", "workflow_dispatch"}]
        require(bool(eligible), "required exact-source workflow not executed")
        latest = max(eligible, key=lambda run: run["id"])
        run_id = latest["id"]
        if path.endswith("/ci.yml"):
            require(str(run_id) == ci_run_id, "supplied CI run is not latest exact-source run")
        endpoint = prefix + f"/actions/runs/{run_id}"
        run = github_json(endpoint)
        attempt = run.get("run_attempt")
        require(type(attempt) is int and attempt > 0, "missing attempt")
        jobs = paginated(endpoint + f"/attempts/{attempt}/jobs", "jobs")
        checks = {job["id"]: github_json(prefix + f"/check-runs/{check_id(job, repository)}") for job in jobs}
        validate_workflow_receipt(
            repository=repository,
            release_sha=release_sha,
            path=path,
            workflow=workflow,
            run=run,
            jobs=jobs,
            checks=checks,
        )
        after = github_json(endpoint)
        require(
            after.get("run_attempt") == attempt
            and after.get("status") == "completed"
            and after.get("conclusion") == "success",
            "workflow changed during observation",
        )
        selected[path] = run_id
    # Detect controls or main moving during the sequence, before the caller obtains provider credentials.
    require(github_json(prefix + "/branches/main").get("commit", {}).get("sha") == release_sha, "main moved")
    validate_branch_protection(github_json(prefix + "/branches/main/protection"))
    validate_environment(github_json(prefix + "/environments/production"))
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--ci-run-id", required=True)
    args = parser.parse_args()
    try:
        selected = validate_live_governance(args.repository, args.release_sha, args.ci_run_id)
    except (GovernanceGateError, KeyError, TypeError, ValueError, OSError, subprocess.SubprocessError):
        print("::error::P1 governance rejected missing, mismatched, or unsuccessful evidence", file=sys.stderr)
        return 1
    print(json.dumps({"status": "PASS_OBSERVED_P1_GOVERNANCE", "release_sha": args.release_sha, "runs": selected}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
