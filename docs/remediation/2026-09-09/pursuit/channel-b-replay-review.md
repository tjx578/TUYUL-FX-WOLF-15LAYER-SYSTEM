# Retained Channel B report replay verification

verify_reconciliation_replay takes externally supplied receipt digest, source hashes, full account identifier, exact window, verifier clock and maximum age. It checks integrity and input hashes, verifies account identity, bounds collection clocks and age from collection start, re-executes the existing Channel B evaluator and compares the whole report body. Only a consistent report with EXECUTED_PASS satisfies replay acceptance. No tolerance or active DEMO age policy is selected; test age is fixture-only.

A related account-binding gap is corrected: missing/coerced mismatch counts no longer imply zero; boolean freshness ages are rejected. Five missing-count cases prove incomplete binding cannot pass.

Final cr2: 91 passed, no skips, exact JUnit/collection identities, source unchanged and scoped Ruff/format pass. Seventeen new cases include valid replay, wrong digest/account/source/window/input, age boundary and expiry, invalid clock/scope, coherently resealed false evaluation, and a coherently replayed blocked gate. Tests use retained fixtures with no live DB or broker. The verifier invokes the actual evaluator and integrity checker, not a duplicate implementation.

Review limits: function-level verifier is not yet wired to a runtime risk consumer or independently operated retention service. It cannot authenticate a collector simply because a caller supplies a digest. Source dependency closure and trusted attestor remain unbound. Even successful replay reports independent_reader_attestation NOT_VERIFIED, execution_authority false and production_ready false. No active DEMO profile/age threshold, broker operation, deployment or production mutation. Serial review only; independent agent review unavailable.

Canonical actions closed: none; milestones 0/6. README/register unchanged. Next work: actual collector provenance and a bound trusted retention/verification caller. Existing runner, CI, publication and DEMO blockers persist; do not manufacture active bindings from test fixtures.
