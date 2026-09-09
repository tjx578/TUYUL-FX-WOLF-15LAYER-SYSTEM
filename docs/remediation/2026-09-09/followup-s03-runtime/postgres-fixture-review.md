# PostgreSQL fixture and migration review

Status: OFFLINE_REVIEW_ONLY. No database connection, PostgreSQL initialization, server start, Docker/WSL start, capacity re-poll, repository mutation or Git action occurred during this review. Windows workloads and the two historical VPS remain untouched.

The exact API environment previously installed at sibling `s01-s03-staging/api-exact-venv` successfully parsed the four reviewed files, resolved Alembic's single head `20260909_01`, generated SQL for `20260822_01:20260909_01`, and collected 17 tests in `tests/integration/test_pair_activity_runtime_postgres.py`. The four source hashes were identical before/after. See `postgres-offline-review.json` and its three command logs. SQL generation does not ask PostgreSQL to parse SQL and therefore does not prove real migration success.

## Findings sent to parent

1. CI needs `WOLF15_PAIR_ACTIVITY_TEST_DATABASE_URL` explicitly bound to the same disposable database as its existing literal `DATABASE_URL`. The fixture directly indexes this new variable, so enabling PostgreSQL tests without the new binding fails setup. The intended target is the existing job-scoped `wolf15_ci_test` service, with the exact destructive opt-in and both server-side markers.
2. The reviewed fixture creates the schema directly if its ledger table is absent. That fallback masks an absent/broken migration registration when tests are used as migration acceptance. Require the explicit migration step to install the tables and expected Alembic head before integration execution; direct DDL rehearsal, if retained, must be separately labelled.
3. The reused URL guard checks the authority hostname and database path but accepts URI query parameters/fragments. Libpq connection overrides can defeat the intended loopback-only binding. Reject query/fragment for this constrained fixture DSN and verify connected identity before schema mutation. The current literal CI fixture URL has no query parameters.

The tests cover fresh process recovery, duplicate/concurrent delivery, transactional rollback, failure outcomes, backfill, identity conflicts, binding immutability, SQL authority constraints and stale worker handling. Their current collection count is 17. This review did not claim those tests passed against PostgreSQL.

## Required execution evidence when an authorized Linux runner is available

Use the exact checked-out source and unchanged pinned API requirements in the API job. Record Python/Linux/PostgreSQL versions and dependency closure; run `python -m pip check`. Keep MCP2 in its separately required environment because its dependency graph is incompatible with the API's Pydantic pin.

After verifying the explicit disposable target and marking that new database, run `python -m alembic upgrade head`. Verify `public.alembic_version` is `20260909_01` (or the separately reviewed newer head), and that all six `public.pair_activity_*_v31` tables exist. Do not auto-repair missing tables in the acceptance fixture.

Collect and execute `tests/integration/test_pair_activity_runtime_postgres.py` using the same explicit fixture DSN and opt-in values. Produce JUnit XML, reconcile expected IDs/count against actual results, and reject zero tests, failures, errors or skipped acceptance cases. Run the broader API suite with the same isolated environment; a focused 17-test result cannot stand in for the full CI job. Source hashes and migration identity must match the accepted checkout. No production or broker acceptance follows from these local/CI tests.

## Infrastructure disposition

The one authorized fresh capacity check was 94.7967% committed memory, above the strict 90% start guard. Native PostgreSQL 17.11 binaries are available and hash-bound, but no cluster exists and no fixture DSN has been generated. Docker's Linux engine is unavailable; the only WSL distro is stopped docker-desktop. No verified alternate Linux host exists. Both native PostgreSQL runtime acceptance and Linux runtime acceptance remain NOT_EXECUTED.

The native harness passed 8 offline guard/ownership tests. High or unmeasurable capacity blocks initialization/start. A stop of a verified owned instance does not require a capacity PASS and therefore remains available to release resources; foreign state, mismatched PID/data directory/port/binary still blocks stop. No restart or deletion operation is implemented.
