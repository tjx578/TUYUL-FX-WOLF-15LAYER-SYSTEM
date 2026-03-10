# 🐺 TUYUL FX — WOLF 15-LAYER SYSTEM (v7.4r∞)

> **Status:** 🟢 FINAL · LOCKED · LIVE READY  \
> **Scope:** LIVE TRADING · EA · DASHBOARD · PROP FIRM  \
> **Authority:** **Layer-12 ONLY (Constitution Zone)**  \
> **Execution Mode:** **TP1_ONLY** · **Pending Orders Only** · **No Market Execution**

---

## 📌 Master Output Reference (WOLF 15-LAYER)

Sistem ini menggunakan **WOLF 15-LAYER OUTPUT TEMPLATE** sebagai
**referensi utama cara sistem berpikir, menilai, dan mengambil keputusan**.

📄 **Primary Reference Document:**

- `docs/WOLF_15_LAYER_OUTPUT_TEMPLATE_v7.4r∞.md`

### Fungsi Dokumen Ini

- Standar output analisis (L1–L15)
- Referensi audit & training
- Acuan validasi hasil L14 JSON
- Dokumentasi bagaimana **Layer-12 mengambil keputusan**

### Catatan Penting

- Dokumen ini **TIDAK DIEKSEKUSI**
- Dokumen ini **TIDAK MENGGANTIKAN LOGIC**
- Otoritas final tetap pada:
  - `constitution/gatekeeper.py`
  - `constitution/verdict_engine.py`

Jika terjadi perbedaan:
> **Konstitusi & kode selalu menang.**

---

## 🔒 Constitutional Rules (Non-Negotiable)

- **L12 (constitution/) = satu-satunya otoritas final**
- **H1 = candle pembuat setup**
- **M15 = cancel only**
- **analysis/** tidak pernah menyentuh order
- **execution/** tidak pernah berpikir (blind executor)
- **EA = executor only**
- **Dashboard = read-only monitoring & audit**
- Jika ada shortcut/override/bypass → **INVALID SYSTEM**

---

## 🧠 System Flow

Finnhub API (WebSocket / REST)
     ↓
ingest/ (feed + candle builder)
     ↓
context/ (Live Context Bus)
     ↓
analysis/ (L1–L11) + synthesis.py
     ↓
constitution/ (gatekeeper.py + verdict_engine.py)  ← L12 FINAL
     ↓
execution/ (pending/cancel/expiry/guard/state machine)
     ↓
ea_interface/ (command schema)
     ↓
Broker/EA Executor

---

## 📡 Data Provider

Sistem menggunakan **Finnhub** sebagai satu-satunya data provider untuk:

- **Real-time forex quotes** via WebSocket (`ingest/`)
- **Candle/OHLCV data** via REST API (`ingest/candle_builder`)
- **Economic calendar & news events** (`news/` → news lock engine)

> ⚠️ Pastikan `FINNHUB_API_KEY` sudah diset di `.env` (lihat `.env.example`).

---

## 📁 Repo Structure (High-Level)

- `config/` : semua konfigurasi (pairs, prop-firm, telegram, thresholds constitution)
- `ingest/` : Finnhub realtime feed + candle builder
- `context/` : unified market state (read-only)
- `analysis/` : L1–L11 + synthesis (candidate setup)
- `constitution/` : Gatekeeper + L12 Verdict + audit log (sole authority)
- `execution/` : pending placement + cancel + expiry + execution guard
- `news/` : news lock engine
- `risk/` : prop-firm rules, drawdown, risk multiplier
- `alerts/` : telegram notifier + formatter
- `dashboard/` : backend API (read-only) + frontend UI tunggal di `dashboard/nextjs/`
- `storage/` : redis snapshot + trade journal
- `schemas/` : JSON schemas (L12, L14, alerts)
- `ea_interface/` : command schema + sync contract
- `tests/` : unit tests untuk gate/news/cancel/prop-firm
- `scripts/` : run scripts + health check

## 🏗️ Production Service Layout (Distributed)

Repository now includes service-scoped entrypoints under `services/` to support
multi-service deployment without duplicating core logic:

- `services/api/` → public FastAPI service (read-only governance boundary)
- `services/engine/` → engine runner (no public HTTP)
- `services/ingest/` → ingest worker
- `services/orchestrator/` → governance mode/compliance runtime
- `services/worker/` → scheduled jobs

Shared contracts and state registry:

- `contracts/` → DTO + websocket event contracts
- `state/` → Redis keys/channels/consumer groups
- `infrastructure/railway/service-map.md` → deployment responsibility matrix

Design rule: preserve constitutional separation (analysis ≠ execution authority,
dashboard/API ≠ decision authority, Layer-12 remains sole decision gate).

---

## 🧪 Sandbox & Experimental Modules

Folder `sandbox/` berisi modul **non-runtime** untuk:

- reasoning simulation
- output validation
- research & experimentation

⚠️ Modul di folder ini **TIDAK DIEKSEKUSI OLEH SISTEM LIVE**.

## 📚 Documentation (Operational)

Dokumentasi ini **bukan bagian runtime**, digunakan untuk:
audit · compliance · SOP · training.

- `docs/FINAL_SYSTEM_REVIEW.md`
- `docs/END_TO_END_SIMULATION.md`
- `docs/GO_LIVE_CHECKLIST_PROP_FIRM.md`
- `docs/OUTBOX_ADMIN_API.md` (inspect/replay outbox admin API)

⚠️ File di folder `docs/` **tidak pernah dipanggil oleh kode**.

## Outbox Admin API (Ringkas)

Endpoint outbox admin tersedia di prefix `/api/v1/outbox` (wajib auth).

- `GET /api/v1/outbox/pending` (inspect + filter)
- `GET /api/v1/outbox/{outbox_id}` (single record detail)
- `POST /api/v1/outbox/retry-batch` (mass replay dengan safety cap)

Contoh request-response lengkap:

- `docs/OUTBOX_ADMIN_API.md`

---

## ✅ Quick Start

### 1) Setup Environment

```bash
python -m venv .venv
source .venv/bin/activate   # windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2) Configure Env

Copy `.env.example` → `.env` dan isi key yang diperlukan:

```bash
cp .env.example .env
```

Pastikan variabel berikut terisi:

```env
FINNHUB_API_KEY=your_finnhub_api_key_here
```

### 3) Run (Live Or Paper)

- Live engine:

```bash
bash scripts/run_live.sh
```

- Dashboard:

```bash
bash scripts/run_dashboard.sh
```

> Catatan: file `main.py` adalah entrypoint dan **tidak boleh berisi logic analisis/eksekusi**.

---

## 🧪 Run Tests

```bash
pytest -q
```

Test penting:

- `tests/test_l12_gate.py` : L12 tidak bisa bypass
- `tests/test_news_lock.py` : news lock bekerja
- `tests/test_m15_cancel.py` : M15 cancel-only
- `tests/test_prop_firm.py` : aturan prop-firm

---

## 🚀 CI/CD

- CI workflow: `.github/workflows/wolf-pipeline-ci.yml`
  - Trigger: `pull_request` ke branch `main`, `workflow_dispatch`

Gate CI mencakup lint, type check, constitutional boundary, tests, coverage, dashboard build, dan **secret scan (gitleaks)**.

- Deploy workflow: `.github/workflows/railway-deploy.yml`
  - Trigger otomatis: hanya setelah workflow `CI` sukses di branch `main`
    - Trigger manual: `workflow_dispatch`

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

- `RAILWAY_TOKEN` → token deploy Railway (wajib untuk workflow deploy)

### Recommended Branch Protection (main)

- Require a pull request before merging
- Require status checks to pass before merging
- Mark `Governance Verdict` sebagai required check
- Require branches to be up to date before merging
- Include administrators (recommended)

---

## 🔐 Logging & Audit

- Semua gate failure dicatat via `constitution/violation_log.py`
- Snapshot JSON untuk L14 disimpan via `storage/snapshot_store.py`
- Dashboard hanya membaca state & audit output, tidak bisa memodifikasi apa pun

---

## 🧩 Environment Variables

Lihat `.env.example` untuk daftar lengkap.

### Orchestrator Runtime (services/orchestrator)

Environment variables berikut dipakai oleh `services/orchestrator/state_manager.py`:

```env
# Redis pub/sub channel for orchestrator command + status events.
# Default fallback: state.pubsub_channels.ORCHESTRATOR_COMMANDS
ORCHESTRATOR_CHANNEL=wolf15:orchestrator:commands

# Redis snapshot keys written/read by orchestrator
ORCHESTRATOR_STATE_KEY=wolf15:orchestrator:state
ORCHESTRATOR_ACCOUNT_STATE_KEY=wolf15:account:state
ORCHESTRATOR_TRADE_RISK_KEY=wolf15:trade:risk

# Loop tuning (seconds)
ORCHESTRATOR_LOOP_SLEEP_SEC=0.5
ORCHESTRATOR_COMPLIANCE_INTERVAL_SEC=5
ORCHESTRATOR_HEARTBEAT_INTERVAL_SEC=30
```

Operational behavior:

- `evaluate_compliance(account_state, trade_risk)` dieksekusi periodik.
- Severity `critical` memicu mode `KILL_SWITCH`.
- Severity `warning` memicu mode `SAFE`.
- Status/transition dipublish kembali ke channel orchestrator dan disimpan ke `ORCHESTRATOR_STATE_KEY`.

### Ingest Calendar News Runtime (ingest/calendar_news.py)

Environment variables berikut dipakai oleh poller economic calendar berbasis provider chain:

```env
# Enable or disable calendar ingestion loop.
# Default: true
NEWS_INGEST_ENABLED=true

# Polling interval in seconds for provider-chain calendar refresh.
# Default: 300
NEWS_POLL_INTERVAL_SEC=300

# Provider priority selector used by news.provider_selector.
# Default: forexfactory
NEWS_PROVIDER=forexfactory
```

---

## ⚠️ Safety Notes

- Gunakan akun demo/paper sebelum live
- Pastikan `constitution.yaml` thresholds sudah benar
- Pastikan news lock aktif untuk event high impact
- Jangan mengubah struktur repo (LOCKED)

---

## 📜 License

Private / Proprietary (edit sesuai kebutuhan)

---

## 📡 Data Flow

Finnhub API → ingest/ → context/ → analysis/ (L1-L11) → constitution/ (L12) → execution/ → EA
