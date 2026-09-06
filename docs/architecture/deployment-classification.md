# Deployment Classification

**Status:** Canonical current-state deployment policy
**Scope:** Deployment target classification, support expectations, and operational truth hierarchy for TUYUL FX
**Audience:** Architecture, DevOps, runtime operators, maintainers
**Last Verified:** 2026-09-06 against repository deployment definitions (not production)
**Source of Truth:** `docker-compose.yml`, `railway-*.toml`, `services/*/Dockerfile`, `dashboard/nextjs/vercel.json`

---

## 1. Purpose

Dokumen ini mendefinisikan klasifikasi resmi untuk seluruh jalur deployment TUYUL FX.

Tujuannya:

* mengurangi deployment fragmentation
* menegaskan mana jalur deploy yang menjadi acuan utama
* membedakan mana deployment yang masih didukung, mana yang hanya opsional
* mencegah drift antara runtime behavior, env contract, startup order, dan observability

Dokumen ini adalah **source of truth untuk klasifikasi deployment**, bukan untuk threshold constitutional, boundary dashboard, atau worldview arsitektur sistem.

---

## 2. Core Rule

TUYUL FX boleh memiliki lebih dari satu cara deploy, tetapi **tidak semua jalur deploy memiliki status yang sama**.

Setiap deployment target harus diklasifikasikan sebagai salah satu dari tiga status berikut:

* **Canonical** — jalur acuan utama yang harus paling dijaga sinkronisasinya dengan repo aktif
* **Supported** — jalur yang masih didukung dan boleh dipakai, tetapi bukan baseline utama
* **Legacy / Removed** — jalur yang pernah ada tetapi sudah dihapus dari repo atau didepresiasi dari toml aktif

---

## 3. Current Classification

### 3.1 Canonical cloud deployment — Railway

**Railway** adalah **canonical cloud deployment target**.

Alasan:

* repo memiliki Railway definitions for independently owned runtime roles
* Railway topology keeps selected consolidated roles while enforcing a separate
  orchestration owner:
  * `railway.toml` = API-only; both API start scripts reject an enabled
    `WOLF15_EMBED_ORCHESTRATOR`
  * `railway-orchestrator.toml` = standalone orchestration and compliance owner
  * `railway-execution.toml` = Allocation + Execution consolidated via `services/trade/runner.py`
  * `railway-engine.toml` = Engine-only (`RUN_MODE=engine-only`)
* dedicated service entrypoints (`services/api/main.py`, `services/engine/runner.py`, `services/trade/runner.py`, `services/dashboard_bff/main.py`) menegaskan arah service-oriented runtime
* startup scripts di `deploy/railway/` sudah lengkap (14 scripts)

**Active Railway definitions:**

| Config | Start Script | Purpose | Lifecycle |
| ------ | ----------- | ------- | --------- |
| `railway.toml` | `start_api.sh` | API-only, including read/WebSocket projections | provider/default policy |
| `railway-orchestrator.toml` | `start_orchestrator.sh` | Standalone orchestration and compliance owner | ON_FAILURE (5 retries) |
| `railway-ingestor.toml` | `start_ingest.sh` | Standalone market-data ingest | ON_FAILURE (5 retries) |
| `railway-engine.toml` | `start_engine_consolidated.sh` | Engine-only pipeline | ON_FAILURE (5 retries) |
| `railway-execution.toml` | `start_trade_consolidated.sh` | Allocation + Execution consolidated | ON_FAILURE (5 retries) |
| `railway-dashboard-bff.toml` | `start_dashboard_bff.sh` | Dashboard BFF aggregation | ON_FAILURE (5 retries) |
| `railway-ea-bridge.toml` | `start_ea_bridge.sh` | SHADOW MT5 command bridge | ON_FAILURE (5 retries) |
| `railway-pressure-outbox.toml` | `start_pressure_outbox.sh` | Durable pressure dispatcher/inbox worker | ON_FAILURE (5 retries) |
| `railway-migrator.toml` | `start_migrator.sh` | One-shot DB migration (alembic) | NEVER restart |
| `railway-worker-montecarlo.toml` | `start_worker.sh` | Monte Carlo cron (daily 1:00 UTC) | NEVER restart |
| `railway-worker-backtest.toml` | `start_worker.sh` | Nightly backtest cron (daily 1:30 UTC) | NEVER restart |
| `railway-worker-regime.toml` | `start_worker.sh` | Regime recalibration cron (Sunday 2:00 UTC) | NEVER restart |

**Compatibility/consolidation definitions:**

| Config | Original Purpose | Status |
| ------ | --------------- | ------ |
| `railway-ingestor.toml` | Standalone ingest | Active source contract; deployment status requires external evidence |
| `railway-allocation.toml` | Standalone allocation | DEPRECATED — consolidated into trade service |

**Implikasi:**

* ketika terjadi konflik antar deployment mode, active Railway definitions and
  executable start scripts are the repository-level source for service separation
* semua evolusi runtime topology baru harus terlebih dulu kompatibel dengan jalur canonical ini
* repository classification does not prove provider deployment, replica count,
  image identity, or effective environment

### 3.2 Canonical local / integration deployment — Docker Compose

**Docker Compose** adalah **canonical local / integration deployment target**.

Compose file berisi **two stacks** yang coexist selama transisi:

**Monolith-Compatible Stack (legacy entrypoints):**

| Service | Port | Description |
| ------- | ---- | ----------- |
| `app` | 8000 | Main ASGI application (monolith, `EMBED_INGEST=true`) |
| `wolf-allocation` | 9102 | Allocation manager worker (`allocation.async_worker`) |
| `wolf-execution` | 9103 | Execution worker (`execution.async_worker`) |
| `wolf-dashboard` | 3000 | Next.js dashboard frontend |

**Per-Service Stack (service-oriented builds):**

| Service | Dockerfile | Description |
| ------- | --------- | ----------- |
| `wolf-api` | `services/api/Dockerfile` | Dedicated API service (ASGI) |
| `wolf-engine` | `services/engine/Dockerfile` | Dedicated engine process |
| `wolf-ingest` | `services/ingest/Dockerfile` | Dedicated ingest process |
| `wolf-orchestrator` | `services/orchestrator/Dockerfile` | Governance mode control |
| `wolf-worker` | `services/worker/Dockerfile` | Generic worker (`WOLF15_WORKER_ENTRY` selects task) |

**Infrastructure / Observability:**

| Service | Port | Description |
| ------- | ---- | ----------- |
| `redis` | 6379 (localhost only) | Redis 7 — cache, pubsub, context bridge |
| `postgres` | 5432 (localhost only) | PostgreSQL 16 — persistence |
| `prometheus` | 9090 | Metrics scraper |
| `grafana` | 3001 | Dashboards and alerting |
| `tempo` | 4317, 3200 | Distributed tracing (OTLP) |

**Total: 14 services** (4 legacy + 5 per-service + 5 infrastructure)

**Network:** semua service share `wolf15_net` bridge network. Redis dan Postgres bound ke `127.0.0.1` only.

**Implikasi:**

* Compose tidak boleh diperlakukan sebagai file opsional kecil
* sebelum Compose dipensiunkan, harus ada pengganti yang setara untuk local full-stack reproducibility

### 3.3 Supported frontend deployment — Vercel

**Vercel** diklasifikasikan sebagai **supported deployment target** untuk dashboard frontend.

Alasan:

* `dashboard/nextjs/vercel.json` aktif, region = SIN1 (Singapore)
* `next.config.js` mengatur API base URL dan WebSocket origin dari env
* dashboard frontend tidak mengandung constitutional logic, sehingga deployability-nya terpisah dari backend

**Implikasi:**

* Vercel hanya relevan untuk dashboard frontend, bukan backend services
* Vercel deploy berjalan independen dari Railway/Compose backend
* perubahan backend API contract harus divalidasi terhadap dashboard build

### 3.4 Removed deployment — Hostinger VPS

**Hostinger VPS bare-metal** diklasifikasikan sebagai **removed**.

Fakta:

* `deploy/hostinger/` sudah **dihapus dari repo**
* satu-satunya artifact ops yang tersisa adalah `deploy/nginx/api.yourdomain.com.conf` (reverse proxy config dengan placeholder domain)
* repo tetap berjalan penuh tanpa Hostinger

**Implikasi:**

* Hostinger tidak boleh dipakai sebagai acuan current runtime behavior
* `deploy/nginx/` tetap tersedia sebagai referensi konfigurasi reverse proxy jika dibutuhkan untuk deploy alternatif di kemudian hari

---

## 4. Classification Matrix

| Deployment target | Status | Primary purpose | Source of truth scope | Notes |
| ----------------- | ------ | --------------- | -------------------- | ----- |
| Railway | **Canonical** | Cloud runtime (separate orchestration owner) | Repository deployment contract only | Provider state requires external observation |
| Docker Compose | **Canonical** | Local/integration full-stack | Local reproducibility, integration validation | 14 services (hybrid transitional) |
| Vercel | **Supported** | Dashboard frontend deployment | Frontend deployment only | SIN1 region, `dashboard/nextjs/` |
| Hostinger VPS | **Removed** | (formerly bare-metal ops) | N/A | `deploy/hostinger/` deleted from repo |
| Nginx reverse proxy | **Artifact** | Reverse proxy config reference | Ops convenience only | `deploy/nginx/`, placeholder domain |

---

## 5. Service Entrypoints

| Service | Entrypoint | Description | WOLF15_SERVICE_ROLE |
| ------- | --------- | ----------- | ------------------- |
| API | `services/api/main.py` | FastAPI ASGI app via `api.app_factory.create_app()` | `api` |
| Engine | `services/engine/runner.py` | Analysis pipeline + health probe on :8081 | `engine` |
| Trade | `services/trade/runner.py` | Consolidated allocation + execution; dual Prometheus ports | `trade` |
| Ingest | `services/ingest/ingest_worker.py` | Market data acquisition; lightweight health probe first | `ingest` |
| Orchestrator | `services/orchestrator/state_manager.py` | Sole orchestration/compliance runtime, never strategy or broker authority | `orchestrator` |
| Dashboard BFF | `services/dashboard_bff/main.py` | Non-authoritative BFF aggregation for dashboard | `dashboard-bff` |
| Worker | `services/worker/` | Dispatched by `WOLF15_WORKER_ENTRY` env var | (per job) |
| Legacy monolith | `main.py` | Logical flow reference; still functions as combined entrypoint | N/A |

---

## 6. Context Modes

| Mode | Backend | Use Case |
| ---- | ------- | -------- |
| `CONTEXT_MODE=local` | In-process dict | Single-process, development |
| `CONTEXT_MODE=redis` | RedisContextBridge | Multi-service, production |

---

## 7. Operational Truth Hierarchy

Untuk urusan deployment, gunakan hierarchy berikut:

1. **Current runtime topology docs** (`runtime-topology-current.md`)
2. **Service entrypoints aktif** (tabel Section 5)
3. **Canonical deployment definitions** (Railway tomls, `docker-compose.yml`)
4. **Supported deployment adapters** (Vercel config)
5. **Reference architecture docs** (`reference-architecture.md`)

Dalam praktiknya:

* bila ada konflik antara Compose dan referensi lama, **Compose lebih dipercaya** untuk local/integration behavior
* bila ada konflik antara Railway dan referensi lama, **Railway lebih dipercaya** untuk cloud runtime/service separation
* bila ada konflik antara dokumen referensi lama dan current deployment files, **deployment files aktif menang**

---

## 8. What Each Deployment Must Guarantee

### 8.1 Railway must guarantee

* dedicated runtime separation untuk service utama
* env contract yang sesuai dengan current service topology
* startup path yang sinkron dengan service entrypoints aktif
* health semantics (`/healthz` liveness, `/readyz` readiness) yang konsisten dengan runtime responsibilities

### 8.2 Docker Compose must guarantee

* one-command full-stack bring-up untuk local/integration
* Redis/Postgres/observability/dashboard/backend stack yang reproducible
* jalur debug lintas-service yang cukup dekat dengan runtime production mindset
* kemampuan memvalidasi integrasi tanpa bergantung pada provider cloud

### 8.3 Vercel must guarantee

* dashboard frontend build yang konsisten dengan backend API contract
* environment variables untuk API base URL dan WS origin yang benar
* region deployment yang sesuai (currently SIN1)

---

## 9. Support Policy

### 9.1 Canonical targets

Canonical targets wajib:

* tetap sinkron dengan perubahan repo
* diprioritaskan saat ada perubahan startup/runtime path
* diprioritaskan untuk smoke test dan acceptance check
* tidak boleh tertinggal dokumentasinya

### 9.2 Supported targets

Supported targets:

* boleh tetap ada dan didukung
* diprioritaskan setelah canonical targets
* harus jelas scope-nya (Vercel = frontend only)

### 9.3 Removed targets

Removed targets:

* tidak lagi menjadi bagian dari deployment surface
* artifact yang tersisa (nginx conf) bersifat referensi saja
* tidak boleh diam-diam diperlakukan sebagai canonical

---

## 10. Change Management Rule

Setiap perubahan baru yang menyentuh runtime harus dievaluasi menurut urutan ini:

1. Apakah perubahan ini kompatibel dengan **Railway** sebagai canonical cloud deployment?
2. Apakah perubahan ini tetap bisa direproduksi di **Docker Compose** sebagai canonical local/integration deployment?
3. Jika menyentuh dashboard, apakah perubahan ini kompatibel dengan **Vercel** deployment?

Jika jawaban nomor 1 dan 2 tidak jelas, perubahan belum siap dipromosikan.

---

## 11. Decommission Rules

### Untuk Docker Compose

Compose **tidak** boleh dipensiunkan sebelum tersedia pengganti yang setara untuk:

* local full-stack reproducibility
* integration testing
* service interaction debugging
* fallback validation saat cloud path bermasalah

### Untuk Railway

Railway sebagai canonical cloud target hanya boleh diganti jika sudah ada canonical cloud replacement yang:

* mendukung service decomposition aktif
* memiliki env contract yang matang
* punya observability dan startup semantics yang setara atau lebih baik

### Untuk deprecated Railway tomls

`railway-allocation.toml` and superseded compatibility scripts may be removed only if:

* consolidated ownership has verified runtime evidence;
* exact rollback targets no longer depend on them; and
* removal cannot restore embedded orchestration or create a second writer.

`railway-orchestrator.toml` and `start_orchestrator.sh` are canonical, not
deprecation candidates. `railway-ingestor.toml` remains listed by the service
ownership contract until a separately approved topology change says otherwise.

---

## 12. Anti-Drift Policy

Untuk menghindari deployment fragmentation, repo harus menghindari kondisi berikut:

* startup order berbeda jauh antara canonical targets tanpa alasan jelas
* env contract berbeda diam-diam antar deployment
* service naming dan runtime responsibility berubah di satu target tetapi tidak di target canonical lain
* observability hanya aktif di salah satu jalur deployment
* bug hanya muncul di satu jalur karena deployment path tidak lagi dipelihara

Jika gejala di atas muncul, canonical target harus dipakai sebagai pembanding pertama.

---

## 13. Deprecation Notes

* `deploy/hostinger/` — removed, no longer part of deployment surface
* `RUN_MODE=all|engine-only|ingest-only` — legacy monolith mode selector; being superseded by per-service Dockerfiles and Railway consolidated services
* `railway-orchestrator.toml` — canonical standalone orchestration definition
* `railway-ingestor.toml` — standalone ingest definition; runtime deployment is not inferred from its presence
* `railway-allocation.toml` — compatibility definition superseded by the trade service

---

## 14. Non-Goals

Dokumen ini tidak mendefinisikan:

* threshold constitutional aktif
* dashboard authority boundary
* daftar WS/API endpoint aktif
* component inventory file-by-file
* operational runbook detail per platform

---

## 15. Final Rule

Deployment target adalah **cara menjalankan sistem**, bukan **otoritas sistem**.

Yang menjadi acuan utama tetap:

* constitutional boundaries
* runtime truth aktif
* canonical topology docs
* active config and service entrypoints

Tidak ada deployment target yang boleh diam-diam menciptakan perilaku runtime baru yang bertentangan dengan sistem konstitusional TUYUL FX.

---

## 16. Changelog

```text
v1.0 — Initial deployment classification (flat inventory format)
v2.0 — Rewritten with 3-tier classification model
v2.1 — Corrected API-only/standalone-orchestrator ownership; removed the stale embedded-orchestrator classification
       - Railway: canonical repository definitions with a separate orchestrator owner
       - Docker Compose: canonical local/integration (14 services)
       - Vercel: supported (dashboard frontend, SIN1)
       - Hostinger: removed (deploy/hostinger/ deleted from repo)
       - Added: service entrypoints incl. trade, dashboard_bff, ingest_worker
       - Corrected: API-only plus standalone orchestrator; Trade=Alloc+Exec remains consolidated
       - Added: operational truth hierarchy, change management, decommission rules
       - Added: anti-drift policy, support policy per tier
       - Added: WOLF15_SERVICE_ROLE mapping
```
