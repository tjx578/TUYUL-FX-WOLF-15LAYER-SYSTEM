> Historical checkpoint: final validation and source commit subsequently completed; see collector-final-review.md and evidence/collector-final-validation.json. General host/runtime gates remain open.

# Collector gate and provenance checkpoint

Uncommitted source rejects configured tool-set mismatch before transport launch and listed tool-set mismatch before calling tools. Audit database URL values are removed from configured child environment case-insensitively; account-binding keys remain session sourced. Added provenance binds local helper file hashes and a digest of configured command/args/cwd/tools, with configured_server_identity UNVERIFIED and environment_values_bound false. It is not external server attestation.

Four new fixtures exercise no-launch/no-read on mismatch, removal of configured DSN variants and no credential values in report, and helper source drift rejection. cp1 passed all 11 Native MCP tests with exact identities in a separate existing MCP 2.0.0 environment. A subsequent import-order formatting fix changed final test bytes. cp2 failed BEFORE collection: Git source snapshot could not allocate 1 MiB. Therefore final-source test acceptance is NOT_EXECUTED and commit is pending. No repeated memory probe, test retry, process stop or host cleanup was attempted.

The earlier comment about broker-secret separation concerned configured env reinsertion; this patch does not claim every SDK inheritance path or arbitrary configured command has been attested. Fixture transport and FakeMT5 were used, with no broker interaction. Existing mandatory Native MCP CI job includes this test file; API dependency environment remains separate.

Next action requires a verified capacity change before final-source validation and Git commit. Preserve this working tree, run the same bounded Native MCP suite, verify source/receipt hashes and manifest, then commit only scoped files. Existing publication gate still holds. Other independent code may continue only within host capacity; do not repeatedly launch failed heavy operations.

No README/canonical register changes, no milestone closure, no production/provider/broker mutation. Independent agent review unavailable.
