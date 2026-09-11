# C03 reconciliation and engine shutdown follow-up

Status: **PARTIAL — source/local verification complete for the described patch; final Linux candidate acceptance pending. P1 remains HOLD.**

The source baseline is `5d109e2d64e4b653b1a9a916736e3d2b75ac42c1` on Draft PR #436. Its completed CI run `34372125336` failed the built-engine step after the bootstrap-failure case passed; the next case timed out. The Python job completed successfully: 10,464 coverage cases, six separately executed benchmark cases, two PostgreSQL drain cases and four Redis owner cases, with no JUnit failures/errors/skips. These counts overlap other suites and are not added. All 100 dedicated PostgreSQL cases also passed with source manifests and identity sets verified. Supported upgrade `20260909_05` to head `20260909_07` preserved the fixture ledger row. These results apply to the baseline, not automatically to this patch.

The runtime receipts bind the baseline's orchestrator, engine/trade, ingest and pressure-outbox cases to Git source hashes. Orchestrator normal shutdown and dependency failure passed. The actual trade-role invalid-dual-plane case exited nonzero with `EXECUTION_PLANE_CONFLICT`, left disposable database/Redis state unchanged, and sent zero dispatch requests to a recording sink whose positive control succeeded. This remains narrower than all legacy execution paths and is not broker acceptance. See [baseline review](5d109e2d/review.json).

## Reviewed deltas and implementation

| Input | Bound source | Reconciliation |
|---|---|---|
| #416 | `2ee5239ec0e029805c54b364d973f33c5674e9e7` | Explicit health-probe thread/loop owner with stop, bounded join/close, context-manager cleanup and compatibility delegation. Engine and orchestrator retain the owner and close after normal processing or fatal diagnostic hold. |
| #415 | `f7be6986d0bb052049fa75ef5598a6151851ab82` | Restored portable two-wave concurrency cases, broader migration-owner checks, stdout/stderr redaction acceptance, six additional portable correctness companions, and the WS five-warmup/thirty-measurement median workload. Existing stronger/newer tests remain. |
| #413 | `cb04a3c83c36c74310c776477adfe051c55ce635` | Migration runner/start script bytes matched the baseline in agent review. Four-target deployment selection and negative substitution/expansion tests are adapted to the current manual-only policy. Automatic-release assertions are superseded by that policy; no automatic trigger was restored. |

The signal callback previously called `Event.set()` without waking an idle event-loop selector. It now calls the owning loop's `call_soon_threadsafe`. A source-bound negative control using the previous committed function waited 1.515 seconds for the next timer; the fixed function woke after 0.062 seconds under the same fixture. This confirms the wake-up defect locally. The built-image timeout still requires Linux rerun to confirm resolution. The built-engine acceptance now retains the failing case, stage and allowlisted lifecycle markers; failure does not produce acceptance.

## Performance gate reconciliation

The manifest preserves #415's 22 definitions / 28 instances and two portable hang guards. One additional existing recording-client WS benchmark is retained, giving **23 definitions / 29 required benchmark instances**. Every benchmark retains its workload and assertions. All declared correctness companions remain outside the benchmark marker.

The existing required `Require uninstrumented latency budgets` step now runs the complete reviewed inventory through `scripts/ci/performance_acceptance.py`. Coverage is disabled explicitly. The gate rejects nonzero execution, missing/duplicate/extra cases, failures/errors/skips, source changes and substituted parameter identities. The five symbol labels and three pair-count labels are pinned in the manifest; equal case counts are insufficient. JUnit and source/manifest hashes are written to the uploaded receipt. The 300-second per-test watchdog is process safety; exact-10k elapsed time is observational, while correctness and workload completion are mandatory. Historical qualification hashes remain reference-only.

Marker edits were applied with an AST body comparison, preserving all test bodies. This implements the reviewed separation rather than declaring the former six-case lane equivalent to the entire inventory.

## Local evidence and independent review

- `reconcile-owner-signal-a1`: collection succeeded, execution interrupted before cases because the new test's signal mock retained the asyncio runner handler. The mock was corrected; this failed attempt is preserved.
- `reconcile-owner-signal-a2`: 73 passed, no failures/errors/skips, unchanged source.
- `reconcile-c03-a1`: 249 passed, no failures/errors/skips, unchanged source. The process handle was unavailable at final retrieval; completed log/JUnit/receipt and absence of the matching process established completion.
- `reconcile-performance-routing-a1`: 126 passed, no failures/errors/skips, unchanged source.
- `reconcile-performance-identity-a1`: 16 passed, no failures/errors/skips, unchanged source after the independent review finding was repaired.

Independent agent review identified a same-count parameter-substitution weakness in the first performance verifier. Explicit expected names and a negative substitution test repair it. The review found no additional actionable issue in the scoped runtime/CI diff; it is not a full P1 closure review. Whole-repository Ruff lint and formatting checks passed before publication.

Local logs, JUnit files and full before/after receipts are retained under the existing staging `ci-evidence` directory and summarized in `c03-local-validation.json`. No overlapping suite counts are summed.

## Next gate

Publish the bound candidate, then inspect its required GitHub checks, all 29 uninstrumented performance identities, all seven built-engine cases, PostgreSQL/Redis receipts and source hashes. Reconcile main and evaluate C01–C06 together before any P1 closure or merge decision. No production deployment, migration, broker activation or filesystem cleanup is performed by this patch. Natural DEMO bindings and later milestones remain separate, open work.
