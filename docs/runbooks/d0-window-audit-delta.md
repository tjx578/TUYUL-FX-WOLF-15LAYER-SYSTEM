# D0 window audit delta

Revision `20260915_02` adds `wolf15_audit.d0_window_counts_v1`, a global,
single-row aggregate. Its four bigint columns are `open_window_count`,
`queued_count`, `armed_count`, and `reconciliation_required_count`.
Only QUEUED, ARMED and RECONCILIATION_REQUIRED are open; an empty source
returns four zeros. Counts are not clamped to the single-open-window invariant.
No account, command, payload or credential fields are exposed. The existing
auditor role receives SELECT on this view, not access to the underlying table.
If the role is provisioned after migration, its separately reviewed provisioning
must grant SELECT on this view. Missing permissions remain NOT_MEASURED.

## Deployment

Review the exact migration and CI results before publication. Inspect the
deployed Alembic revision and migrator source before applying it: do not change
a release-pinned migrator to another branch and blindly run `upgrade head`.
Apply through the existing migration owner only after its pending revision set
is confirmed within the authorized scope. Downgrade drops only the new view.

## One read-only delta

Use role `wolf15_auditor`, repeatable-read/read-only and a bounded timeout:

```sql
SELECT open_window_count, queued_count, armed_count, reconciliation_required_count
FROM wolf15_audit.d0_window_counts_v1;
```

Retain actual field values from executor identity, freshness, internal binding
and execution containment views alongside this query, rather than just row
counts. Bind the exact executor/account/server to the accepted DEMO target;
require mode_version=2, ONLINE, fresh heartbeat/snapshot, Algo Trading OFF,
kill switch ENGAGED, active/ambiguous commands 0/0, current positions/orders
0/0, and all four window counts zero. Retain timestamps and cleanup evidence.
Direct MT5 account/positions/orders observations are read-only; this delta does
not rerun Channel-B identity acceptance or credential lifecycle.

Query denial, missing data, stale evidence or any mismatch means HOLD. A capture
exit code of zero alone is not acceptance. Only the complete passing matrix
permits S5 PASS/CLOSED and D0_PREFLIGHT READY_FOR_FINAL_RUN. It does not authorize
a command, window mutation, Algo Trading change, kill-switch release, broker
effect, real-money execution or automatic multi-pair operation.
