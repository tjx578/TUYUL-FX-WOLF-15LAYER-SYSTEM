# 🐺 TUYUL-FX — WOLF 15-LAYER SYSTEM

**Status:** 🟢 Production Architecture Baseline
**Scope:** Live Trading · Analysis Engine · Governance · Risk · Execution · Dashboard · Prop Firm
**Authority:** Layer 12 (Constitution Zone)

---

 📌 Gambaran Sistem

TUYUL-FX adalah **sistem trading kuantitatif berbasis arsitektur berlapis (layered system)** yang dirancang untuk:

* Mengubah data pasar realtime menjadi keputusan trading terstruktur
* Menjamin keputusan hanya dihasilkan oleh jalur konstitusional (Layer 12)
* Menjaga integritas melalui freshness, governance, dan risk enforcement
* Mengontrol eksekusi melalui sistem yang terpisah dari analisa

Sistem ini bukan sekadar EA atau dashboard, melainkan:

👉 **Trading Operating System berbasis governance dan auditability**

---

🧠 Prinsip Inti Sistem

## 1. Layer 12 adalah satu-satunya otoritas keputusan

* Semua layer sebelumnya hanya memberikan sinyal, scoring, atau validasi
* Hanya Layer 12 yang boleh menghasilkan **final trade verdict**

## 2. Analisa ≠ Eksekusi

* `analysis/` → berpikir
* `execution/` → menjalankan
* Tidak boleh ada kebocoran authority di antara keduanya

## 3. Dashboard bukan strategy engine

Dashboard:

* boleh membaca
* boleh mengontrol operasional (governed)
* tidak boleh menentukan arah market

## 4. Freshness > Data Presence

Data ada ≠ data valid

Sistem membedakan:

* LIVE
* DEGRADED
* STALE_PRESERVED
* NO_PRODUCER
* NO_TRANSPORT

## 5. Semua harus bisa diaudit

* Journal append-only
* State tidak boleh dimanipulasi diam-diam
* Semua keputusan harus bisa ditelusuri

---

🔄 Alur Sistem (High-Level)

```text
Finnhub / News / Market Sources
        ↓
ingest/
        ↓
Redis (state + pubsub)
        ↓
context/ (LiveContextBus)
        ↓
analysis/ (L1–L11)
        ↓
constitution/ (L12 FINAL VERDICT)
        ↓
orchestrator / risk / execution
        ↓
ea_interface /
        ↓
Broker / MT5 EA
```

---

🧱 Struktur Layer Runtime

## 1. Ingest Layer

Fungsi:

* Ambil data realtime
* Validasi payload
* Bangun candle
* Publish ke Redis

Authority: **data production only**

---

## 2. Redis Runtime Layer

Fungsi:

* Low latency state
* Pub/Sub
* Warmup support

Bukan final truth, tapi **runtime truth tercepat**

---

## 3. Context Layer

Fungsi:

* Hydration
* Sinkronisasi state
* Feed ke engine

Komponen utama:

* `LiveContextBus`

---

## 4. Governance Layer

Fungsi:

* Freshness check
* Data quality gate
* Producer heartbeat
* Kill-switch

Jika gagal → sistem masuk **HOLD**

---

## 5. Analysis Layer (L1–L11)

Fungsi:

* Market perception
* Structure
* Momentum
* Liquidity
* Confluence

Tidak boleh langsung trade

---

## 6. Constitution Layer (L12)

Fungsi:

* Final decision
* Risk validation
* Output verdict

👉 **Satu-satunya sumber kebenaran keputusan trading**

---

## 7. Execution Layer

Fungsi:

* Place order
* Cancel
* Track lifecycle

Tidak boleh berpikir

---

## 8. Dashboard Layer

Fungsi:

* Monitoring
* Control (governed)
* Audit

Tidak boleh override keputusan

---

📁 Struktur Repository

```text
analysis/        → Layer L1–L11
constitution/    → Layer 12 (final authority)
ingest/          → market data ingestion
context/         → runtime context
execution/       → order handling
ea_interface/    → EA bridge
risk/            → prop firm & runtime risk
news/            → news lock engine
alerts/          → notification system
api/             → backend API
services/        → service entrypoints
dashboard/       → frontend + UI
contracts/       → DTO & schema
state/           → Redis key registry
storage/         → journal & snapshot
tests/           → unit tests
```

---

🏗️ Arsitektur Deployment

Sistem berjalan dalam beberapa service:

```text
Vercel → Dashboard
Railway → API + Engine + Orchestrator
Railway → Redis
Railway → PostgreSQL
Railway → EA Bridge (optional)
```

---

📊 Model Data & Freshness

Keputusan hanya valid jika:

* tick terbaru (last_seen_ts valid)
* producer hidup
* warmup cukup
* data quality valid

Jika tidak:
👉 sistem wajib **HOLD**

---

⚠️ Failure Handling

Sistem dirancang untuk menghadapi:

* WebSocket disconnect
* Redis lag
* Missing data
* Stale state
* Provider failure

Semua failure harus:

* terdeteksi
* diklasifikasi
* tidak menghasilkan keputusan salah

---

🛑 Enforcement Rules

## Non-Negotiable

* Layer 12 = satu-satunya authority
* Tidak boleh ada bypass
* Stale data tidak boleh dianggap fresh
* Execution tidak boleh membuat keputusan
* Dashboard tidak boleh override

## HOLD Trigger

* Stale data
* No producer
* Warmup belum cukup
* Risk violation
* Kill switch aktif

---

⚙️ Quick Start

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Env

```bash
cp .env.example .env
```

Isi:

```env
FINNHUB_API_KEY=your_key
REDIS_URL=...
DATABASE_URL=...
```

## Run

```bash
bash scripts/run_live.sh
```

Dashboard:

```bash
bash scripts/run_dashboard.sh
```

---

🧪 Testing

```bash
pytest -q
```

Test penting:

* `tests/test_l12_gate.py` : L12 tidak bisa bypass
* `tests/test_news_lock.py` : news lock bekerja
* `tests/test_m15_cancel.py` : M15 cancel-only
* `tests/test_prop_firm.py` : aturan prop-firm

---

## 🚀 CI/CD

* CI workflow: `.github/workflows/wolf-pipeline-ci.yml`
  * Trigger: `pull_request` ke branch `main`, `workflow_dispatch`

Gate CI mencakup lint, type check, constitutional boundary, tests, coverage, dashboard build, dan **secret scan (gitleaks)**.

* Deploy workflow: `.github/workflows/railway-deploy.yml`
  * Trigger otomatis: hanya setelah workflow `CI` sukses di branch `main`
    * Trigger manual: `workflow_dispatch`

### Railway Service Manifests

Mapping service ke file deploy Railway dan start script:

| Service | Railway TOML | Start Script |
| --- | --- | --- |
| API | `railway.toml` | `deploy/railway/start_api.sh` |
| Ingestor | `railway-ingestor.toml` | `deploy/railway/start_ingest.sh` |
| Engine | `railway-engine.toml` | `deploy/railway/start_engine.sh` |
| Allocation | `railway-allocation.toml` | `deploy/railway/start_allocation.sh` |
| Execution | `railway-execution.toml` | `deploy/railway/start_execution.sh` |
| Orchestrator | `railway-orchestrator.toml` | `deploy/railway/start_orchestrator.sh` |
| Worker Backtest | `railway-worker-backtest.toml` | `deploy/railway/start_worker.sh` |
| Worker Monte Carlo | `railway-worker-montecarlo.toml` | `deploy/railway/start_worker.sh` |
| Worker Regime | `railway-worker-regime.toml` | `deploy/railway/start_worker.sh` |

### Required GitHub Secrets

* `RAILWAY_TOKEN` → token deploy Railway (wajib untuk workflow deploy)

### Recommended Branch Protection (main)

* Require a pull request before merging
* Require status checks to pass before merging
* Mark `Governance Verdict` sebagai required check
* Require branches to be up to date before merging
* Include administrators (recommended)

---

## 🔐 Logging & Audit

* Semua gate failure dicatat via `constitution/violation_log.py`
* Snapshot JSON untuk L14 disimpan via `storage/snapshot_store.py`
* Dashboard hanya membaca state & audit output, tidak bisa memodifikasi apa pun

---

## Production Service Layout

The repository supports distributed deployment through service-scoped entrypoints under `services/`.

Typical production layout:

```text
services/api/            # public API + operator/backend surface
services/engine/         # analysis and constitutional runtime
services/ingest/         # market/news/calendar ingestion
services/orchestrator/   # coordination, compliance runtime, operational flow
services/worker/         # background jobs and scheduled workloads
```

Shared runtime dependencies:

* **Redis** for low-latency shared state, heartbeat keys, queues, and fanout
* **PostgreSQL** for durable persistence, audit history, settings revisions, journals, and recovery snapshots

A production topology for TUYUL-FX commonly separates dashboard delivery, API/control, ingest, engine, orchestrator, execution routing, Redis, and PostgreSQL into distinct runtime planes.

---

## Data and Freshness Model

The system is designed to avoid stale-data deception.

Key principles:

* freshness is computed from `last_seen_ts` and heartbeat age,
* key disappearance alone must not define freshness,
* stale-preserved state may remain visible for continuity and diagnosis,
* readiness must reflect freshness and warmup sufficiency, not only process liveness.

The engine must degrade safely when:

* producer heartbeat disappears,
* warmup is incomplete,
* Redis lag or recovery inconsistency is severe,
* runtime data quality falls below minimum legitimacy.

When unsafe conditions are detected, the system must surface the truth clearly and force `HOLD` where required.

---

## Runtime Risk and Compliance Model

TUYUL-FX is designed around layered protection rather than a single risk check.

The institutional risk stack can include the following protection layers:

1. Signal Integrity
2. Strategy Risk Rules
3. Runtime Risk Governor
4. Execution Control
5. Capital Guardian
6. Infrastructure Circuit Breaker

This allows the system to:

* reject broken or low-legitimacy inputs,
* enforce per-trade and per-account constraints,
* respect prop-firm rules,
* react to execution anomalies,
* halt or reduce activity when drawdown, exposure, or infrastructure conditions become unsafe.

Compliance mode, kill-switch behavior, and guarded overrides must all remain auditable.

---

## Operational Flow

The operator-facing workflow is designed so that market decision authority and account/action binding remain separate.

Canonical flow:

1. Engine produces a global signal or verdict.
2. Operator or approved automation binds that signal to an account/EA context through controlled flow.
3. Risk / firewall / governance layers validate legality.
4. Execution intent is created only if allowed.
5. Execution lifecycle is tracked and reconciled.
6. Journal and read models reflect final truth.

This model prevents the dashboard or execution layer from becoming an alternate market-decision path.

---

## Settings, Resolver, and Governance

Settings are not treated as loose UI toggles.

Production doctrine requires:

* hierarchical config resolution,
* protected fields,
* lock enforcement,
* immutable revision history,
* optional approval workflow for high-risk changes,
* no direct overwrite of active truth without governance.

In mature deployments, effective runtime config should be derived from scoped layers such as:

* global defaults,
* prop-firm constraints,
* account overrides,
* EA profile rules,
* pair-specific overrides.

The engine should consume **effective resolved config**, not arbitrary local UI state.

---

## Dashboard Role

The dashboard is intentionally powerful in operations but limited in authority.

It may be used for:

* observing signals, trades, risk, health, and freshness,
* binding signals to specific accounts or EA contexts,
* reviewing legality and execution status,
* managing governed settings,
* reading journal and audit state,
* surfacing risk/compliance warnings,
* invoking controlled operational commands through backend APIs.

It must not:

* create trade direction,
* bypass constitutional verdicts,
* mutate execution truth arbitrarily,
* rewrite journal history,
* weaken protected constraints without proper governance.

---

## Documentation Doctrine

Repository documentation should be structured so that architecture truth is clearly separated from concepts, research, and legacy material.

Recommended documentation layout:

```text
docs/
  architecture/   # official system truth
  concepts/       # R&D, subsystem deep dives, experimental ideas
  knowledge/      # reference material and research notes
  legacy/         # archived or superseded documents
```

The `docs/architecture/` package should be treated as the official source of truth for:

* data flow,
* authority boundaries,
* stale-data guardrails,
* execution feedback,
* deployment topology,
* service contracts,
* operational flow,
* governance/settings,
* risk/compliance,
* migration plans.

---

## Quick Start

### 1. Create virtual environment

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment

```bash
cp .env.example .env
```

Populate required values such as provider credentials, database URLs, Redis connection, JWT/auth settings, and deployment/runtime variables.

### 4. Start the appropriate service(s)

Depending on deployment style, start the required service entrypoints or scripts for:

* API
* ingest
* engine
* orchestrator
* workers
* dashboard

### 5. Run tests

```bash
pytest -q
```

---

## Testing Expectations

This repository should maintain tests that defend constitutional and operational behavior, including areas such as:

* Layer 12 authority,
* stale-data handling,
* news or calendar lock behavior,
* prop-firm or compliance enforcement,
* execution lifecycle transitions,
* API contract correctness,
* dashboard/control-path regression checks.

---

## Deployment Expectations

A production deployment should preserve these properties:

* TLS and strict origin/auth discipline,
* Redis-backed low-latency state and rate limiting where needed,
* durable PostgreSQL persistence for journal/audit/config,
* explicit WebSocket and API base URLs,
* freshness-aware readiness,
* safe restart and reconciliation behavior,
* observability for ingest, engine, risk, execution, and transport layers.

---

## Non-Negotiable Rules

* Layer 12 is the only final verdict authority.
* No dashboard path may become a strategy override path.
* Execution may transmit approved intent only.
* Stale data must never be silently treated as fresh.
* Append-only audit and journal history must remain intact.
* Governance must be explicit, not implied.

---

## Current Reality

This repository already contains strong architectural foundations, but different parts of the system may be at different maturity levels.

Some modules already reflect production-grade direction, while others may still be in transition toward:

* stronger service separation,
* more explicit governance,
* tighter config resolution,
* clearer stale-data enforcement,
* fuller execution reconciliation,
* richer operational observability.

The correct path forward is controlled migration and hardening, not authority drift.

---

## Closing Principle

TUYUL-FX must be operated as a governed analytical system, not as a collection of convenience shortcuts.

If a component cannot prove freshness, legitimacy, authority, and auditability, it must not be allowed to silently behave as if it can.
**END OF FILE**
