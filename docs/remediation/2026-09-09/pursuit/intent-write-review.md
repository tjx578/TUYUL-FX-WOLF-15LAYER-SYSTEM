# Execution intent write failure review

Available PostgreSQL write exceptions previously logged and returned normally. Create/transition could then advance local state and reconciliation could report a result without a successful write. Both insert and update now re-raise the original exception before cache, memory and idempotency-index mutation.

Expected versus actual: injected insert, transition-update and reconciliation-update failures all propagate the original exception; execute is called once and local state remains unchanged. 58 scoped tests pass, including three new cases; collection and JUnit identities match exactly. Ruff and formatting pass for changed Python files.

This is local fault injection, not PostgreSQL persistence acceptance. The unavailable-database fallback, read-error handling, affected-row verification and concurrent insert conflict handling still require separate durability assessment. No broker attestation or execution authority is introduced. Review was serial; independent agent review remains unavailable.

Reservation release source inspection found CONSUMED retained in active-risk accounting; no release change was justified by this inspection. This does not establish database recovery correctness.

Canonical register and README files unchanged. S03 database acceptance remains 63 tests unexecuted; no milestone closed. Push and merge remain HOLD under existing publication and runtime gates.
