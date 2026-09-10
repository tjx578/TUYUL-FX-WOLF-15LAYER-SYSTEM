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
        "Run pytest with coverage",
    },
    "Dashboard build (Next.js)": {"Lint", "Dashboard tests", "Build"},
    "Deprecated shim guard": {"Block resurrected shim files", "Block deprecated imports in production code"},
    "Architecture drift guard": {
        "analysis/ must not contain execution logic",
        "execution/ must not contain strategy logic",
        "L12 signal must not carry account state",
    },
    "CI Gate": {"Evaluate all upstream jobs"},
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
) -> None:
    """Reject missing evidence, source substitution, or successful-but-skipped CI."""
    require(bool(re.fullmatch(r"[0-9a-f]{40}", release_sha)), "release SHA must be full lowercase hex")
    require(release_sha == checkout_sha == remote_main_sha, "checkout/release/current main mismatch")
    require(bool(re.fullmatch(r"[1-9][0-9]*", ci_run_id)), "CI run id must be a positive integer")
    require(str(run.get("id")) == ci_run_id, "CI run id mismatch")
    require(workflow.get("path") == CI_PATH and workflow.get("state") == "active", "untrusted CI workflow")
    require(run.get("workflow_id") == workflow.get("id") and workflow.get("id") is not None, "workflow id mismatch")
    require(run.get("path") == CI_PATH, "CI run workflow path mismatch")
    require(run.get("repository", {}).get("full_name") == repository, "CI repository mismatch")
    require(run.get("head_repository", {}).get("full_name") == repository, "fork CI cannot authorize release")
    require(run.get("head_sha") == release_sha and run.get("head_branch") == "main", "CI source mismatch")
    require(run.get("event") in {"push", "workflow_dispatch"}, "untrusted CI event")
    require(run.get("status") == "completed" and run.get("conclusion") == "success", "CI did not succeed")
    require(isinstance(run.get("run_attempt"), int) and run["run_attempt"] > 0, "missing CI attempt")
    names = [job.get("name") for job in jobs]
    require(len(names) == len(set(names)) and set(REQUIRED_STEPS).issubset(names), "missing or duplicate CI jobs")
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
            REQUIRED_STEPS.get(job["name"], set()).issubset({step.get("name") for step in steps}),
            "required CI step absent",
        )


def command(args: list[str]) -> str:
    # Do not print provider output or environment variables on an error.
    result = subprocess.run(args, capture_output=True, text=True, check=False, timeout=60)
    require(result.returncode == 0, "read-only evidence command failed")
    return result.stdout.strip()


def github_json(endpoint: str) -> Any:
    return json.loads(command(["gh", "api", "-H", "Accept: application/vnd.github+json", endpoint]))


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
        jobs: list[dict[str, Any]] = []
        for page in range(1, 101):
            response = github_json(f"{prefix}/runs/{ci_run_id}/attempts/{attempt}/jobs?per_page=100&page={page}")
            batch = response.get("jobs", [])
            jobs.extend(batch)
            if len(jobs) == response.get("total_count"):
                break
            require(bool(batch), "incomplete jobs pagination")
        else:
            raise ReleaseGateError("jobs pagination limit exceeded")
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
        latest_run = github_json(f"{prefix}/runs/{ci_run_id}")
        require(
            latest_run.get("run_attempt") == attempt
            and latest_run.get("status") == "completed"
            and latest_run.get("conclusion") == "success",
            "CI was rerun or changed during verification",
        )
        print(f"PASS_EXACT_SOURCE_CI sha={release_sha} run_id={ci_run_id} attempt={attempt}")
        return 0
    except (ReleaseGateError, KeyError, OSError, ValueError, IndexError, subprocess.SubprocessError):
        print("::error::Exact-source CI gate rejected missing, mismatched, or unsuccessful evidence", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
