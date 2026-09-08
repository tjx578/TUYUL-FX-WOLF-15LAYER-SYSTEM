# S03 v3.1 activity kernel — local validation

Baseline: root clean `261a3b476055accc3d0ea45ebc80a910e0e80f6b`. Three new source files were staged in the C workspace and handed to the parent for controlled copying. This agent did not write D source files, commit, or change a provider.

**39 focused tests pass (1.58 seconds)** with Python 3.11.9 and Pydantic 2.10.3. Ruff check and format pass using repository pyproject configuration. The parent owns validation with pinned Pydantic 2.9.2 and combined report/pipeline integration tests. These host component results do not close runtime acceptance.

Public APIs are `PairActivityPolicyV31`, `RawActivityCoverageV31`, `PairActivityEvaluationV31`, `PairActivityAuditV31`, `pair_activity_ledger_hash(raw_events)` and `build_pair_activity_audit(raw_events, coverage=..., policy=..., decision_at_utc=..., previous_evaluations=...)`. Policy and completeness attestation must be bound by the caller. There is no default production gap, TTL or policy selection.

BUY0/SELL150/BUY300 remains one 300-second activity with a GRANTED analysis activity and CONFLICT quality. Hypothesis, risk and execution authority remain false. Parsing the new schema as a legacy directional grant fails. Legacy v2 functions and receipt identities remain unchanged.

A gap above bound policy suspends without finalizing. A different symbol finalizes the activity. Open activity freshness uses decision time minus its latest raw event. Finalized activity continuity ends at the next symbol's raw event, and global source freshness is checked separately. The audit validates finalizer identity/timestamp against the actual next global row and the global watermark against the latest raw row. Future evidence and window/hash mismatches block grants. UNKNOWN coverage never becomes NO_RAW_ACTIVITY.

First-threshold admission identity, prefix, time and expiry remain immutable while latest quality and evaluation receipts can advance. Duplicate and reordered replay preserve identities. Local JSON serialization, restore and restart replay preserve receipts. Late cross-symbol events, changed pre-admission lineage and changed policy require RECONCILIATION_REQUIRED while retaining prior admission identity. A prior admitted activity omitted from replay raises an explicit reconciliation error. Revalidation catches model_copy/model_construct bypasses. Tests reject tampered payload hashes, counts, gaps, quality, scope, global ordering and finalizers.

Remaining S03 gates include actual canonical raw completeness attestation, selected policy, normalized logical-pulse identity for THROTTLED plus DOWNGRADED twin facts, and the real durable PostgreSQL writer/schema, attachment, SLA and recovery path. Counts remain raw-fact counts; logical pulse counts are not inferred. Local JSON persistence is not PostgreSQL durability. The parent adapter can invoke the kernel with explicit bound inputs while preserving legacy signal/risk/EA authority. Broker, DEMO and production DONE are not established.

Independent review found and corrected finalized-block freshness semantics. The regression with A0..300 followed by B301..370 under a 60-second gap policy preserves A's unexpired admission. An open A activity becomes stale, a stopped global source suspends all activities, and a forged finalizer timestamp with a recomputed receipt hash fails global audit validation.
