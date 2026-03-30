# MEGA AUDIT REPORT — TUYUL FX Wolf-15 Layer System

**Date:** 2026-03-26  
**Audited by:** GitHub Copilot Coding Agent  
**Branch:** copilot/remove-debug-files  
**Scope:** Full end-to-end repository assessment — code debt, bugs, architecture gaps, CI failures  

---

## Executive Summary

The repository is a sophisticated multi-service trading system with solid architectural boundaries,
but has accumulated significant **code debt at the root level** and has **two active CI failures**
that block merges to `main`. The dashboard (Next.js) builds and passes CI. The Python test suite
fails due to one fixable bug. Ruff formatting is broken across 96 files.

**CI State on `main` (run #2339):**

| Job | Status | Root Cause |
| ----- | -------- | ------------ |

| Ruff lint | ❌ FAIL | 96 files need `ruff format` |
| Python tests | ❌ FAIL | `FINNHUB_API_KEY` singleton bug in test fixture |
| Dashboard build | ✅ PASS | — |

**This PR fixes all three items.**

---

## PHASE 0: Root-Level Code Debt — CRITICAL

### Finding 0.1 — 40+ Debug / Scratch Files Committed to `main`

*Severity: HIGH (code debt, pollutes repo, confuses contributors)**

The following files were committed directly to the repo root. They are debug outputs,
probe scripts, and temporary CI artifacts that should never have been committed:

| Category | Files |
| ---------- | ------- |

| PR004 debug txt | `_pr004_collect.txt`, `_pr004_cors.txt`, `_pr004_cors2.txt`, `_pr004_existing.txt`, `_pr004_gov.txt`, `_pr004_gov2.txt`, `_pr004_gov3.txt`, `_pr004_out2.txt`, `_pr004_out3.txt`, `_pr004_static.txt`, `_pr004_test_out.txt` |
| Test output txt | `_test_dash_err.txt`, `_test_full_out.txt`, `_test_full_out2.txt`, `_test_full_out3.txt`, `_test_iter.txt`, `_test_iter2.txt`, `_test_iter4.txt`, `_test_monitor.txt`, `_test_monitor2.txt`, `_test_pr004_wg.txt`, `_test_run_current.txt`, `_suite_out.txt` |
| PR artifacts txt | `pr004_existing_tests.txt`, `pr004_full.txt`, `pr004_ruff.txt`, `pr004_ruff2.txt`, `pr004_tsc.txt`, `pr004_tsc2.txt`, `pr004_tsc3.txt`, `pr004_wg2.txt`, `pr004_wg_result.txt`, `contract_test_out.txt` |
| TSC artifacts | `tsc_pr005.txt`, `tsc_pr006.txt`, `tsc_pr006b.txt` |
| Debug scripts | `_run_suite.py`, `_check_endpoint.py`, `_check_quotes.py`, `redis_diagnostic.py`, `warmup_inject.py` |

**Fix applied in this PR:** All 40 files removed via `git rm`. `.gitignore` updated with
comprehensive patterns to prevent recurrence (e.g., `_pr004_*.txt`, `_test_*.txt`, `pr004_*.txt`, `tsc_pr*.txt`).

---

## PHASE 1: CI Failures — CRITICAL

### Finding 1.1 — Ruff Format Failure (96 files)

**Severity: CRITICAL (blocks CI on every push)**  
**File:** 96 Python source files across the codebase  
**CI Job:** `Ruff lint & format` → `Ruff format check (hard fail)`

**Root Cause:** `ruff format` was never run after a batch of commits. The format check
(`ruff format --check`) is a hard-fail gate in CI, blocking all merges.

**Fix applied in this PR:** `ruff format . --config pyproject.toml` applied. All 96 files reformatted.
Ruff lint still passes (`ruff check` had zero violations).

### Finding 1.2 — Python Test Failure: `FINNHUB_API_KEY` Singleton Bug

**Severity: CRITICAL (blocks CI tests)**  
**File:** `tests/test_finnhub_ws_reconnect.py:97`  
**Error:**
``

ERROR tests/test_finnhub_ws_reconnect.py::TestLeaderElection::test_acquire_leader_lock_success
RuntimeError: No FINNHUB_API_KEY configured — cannot start WebSocket client.
``

**Root Cause (detailed):**

1. `ingest/finnhub_key_manager.py` exports a module-level singleton:

   ```python
   # line 290
   finnhub_keys = FinnhubKeyManager()  # reads env vars at import time
   ```

2. `FinnhubKeyManager.__init__` calls `_load_keys()` which reads `os.getenv("FINNHUB_API_KEY")`.
   In CI, no `FINNHUB_API_KEY` is set → `_keys = []`.
3. The test fixture used `patch.dict("os.environ", {"FINNHUB_API_KEY": "test-token"})` —
   but the singleton had already been loaded **at module import time** (before any test ran),
   so patching the env var after the fact has no effect on `finnhub_keys._keys`.
4. `FinnhubWebSocket.__init__` calls `self._token = self._key_manager.current_key()`
   which returns `""` → raises `RuntimeError`.

**Fix applied in this PR:** Changed the `ws_client` fixture to use `patch.object(finnhub_keys, "current_key", return_value="test-token")` which patches the singleton's method directly, bypassing the stale singleton state:

```python
# Before (broken):
with patch.dict("os.environ", {"FINNHUB_API_KEY": "test-token"}):
    client = FinnhubWebSocket(...)

# After (fixed):
with patch.object(finnhub_keys, "current_key", return_value="test-token"):
    client = FinnhubWebSocket(...)
```

---

## PHASE 2: Architecture Issues — MEDIUM / LOW

### Finding 2.1 — Dual `engine/` and `engines/` Directories

*Severity: MEDIUM (naming confusion, unclear ownership)**

| Directory | Contents | Role |
| ----------- | ---------- | ------ |

| `engine/` | `trq_engine.py`, `trq_redis_bridge.py` | Zone A micro-wave engine (M1/M5/M15) |

| `engines/` | 18 files: `bayesian_update_engine.py`, `correlation_risk_engine.py`, ML models, etc. | Extended analytical engines used by pipeline |

Both directories are legitimate and actively used — they are NOT dead code. However, the naming is confusing for contributors. The architecture comment says "Zone A (M1/M5/M15 micro-wave, engine/)" but `engines/` contains the extended engine suite (Bayesian, Monte Carlo, Quantum, etc.) used by the constitutional pipeline.

**Recommendation (not fixed here — breaking change):** Rename `engines/` to `analysis/engines/` or document the distinction clearly.

### Finding 2.2 — Root-Level `src/` Directory (Stale Dashboard Copy)

**Severity: MEDIUM (code debt, confusion)**  
**Path:** `/src/` (root)

The root `src/` directory contains 54 files that appear to be a stale/older copy of the dashboard
source. The active dashboard lives in `dashboard/nextjs/src/` (402 files). Comparison confirms:

- `dashboard/nextjs/src/` has 348 more files
- Files that exist in both differ in content (`layout.tsx`, `globals.css`, etc.)
- `src/` is never referenced in any Python import or build pipeline

The root-level `next.config.ts`, `package.json`, `tsconfig.json`, and `postcss.config.js` are
similarly leftover from before the dashboard was moved to `dashboard/nextjs/`.

**Recommendation:** Remove `src/`, `next.config.ts`, `postcss.config.js` from root in a
dedicated cleanup PR (verify no CI jobs reference them first).

### Finding 2.3 — `ingest_service.py` Monolith (1,122 lines at root)

*Severity: MEDIUM (violates module boundary principle)**

`ingest_service.py` (1,122 lines) lives at the repo root but contains the full Finnhub ingest
service implementation. The modular implementation should live in `services/ingest/`.

The actual worker entrypoint `services/ingest/ingest_worker.py` imports from `ingest_service.py`,
so this is a dependency coupling issue. The code works, but violates the stated goal of
keeping root-level files as thin entry-points.

**Recommendation:** Refactor into `ingest/` package modules (already partially done — `ingest/`
directory contains `finnhub_ws.py`, `finnhub_candles.py`, `normalizer.py`, etc.).

### Finding 2.4 — `main.py` Slightly Over Target Size

**Severity: LOW**  
**Actual:** 369 lines (target: ~280 lines)

`main.py` is described as a "slim ~280 line orchestrator" but is 369 lines. The excess is
from `RUN_MODE` routing logic (api-only, ingest-only, engine-only, all modes). This is
acceptable but can be trimmed by moving mode-dispatch logic to a `startup/run_mode.py` module.

### Finding 2.5 — Two API Entry Points (`app.py` + `api_server.py`)

*Severity: LOW (intentional design, but confusing)**

- `app.py` — ASGI shim (`from api_server import app`) for `gunicorn app:app`
- `api_server.py` — Full FastAPI bootstrap (`python api_server.py`)

Both share the same `FastAPI` instance via `api/app_factory.py`. This is documented in
`app.py`'s docstring. Not a bug, but can confuse new contributors.

---

## PHASE 3: Ingest Service Analysis — PASS with NOTES

### Finding 3.1 — Ingest Data Flow (✅ Correct)

Traced data flow from `services/ingest/ingest_worker.py` → `ingest_service.py`:

1. `FinnhubWebSocket` subscribes to Finnhub WS ticks
2. Ticks → `CandleBuilder` (M1 → M5 → M15 → H1 aggregation chain)
3. Completed candles → `core.candle_bridge_fix.publish_candle_sync` → Redis `wolf15:candle_history:{SYM}:{TF}` (HASH)
4. M15 candles → `MicroCandleChain` → Redis (Zone A engine)

**`CONTEXT_MODE` env var handling (✅ Correct):** Ingest service respects `CONTEXT_MODE` to
switch between Redis warmup (production) and Finnhub REST warmup (cold-start).

### Finding 3.2 — Redis Key Consistency (✅ Correct)

`state/redis_keys.py` is a backward-compatibility shim re-exporting from `core/redis_keys.py`.
All canonical keys are in `core/redis_keys.py`. Publishers (`ingest_service.py`) and consumers
(`startup/candle_seeding.py`, `context/redis_consumer.py`) use matching key patterns.

Warmup consumer reads `wolf15:candle:{sym}:{tf}` HASH via `"data"` field (JSON string),
consistent with `RedisContextBridge.write_candle` output.

### Finding 3.3 — Finnhub WS Singleton Key Bug (✅ Fixed in CI Fix Above)

See Finding 1.2 for root cause. The `finnhub_keys` singleton now correctly initializes
in production (env vars set) but the test fixture was broken. Fixed.

---

## PHASE 4: Engine / Analysis Pipeline — PASS

### Finding 4.1 — Pipeline Layers L1–L11 (✅ Correct)

All layers present in `analysis/layers/`:
`L1_context.py`, `L2_mta.py`, `L3_technical.py`, `L4_session_scoring.py`,
`L5_psychology.py`, `L6_risk.py`, `L7_probability.py`, `L8_tii_integrity.py`,
`L9_smc.py`, `L10_position_sizing.py`, `L11_rr.py`

Each follows the class-based pattern with `analyze(candles, ...)` method. Zone annotations
present in docstrings. No side-effects in analysis layer code detected.

### Finding 4.2 — Pipeline Orchestrator `unified_pipeline.py` (✅ Correct)

Located at `analysis/orchestrators/unified_pipeline.py`. Runs all 15 layers in 8 phases.
This is the primary analytical entrypoint (not `main.py`).

---

## PHASE 5: Constitution (L12 Gate) — PASS

### Finding 5.1 — L12 Gate Architecture (✅ Correct)

- `constitution/gatekeeper.py` — 9-gate sequential firewall
- `constitution/verdict_engine.py` — V1/V2 verdict computation
- `schemas/validator.py` — Runtime schema validation enforcing no account state in L12 signals
- Verdict values: `EXECUTE`, `EXECUTE_REDUCED_RISK`, `HOLD`, `NO_TRADE`, `ABORT`
- Score thresholds: wolf ≥ 0.70, tii ≥ 0.90, frpc ≥ 0.93

### Finding 5.2 — L12 Signal Integrity (✅ Correct)

`schemas/signal_contract.py` and `schemas/l12_schema.json` define the signal contract.
Constitutional rule verified: L12 signals do **not** contain `balance`, `equity`, or `margin`
fields. `schemas/validator.py` enforces this at runtime via `jsonschema`.

---

## PHASE 6: Execution — PASS

### Finding 6.1 — State Machine FSM (✅ Correct)

`execution/state_machine.py`:

- Enum FSM: `IDLE → PENDING_ACTIVE → FILLED/CANCELLED`
- Singleton, thread-safe via `threading.Lock`
- Replay-safe: terminal→same-terminal returns `REPLAY_TERMINAL_NOOP`
- No strategy logic in execution — constitutional rule respected

---

## PHASE 7: API Service — PASS with NOTES

### Finding 7.1 — CORS Configuration (✅ Correct)

`api/app_factory.py` reads `CORS_ORIGINS` env var plus auto-derives Vercel preview origins.
Railway deployments must set `CORS_ORIGINS` to include the dashboard's Railway domain.
The configuration supports wildcard `*.railway.app` via `CORS_ORIGIN_REGEX`.

**Note:** If dashboard shows CORS errors in production, check that `CORS_ORIGINS` env var
on the API Railway service includes the exact dashboard domain (e.g. `https://wolf15-dashboard.up.railway.app`).

### Finding 7.2 — Router Registry (✅ Correct)

`api/router_registry.py` uses a declarative `RouterEntry` dataclass list. All routers are
mounted by `api/app_factory.py`. No orphaned routers detected.

### Finding 7.3 — Auth Middleware (✅ Correct)

`api/middleware/auth_middleware.py` uses `verify_api_key` dependency for service-to-service
auth. JWT via `PyJWT` for user-facing endpoints. Dashboard uses owner-mode auth (see Phase 8).

---

## PHASE 8: Dashboard — PASS (CI builds successfully)

### Finding 8.1 — Dashboard CI Build (✅ PASS)

Dashboard CI job `Dashboard build (Next.js)` passes consistently (CI run #2339). The dashboard
compiles and builds without errors.

### Finding 8.2 — API URL Configuration (✅ Correct)

`dashboard/nextjs/next.config.js` correctly resolves API base from env vars in priority order:

1. `INTERNAL_API_URL` (Railway server-side)
2. `NEXT_PUBLIC_API_BASE_URL`
3. `API_BASE_URL`
4. `API_DOMAIN`

The `/api/:path*` rewrite routes all dashboard API calls to the backend.

### Finding 8.3 — WebSocket URL Configuration (⚠️ Requires Production Attention)

`NEXT_PUBLIC_WS_BASE_URL` must be set to the Railway backend WebSocket origin
(e.g., `wss://wolf15-api.up.railway.app`). If unset in production, WS connections
fail silently. The `next.config.js` validates this and throws for protected deployments.

**Action required:** Verify `NEXT_PUBLIC_WS_BASE_URL` is set in the dashboard Railway service variables.

### Finding 8.4 — Stale Root-Level Next.js Config Files (MEDIUM)

The following files at the repo root are leftovers from before the dashboard was moved to `dashboard/nextjs/`:

- `next.config.ts` (a bare-bones stub, 228 bytes — does nothing)
- `package.json` (references old dependencies like `next: ^15.0.0`)
- `tsconfig.json` (bare TypeScript config)
- `postcss.config.js` (bare PostCSS config)

These are NOT used by the actual dashboard build (which uses `dashboard/nextjs/next.config.js`).
They can confuse IDEs and contributors. **Recommend removing in a follow-up PR.**

### Finding 8.5 — Root `src/` Directory (MEDIUM — Stale Copy)

See Finding 2.2. The `src/` directory at root is a stale copy of older dashboard code.
It is not referenced by any active build or service. Remove in a follow-up PR.

---

## PHASE 9: Inter-Service Communication — PASS

### Finding 9.1 — Redis Streams Key Registry (✅ Correct)

- Canonical keys: `core/redis_keys.py` (re-exported via `state/redis_keys.py` for backward compat)
- Streams: `infrastructure/redis/stream_publisher.py`, `stream_consumer.py`
- Three priority tiers: CRITICAL/NORMAL/LOW
- Consumer groups: `state/consumer_groups.py`

Publisher and consumer key names match. No key mismatch detected.

### Finding 9.2 — Redis Pub/Sub vs Streams (✅ Correct Design)

Pub/Sub (`infrastructure/redis/pubsub_manager.py`) is used only for ephemeral data
(heartbeats, cache invalidation). Critical data uses Streams (`XADD`/`XREADGROUP` with `XACK`).
This correctly prevents data loss during Redis disconnect.

---

## PHASE 10: Risk & Journal — PASS

### Finding 10.1 — Risk Module (✅ Correct)

`risk/prop_firm.py` implements `check(account_state, trade_risk) → {allowed, code, severity}`.
Constitutional boundary respected: risk module receives account state from dashboard,
never computes market direction.

### Finding 10.2 — Journal (✅ Correct)

`journal/journal_writer.py` — append-only  
`journal/audit_trail.py` — hash-chained JSONL + Postgres  
`journal/builders.py` — J1/J2 entry builders  
Constitutional rule verified: journal is write-only (no decision authority).

---

## PHASE 11: Deployment & Configuration — PASS with NOTES

### Finding 11.1 — Railway Start Commands (✅ Correct)

All `railway-*.toml` files point to scripts in `deploy/railway/`:

| Service | Start Script |

| --------- | ------------- |
| API | `deploy/railway/start_api.sh` |
| Engine | `deploy/railway/start_engine.sh` |
| Ingest | `deploy/railway/start_ingest.sh` |
| Orchestrator | `deploy/railway/start_orchestrator.sh` |
| Migrator | `deploy/railway/start_migrator.sh` |
| Allocation | `deploy/railway/start_allocation.sh` |
| Execution | `deploy/railway/start_execution.sh` |
| Workers | `deploy/railway/start_worker.sh <module>` |

### Finding 11.2 — Dockerfile (✅ Correct)

Multi-stage build with Python 3.11. All services share one `Dockerfile`.

### Finding 11.3 — Environment Variables (⚠️ Review Required)

`.env.example` documents all required env vars. Critical ones for production:

- `FINNHUB_API_KEY` — **Required** for ingest service (no fallback in production)
- `REDIS_URL` — Required for all services
- `DATABASE_URL` — Required for API + migrator
- `CORS_ORIGINS` — Required for dashboard CORS to work
- `NEXT_PUBLIC_WS_BASE_URL` — Required for dashboard WebSocket connections
- `DASHBOARD_JWT_SECRET` / `JWT_SECRET` — Required for auth

---

## Summary: Findings by Severity

| Severity | Count | Fixed in this PR? |

| ---------- | ------- | ------------------- |
| CRITICAL | 2 | ✅ Yes (ruff format, test fixture bug) |
| HIGH | 1 | ✅ Yes (40+ debug files removed) |
| MEDIUM | 4 | ⚠️ Documented; separate PRs recommended |
| LOW | 2 | ⚠️ Documented |

### MEDIUM Findings (require follow-up PRs)

1. **`src/` root directory** — stale dashboard copy, 54 files, not referenced anywhere. Remove.
2. **Root `next.config.ts`, `package.json`, `tsconfig.json`, `postcss.config.js`** — stale Next.js files. Remove.
3. **`ingest_service.py` monolith** — 1,122 lines at root, should be modularized into `ingest/`.
4. **`engine/` vs `engines/` naming** — confusing but both active; document or rename.

### LOW Findings (no action required now)

1. `main.py` slightly over target size (369 vs 280 lines)
2. `app.py` + `api_server.py` dual entry points (intentional, documented)

---

## Constitutional Compliance Verification

| Rule | Status |

| ------ | -------- |
| No execution authority in analysis modules | ✅ PASS |
| Dashboard/EA cannot override L12 verdict | ✅ PASS |
| No market direction computed in execution/dashboard | ✅ PASS |
| Journal is write-only/append-only (immutable) | ✅ PASS |
| EA is executor-only (no strategy logic) | ✅ PASS |
| L12 signals do NOT contain account state | ✅ PASS |

---

## Action Items After This PR

1. **Production env vars:** Verify `CORS_ORIGINS` and `NEXT_PUBLIC_WS_BASE_URL` are set in Railway
2. **Follow-up cleanup PR:** Remove `src/`, `next.config.ts`, `package.json`, `tsconfig.json`, `postcss.config.js` from root
3. **Consider:** Modularizing `ingest_service.py` into the `ingest/` package
4. **Consider:** Documenting `engine/` vs `engines/` distinction in architecture docs
