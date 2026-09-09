# C05 governance validator and observed controls

This subtask adds `scripts/ci/p1_governance_gate.py` and `tests/test_p1_governance_gate.py`. It performs read-only GitHub REST observations through `gh api`; it has no settings mutation, provider, deployment, broker or credential-verification command.

## Current observed status

Readback against main `68ad0794e087177571972a7b95f4b7dde70b5286`:

- Main branch protection: **PASS_OBSERVED** against the validator after the parent applied controls. Required contexts are CI Gate, Security Gate and Docs Gate, strictly bound to GitHub Actions app 15368; administrators are enforced; at least one approval and dismissal of stale approvals are required; force-pushes/deletions are disabled. Additional configured requirements are retained in the full receipt.
- Production environment: **HOLD**. At this observation the environment allowed administrator bypass, had no required-reviewer rule and had no deployment branch restriction.
- All three workflow receipts on a final integrated immutable candidate: **NOT_EXECUTED** by this subtask. It would be incorrect to treat local validator fixtures as those receipts.
- Repository-wide elimination of alternate provider authority: **HOLD**. A repository-level Railway credential remains outside the protection offered by an environment gate. The parent reports disabling the legacy provider workflows and retiring arbitrary canary/incident paths; this helper neither moves/deletes credentials nor proves every possible alternate workflow is absent.

`github-observation.json` preserves the earlier read showing main unprotected, the old ruleset disabled, environment controls absent, and the observed Actions app identity. `validator-readback.json` preserves the later fresh main/environment observation and hash-bound local validator result. Protection changes were made by the parent, not this subtask.

## Gate behavior

The validator rejects missing, weak or app-unbound main protection and requires a production environment with actual reviewers, self-review prevention, no administrator bypass and protected-branch-only deployments.

For each of the allowlisted CI, security and docs workflow paths it requires the latest eligible main push/manual run for the exact release SHA, the correct repository/workflow identity, completed success, matching run attempt, every required job and step, actual runner evidence and an authenticated GitHub Actions check-run from the same check suite. CI requires all existing release-helper steps plus the built-runtime job and its two explicit build/acceptance steps. Missing, skipped, failed, foreign-source and foreign-app receipts fail closed. Job-to-check binding uses the repository-bound `check_run_url`, not an assumption that the Actions job id equals the check id. CI attempt/state and current main/settings are re-observed before returning.

Job metadata cannot by itself prove that an internal pytest command ran nonzero tests without skips. Required suite scripts must enforce those assertions and supply their test receipts; this validator checks that those steps actually succeeded. Similarly, it is a point-in-time observation, not an atomic lock against subsequent repository/settings changes.

## Local verification and integration

92 local tests passed, zero failed/skipped, in 1.32 seconds. Fixtures cover missing/weak protection, admin/review bypass, invalid environment, missing runtime job, skipped steps, absent runners, source/run/attempt substitution, disabled or foreign workflows, forged app/check-suite identity, malformed check URLs, distinct job/check ids, absent docs runs, newer CI runs, changed attempts and incomplete pagination. Ruff lint/format and diff whitespace check passed.

API: `validate_live_governance(repository, release_sha, ci_run_id)` returns a workflow-path/run-id mapping or raises `GovernanceGateError`. CLI takes `--repository`, `--release-sha` and `--ci-run-id` and fails closed without printing raw GitHub error responses.

Least-invasive integration is a lazy import and call from the existing release gate after its exact-source CI validation, before any successful gate message/provider credential step. A top-level circular import should be avoided because the new module reuses the existing required CI step contract. This subtask did not change that helper, workflow files, provider settings, or the staged Railway patch.

C05 remains partial and controlled/fail-closed; it is not release-ready while the environment/credential boundaries and actual candidate C01/C03/runtime evidence remain unresolved. No BFF/device/trading milestone is promoted into P1 by this report.
