# ✅ GO-LIVE CHECKLIST — PROP FIRM (STAGED)

## TUYUL FX WOLF 15-LAYER SYSTEM

> Prinsip utama: **jangan langsung full capital**. Go-live harus bertahap,
> terukur, dan bisa rollback kapan pun ada anomali.

---

## 0) BASELINE (WAJIB SEBELUM PHASE)

- [ ] `.env` valid (API key, JWT, Redis, DB)
- [ ] Semua test kritikal pass (`pytest -q`)
- [ ] Batas otoritas tetap aman:
  - [ ] `constitution/` tetap jadi decision authority tunggal (L12)
  - [ ] `execution/` hanya executor (tanpa logic arah market)
  - [ ] dashboard tidak override verdict L12
- [ ] News lock + M15 cancel + prop guard berfungsi
- [ ] Journal append-only aktif (J1–J4, termasuk reject)

---

## 1) PHASE 3 — STAGED GO LIVE

### STEP 1 — Shadow Mode (1–3 hari)

**Tujuan:** validasi alur tanpa kirim order ke broker.

- [ ] Set mode eksekusi ke dry validation (`TUYUL_EXECUTION_MODE=DRY`)
- [ ] Signals tetap berjalan
- [ ] Risk calculation tetap berjalan
- [ ] Tidak ada routing order LIVE ke broker/EA
- [ ] Simpan semua verdict + hasil risk preview + rejection reason
- [ ] Bandingkan hasil sistem vs ekspektasi manual
- [ ] Jika ada anomaly -> fix dulu, ulang shadow sampai stabil

**Exit criteria Step 1:**

- [ ] Tidak ada mismatch mayor di verdict/risk
- [ ] Tidak ada error berulang di journal/event pipeline

---

### STEP 2 — Micro Capital Mode (7 hari)

**Tujuan:** validasi eksekusi real dengan eksposur minimum.

Parameter operasi:

- [ ] Risk per trade = **0.1%**
- [ ] Max open trade = **1**
- [ ] `execute_all` / auto-take-all **disabled** (manual/terkontrol)

Monitoring wajib:

- [ ] DD calculation akurat
- [ ] Risk preview ≈ realized risk
- [ ] EA confirmation flow stabil (placed -> filled/cancelled)
- [ ] Trade close reliability stabil

**Exit criteria Step 2:**

- [ ] Tidak ada DD miscalculation
- [ ] Tidak ada double execute
- [ ] Tidak ada race condition signifikan

---

### STEP 3 — Controlled Scale

**Tujuan:** naikkan kapasitas secara konservatif setelah micro stabil.

- [ ] Risk per trade naik ke **0.3%**
- [ ] Max open trades naik ke **2**
- [ ] Compliance mode tetap **ON**
- [ ] Tetap monitor metrik Step 2 (DD, preview accuracy, confirm, close)

**Exit criteria Step 3:**

- [ ] Stabil minimal beberapa siklus pasar/session
- [ ] Tidak ada pelanggaran guard/compliance

---

### STEP 4 — Full Production

Full production hanya jika seluruh syarat berikut lolos:

- [ ] Tidak ada auth issue
- [ ] Tidak ada DD miscalc
- [ ] Tidak ada double execute
- [ ] Tidak ada race condition
- [ ] Audit log stabil
- [ ] WebSocket stabil

---

## 2) INFRASTRUCTURE CHECKLIST (SEBELUM LIVE)

- [ ] TLS enabled
- [ ] CORS restricted (hanya origin resmi)
- [ ] ENV secrets tidak ada di repo
- [ ] DB backup aktif (terjadwal + teruji restore)
- [ ] Redis persistence aktif (RDB/AOF sesuai target RPO)
- [ ] Health endpoint dimonitor (HTTP + Redis + constitutional health)
- [ ] Auto-restart aktif (service manager/platform)
- [ ] Log rotation aktif
- [ ] Alerts aktif untuk:
  - [ ] EA disconnect
  - [ ] DD > 70%
  - [ ] WS drop rate spike
  - [ ] Error rate spike

---

## 3) FINAL DECLARATION

Checklist complete = **safe to scale**.

Jika ada 1 item kritikal gagal -> **rollback ke phase sebelumnya**,
bukan dipaksa lanjut.

---

Dokumen ini **WAJIB** dipakai sebagai gate operasional sebelum live prop firm.
