# Independent S03 durable runtime source review

Verdict: no remaining blocking issue identified in this bounded source review after the implementation and test/CI corrections below. PostgreSQL acceptance remains BLOCKED / NOT_EXECUTED. No local PG PASS, deployment readiness, or full S03 DONE is claimed.

Scope: explicit runtime/coverage contracts, PostgreSQL schema/store, runtime factory, live analyzer handoff, migration and intended local/integration tests. No PostgreSQL instance was started or connected, and no repository file was written by this review. Parent reports host memory pressure at 94.8% and no usable Linux host; that runtime blocker is not independently measured here and is not overridden. Existing workloads remain untouched.

## Findings and disposition

R01 (corrected source): recoverable suspension lost original admission prefix. The store previously selected its frozen admission only when latest had neither admission_id nor previous_admission_id. A normal coverage suspension retains previous_admission_id but has admission_lineage_hash=None, making the next identical complete population look like changed lineage. A pure-kernel reproduction produced GRANTED -> SUSPENDED -> RECONCILIATION_REQUIRED without a data change. Store now uses the frozen receipt when latest has no active admission and is not explicitly RECONCILIATION_REQUIRED. A second pure-kernel check with this selection recovers the original GRANTED ID, while changed backfill stays RECONCILIATION_REQUIRED on repeat. The actual PG recovery regression still needs execution.

R02 (corrected source): snapshot authority protection was incomplete. Initial snapshot CHECK enforced only execution_authority=false, and stored snapshot return compared audit only. Current schema requires all three top-level hypothesis/risk/execution fields to be exactly JSON false with IS TRUE, rejecting JSON null/missing/string values; the store defensively checks the three fields before returning a previously committed snapshot. Evaluation rows independently require all four non-executable fields false, and added row-ID checks plus composite attachment foreign keys bind the evaluation to the same ledger/activity. These are reviewed SQL expressions, not demonstrated PostgreSQL results.

R03 (corrected source): each append rewrote every historical raw and logical row under the analyzer/ledger locks. Current append computes added raw IDs, inserts only new facts and updates only logical observations touched by those facts. Duplicate-only delivery no longer writes all historical rows. It still reads and normalizes the full bounded ledger under serialization, so production throughput/SLA is not measured and large ledgers remain a performance limitation.

R04 (corrected test source): authority-negative PG fixtures now include evaluation_id/activity_id matching their row columns, parameterize all four evaluation and all three snapshot flags, and have a positive all-false SQL insertion control. Missing/null/string/true authority values are therefore isolated from unrelated row-ID violations. Coverage-loss recovery, durable twin/duplicate observations and incomplete coverage watermark regressions were also added. This strengthens intended tests without claiming they ran.

R05 (corrected CI source): the strict runner originally checked only case count and uniqueness, permitting a same-count wrong-identity JUnit file. validate_junit now compares exact normalized collection identities (module/class/name) to JUnit identities and rejects duplicates, missing cases, failures, errors and skips. The unit suite includes a same-count/wrong-identity rejection. Source before/after hashes include the runner itself and the raw-authority/event-ID helper. The workflow supplies a dedicated disposable-test DSN, requires the acceptance runner without continue-on-error, and uploads receipts with always() and missing-artifact failure. Unavailable DB cannot silently become accepted by skipping tests. No CI/PG job was run by this reviewer.

The new covered_through watermark is separate from raw_watermark. It advances only when audit coverage is COMPLETE and the checkpoint end is not future; incomplete snapshots can record observed raw progress without claiming complete coverage. Recovery starts from the prior covered watermark minus explicit overlap, while execution still reads the full bounded ledger. Complete-but-reconciliation-required evidence remains distinct from an active grant.

## Reviewed invariants

- Binding and checkpoint are versioned, timezone-aware, scoped by ledger/deployment/attestor and selected SSOT. Completeness compares independently supplied expected raw count and hash to durable normalized facts. The hash is not itself attestor authenticity. Missing/mismatched scope or population stays UNKNOWN/INCOMPLETE; future/outside-window evidence is rejected by the kernel.
- Runtime requires explicit source observation identity for persisted logical observations. Equal-time distinct producer identities remain separate, while typed twin facts remain traceable to their individual raw IDs.
- A ledger row INSERT plus SELECT FOR UPDATE serializes append/evaluation for that immutable binding. Both callers acquire the same ledger lock before reading/writing. Binding changes on an existing ledger fail rather than replacing policy or source scope.
- Evaluation rows, activity attachments, snapshots and watermark updates share one psycopg connection transaction. The injected after-evaluations callback is before snapshot/watermark commit, allowing a rollback test. Return occurs only after context-manager commit. This is source reasoning pending actual database failure injection.
- Evaluation collision compares persisted full payload. Snapshot retries return the report actually stored on first commit, retaining original trigger/replay boundary rather than synthesizing new metadata under the same identity. The audit is compared to current validated computation before return.
- Recovery replays the full bound ledger, an explicit superset of watermark-minus-overlap. A stale decision time cannot rewind evaluated_through. Frozen original admission persists separately from latest evaluation; backfill reconciliation stays explicit.
- Record failures latch RECOVERY_REQUIRED. snapshot catches expected database/data/file errors and returns structured non-executable unavailable output. Factory has no fallback to general DATABASE_URL, requires explicit activity DSN/binding path and matching deployment, and does not run DDL. Startup migration remains separate.

## Acceptance limits

The attachments table currently links activity_id to current/frozen evaluation. It does not contain a strategy_lifecycle_id or emission_id. Its row count therefore does not prove SSOT lifecycle/emission attachment or no duplicate strategy lifecycle. Similarly, current source does not establish evaluator SLA/cutover incident scheduling. Keep those as separate unresolved acceptance items.

Reviewed PG test source covers service reconstruction with empty memory, a fresh subprocess against the same DB, competing connections, injected rollback, missing policy/coverage, backfill, source-identity collision, binding collision, SQL authority rejection and stale watermark. None was executed by this reviewer. Do not turn fixture collection, pure-kernel checks, code inspection or blocked/skipped database tests into local PG acceptance.

All new runtime outputs remain observational/non-executable. Actual source/attestor approval, deployed binding, production policy, measured ledger cohort, transaction durability/concurrency and post-restart runtime behavior remain distinct from source implementation. Full S03 and S01 remain incomplete until their applicable gates are satisfied.

## Final reviewed worktree byte hashes

These are a review snapshot of working files, not a commit claim. Parent may revise tests before final validation.

| Path | SHA-256 |
| --- | --- |
| contracts/strategy_5scr_activity_runtime.py | 7ae75b6f6bf6a707ae0724c39804872642666e2540ddc01dc0d1758181852e2a |
| storage/strategy_5scr_activity_schema.py | ea38653ee636db378e4068f375954faabcdd680894a3026c53fa9ca4544962d8 |
| storage/strategy_5scr_activity_runtime.py | 2a9e2d9460422fdd1de3437df13704897d5b7741ad759105af731bc148b53367 |
| analysis/strategy_5scr_activity_service.py | 763d1af01745d5258139c3f163b6f47d65e82e4a43fc3fd5663bab9825f3d905 |
| analysis/signal_throttle_log_analyzer.py | 95797f2e0ce9da9c73bfeb58f4a12e0f7fc1fab0f251c3484bb566a003e53680 |
| storage/migrations/versions/20260909_01_pair_activity_runtime.py | 05d515b9119a61ad9c7b3eb014603e405d7881466b59a7862c7db78a59e54a8a |
| tests/test_activity_runtime_binding.py | 24fd14ab986565f3bfe60ebb3d18f5be2a5eb953a94bd802c1a1867910a80bb0 |
| tests/integration/test_pair_activity_runtime_postgres.py | 2aa90a87df61c6fafb7084d953cf40736c1c65e43f5c1ac6cfb29f03229604c8 |
| scripts/ci/run_pair_activity_runtime_acceptance.py | aba938afae4e07dd3c9f4138245b57160cd56d09a4002fe455863e5642313843 |
| tests/test_pair_activity_ci_receipt.py | 6fcefd5e7bb21e225ff13e8339c337f89e7eeef12ba8eaedba99ef948aa7061b |
| .github/workflows/ci.yml | a5da25e9cfd9885c7412672372fb452f810dbe1eaa9edfdeec9267cc888862b8 |

Final scope note: parent reported 612 passing non-PG cases before the final two CI-receipt file changes, with targeted receipt tests to follow. This report does not convert that parent update into independently executed tests. Its independent dynamic check was only the two pure-kernel suspension/backfill selection reproductions described above.
