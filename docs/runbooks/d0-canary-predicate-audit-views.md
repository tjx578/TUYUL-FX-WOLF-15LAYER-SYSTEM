# D0 canary predicate audit views (revision `20260919_01`)

Two read-only `wolf15_audit` projections close the two canary predicates the auditor could not measure
in the Step 4B TEST_ONLY evaluation. Both are `security_barrier` views; `wolf15_auditor` receives
`SELECT` on the views only and no privilege on any base table.

| View | Keyed by | Exposes |
| --- | --- | --- |
| `executor_snapshot_symbol_capability_v1` | exact `(executor_id, snapshot_id)` | S-level `trade_allowed`, `autotrading_enabled`, `margin_mode`, `account_matches_executor`; per symbol: `canonical_symbol`, `broker_symbol`, `digits`, `point`, `tick_size`, `volume_min/max/step`, `stops_level_points`, `freeze_level_points` |
| `direct_reconciliation_receipt_v1` | `(executor_id, source_snapshot_id)` | `reconciliation_id`, `observed_at`, `broker_ledger_reconciled`, `terminal_reason`, position/pending/orphan/unattributed/ambiguous/ledger-mismatch counts, non-secret digests, `source_snapshot_exists` |

Not exposed: balances, equity, login hashes, snapshot/receipt payloads, tickets, position identifiers.
`SymbolCapability` carries no per-symbol trade mode; terminal trading state is the S-level flags.

The views read exact stored snapshots; they never pick "latest". Evaluators must query with the
packet's snapshot `S`. No enqueue, arm, EA, wrapper, heartbeat or execution-flag behaviour changes.

Applying this revision moves the Alembic head from `20260915_02` to `20260919_01`. Components that pin
the head (for example the C2 wrapper writer's schema-head capability check) must be re-qualified
against the new head before they run on a database migrated to it.
