# Runner evidence binding and pressure expiry follow-up

**INCOMPLETE / HOLD; 0/6 milestones complete.** This is source and offline evidence work on PR #428, not a provisioned runner, PostgreSQL acceptance, approved policy, or DEMO packet.

Source commit: `94cd6a5d0bf920ad6b5ca5f9475d273b0c7ab334`; previous candidate: `90f5d777a89c134fbc528c6b667666d68d8dcdb1`.

## Concrete changes

The acceptance runner now creates an exclusive UUID directory before collection and retains a failure-default receipt. It binds Git head/tree/clean-worktree state, source and configuration hashes, the complete migration-file graph, selected SSOT bytes, package versions, OS/host identity and scoped capacity. GitHub CI declares the expected PostgreSQL major as 16; a separately configured native 17 run is supported. Neither version is inferred from a desired outcome. Disabled negative controls do not probe host capacity or connect to a database.

The guarded PostgreSQL fixture records before/after observations from actual connections: database/user/address/port/OID, server version and postmaster start, installed migration head, the six required tables, disposable markers and selected durability/configuration settings. Runtime-helper calls record their fixture binding and checkpoint, including test-only policy and provenance. Receipts require the same run nonce, unchanged database identity/configuration, exact JUnit case identities, zero failures/errors/skips, unchanged source and a clean worktree. Artifacts are hashed; logs redact database URLs and password components. These are locally generated evidence records, not an authenticated approval mechanism.

The existing V1 directional thesis consumer now treats `valid_until` as exclusive. With the otherwise valid fixture, one microsecond before expiry remains READY; exactly at expiry and one microsecond after produce REJECTED / PRESSURE_AUTHORITY_EXPIRED and no build artifact. This removes a boundary defect; it does not bind V3.1 to the V1 consumer or authorize a new direction.

## Expected versus actual

| Gate | Expected | Observed in this follow-up |
|---|---|---|
| Targeted local regression | Exact collected/JUnit identities; zero failure/error/skip | 241/241 PASS in pinned Windows API environment; source stable |
| PostgreSQL module inventory | Preserve the existing 45 identities | Exact match to previous 45-case control |
| Database unavailable | Strict runner must refuse skipped cases | 45 skipped; pytest exit 0; gate exit 1; accepted=false |
| Real PostgreSQL metadata/restart/concurrency | Actual guarded connections and zero-skip acceptance | NOT_EXECUTED; helper behavior covered only by offline mocks |
| Migration execution | Apply and record the required upgrade against the disposable instance | NOT_EXECUTED; observed head will still label upgrade execution NOT_BOUND |
| Linux runner | Verified identity/configuration/capacity and executed checks | UNBOUND; GitHub repository runner inventory returned zero |
| Static quality | Ruff lint and format | PASS; 1,386 Python files formatted |
| Independent final agent review | Completed review of final patch | NOT_COMPLETED: agents hit a Codex usage limit; parent completed implementation/review/verification |

The previous 613-test result belongs to the preceding implementation scope. Do not add 241 to 613: the suites overlap. The new 241-test receipt binds the current changed files; its pre-commit SHA plus exact file hashes are reconciled to the source commit in `evidence/runner-binding-source-commit.json`. The negative control ran on that clean source commit.

## Runner and migration handoff

`disposable-runner-binding-proposal.json` intentionally contains null host/configuration/capacity/instance/credential-reference fields and status UNBOUND. It cannot activate a runner. Existing Windows workloads and historical VPSs remain preserved; no host-capacity recheck, service start, database connection, provider provisioning or billing action occurred in this follow-up.

Once a dedicated disposable runner is bound, its operator must provide current capacity evidence, OS/architecture, exact database version, least-scope access and a clean checkout of the candidate. Use an isolated test database with explicit loopback identity and disposable markers, never an operational DSN. The existing CI migration owner runs `python -m alembic upgrade head`; API/engine startup remain non-migrators. Record the actual starting revision, upgrade command/exit/output, resulting installed head and database instance identity. An observed head alone cannot establish that an upgrade ran. Fresh initialization and the selected parent-to-head upgrade need their own execution records where required; do not substitute SQL generation or silently run downgrade tests.

Then invoke `python scripts/ci/run_pair_activity_runtime_acceptance.py` with the explicit disposable-test configuration and expected PostgreSQL major. Receipts appear under `artifacts/pair-activity-runtime/<run-id>/`. Passing this subset proves only the executed persistence/recovery cases. The current runner deliberately reports `migration_upgrade_execution=NOT_BOUND` because CI migration execution precedes its invocation. A separate bound migration receipt is still required to close migration acceptance. No runner was provisioned or activated by this patch.

## Remaining consumer dependencies

The actual directional-thesis repository entrypoint is `storage/strategy_5scr_directional_thesis_v1_repository.py:1262`, which builds V1 evidence and calls the existing reducer. No production consumer of `PressureAuthorityV31` / `evaluate_pressure_direction` was found. A V1-to-V3.1 adapter cannot invent formal transition, source lineage, approved policy digest or unresolved-route authority.

`LifecycleV2ShadowRunner.poll_once` in `services/pressure_outbox/lifecycle_shadow_worker.py:295` reads delivered legacy events through `storage/strategy_5scr_lifecycle_v2_repository.py:448`, converts them using `episode_event_from_outbox_row`, reduces and persists the lifecycle/link. Its database query joins the old inbox/outbox. S03 activity attachments currently bind activity/evaluation, not strategy lifecycle/emission. The legacy delivery admission and this adapter do not provide the mixed-direction S03 route. S03 also has a dedicated DSN while the lifecycle repository has its own persistence owner. Adding a sidecar link would not establish a shared transaction or delivery path.

The next integration must explicitly bind event delivery, lifecycle identity, transaction/outbox ownership and policy/attestor provenance, then test duplicate/replay/restart and zero hypothesis/risk/order authority through that path. This remains open; no alternate writer or fabricated active policy was introduced. DEMO account/risk/EA/canary/independent-broker-reader bindings remain incomplete.
