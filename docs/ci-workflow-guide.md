# CI workflow guide

The required checks are produced by the canonical workflows below. Editing
application files still follows the normal branch, PR and review process.
No new account, secret, environment approval or deployment permission is needed.

| Entry point | Purpose |
| --- | --- |
| `.github/workflows/ci.yml` | CI Gate: Ruff, Python tests and 85% coverage, disposable-service and built-runtime acceptance, dashboard lint/tests/strict build, separate native MCP tests, repository guards and reusable Pyright checks |
| `.github/workflows/lint.yml` | Maintained hard-fail Pyright checks, with separate core and native MCP environments; also called by CI |
| `.github/workflows/wolf-security-scan.yml` | Security Gate: dependency audits and redacted secret detection |
| `.github/workflows/docs-hygiene.yml` | Docs Gate: architecture reading order, legacy quarantine and cross-references |
| `.github/workflows/wolf-pipeline-ci.yml` | Optional manual entry point calling CI, security and docs from the same commit |

The manual entry point has no push or pull-request trigger. Its local reusable
workflow references resolve to the caller's commit, so checks cannot drift to
another branch revision. It inherits no repository secrets and requires only
`contents: read`. Its concurrency namespace differs from both CI and nested
Lint, preventing cancellation between caller and callee.

The final **Manual verification summary** requires all three called workflows
to succeed. Failure, cancellation, skipped work, or missing/malformed results
cannot produce a successful summary. Each canonical gate continues to require
all its upstream jobs. The manual run consumes the runners used by a full CI,
security and docs run; use it deliberately when combined verification is needed.

## Ruff version for local development

Use Ruff **0.15.7**, the version pinned by the canonical CI workflow and
`requirements.txt`. Inside the activated core virtualenv, run
`python -m pip install ruff==0.15.7` to update an existing installation, then run
`python -m ruff check . --config pyproject.toml` and
`python -m ruff format --check --diff . --config pyproject.toml` from the repo root.

`pyproject.toml` requires that exact version and rejects other Ruff versions
before checking or formatting files. When intentionally upgrading Ruff, update
that requirement, `requirements.txt`, `.github/workflows/ci.yml`, the manually
dispatchable `.github/workflows/wolf-ci.yml`, and this guide together. Review
lint and formatting differences before adopting a new version.

## Checks retained from the old manual pipeline

`scripts/ci/check_repository_contracts.py` runs in the canonical Python tests job
after dependency installation. It validates both required Draft 7 schemas,
config YAML, additional dashboard/EA/execution boundary patterns, specific
Pyright suppression comments and tracked generated coverage/result files.
Unreadable or missing required inputs fail the check. Diagnostics identify the
file and rule without printing source content or parser errors containing data.
`.coveragerc` is configuration and is allowed.

The existing canonical drift guard retains the analysis/execution separation
and account-state exclusion from L12. Pattern checks are bounded spot checks,
not a proof of every semantic authority boundary. Secret detection belongs to
the maintained security workflow and its redacted receipt; the old raw grep
output and comment-based bypass are removed with the legacy implementation.

The old standalone mypy invocation is retired with that manual implementation.
It covered a different scope from Pyright; this is a consolidation onto the
maintained, required Pyright gate, not a claim that the two tools are identical.
Pyright uses the repository configuration, not an invented strict-mode label.
The existing executable-token ASCII regression test permits Unicode in comments
and strings; the old blanket text prohibition is not reinstated. The old journal
mutation grep is also not carried forward: `Counter.update()`, `dict.update()`
and timestamp truncation are not proof of persistent journal mutation. Existing
journal behavior tests remain part of the full suite; this change does not claim
to add a complete persistent-storage immutability audit.

## Evidence and release boundary

A successful manual wrapper run is useful verification but does not replace
the separate canonical workflow receipts required by
`scripts/ci/railway_release_source_gate.py`. That validator still binds workflow
path, source commit, main branch, run attempt, runner and executed steps. The new
repository-contract step is also required in the canonical CI receipt. No
release allowlist or branch-protection context is broadened for this wrapper.
The separate P1 governance gate also requires the current Docs quarantine step
names; regression tests bind its receipt validation to the workflow and reject
missing or skipped guards.

The historical `wolf-ci.yml` and `wolf-15-ci.yml` remain manually dispatchable;
their headers no longer call them disabled or authoritative. Use the entry
points above for maintained checks. Their old job labels are not release proof.

Local actionlint and regression tests verify configuration and failure handling.
They do not prove GitHub runner execution, Linux service acceptance, coverage,
dashboard build success, deployment health or broker behavior. Those claims need
fresh results for the final pushed commit. No deployment is triggered by the
manual wrapper. To roll back this consolidation, revert its scoped commit;
application and database rollback are not required.

## Performance guard

`perf-guard.yml` complements the six required, uninstrumented latency benchmarks
in `ci.yml`; it does not replace their exact-case JUnit gate. Python, test,
configuration and dependency changes trigger the guard. `Perf Gate` is not a
replacement for the protected branch's CI, security or documentation gates.

The guard preserves three checks:

- Imports: the four critical modules must all import successfully in one fresh
  Python interpreter within an aggregate 10-second wall-time budget, including
  interpreter startup. Shared dependencies are imported once within that chain.
  A separate 30-second process timeout rejects hangs; it is not a larger budget.
- Tests: non-`slow` core tests must pass and each **call phase** must take at most
  five seconds. Setup and teardown remain subject to pytest's timeout, but are
  not included in the five-second metric. Integration tests keep their existing
  separate CI coverage; native MCP tests use the dedicated MCP environment in
  canonical CI. Empty, failed, skipped, missing or malformed JUnit evidence fails.
- Size: both tick modules must exist and contain at most 500 lines. This is a
  maintainability limit, not a measurement of runtime complexity or throughput.

Run `python -m scripts.ci.perf_guard imports`, `tests`, or `size` from the repo
root in the core test environment. Results and complete subprocess logs are
written under `artifacts/perf-guard/` and uploaded per matrix job even on failure.
The tests subprocess has a 25-minute bound; jobs have a 30-minute bound. Every
matrix leg must succeed for Perf Gate to pass. Do not add `slow` markers or change
budgets just to hide a regression. Local Windows timings do not establish the
Linux GitHub runner's performance. None of these checks deploys Railway or grants
SignalThrottle, risk, or broker authority.
