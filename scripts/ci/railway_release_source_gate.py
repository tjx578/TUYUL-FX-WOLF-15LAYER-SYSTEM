"""Read-only, exact-source CI receipt gate; this module never invokes Railway."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

CI_PATH = ".github/workflows/ci.yml"
REQUIRED_STEPS = {
    "Ruff lint & format": {"Ruff check (lint — hard fail)", "Ruff format check (hard fail)"},
    "Python tests (pytest)": {
        "Apply database migrations",
        "Mark PostgreSQL as a disposable test environment",
        "Qualify disposable Linux PostgreSQL and Redis runner",
        "Require supported PostgreSQL upgrade with existing data",
        "Require distributed mode-owner Redis acceptance",
        "Require actual in-flight PostgreSQL shutdown drain",
        "Require effective Railway API role acceptance",
        "Require executed S03 PostgreSQL acceptance",
        "Require separate S03 producer and relay PostgreSQL acceptance",
        "Require separate S03 consumer and owner PostgreSQL acceptance",
        "Require disposable consumer application-role PostgreSQL acceptance",
        "Require separate candidate capacity and TEST_ONLY transaction PostgreSQL acceptance",
        "Run pytest with coverage",
        "Require uninstrumented latency budgets",
    },
    "Dashboard build (Next.js)": {"Lint", "Dashboard tests", "Build"},
    "P1 built runtime acceptance": {
        "Build candidate runtime image",
        "Require built runtime ownership readiness and shutdown acceptance",
        "Require actual orchestrator role process acceptance",
        "Require actual ingest role process acceptance",
        "Require actual engine and trade role process acceptance",
        "Require built engine failure recovery and quiescent shutdown",
        "Require actual pressure outbox role process acceptance",
    },
    "Native MCP fixture tests": {"Install isolated MCP test dependencies", "Run native MCP fixture suite"},
    "Built API bootstrap": {"Build exact-source API image", "Exercise built API bootstrap and served readiness"},
    "Deprecated shim guard": {"Block resurrected shim files", "Block deprecated imports in production code"},
    "Architecture drift guard": {
        "analysis/ must not contain execution logic",
        "execution/ must not contain strategy logic",
        "L12 signal must not carry account state",
    },
    "CI Gate": {"Evaluate all upstream jobs"},
}
RELEASE_WORKFLOWS = {
    CI_PATH: REQUIRED_STEPS,
    ".github/workflows/wolf-security-scan.yml": {
        "pip-audit (Python deps)": {"Run pip-audit (hard-fail)"},
        "npm audit (Node deps)": {"Validate lockfile sync", "Run npm audit (report)"},
        "Secret leak scan": {"Scan for secrets (hard-fail)"},
        "Security Gate": {"Evaluate security results"},
    },
    ".github/workflows/docs-hygiene.yml": {
        "Architecture reading-order integrity": set(),
        "Legacy docs quarantine": {
            "Reject legacy documentation references in production Python",
            "Verify historical quarantine index exists",
        },
        "Architecture cross-reference check": {"Check internal markdown links"},
        "Docs Gate": {"Evaluate docs hygiene jobs"},
    },
}


class ReleaseGateError(ValueError):
    """The supplied source or CI evidence does not permit release."""


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ReleaseGateError(reason)


def validate_receipt(
    *,
    release_sha: str,
    checkout_sha: str,
    remote_main_sha: str,
    repository: str,
    ci_run_id: str,
    workflow: dict[str, Any],
    run: dict[str, Any],
    jobs: list[dict[str, Any]],
    expected_path: str = CI_PATH,
) -> None:
    """Reject missing evidence, source substitution, or successful-but-skipped CI."""
    require(bool(re.fullmatch(r"[0-9a-f]{40}", release_sha)), "release SHA must be full lowercase hex")
    require(release_sha == checkout_sha == remote_main_sha, "checkout/release/current main mismatch")
    require(bool(re.fullmatch(r"[1-9][0-9]*", ci_run_id)), "CI run id must be a positive integer")
    require(str(run.get("id")) == ci_run_id, "CI run id mismatch")
    require(expected_path in RELEASE_WORKFLOWS, "untrusted required workflow")
    required_steps = RELEASE_WORKFLOWS[expected_path]
    require(workflow.get("path") == expected_path and workflow.get("state") == "active", "untrusted CI workflow")
    require(run.get("workflow_id") == workflow.get("id") and workflow.get("id") is not None, "workflow id mismatch")
    require(run.get("path") == expected_path, "CI run workflow path mismatch")
    require(run.get("repository", {}).get("full_name") == repository, "CI repository mismatch")
    require(run.get("head_repository", {}).get("full_name") == repository, "fork CI cannot authorize release")
    require(run.get("head_sha") == release_sha and run.get("head_branch") == "main", "CI source mismatch")
    require(run.get("event") in {"push", "workflow_dispatch"}, "untrusted CI event")
    require(run.get("status") == "completed" and run.get("conclusion") == "success", "CI did not succeed")
    require(isinstance(run.get("run_attempt"), int) and run["run_attempt"] > 0, "missing CI attempt")
    names = [job.get("name") for job in jobs]
    require(len(names) == len(set(names)) and set(required_steps).issubset(names), "missing or duplicate CI jobs")
    for job in jobs:
        require(job.get("head_sha") == release_sha, "job source mismatch")
        require(job.get("run_id") == run["id"] and job.get("run_attempt") == run["run_attempt"], "job run mismatch")
        require(job.get("status") == "completed" and job.get("conclusion") == "success", "required job not successful")
        require(isinstance(job.get("runner_id"), int) and job["runner_id"] > 0, "job has no runner evidence")
        steps = job.get("steps") or []
        require(bool(steps), "job has no step evidence")
        require(
            all(step.get("status") == "completed" and step.get("conclusion") == "success" for step in steps),
            "failed, skipped, or incomplete CI step",
        )
        require(
            required_steps.get(job["name"], set()).issubset({step.get("name") for step in steps}),
            "required CI step absent",
        )


def command(args: list[str]) -> str:
    # Do not print provider output or environment variables on an error.
    result = subprocess.run(args, capture_output=True, text=True, check=False, timeout=60)
    require(result.returncode == 0, "read-only evidence command failed")
    return result.stdout.strip()


def github_json(endpoint: str) -> Any:
    return json.loads(command(["gh", "api", "-H", "Accept: application/vnd.github+json", endpoint]))


def collect_jobs(prefix: str, run: dict[str, Any]) -> list[dict[str, Any]]:
    attempt = run.get("run_attempt")
    require(isinstance(attempt, int) and attempt > 0, "missing CI attempt")
    jobs: list[dict[str, Any]] = []
    for page in range(1, 101):
        response = github_json(f"{prefix}/runs/{run['id']}/attempts/{attempt}/jobs?per_page=100&page={page}")
        batch = response.get("jobs", [])
        jobs.extend(batch)
        if len(jobs) == response.get("total_count"):
            return jobs
        require(bool(batch), "incomplete jobs pagination")
    raise ReleaseGateError("jobs pagination limit exceeded")


def latest_required_run(response: dict[str, Any], release_sha: str) -> dict[str, Any]:
    runs = response.get("workflow_runs", [])
    require(len(runs) == response.get("total_count"), "required workflow history incomplete")
    eligible = [
        run
        for run in runs
        if run.get("head_sha") == release_sha
        and run.get("head_branch") == "main"
        and run.get("event") in {"push", "workflow_dispatch"}
    ]
    require(bool(eligible), "required workflow has no exact-source main run")
    require(all(isinstance(run.get("id"), int) and run["id"] > 0 for run in eligible), "invalid required run id")
    # Do not fall back to an older success while the newest run is failing/pending.
    return max(eligible, key=lambda run: run["id"])


def main() -> int:
    try:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
        repository = os.environ["GITHUB_REPOSITORY"]
        require(bool(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)), "invalid repository")
        event_name = os.environ["GITHUB_EVENT_NAME"]
        if event_name == "workflow_run":
            source = event.get("workflow_run", {})
            release_sha, ci_run_id = source.get("head_sha", ""), str(source.get("id", ""))
        else:
            require(event_name == "workflow_dispatch", "unsupported release event")
            require(os.environ.get("GITHUB_REF") == "refs/heads/main", "dispatch must use main workflow")
            source = event.get("inputs", {})
            release_sha, ci_run_id = source.get("release_sha", ""), str(source.get("ci_run_id", ""))
        require(bool(re.fullmatch(r"[0-9a-f]{40}", release_sha)), "invalid release SHA")
        require(bool(re.fullmatch(r"[1-9][0-9]*", ci_run_id)), "invalid CI run id")
        prefix = f"/repos/{repository}/actions"
        workflow = github_json(f"{prefix}/workflows/ci.yml")
        run = github_json(f"{prefix}/runs/{ci_run_id}")
        attempt = run.get("run_attempt")
        require(isinstance(attempt, int) and attempt > 0, "missing CI attempt")
        jobs = collect_jobs(prefix, run)
        require(not command(["git", "status", "--porcelain", "--untracked-files=all"]), "release checkout is dirty")
        current_main = command(["git", "ls-remote", "--exit-code", "origin", "refs/heads/main"]).split()[0]
        validate_receipt(
            release_sha=release_sha,
            checkout_sha=command(["git", "rev-parse", "HEAD"]),
            remote_main_sha=current_main,
            repository=repository,
            ci_run_id=ci_run_id,
            workflow=workflow,
            run=run,
            jobs=jobs,
        )
        verified_runs = [run]
        for path in RELEASE_WORKFLOWS:
            if path == CI_PATH:
                continue
            name = path.rsplit("/", 1)[1]
            required_workflow = github_json(f"{prefix}/workflows/{name}")
            response = github_json(f"{prefix}/workflows/{name}/runs?head_sha={release_sha}&branch=main&per_page=100")
            required_run = latest_required_run(response, release_sha)
            validate_receipt(
                release_sha=release_sha,
                checkout_sha=release_sha,
                remote_main_sha=current_main,
                repository=repository,
                ci_run_id=str(required_run["id"]),
                workflow=required_workflow,
                run=required_run,
                jobs=collect_jobs(prefix, required_run),
                expected_path=path,
            )
            verified_runs.append(required_run)
        for verified in verified_runs:
            name = verified["path"].rsplit("/", 1)[1]
            current = latest_required_run(
                github_json(f"{prefix}/workflows/{name}/runs?head_sha={release_sha}&branch=main&per_page=100"),
                release_sha,
            )
            require(current["id"] == verified["id"], "new required workflow run supersedes verified evidence")
            latest_run = github_json(f"{prefix}/runs/{verified['id']}")
            require(
                latest_run.get("head_sha") == release_sha
                and latest_run.get("run_attempt") == verified["run_attempt"]
                and latest_run.get("status") == "completed"
                and latest_run.get("conclusion") == "success",
                "required workflow was rerun or changed during verification",
            )
        require(
            command(["git", "ls-remote", "--exit-code", "origin", "refs/heads/main"]).split()[0] == release_sha,
            "main advanced during verification",
        )
        if __package__:
            from .p1_governance_gate import GovernanceGateError, validate_live_governance
        else:
            from p1_governance_gate import GovernanceGateError, validate_live_governance

        try:
            validate_live_governance(repository, release_sha, ci_run_id)
        except GovernanceGateError as exc:
            raise ReleaseGateError("required governance or auxiliary gate evidence missing") from exc
        print(f"PASS_EXACT_SOURCE_CI sha={release_sha} run_id={ci_run_id} attempt={attempt}")
        return 0
    except (ReleaseGateError, KeyError, OSError, ValueError, IndexError, subprocess.SubprocessError):
        print("::error::Exact-source CI gate rejected missing, mismatched, or unsuccessful evidence", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
