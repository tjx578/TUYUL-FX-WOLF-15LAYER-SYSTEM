# 🐺 TUYUL-FX — WOLF 15-LAYER SYSTEM

**Status:** 🟢 Production Architecture Baseline
**Scope:** Live Trading · Analysis Engine · Governance · Risk · Execution · Dashboard · Prop Firm
**Authority:** Layer 12 (Constitution Zone)

---

# 📌 Gambaran Sistem

TUYUL-FX adalah **sistem trading kuantitatif berbasis arsitektur berlapis (layered system)** yang dirancang untuk:

* Mengubah data pasar realtime menjadi keputusan trading terstruktur
* Menjamin keputusan hanya dihasilkan oleh jalur konstitusional (Layer 12)
* Menjaga integritas melalui freshness, governance, dan risk enforcement
* Mengontrol eksekusi melalui sistem yang terpisah dari analisa

Sistem ini bukan sekadar EA atau dashboard, melainkan:

👉 **Trading Operating System berbasis governance dan auditability**

---

# 🧠 Prinsip Inti Sistem

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

# 🔄 Alur Sistem (High-Level)

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

# 🧱 Struktur Layer Runtime

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

# 📁 Struktur Repository

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

# 🏗️ Arsitektur Deployment

Sistem berjalan dalam beberapa service:

```text
Vercel → Dashboard
Railway → API + Engine + Orchestrator
Railway → Redis
Railway → PostgreSQL
Railway → EA Bridge (optional)
```

---

# 📊 Model Data & Freshness

Keputusan hanya valid jika:

* tick terbaru (last_seen_ts valid)
* producer hidup
* warmup cukup
* data quality valid

Jika tidak:
👉 sistem wajib **HOLD**

---

# ⚠️ Failure Handling

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

# 🛑 Enforcement Rules

## Non-Negotiable:

* Layer 12 = satu-satunya authority
* Tidak boleh ada bypass
* Stale data tidak boleh dianggap fresh
* Execution tidak boleh membuat keputusan
* Dashboard tidak boleh override

## HOLD Trigger:

* Stale data
* No producer
* Warmup belum cukup
* Risk violation
* Kill switch aktif

---

# ⚙️ Quick Start

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

# 🧪 Testing

```bash
pytest -q
```

Test penting:

* L12 gate
* News lock
* Prop firm rules
* Cancel logic

---

# 📚 Dokumentasi

```text
docs/
  architecture/   → source of truth sistem
  concepts/       → riset
  knowledge/      → referensi
  legacy/         → arsip
```

Dokumen penting:

* data-flow-final.md
* authority-boundaries.md
* stale-data-guardrails.md
* execution-feedback-loop.md
* deployment-topology-final.md
* service-contracts.md

---

# 🔐 Logging & Audit

* Semua violation dicatat
* Snapshot disimpan
* Trade journal immutable

---

# 🧩 Prinsip Akhir

Sistem hanya boleh dianggap valid jika:

* data fresh
* producer hidup
* governance lolos
* Layer 12 memutuskan

Jika tidak:
👉 sistem harus **menahan diri (HOLD)**

---

# 🐺 Filosofi Sistem

TUYUL-FX bukan sistem untuk "menang cepat".

Ini adalah sistem untuk:

* bertahan
* disiplin
* terkontrol
* dapat diaudit

Jika ada bagian sistem yang tidak bisa menjelaskan:

* darimana data datang
* siapa yang punya authority
* bagaimana keputusan dibuat

maka bagian tersebut **tidak layak digunakan di live trading**.

---

# 🐺 TUYUL-FX — WOLF 15-LAYER SYSTEM

**Status:** Active Architecture Baseline
**Scope:** Analysis Engine · Governance · Runtime Risk · Execution Routing · Dashboard · Prop-Firm Operations
**Decision Authority:** **Layer 12 only**
**Core Rule:** No module outside the constitutional decision path may create, mutate, or override a trade verdict.

---

## What This System Is

TUYUL-FX is a **layered market analysis and trading control system** built to transform live market data into **validated trade decisions** and then route those decisions through **risk, governance, and execution controls**.

The system is deliberately split into distinct responsibilities so that:

* ingest produces and validates data,
* the engine builds context and performs analysis,
* Layer 12 produces the only valid trade verdict,
* downstream services coordinate, constrain, and execute,
* the dashboard exposes system truth and operational controls **without becoming market decision authority**.

This repository is not just an EA project and not just a dashboard. It is a **multi-layer trading operating system** built around constitutional decision flow, stale-data protection, risk enforcement, and auditable execution handling.

---

## Core System Doctrine

### 1. Layer 12 is the sole verdict authority

All earlier layers may detect, score, penalize, or veto conditions, but the **final constitutional trade verdict belongs only to Layer 12**.

### 2. Analysis and execution are separated

`analysis/` and engine logic may reason about the market.
`execution/` and EA-facing layers may execute approved intent only.

### 3. Dashboard is operational, not sovereign

The dashboard can read system state, bind signals to accounts, request controlled actions, review risk, inspect journal state, and change governed settings through audited paths.
It **cannot invent direction, override constitutional verdicts, or bypass runtime protection**.

### 4. Freshness matters as much as data presence

The system distinguishes between:

* `LIVE`
* `DEGRADED_BUT_REFRESHING`
* `STALE_PRESERVED`
* `NO_PRODUCER`
* `NO_TRANSPORT`

Data availability alone is not enough. The system must confirm freshness, producer heartbeat, and warmup sufficiency before it can be trusted for normal operation.

### 5. Journal and audit trails are append-only

Operational history, governance actions, and execution lifecycle outcomes must remain traceable.

---

## High-Level System Flow

```text
External Market / Event Sources
    ↓
Ingest Authority Layer
    ↓
Redis Durability + Fanout Layer
    ↓
Engine Context / Recovery Layer
    ↓
Freshness / Quality / Governance Layer
    ↓
Wolf Analysis Constitutional DAG (Layer 1–15)
    ↓
Layer 12 Final Verdict
    ↓
Coordination / Execution / Journal / API / Dashboard Consumers
```

In production, live ticks and higher-timeframe candle/news data are ingested and written into Redis-backed shared runtime state, then consumed by the engine through `RedisConsumer` and `LiveContextBus`. The pipeline executes Layers 1–15 sequentially, with Layer 12 acting as the only final verdict gate. Risk, legality, execution, and observability then operate downstream of that verdict rather than replacing it.

---

## Main Runtime Planes

### 1. Ingest Plane

Responsible for:

* live tick acquisition,
* payload validation,
* spike filtering,
* candle construction,
* fallback scheduling,
* producer heartbeat publication.

This layer has **data production authority**, not trade authority.

### 2. Runtime State Plane

Backed primarily by Redis for:

* latest tick/candle state,
* recent candle history,
* heartbeat keys,
* pub/sub fanout,
* warmup support,
* cross-service state distribution.

PostgreSQL remains the durable persistence layer for journal, audit, ledger, recovery snapshots, and longer-horizon recovery.

### 3. Analysis Plane

Centered around the Wolf constitutional pipeline:

* perception,
* confluence,
* probability,
* validation,
* execution preparation,
* constitutional verdict,
* reflective/meta layers.

The engine owns runtime analytical truth.
**Layer 12 owns final trade verdict truth.**

### 4. Governance and Risk Plane

Responsible for:

* freshness classification,
* stale-data enforcement,
* runtime risk gating,
* prop-firm compliance,
* kill-switch and hold rules,
* config locking and approval flows.

This layer may constrain or block execution, but it does not generate market direction.

### 5. Coordination and Execution Plane

Responsible for:

* orchestrating post-verdict actions,
* validating legality before execution,
* creating execution intent,
* tracking execution lifecycle,
* reconciling acknowledgement/fill/reject/cancel outcomes.

Execution services must never invent signals or modify constitutional trade direction.

### 6. API and Dashboard Plane

Responsible for:

* authenticated read/write operational endpoints,
* published system state,
* portfolio and trade read models,
* settings governance surfaces,
* WebSocket / SSE / REST fallback delivery,
* operator workflows such as signal binding and monitored execution actions.

The dashboard is a **control surface**, not a strategy engine.

---

## Repository Structure

```text
alerts/          # alert formatting and notifier integrations
analysis/        # analytical layers, gates, synthesis, and pre-verdict logic
api/             # HTTP/WebSocket/API middleware, routes, auth, rate limits
config/          # config files, thresholds, presets, schemas, defaults
constitution/    # constitutional gates and final verdict authority
context/         # runtime context bus, Redis bridge, hydration consumers
contracts/       # DTOs and cross-service event/request contracts
dashboard/       # frontend and dashboard-facing backend/UI code
deploy/          # deployment scripts and service startup helpers
ea_interface/    # EA command schema and sync boundary
execution/       # execution intent, order routing, reconciliation, guards
ingest/          # live feed collectors, candle builders, provider ingestion
infrastructure/  # deployment responsibility notes and infra docs
news/            # calendar/news ingestion and lock support
risk/            # runtime risk, prop-firm rules, drawdown/exposure governance
schemas/         # JSON schemas for system contracts and outputs
services/        # service-scoped entrypoints for distributed deployment
state/           # Redis keys, channels, consumer groups, shared state registry
storage/         # snapshot persistence, journal helpers, recovery storage
tests/           # unit/integration/contract validation
```

> Design rule: preserve constitutional separation. Analysis is not execution. API is not verdict authority. Dashboard is not strategy. Layer 12 remains the final gate.

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
