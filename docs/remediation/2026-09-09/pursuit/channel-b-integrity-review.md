# Channel B report integrity

The existing run_reconciliation caller now seals its report with digests of database/broker snapshots, report payload and a receipt containing local orchestration source-file hashes. Source files are compared before and after collection; missing/changed files prevent a sealed result. The output contains hashes, not raw additional account, ticket or credential data.

verify_report_integrity requires an externally retained expected digest. It detects changed report fields, input digests, source metadata and self-rehashed tampering relative to that retained digest. The returned report is detached from caller nested dictionaries. Nonfinite numbers and naive evidence timestamps are rejected by serialization.

61 tests pass, including 12 new cases and an actual run_reconciliation invocation with mocked broker/database functions. Exact collection/JUnit identities match, source unchanged during the run, scoped Ruff/format pass. Existing gate and readiness values are preserved, including NOT_EXECUTED on unavailable evidence.

Limits: INTEGRITY_ONLY_NOT_ATTESTED, collector_identity UNVERIFIED. Local disk source hashes are not loaded-code or external-server attestation, and do not include runtime dependency closure. No active attestor, trusted retention service or risk consumer is configured. Digests are integrity references, not cryptographic proof of an independent reader or runtime evidence. Input snapshots still require separately bound secure retention for later full re-verification. No new activation or readiness authority is created. Serial review only.

Canonical actions closed: none; milestones 0/6. README/register unchanged; publication and runtime gates HOLD. Next work is binding configured collector provenance and trusted consumer/retention to this existing report path without accepting heartbeat self-report as independent reconciliation.
