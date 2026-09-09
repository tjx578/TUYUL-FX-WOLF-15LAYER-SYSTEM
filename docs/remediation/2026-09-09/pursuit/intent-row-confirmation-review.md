# Intent row confirmation review

Insert requires INSERT 0 1; conflicting idempotency insert, SKIP or other unconfirmed outcomes raise ExecutionIntentWriteConflictError before publishing local state. Update now predicates on the previously validated state and requires UPDATE 1. A mismatch is explicit rather than a successful local transition.

65 tests pass with exact collection/JUnit identities, including seven new command-tag cases and previous write-exception controls. Positive insert/update each publish once; rejected outcomes preserve memory/cache/idempotency index. Tests inspect the bound state predicate but do not execute SQL on PostgreSQL. Ruff passes on changed files. An intermediate lint naming issue and temporary text-encoding churn were corrected before final iw4 run and commit.

Limits: state-only comparison is not a version counter and does not prove all concurrency races closed. Conflict recovery needs authoritative reload; concurrent idempotency callers are not yet transparently converged. Existing unavailable-database fallback and read-failure behavior remain. No broker operation, active policy, migration or deployment occurred. Independent agent review unavailable; serial diff review only.

Canonical actions closed: none. Milestones 0/6. Existing 63 S03 PostgreSQL cases remain unexecuted. Push/merge HOLD under existing publication/runtime gates.
