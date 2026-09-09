# Remote reconciliation on 2026-09-10

PR #436 was independently observed as MERGED at head 2701b9d4a7ede34fc1a05a9a0566b139fcbbc16a. The prior local push was rejected; no force-push was used. Local C03 commit 0c2a56c8 and its history were retained. A follow-up branch codex/p1-c03-runtime-closure-20260910 carries the unpublished C03 package.

The overlapping SIGTERM fixes were reconciled by preserving remote loop.add_signal_handler preference and its Windows call_soon_threadsafe fallback. Both remote tests and the local idle-loop regression remain. The regression explicitly forces the fallback so it is meaningful on Linux as well as Windows. The remote persistence typing, allocation cleanup, and supervisor changes remain intact. This reconciliation passed 48 local tests without failures/errors/skips.

Main subsequently advanced through fa7d027d. Its runtime/readiness and stricter source governance changes were integrated. The affected suite passed 223 tests without failures/errors/skips, with unchanged source during the run. Full local receipts accompany this report. Counts overlap earlier suites and are not aggregated. Linux validation of this follow-up candidate remains pending.

C05 conflict observed: current GitHub main protection reports zero required approvals and require_last_push_approval=false, while main's p1_governance_gate now requires at least one independent approval and last-push approval. CI/Security/Docs checks remain strict. Source unit tests pass against their fixtures; provider policy does not satisfy the current source gate. No provider controls were changed to resolve this difference. P1/release remain HOLD pending policy reconciliation and candidate acceptance.

The historical 100 PostgreSQL and 10,464 Python results remain bound to 5d109e2d and are not claimed as results for the new candidate. No main merge, deployment, production migration, or broker action was performed by this reconciliation task.
