# Combined S03/API exact-environment verification

Accepted verdict: **PASS_LOCAL_BOUNDED_COMBINED_SUITE**. Final collection and XML agree: **334 tests, 0 failures, 0 errors, 0 skipped**. Collection exit 0; pytest exit 0. Execution took 32.69 seconds; collection plus execution/receipt took 55.77 seconds.

The run used the previously established full-requirements Windows Python 3.11.9 environment, with Pydantic 2.9.2, pydantic-settings 2.5.2, pytest 8.3.2 and pytest-asyncio 0.24.0. No dependency installation or pin change was performed during this combined verification. Prior full requirements installation and pip-check receipts remain separate supporting evidence.

The subject is the worktree on base HEAD `261a3b476055accc3d0ea45ebc80a910e0e80f6b` plus the eight changed source/test files recorded in the receipt. It is not claimed as a new committed or deployed artifact. Before/after HEAD, tracked diff digest, all 14 test-file digests and all eight changed-file digests match exactly (`source_unchanged=true`). Exact commands, expected test IDs and file SHA256s are in `combined-s03-final-exact-receipt.json`.

The 14 requested files cover pair-activity contracts/report integration, API boot/readiness and ownership, required CI/release gates, legacy raw/pair admission, runtime selection and persistence fixtures, signal log analysis, directional thesis containment and pressure direction recovery. Normal conftests loaded. No pytest cache or bytecode was written to the repository; temp files and XML remained in C staging. Execution subprocesses used an allowlisted environment, no dotenv, unavailable localhost fixture DB/Redis URLs and disabled new-risk flags.

## Failure history retained

| Receipt | Measured result | Acceptance |
|---|---|---|
| combined-s03-exact | 333 passed, source changed during import correction | NOT_ACCEPTED_FOR_FINAL_SOURCE |
| combined-s03-frozen-exact | 332 passed, 1 failed; source unchanged | FAIL, investigated without blind retry |
| baseline-event-order-reproduction | Baseline/current recording methods have matching AST hashes; two fixed timestamps demonstrate both canonical orders | PREEXISTING_TEST_ORDER_ASSUMPTION_PROVEN |
| baseline-order-fix-target | 2 passed, no skip; source unchanged | PASS_LOCAL_TARGET |
| combined-s03-final-exact | 334 passed, no skip; all eight source hashes stable | PASS_LOCAL_BOUNDED_COMBINED_SUITE |

The failing pre-existing test assumed physical insertion order for THROTTLED and DOWNGRADED_TO_HOLD events, despite the producer's `(timestamp, raw_event_id)` canonical ordering. With fixture deployment `fixture-baseline-order`, `2026-09-08T20:20:00Z` produces THROTTLED first, while `2026-09-08T20:20:03Z` produces DOWNGRADED_TO_HOLD first. The committed baseline and new source agree at both times, and both events remain non-executable. The parent changed the test to verify both deterministic cases, canonical order, event-type-specific direction fields, timestamp/count and zero execution authority. Production recording/order logic was not changed to satisfy the test.

Warnings remain non-fatal and recorded: Starlette's deprecated BlockingPortal alias and pytest-asyncio's unspecified future fixture-loop-scope default.

This receipt is not the full repository required suite, Linux validation, remote CI execution, PostgreSQL integration, production runtime or broker acceptance. It does not close all S03/milestone requirements or authorize main merge, deployment or broker execution. No provider, production database or broker action occurred.
