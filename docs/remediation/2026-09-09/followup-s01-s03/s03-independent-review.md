# Independent S03 source review

Verdict: no remaining blocking source finding identified in this bounded review after the finalized-block freshness correction. This is permission to continue local integration verification only. S03 remains PARTIAL; source and fixture results do not establish durable production completion, policy approval, or order authority.

Scope: staged v3.1 pair-activity contract and pure evaluator, reporting adapter, analyzer/pipeline observability integration and focused regression source. Normative reference is selected SSOT SHA-256 6daea387745ffa305d3cd55b0fee4f0efed79be21e24503c2a1f8a16c6a83902, especially sections 7 and 10. Parent owns final integrated test receipts. No provider or broker was accessed and this review modified no source code.

## Finding resolved during review

S03-R01: the original evaluator compared decision time to the last event of every pair, including already finalized blocks. With A at seconds 0,60,120,180,240,300 and B at 301,350,370, a 60-second gap policy incorrectly suspended A at decision 370 despite continuing global raw input and a valid finalization boundary. The corrected evaluator binds finalized_at_utc to the exact next global raw event, measures a finalized block tail to that boundary, measures an open block tail to decision time, and separately measures current global source freshness. The audit recomputes both watermarks from the complete normalized population. A forged finalizer timestamp with a recomputed receipt hash is rejected at aggregate validation.

Verification: independent reread of evaluator lines 138-146, contract lines 139-175 and aggregate lines 262-268 confirms this correction. Regression source includes the exact A/B fixture, unchanged admission identity, a stopped-source negative case and forged-finalizer rejection. Implementing specialist reported 39 focused tests PASS and Ruff PASS for the amended source; this reviewer did not independently rerun that suite. The parent must retain the actual final integrated test receipt rather than treating this reported count as an independent test execution.

## Reviewed invariants

- Pair activity is grouped by contiguous raw symbol events; direction is separate current quality. BUY/SELL mixing does not reset activity, yet activity grants carry no hypothesis, risk or execution authority.
- Raw population identity, unique event count, aggregate ordering, symbol interruption and source hash are revalidated. Future or outside-window raw rows and mismatched coverage hashes cannot grant. Empty UNKNOWN coverage cannot become measured NO_RAW_ACTIVITY.
- Coverage COMPLETE is an explicit caller attestation bound to a ledger hash and window. Computing the hash alone does not prove the production ledger is complete; deployment, ledger provenance and the attestor remain runtime binding requirements.
- Policy identity, maximum source gap and admission TTL are explicit. No production values are inferred from fixture choices. Source gap suspends the same activity; only a cross-symbol raw event finalizes it.
- Admission lineage freezes at the first 300-second crossing, and later telemetry does not extend expiry. Current direction quality is computed over current block observations, separately from the frozen admission prefix.
- Prior receipts are revalidated. Changed admission prefix, activity identity or policy requires reconciliation; omission of a prior admitted activity from replay is rejected. Duplicate/reordered replay retains identity without inflating raw counts. Corrected cross-symbol backfill cannot silently preserve an incompatible grant.
- The adapter defaults to UNBOUND without explicit context, validates the complete audit before emitting observability, and rejects malformed receipts. Its output does not convert the new activity identifier into the legacy directional PairAdmissionGrant. Legacy grant consumers remain separate.

## Remaining milestone gates

The patch does not implement a durable ledger writer, authoritative completeness attestor, approved deployment/policy binding, or production restart/crash reconciliation run. JSON roundtrip or subprocess replay is useful local proof but does not establish storage transactionality, restart operation, or deduplication across real persisted scanner cohorts. S04 hypothesis/pressure authority, typed promotion into legacy consumers and all production/broker readiness remain outside this source-only result. Keep S03 PARTIAL and all execution-authority flags false.

## Reviewed byte identities

| Staged path | SHA-256 |
| --- | --- |
| contracts/strategy_5scr_pair_activity.py | a1b0e24f8f441a6db99e744b177b532466c601ad0bfe10d37234c7f76e10adb9 |
| analysis/strategy_5scr_pair_activity.py | eb90e3c54a24297928a1e8008600259ee9880871c1acc5e4f0d02ae748bc4ec0 |
| analysis/strategy_5scr_pair_activity_report.py | 2a251fb17864d605bb68dc0dfe55dde4cfd9056307b4dc1cbdf84c6680ae61c6 |
| tests/test_strategy_5scr_pair_activity.py | 914c2aaf057b93f6b049ae1aa6e1f68e56bc0d0b4df00f0b39ab87c2fd4da838 |
| tests/test_pair_activity_report_integration.py | 7fbb750f1aac230adcc7aebc803f38de02f6a719e70ea6d3d9349027ece2c015 |
