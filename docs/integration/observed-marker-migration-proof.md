The production audit snapshot at 2026-09-07 17:50:23 UTC observed Alembic marker
`20260823_01`. Existing clean-database migration receipts do not test the D0
historical-row classification at that marker.

`tests/integration/test_observed_marker_migration_postgres.py` is a focused,
runner-bound PostgreSQL regression. It creates each isolated test database by
running real migrations to `20260823_01`, asserts the later tables/columns are
absent, and inserts synthetic signed commands plus related canary windows under
the unchanged historical schema. It reuses the existing engineering-canary
builder and signed-envelope implementation for valid historical payloads. It
does not invoke a command issuer, EA, broker, production service, or production
database.

The four cases are:

1. All seven terminal states with non-null terminal timestamps survive upgrade
   to `20260908_01`. Every original command column and canary window is preserved;
   only the four new fields appear. Historical classification shares the one
   migration transaction timestamp. Updates/deletes and forged new exemptions
   must be rejected by the named PostgreSQL constraints/triggers.
2. An unresolved `QUEUED` command with null terminal time rejects the upgrade.
3. A `QUEUED` command with a terminal timestamp still rejects it, independently
   exercising the state predicate rather than merely the null-time predicate.
4. A `FILLED` command with null terminal time rejects it.

Each rejection case includes valid terminal control history. Full row, window,
column, table-presence, and Alembic-marker snapshots must remain equal after the
failed real upgrade. No constraint/trigger is disabled, no final schema is
seeded, and no revision is stamped. Synthetic before/result JSON is retained
outside the worktree on D. The runner removes its exact tmpfs container only
after saving test results and logs; the test does not issue generic database
cleanup or schema downgrades.

At predecessor-source scope, `execution_commands.terminal_at` is nullable
(`20260719_01_mt5_executor_bridge.py:108`) and has no CHECK coupling it to command
state. The separate canary-window clock checks in
`20260823_01_engineering_demo_canary.py:218` and `:222` are satisfied by a CLOSED
window with a non-null terminal timestamp and null armed timestamp. This makes
the QUEUED/non-null command case compatible with the declared historical schema
without disabling a constraint. PostgreSQL must still admit the real insert
during the campaign; source review is not a runtime insertion receipt.

Execution requires `WOLF15_RUN_OBSERVED_MARKER_MIGRATION=1` and a campaign-created
`WOLF15_MIGRATION_TEST_CONFIG` JSON binding to `127.0.0.1`, an ephemeral published
port, `database_prefix=w15_marker_`, and `production=false`. The historical
`DATABASE_URL` environment is not accepted by the runner. Disabled/default
collection is not runtime evidence. The prepared Windows runner lives in the
task evidence packet and has separate source/hash/resource review; this source
document does not authorize a campaign or claim PostgreSQL PASS.
