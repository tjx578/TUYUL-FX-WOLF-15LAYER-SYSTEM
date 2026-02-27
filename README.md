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

⚠️ File di folder `docs/` **tidak pernah dipanggil oleh kode**.

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
     - Gate: lint, type check, constitutional boundary, tests, coverage, dashboard build, dan **secret scan (gitleaks)**

- Deploy workflow: `.github/workflows/railway-deploy.yml`
  - Trigger otomatis: hanya setelah workflow `CI` sukses di branch `main`
    - Trigger manual: `workflow_dispatch`

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
