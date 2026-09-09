# Final source review and negative control

Final gate control completed 2026-09-08T21:13:11.767287Z on Windows with the exact API Python environment at sibling `s01-s03-staging/api-exact-venv/Scripts/python.exe`.

The final acceptance runner collected 45 cases and its JUnit XML recorded 45 skipped, zero failures, zero errors. Pytest returned zero for skipped cases, but the strict source runner returned 1 and wrote `accepted=false`. This is a successful NEGATIVE CONTROL of refusal, not a PostgreSQL PASS. All bound source hashes remained unchanged; the reviewed runner now hashes itself and the raw-admission helper and compares exact collected versus JUnit test identities.

Environment inheritance was restricted to Windows process plumbing. `WOLF15_RUN_POSTGRES_INTEGRATION=0` and `WOLF15_LOAD_DOTENV=false` were explicit; all database connection variables, opt-ins and real credentials were absent from the runner environment. No test fixture opened PostgreSQL. No capacity recheck, server initialization/start, Docker/WSL mutation or production access occurred.

`negative-control-v2-20260908T211311Z` preserves the final wrapper receipt, runner receipt, XML and logs. `negative-control-v1-20260908T211141Z` preserves the distinct earlier gate control. The repository's ignored `artifacts/pair-activity-runtime` contains the latest NEGATIVE CONTROL and must not be presented as positive acceptance.

Immediately before the final two-file gate adjustment, offline Alembic resolved the single head `20260909_01` and rendered `20260822_01:20260909_01` SQL with exit code zero. Those migration/schema files were unchanged in the subsequent final source hashes, so SQL rendering was not repeated. Logs are `final-migration-heads.log` and `final-activity-migration-offline-sql.log`. Offline SQL rendering is not PostgreSQL SQL execution.

The earlier fixture findings are addressed in the reviewed final fixture: it refuses URI query/fragment overrides before connecting, checks the actual server is loopback, validates database and disposable markers, and requires the migrated ledger table rather than creating it. Runtime behavior remains unproved until these 45 cases execute without skips on the explicit disposable PostgreSQL target. Linux runtime and full remote CI acceptance remain separate unresolved gates.
