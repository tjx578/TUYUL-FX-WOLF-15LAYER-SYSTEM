# S03 durable caller implementation — acceptance remains incomplete

The continuation starts at `main@7bc5d73cb416e26c40271e5df6d719021164637d`, the externally merged PR #423. Its tree was verified identical to the previously tested `98b72297` tree. Work is isolated on `codex/s03-runtime-recovery-20260909`; the original dirty checkout is not the implementation workspace.

Current-main documentation/configuration changes through `68ad0794` were merged as `7de6dc9a`. All tested source Git blobs remained identical to source commit `59f2db54`; no additional runtime code was introduced by that merge. The newly tracked `AGENTS.md` and repo skill assessment were read and applied for review/publication. The earlier agent inventory is retained as a dated pre-merge observation.

**INCOMPLETE / HOLD — 0/6 engineering milestones complete.** Source wiring, migrations, tests and CI admission have advanced. Actual PostgreSQL transaction/restart/concurrency acceptance and Linux execution have not run. Do not promote this package to a valid DEMO packet.

## Implemented caller and persistence boundary

The pipeline constructor now obtains `activity_runtime_from_environment()` and injects it into `SignalThrottleLiveAnalyzer`. The real producer methods preserve source observation identity, enrich scanner/deployment lineage, and persist facts before a runtime snapshot reads its PostgreSQL ledger. The snapshot attaches the v3.1 result to the existing report; missing runtime, dedicated DSN, deployment match or coverage context has an explicit reason. The factory never falls back to the general `DATABASE_URL`, runs DDL, or activates a trading mode.

Binding inputs are `WOLF15_PAIR_ACTIVITY_BINDING_PATH`, `WOLF15_PAIR_ACTIVITY_DATABASE_URL`, `WOLF15_PAIR_ACTIVITY_CHECKPOINT_PATH`, and the matching deployment identity. The JSON binding pins the selected SSOT digest, ledger/producer/scope/attestor identity, explicit policy, bounded population and recovery overlap. Only SHADOW or DISPOSABLE_TEST applicability is accepted. No real production values have been supplied or installed.

Coverage is a separately supplied attestor checkpoint of expected population/hash/window, checked against durable facts. A hash of the available process buffer never creates COMPLETE coverage. Checkpoint authenticity and approval of its source/attestor remain real binding requirements; these local contract checks do not prove an arbitrary attestor is authorized. The current implementation replays the entire bounded ledger, a superset of the explicit overlap. It refuses capacity overflow instead of silently dropping history.

The new six-table v3.1 store serializes each ledger using a PostgreSQL row lock. Source insertion is idempotent. It writes only newly observed raw facts and changed logical observation mappings, rather than rewriting historical rows. Evaluation, activity attachment, immutable snapshot and watermarks commit in one transaction. Frozen admission identity survives recoverable suspension; actual backfill reconciliation remains sticky. A raw observed watermark is distinct from `covered_through`, which does not advance on incomplete coverage. Failed durable writes latch recovery-required status instead of continuing with a partial buffer.

**Activity attachments are not strategy lifecycle/emission attachments.** The store links activity to evaluation/frozen evaluation. Actual lifecycle/emission consumption, missing-outcome SLA incidents, calibrated policies, retention/cutover and deployed-source acceptance remain open. These are not claimed DONE by the presence of database tables.

## Observation identity and direction

The producer emits an explicit `source_observation_id` and schema. Intentional THROTTLED/DOWNGRADED twins share one logical observation while preserving both raw facts. A delivery retry must retain that identity; empty/invalid IDs are rejected. Distinct explicit observations remain distinct even with identical raw values/timestamp. Raw IDs use a new explicit-identity hash basis; inputs without identity retain historical hashes. Durable runtime admission requires explicit source identity.

Emit/parse/replay preserves the original source timestamp, even when an export timestamp differs. Sampled logs remain incomplete unless an independent complete-population binding proves otherwise. Equal-time cross-symbol facts with explicit identity are rejected as `AMBIGUOUS_GLOBAL_SOURCE_ORDER`; a hash ordering cannot substitute for an unprovided global source sequence. Same-symbol ties are allowed.

The existing BUY0/SELL150/BUY300 kernel acceptance remains one 300-second activity with CONFLICT direction quality when coverage/continuity are valid. A collected PostgreSQL test now exercises this exact sequence through actual producer/caller methods and a new caller after restart. That PostgreSQL test has **not executed** on this host. Passing kernel, normalization, parser and mocked-boundary tests cannot substitute for it.

All v3.1 evaluations and reports deny hypothesis, capital/risk and execution authority. SQL constraints additionally require actual JSON boolean false, rejecting missing/null/string/true values. The versioned activity receipt is not converted into a legacy directional grant, risk reservation or executable command.

## S01 source corrections

The isolated pressure authority v3.1 contract requires source contract version and explicit nullable invalidation fields, validates lineage/time/formal transition, and denies unresolved/unapproved policy or separate routes. Its positive result is only a directional analysis prerequisite, never a hypothesis/risk/order grant. Generated schemas/examples are included in evidence and have model/schema validation receipts.

The old consumers are unchanged. Remaining lifecycle enum, candidate/order/cost/target shape, active policy registry and mandatory downstream authority mapping are documented in `contract-assessment.md`. Full S01 remains partial; the chosen v3.1 source does not supply calibrated gap/TTL/SLA/overlap values or a production DEMO binding. The missing historical assessment bytes remain a provenance limitation, not a reason to relabel tests as production proof.

## Verification and infrastructure disposition

**613 collected = 613 passed, zero failures/errors/skips** on the final source. Exact identities and hashes are in `validation.json`. The pinned Windows API environment uses Python3.11.9, Pydantic2.9.2 and pytest8.3.2. Intermediate/overlapping runs are retained without summing them as separate unique coverage. Whole-repository Ruff0.15.7 lint/format passed before documentary packaging.

The PostgreSQL module contains **45 collected acceptance cases** covering actual caller 300-second activity, fresh-process restart, concurrent independent connections, rollback between evaluation and watermark, duplicate/twin delivery, backfill, incomplete coverage, frozen grant recovery, stale workers, and database authority constraints with positive controls. They require an explicitly migrated loopback disposable database and reject URI overrides. They do not create missing schema automatically.

Alembic resolves one head `20260909_01`. Offline SQL generation succeeded. This is not PostgreSQL execution. The CI job now supplies the dedicated fixture DSN and invokes a strict acceptance runner before the broader test suite. It compares every collected identity with JUnit and binds source hashes before/after, including its own code and raw helper. The mandatory native MCP job remains in its separate dependency environment.

The deliberate unavailable-database negative control collected45/skipped45: pytest returned0 but the acceptance runner returned1 and `accepted=false`. This proves refusal to accept skipped database tests; it proves no database behavior.

Docker's Linux engine is absent; only stopped docker-desktop WSL was found. PostgreSQL17.11 native binaries are present. The one fresh capacity recheck measured94.7967% committed memory, above the start guard. The user confirmed no memory cleanup and no verified disposable Linux host, preserving existing Windows workloads and historical VPSs. No PostgreSQL instance was initialized, no DSN created, and no further capacity polling or Docker/WSL start was performed. The guarded native harness remains an offline-tested preparation artifact, not a completed environment setup.

## Remaining closing evidence

1. Run the migrated, guarded disposable PostgreSQL acceptance suite; require all45 identities executed without skips, then inspect durable counts, rollback and restart receipts.
2. Run Linux dependency closure and actual required CI at the published source. Jobs without runners/steps do not prove source failure or billing cause.
3. Bind approved complete raw source/attestor, calibrated policies, source ordering, lifecycle/emission consumers, SLA and retention/cutover rules. Verify the actual service cohort.
4. Complete independent DEMO account/server, risk, canary scope, compiled EA and broker-reader bindings before any broker acceptance.

This turn performs no main merge, Railway deployment/configuration change, production database mutation, VPS change, broker command, or billing operation. All supplied assessment inputs remain archived; current action status is updated separately from historical receipts.
