# 🐺 TUYUL FX — WOLF 15-LAYER SYSTEM (v7.4r∞)

> **Status:** 🟢 FINAL · LOCKED · LIVE READY  
> **Scope:** LIVE TRADING · EA · DASHBOARD · PROP FIRM  
> **Authority:** **Layer-12 ONLY (Constitution Zone)**  
> **Execution Mode:** **TP1_ONLY** · **Pending Orders Only** · **No Market Execution**

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

Twelve Data
↓
ingest/ (feed + candle builder)
↓
context/ (Live Context Bus)
↓
analysis/ (L1–L11) + synthesis.py
↓
constitution/ (gatekeeper.py + verdict_engine.py) ← L12 FINAL
↓
execution/ (pending/cancel/expiry/guard/state machine)
↓
ea_interface/ (command schema)
↓
Broker/EA Executor


---

## 📁 Repo Structure (High-Level)

- `config/` : semua konfigurasi (pairs, prop-firm, telegram, thresholds constitution)
- `ingest/` : realtime feed + news + candle builder
- `context/` : unified market state (read-only)
- `analysis/` : L1–L11 + synthesis (candidate setup)
- `constitution/` : Gatekeeper + L12 Verdict + audit log (sole authority)
- `execution/` : pending placement + cancel + expiry + execution guard
- `news/` : news lock engine
- `risk/` : prop-firm rules, drawdown, risk multiplier
- `alerts/` : telegram notifier + formatter
- `dashboard/` : backend API (read-only) + frontend UI
- `storage/` : redis snapshot + trade journal
- `schemas/` : JSON schemas (L12, L14, alerts)
- `ea_interface/` : command schema + sync contract
- `tests/` : unit tests untuk gate/news/cancel/prop-firm
- `scripts/` : run scripts + health check

---

## ✅ Quick Start

### 1) Setup Environment
```bash
python -m venv .venv
source .venv/bin/activate   # windows: .venv\Scripts\activate
pip install -r requirements.txt
2) Configure Env
Copy .env.example → .env dan isi key yang diperlukan:

cp .env.example .env
3) Run (Live Or Paper)
Live engine:

bash scripts/run_live.sh
Dashboard:

bash scripts/run_dashboard.sh
Catatan: file main.py adalah entrypoint dan tidak boleh berisi logic analisis/eksekusi.

🧪 Run Tests
pytest -q
Test penting:

tests/test_l12_gate.py : L12 tidak bisa bypass

tests/test_news_lock.py : news lock bekerja

tests/test_m15_cancel.py : M15 cancel-only

tests/test_prop_firm.py : aturan prop-firm

🔐 Logging & Audit
Semua gate failure dicatat via constitution/violation_log.py

Snapshot JSON untuk L14 disimpan via storage/snapshot_store.py

Dashboard hanya membaca state & audit output, tidak bisa memodifikasi apa pun

🧩 Environment Variables
Lihat .env.example untuk daftar lengkap.

⚠️ Safety Notes
Gunakan akun demo/paper sebelum live

Pastikan constitution.yaml thresholds sudah benar

Pastikan news lock aktif untuk event high impact

Jangan mengubah struktur repo (LOCKED)

📜 License
Private / Proprietary (edit sesuai kebutuhan)
