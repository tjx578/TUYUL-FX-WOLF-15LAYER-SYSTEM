# Dashboard, drift and analysis-admission integration

Local integration only. Production and owner-login runtime verdict: HOLD / NO-SHIP.

Base: freshly fetched origin/main `1837f4b7cbded620c35933af980e9abd166de39e`, including dashboard v2.1 (#421).
Original dirty main: `ec31631864204ca183079966d7834338f7a986cd`.
Recovery snapshot: `3647550ad4416f1316822045604e4240f9dea5b8`, protected by `codex/recovery-integration-20260907-220337`.
Integration branch: `codex/integration-owner-drift-admission-20260907`.

All 32 tracked modifications and 14 Git-visible untracked files were inventoried and SHA-256 hashed before isolated edits. Exact file copies, original index, staged/unstaged binary patches and status are retained at `C:/Users/INTEL/OneDrive/Documents/GitHub/wolf15-integration-recovery-20260907-220337`. A separate Git index produced the recovery commit; dirty main was never stashed, reset or switched. Snapshot blobs and archive bytes were verified. Ignored environment/dependency files were not transplanted.

The companion provenance JSON accounts for all 46 paths: 18 exact snapshot transplants, 4 integration resolutions, 16 upstream safety versions retained, 7 already identical upstream, and 1 unrelated D1 demo register excluded but preserved in recovery. An additional upstream Redis regression test was adapted to the strict lineage contract. Documentation in this integration directory is newly authored provenance.

## Conflict decisions

# Dashboard conflict resolution evidence

Integration baseline: origin/main 1837f4b7cbded620c35933af980e9abd166de39e (dashboard v2.1).
Source recovery snapshot: 3647550ad4416f1316822045604e4240f9dea5b8, parent ec31631864204ca183079966d7834338f7a986cd.

Conflicts were inspected as index stage 2 (upstream) versus stage 3 (recovery snapshot). The upstream versions were deliberately retained for the following paths; the earlier local safety objectives are already superseded by narrower v2.1 behavior:

| Path | Resolution rationale |
| --- | --- |
| dashboard/nextjs/.env.example | Retain viewer profile, BFF projections, no action PIN or owner control settings. |
| dashboard/nextjs/src/__tests__/middleware.auth-loop.test.ts | Retain root-only routing, JWT-shaped-cookie guard and authorization-header override assertions. Backend verification occurs in protected layout and route. |
| dashboard/nextjs/src/__tests__/proxy.containment.test.ts | Retain exact three-path allowlist, all mutation denial, viewer rejection and sanitized BFF errors tests. |
| dashboard/nextjs/src/app/api/auth/ws-ticket/route.ts | Retain unconditional 403; do not export raw HttpOnly bearer to browser JavaScript. |
| dashboard/nextjs/src/app/api/proxy/[...path]/route.ts | Retain GET-only, exact-path, validated scoped viewer, BFF-only, no redirects and limited response headers. |
| dashboard/nextjs/src/app/api/set-session/route.ts | Retain HS256 JWT structure, mandatory expiry, backend viewer validation, expiry-bounded HttpOnly SameSite cookie. |
| dashboard/nextjs/src/app/api/status/route.ts | Retain 403 retired direct-core operator diagnostics. |
| dashboard/nextjs/src/app/login/page.tsx | Retain working scoped-viewer JWT form and verified-session redirect over obsolete owner setup placeholder. |
| dashboard/nextjs/src/lib/server/readOnlyProxyPolicy.ts | Retain exact three paths and traversal rejection; do not restore broad prefix matching. |
| dashboard/nextjs/src/lib/serverAuth.ts | Retain JWT auth method, viewer role and read:dashboard scope; reject generic arbitrary-role sessions. |
| dashboard/nextjs/src/middleware.ts | Retain root-only UI, exact public routes, cookie-authoritative proxy header and cookie stripping; Node route/layout validates session. |
| services/dashboard_bff/auth.py | Retain ViewerBearer OpenAPI scheme and independent JWT viewer role plus read:dashboard scope verification. |
| tests/unit/test_dashboard_bff_containment.py | Retain rejection of owner/operator/API-key/unscoped sessions and ViewerBearer schema tests. |

queryClient.ts: preserved local correction that a 401 represents missing/invalid/expired browser session, and replaced adjacent stale claim that owner mode has no JWT with precise legacy synthetic-owner guard wording. No behavior change.
lib/auth.ts: no delta against upstream during this review. Legacy WS and token helper comments remain baseline; viewer route guard and retired WS route prevent their old control surface from becoming available. No new credential or execution capability.

Current login is a scoped VIEWER JWT flow, not arbitrary owner-role access. Owner-role JWT acceptance is deliberately rejected by v2.1 tests. Owner-login runtime remains HOLD/NOT_EXECUTED; do not interpret local unit success as production login success.

Frontend dependency reuse: existing dirty-main node_modules was referenced through a junction in the isolated worktree; temporary test config places cacheDir inside the isolated worktree and disables Vitest cache. No install or build. Unit tests use mocked requests. Config and junction are test scaffolding, not integration source.

# Drift integration resolution receipt

Worktree: `C:/w15-integration-20260907`.
Base: origin/main `1837f4b7cbded620c35933af980e9abd166de39e`.
Dirty snapshot: `3647550ad4416f1316822045604e4240f9dea5b8`, parent `ec31631864204ca183079966d7834338f7a986cd`.

## Resolution provenance

- api/redis_context_reader.py and context/live_context_bus.py: resolved conflicting comparison methods in favor of dirty snapshot shared compare_closed_h1 delegation, preserving surrounding origin/main content. LiveContextBus obsolete pip import removed as present in the transplanted change.
- context/price_drift.py: new dirty-snapshot comparator retained with strict explicit independent lineages, symbol/timeframe/provider symbol, complete flag, exactly aligned UTC hour, finite positive prices, post-close fresh receipt, rejection of stale/future/ambiguous evidence, and known pip multiplier. Integration-derived compatibility additions return max_drift_pips and aligned rest_close_time/ws_close_time.
- ingest/h1_refresh_scheduler.py and tests/test_h1_refresh.py: origin/main already contains no state action for incomparable evidence. Resolved to upstream behavior and restored exact HEAD file bytes; no staged diff remains for these two paths.
- tests/test_price_drift.py: dirty-snapshot expanded safety tests retained, adding assertions for timestamp/threshold compatibility fields.
- tests/test_redis_context_reader_price_drift.py: integration-derived update to existing upstream regression fixture adds explicit valid REST lineage and fresh timestamps. It asserts missing WS, comparable=False, actionable=False, no drift, and approximate 91.5-pip observational live gap.

An introduced Windows text-decoding issue was detected by staged diff inspection and corrected before final checks. Final API/context changes contain intended method/import changes only; scheduler/H1 test files were restored from exact HEAD bytes.

## Final executed checks

Shell: PowerShell. Cwd for every command: `C:/w15-integration-20260907`.

```powershell
& 'C:/Users/INTEL/OneDrive/Documents/GitHub/TUYUL-FX-WOLF-15LAYER-SYSTEM/.venv/Scripts/python.exe' -m pytest tests/test_price_drift.py tests/test_h1_refresh.py tests/test_redis_context_reader_price_drift.py -q -o addopts= -p no:cacheprovider
```

Result: **73 passed in 4.82s**, successful exit. All external fetches used by focused tests were mocked; no live provider evidence is implied. Existing pytest-asyncio warning: asyncio_default_fixture_loop_scope unset.

```powershell
& 'C:/Users/INTEL/OneDrive/Documents/GitHub/TUYUL-FX-WOLF-15LAYER-SYSTEM/.venv/Scripts/python.exe' -m ruff check api/redis_context_reader.py context/live_context_bus.py context/price_drift.py ingest/h1_refresh_scheduler.py tests/test_h1_refresh.py tests/test_price_drift.py tests/test_redis_context_reader_price_drift.py
```

Result: **All checks passed!**, successful exit. Existing configuration warning: UP038 has been removed and ignoring it has no effect.

```powershell
git diff --cached --check -- api/redis_context_reader.py context/live_context_bus.py context/price_drift.py ingest/h1_refresh_scheduler.py tests/test_h1_refresh.py tests/test_price_drift.py tests/test_redis_context_reader_price_drift.py
```

Result: no output, exit 0. Final tool command group exited 0. No standalone raw log files were created; exact console output remains in tool result chunk `5eee89` for this task. Prior focused final run also passed 73 tests in 4.35s before comment-encoding repair; the later 4.82s run is authoritative for the final scoped bytes.

## Limits

Runtime delivery of independently preserved REST/WS closed-H1 evidence: NOT_MEASURED / HOLD. Redis deduplication may prevent preserving both lineages, in which case comparison remains non-actionable and cannot degrade or recover symbol state. No producer/storage changes were introduced to manufacture comparability.

Deployment, live providers, broker execution, package installation, credential creation, commit, push, merge: NOT_EXECUTED by this subtask.

## Admission and migration verification

The admission contract pins final_direction=WAIT and execution/risk/valid-for-execution to false. Mature advisory remains derived shadow analysis and does not grant canonical PairAdmission. Worker startup defaults disabled and denies execution-plane activation. Database authority CHECK definitions and immutable-record trigger checks remain present. Source and mocked local tests do not establish production identity, grants, or network containment.

Admission/source-guard/pipeline/execution-plane suite: 139 cases passed (pytest quiet output); log `admission-tests.log` in recovery. Command: existing primary `.venv/Scripts/python.exe -m pytest tests/test_strategy_5scr_analysis_admission.py tests/test_strategy_5scr_analysis_admission_worker.py tests/test_signal_decision_source_guard.py tests/test_signal_pressure_state_observability.py tests/test_pair_admission_runtime_selection.py tests/test_execution_plane_fail_closed.py -q --tb=short`, cwd integration worktree.

Cross-sink suite: 84 passed; `cross-sink.log` and `cross-sink.xml`. Command: same Python, `-m pytest tests/test_strategy_5scr_pair_admission.py tests/test_strategy_5scr_risk_reservation.py tests/test_mt5_risk_command_producer.py tests/unit/test_trade_outbox_worker.py tests/test_pressure_outbox_pipeline_integration.py tests/test_pressure_outbox_railway_deployment.py tests/test_observer_export_outbox.py tests/test_5scr_lifecycle_v2_runtime.py --override-ini addopts= --tb=short --junitxml=<recovery>/cross-sink.xml`.

Static AST migration graph: 34 unique revisions, no missing parents, sole head 20260826_01 descending from 20260822_01. No migration was applied.

## Remaining gates

- HOLD: runtime owner login. v2.1 deliberately accepts scoped viewer JWTs and rejects owner/operator roles; older broad owner access is not reintroduced.
- HOLD / NOT_MEASURED: live REST/WS lineage retention and real drift behavior. Missing or deduplicated lineage stays non-actionable.
- HOLD / NOT_EXECUTED: actual PostgreSQL migration, schema/grants/trigger enforcement and durable worker integration. Shadow worker remains disabled by default.
- NOT_EXECUTED: production build, Docker, browser E2E/login, remote CI, production health/auth checks, live provider checks, broker reconciliation and execution.
- NOT_MEASURED: performance and live latency. Comparator scanning is bounded by the 250-candle adapter request; no benchmark claim.
- NOT_EXECUTED: push, merge, deploy, credentials creation and execution activation.

No unit-test pass authorizes deployment or trading. Local dependency reuse is not a clean dependency installation or production artifact validation.

## Dashboard final checks


- Full frontend unit suite: 38 test files, 380 tests passed; exit code 0; duration 130.79 s. Node v24.19.0; reused modules, not a fresh installation. Command: node node_modules/vitest/vitest.mjs run --config vitest.integration.config.ts. Temporary config preserved in this evidence folder and junction removed afterward.
- Focused dashboard BFF containment: 13 tests passed; exit code 0. Command: python -B -m pytest tests/unit/test_dashboard_bff_containment.py -q -o cache_dir=C:/w15-integration-20260907/.pytest_cache_dashboard.
- Primary frontend versions match integration lockfile: next 15.5.14, vitest 3.2.4, typescript 5.9.3, react 19.2.4, vite 7.3.1. This is a targeted version check, not a clean-install integrity attestation.
- NOT_EXECUTED: artifact build, clean dependency install, browser/E2E login, deployed runtime, production authentication, credential creation, deployment, broker/execution calls.
- HOLD: operational owner login and release readiness; arbitrary owner-role access is not admitted by the viewer contract.


Final source delta: 23 paths plus two integration provenance documents. All 18 three-way conflicts resolved. No execution configuration enabled.
