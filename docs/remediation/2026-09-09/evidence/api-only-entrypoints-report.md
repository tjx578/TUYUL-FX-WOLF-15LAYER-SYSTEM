# C02 bounded API entrypoint containment

Implemented in root worktree based on `773150952311db3dbf5188f36536b7837d8ec296`; changes uncommitted at test time. Ownership restricted to `deploy/railway/start_api.sh`, `deploy/railway/start_api_consolidated.sh`, `railway.toml` and new `tests/test_api_only_entrypoints.py`. Root separately changed `api/app_factory.py`.

The canonical API shell now trims leading/trailing whitespace and case-normalizes the legacy `WOLF15_EMBED_ORCHESTRATOR` flag before rejecting `1`, `true`, `yes` and `on`. It exits before launching Gunicorn. The deprecated consolidated locator delegates with `exec` to this canonical entrypoint and no longer forces embedding. Root Railway TOML selects the canonical API entrypoint. Pattern was grounded in prior exact source `711e926a`, with whitespace/case normalization strengthened to match Python for tested ASCII values.

**31 tests passed in 9.53 seconds, zero failed/skipped**:

- Twelve behavioral shell negative cases: six truthy encodings across both entrypoints; exit1 and zero recorded launches.
- Twelve shell positive cases: unset/false/mixed-case false/0/off/empty across both entrypoints; exactly one recorded API Gunicorn invocation, expected port8765, workers3 and keepalive75 preserved.
- One actual TOML parse assertion for API-only start command.
- Six async application-lifespan negative cases: truthy switch raises before Redis or trade-outbox consumer imports; no lifespan entry.

Shell runtime verified: `C:/Program Files/Git/bin/bash.exe`, GNU Bash5.2.37. Tests deliberately do not use Windows system32 WSL launcher. A temporary recording executable named `gunicorn` receives arguments; no real Gunicorn, API service, Redis, database, orchestrator or broker starts. Child environment retains only shell essentials and synthetic test fields.

`python -m ruff check tests/test_api_only_entrypoints.py` passed. `git diff --check` on owned paths passed. Both shell entrypoints have LF source bytes. XML receipt: `api-only-entrypoints-tests.xml`.

SHA256 at test/review completion:

| File | SHA256 |
|---|---|
| deploy/railway/start_api.sh | 138c94ce35694f44bbfc9ea9a2f31c2c971804e50aa5c60ca3bfe01726e2e14b |
| deploy/railway/start_api_consolidated.sh | 6b08ec70efb1aad9d8537098e9a8a062893751fa8421f14308d203323a9705cd |
| railway.toml | d6418dafc4723fa81e83c5d960e583a06b971d283fdf9b9a765c08c01bd718d7 |
| tests/test_api_only_entrypoints.py | 137317c4d49c0ad62c6a774892c605dc9dc585d7c4065c7bafa5c851fcde115b |
| api/app_factory.py (root-owned dependency) | db451576938b657a48b809c91b79514b73244482fc0647a501f94fbe8ecc651c |

**C02 remains PARTIAL.** These tests remove a local path that spawns embedded orchestration per API worker. Actual deployed service UUIDs/config/entrypoints, one healthy dedicated owner, legacy sink/dual-plane isolation and process-level migration/ownership parity are not established. C06 mandatory task-supervisor behavior remains a separate gap. No commit, push, provider change or broker action was performed by this subtask.
