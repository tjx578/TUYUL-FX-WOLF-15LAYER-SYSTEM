# Bounded C02/C06 runtime work

Canonical criteria: `pursuit/input/WOLF15_PURSUIT_GOAL.md` C02 and C06. This
work preserves K05/Transaction A and does not assert production equivalence.

## Concrete defects corrected

- Required engine HTTP, Redis consumer and analysis tasks now fail the process
  through the existing `main` exception path after the configured restart budget.
  Unexpected completion and unexpected cancellation cannot silently succeed.
  Requested shutdown and optional completion remain distinguished.
- Shared HealthProbe readiness cannot remain green after its owner marks it dead.
  Required failure latches health/readiness closed across retries; requalification
  requires process restart. Existing role readiness predicates remain in place.
- Shutdown signals intentional cancellation before draining workers. If tasks
  remain active after both existing drain bounds, pool cleanup is refused with a
  fatal error instead of closing resources underneath active workers.

## Evidence executable on the integrated candidate

`python scripts/ci/p1_runtime_acceptance.py --image IMAGE --output artifacts/p1-runtime.json`
requires an image built from the candidate using the repository Dockerfile.
The runner creates disposable containers with no network, no source mounts,
no capabilities and no production credentials; only random temporary login and
observability values exist inside these containers. It removes containers in
`finally`. Image identity and relevant source digests are included in its receipt.

The actual owner API entrypoint is checked for live health, dependency-failure
readiness 503 with reason, one configured listener, one contained worker startup
attestation and graceful exit 0. Embedded owner requests must exit 78. Required
router removal is injected only into separate container writable layers: diagnostic
mode must serve readiness 503; strict mode must exit nonzero.

A separate component process runs the actual shared supervisor and HealthProbe
from image bytes, observes healthy readiness then required late-failure 503 and
nonzero exit, and tests SIGTERM with worker drain preceding a recording pool close.
This component process is explicitly not a full engine/orchestrator/trade service
entrypoint and its recording cleanup is not real in-flight database proof.

The existing PostgreSQL acceptance module now includes
`test_unprivileged_application_role_enforces_owner_fence`. Under the guarded
DISPOSABLE_TEST fixture, a unique temporary NOLOGIN, NOSUPERUSER, NOBYPASSRLS
role gets only explicit lifecycle/fence table privileges. `SET LOCAL ROLE` and
role flags are asserted. Current fenced lifecycle write succeeds with
execution_authority=false; unbound legacy write, stale owner after handover,
and disabling the database trigger fail. Role objects/grants are removed.
This does not prove a separately authenticated application connection, deployed
roles, malicious-role resistance, or broker-path zero dispatch.

## Remaining C02/C06 closure limits

- Dedicated orchestrator, engine, trade, pressure-outbox and other lifecycle
  writers identified by C02 still need actual role entrypoint/supervision and
  common ownership proof. A dedicated orchestrator is not lifecycle/lot authority.
- Legacy broker-path input with a recording dispatch sink is not executed here.
  Network isolation prevents egress but is not proof the legacy path was reached.
- Every mandatory role bootstrap, late crash, dependency, single listener and
  real in-flight cancellation-before-database-close matrix is not complete.
- Actual environment service configuration/role ownership remains separate from
  disposable CI acceptance. No Railway staged change or deployment was applied.

C02 and C06 remain open until their complete canonical matrix has evidence.
Local Docker discovery did not return; the bounded discovery command was
cancelled without daemon restart. Built-image and PostgreSQL results must come
from the parent candidate CI receipt, not local static/unit results.
