# Independent merge resolution review

Verdict: no blocking finding identified in the bounded staged-source review. The resolution preserves the API-only ownership guard and the incoming read-only startup containment. Final integration tests are owned by the parent; this review does not claim their result.

Merge subjects: local HEAD `c715b3a8d7949b2e3ca3476cfc822cad4748461b` and incoming MERGE_HEAD `e3a0d8c83d5d8de60645a1d4f7c00f66fe9d5941`. There were no unmerged index entries at review time. Compared staged changes independently against both parents. The four reviewed worktree files matched their staged bytes after explicit CRLF/LF normalization.

## Required behavior preserved

- `api/app_factory.py:115` calls the API-only ownership assertion as the first lifespan statement. A truthy WOLF15_EMBED_ORCHESTRATOR fails before lifespan consumer imports or connections, regardless of read-only mode. The obsolete embedded StateManager/thread creation block and threading import are absent.
- `api/app_factory.py:116-120` preserves incoming read-only profile detection and release-environment validation before Redis/outbox imports and startup operations. Read-only startup skips PG initialization (line 152), outbox construction/task creation (line 158), relay start (line 171), peer-health start (line 210), and candle-aggregator start (line 224).
- Startup attestation remains active in read-only mode at line 232. Its orchestrator=false entry is justified by the unconditional ownership guard and removal of the creation path. It describes this API worker's startup, not independent proof about any external orchestrator process. The attestor independently rejects any enabled background entry and non-normalized release flags.
- Readiness retains bootstrap-before-router-import handling: missing/failed router boot returns 503 with bounded reason codes at lines 568-576; no bootstrap exception value is exposed in this response. Normal readiness still gates freshness plus producer, engine and orchestrator heartbeats, returning 503 when any required condition fails. Fallback readiness also remains 503.

## Test resolution review

The owner-dashboard test now patches standard-library threading.Thread, replacing the removed app_factory.threading alias. It continues to assert that no thread was constructed, no PG initialization/candle start was awaited, and no outbox/relay/peer constructor ran; it checks all emitted background flags false. This adapts the patch target without dropping the containment assertions.

The migration-ownership test keeps the incoming behavior-based mocked subprocess invocation, verifies Alembic upgrade/head arguments and capture_output=True, and retains the local source assertion for redact_sensitive_log_text. The migration runner still passes stdout/stderr through that redactor. No migration was executed by this review.

Existing API-only tests still exercise truthy embed flags and intercept lifespan consumer imports to ensure rejection happens first. Existing bootstrap tests retain 503, heartbeat and fallback exception-disclosure cases. Test sources were reviewed only; parent must retain the new combined execution receipt for the actual merge result.

## Boundaries

This review is limited to the resolved API lifespan/readiness and requested test adaptations. It does not establish owner-login browser acceptance, deployment identity, database behavior, production read-only guarantees outside startup, or broker readiness. No D-drive file was written and no test process/provider operation was executed by this reviewer. No review of incoming Codex settings or deployment configuration is implied.

## Reviewed staged identities

| Path | Git blob | SHA-256 of staged bytes |
| --- | --- | --- |
| api/app_factory.py | f3c763b7465e655eafb2ba028fc4a332df88b161 | 134be41989b84979e71146def6148ad4e4a18bfec70644bf5a67df486c37d8d0 |
| api/owner_dashboard_release.py | 70635453d0eb30b5847dbb3a63c697e411e79cee | dc8f0ec73a11f4683165a2190d580e84bf05c22a00a939329638c0299358de5f |
| tests/test_startup_migration_ownership.py | fb59506b983312e36e7411348340a33674ff7308 | 8dd109976e793a81b23139f923a1dabc558941a2b282935442279db7c4246463 |
| tests/unit/test_owner_dashboard_release.py | acfb468e8f12f96c7c1650a22eb9a11769187385 | ec2ed4fc72da315d87dbbdb9ba866900bddde69465266640c98db78d858c9eb2 |
