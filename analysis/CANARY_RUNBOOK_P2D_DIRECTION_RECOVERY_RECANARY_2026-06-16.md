# Re-Canary Runbook — P2D′ Direction Recovery (Diagnostics-Source Recovery)

**Tanggal:** 2026-06-16
**Keputusan owner:** **C — re-canary P2D′ direction recovery** (stack/canary terpisah, **bukan** merge production).
**Stack terpisah = branch `p2d-direction-diagnostic-source-recovery`** (origin HEAD `1fd0da05`, diff vs main = **+201/−0**, **belum** merge ke main).
**Sifat patch:** P2D′ sudah ter-deploy di branch-nya & flag-guarded (default OFF). Re-canary ini **tidak menambah logic** — hanya menyalakan flag di stack terpisah dan **mengukur** apakah arah pulih.

> **P2D′ ≠ `MICROBOOST_DIRECTION_INHERIT_ENABLED`.** Yang terakhir adalah cross-tick *watch-path* resolver (langkah P1 terpisah/berikutnya) yang justru **menolak** counter setup (BUY-at-resistance → `DIRECTION_CONFLICT_PRICE_PHASE`) dan hanya menulis `inherited_direction` ke jalur watch. Bukan itu yang dimaksud C.
> P2D′ = **`_recover_direction_from_diagnostics`** — Akar #2 right-sized patch.

> Melanjutkan, bukan menggantikan: [`CANARY_RUNBOOK_FAMILY_LINEAGE_2026-06-08.md`](CANARY_RUNBOOK_FAMILY_LINEAGE_2026-06-08.md) (C2 + resolver lineage).

---

## 0. Posisi keputusan (locked)

```text
Next step : C — re-canary P2D′ direction recovery (branch p2d-direction-diagnostic-source-recovery)
HTF feed  : HOLD   (HTF_STRUCTURE_SNAPSHOT_ENABLED / HTF_DAILY_PHASE_FEED_ENABLED tetap false)
Merge P2A : HOLD   (preview flags tetap false; A jadi acceptance BERIKUTNYA setelah P2D′ pulih)
A         : tetap acceptance berikutnya setelah direction recovery terbukti
```

Alasan: A pasif; C memperbaiki akar yang menghambat A. Menunggu EARLY_SELL saat `raw_direction_missing` masih dominan = panen `DIRECTION_NOT_RESOLVED` lagi. Yang menahan directional preview = **arah tidak sampai ke Watch** (regresi 8–9 Jun).

---

## 1. Apa yang P2D′ lakukan (verified 2026-06-16)

`pipeline/wolf_constitutional_pipeline.py`:
- `_recover_direction_from_diagnostics(execution)` (`:4055`) — fires **hanya** saat primary sources tidak punya arah (kasus non-execute di mana `execution.direction` sudah dikolaps ke `HOLD` oleh `resolve_trade_direction`, reason `no_l3_direction` / `direction_conflict`).
- Membaca bias per-layer yang **selamat** di `execution.direction_diagnostics.sources` (iterasi l3→l2→l1→l9).
- **Conflict-safe:** ada `conflicts` list non-kosong ATAU layer tidak sepakat → `None` (sistem tidak pernah menebak).
- Hanya men-seed `raw_direction` (untuk klasifikasi counter/continuation, mis. BUY stalled-at-resistance → SELL absorption watch). **Tidak pernah** men-set `final_direction` / `valid_for_execution`; **tidak pernah** emit `SignalJSON`.
- Dipasang sebagai fallback di `_resolve_pressure_observation_direction` (`:4049`) yang menyala HANYA bila primary `found` kosong; primary conflict (len>1) tetap `None`.

**Inilah jaminan struktural** untuk gerbang owner `valid_for_execution=0` & `SignalJSON=0`: P2D′ secara konstruksi tidak menyentuh jalur eksekusi.

---

## 2. Gate 0 — Pre-flight (SUDAH HIJAU 2026-06-16, di branch p2d)

```bash
git checkout p2d-direction-diagnostic-source-recovery
python -m pytest \
  tests/test_pressure_direction_recovery.py \
  tests/test_golden_reference_may27_direction_aware.py -q
```

**Hasil 2026-06-16:** `21 passed` (17 recovery + 4 golden May-27). ✅ Gate 0 LULUS → boleh lanjut canary.

Golden May-27 mengunci otak yang utuh: BUY@MAIN_RESISTANCE+RESISTANCE_PRESSURE_WARNING → `EARLY_SELL_WATCH` (raw=BUY, candidate=SELL, final=WAIT, requires_m15_close=true); SELL@MAIN_SUPPORT → `EARLY_BUY_WATCH`; directionless → counter NONE; counter watch never executable.

---

## 3. Stack canary terpisah (deploy branch p2d, env — SAFE STACK)

Deploy **branch `p2d-direction-diagnostic-source-recovery`** sebagai stack/canary terpisah (bukan main). Env override:

```env
# --- P2D′ recovery: ON (inti re-canary) ---
SIGNAL_THROTTLE_PRESSURE_DIRECTION_RECOVERY=true          # master (default true)
SIGNAL_THROTTLE_PRESSURE_DIRECTION_FROM_DIAGNOSTICS=true  # P2D′ sub-flag (default OFF → ON)

# --- Tetap HOLD (jangan dinyalakan di canary ini) ---
MICROBOOST_DIRECTION_INHERIT_ENABLED=false               # cross-tick watch resolver = langkah terpisah
HTF_STRUCTURE_SNAPSHOT_ENABLED=false
HTF_DAILY_PHASE_FEED_ENABLED=false
SIGNAL_WATCH_MARKET_STRUCTURE_PREVIEW_ENABLED=false
SIGNAL_WATCH_MARKET_STRUCTURE_STATUS_ENABLED=false

# --- Eksekusi tetap terkunci (konstitusional) ---
TRADING_MODE=paper
ALLOW_MARKET_EXECUTION=false
ALLOW_DASHBOARD_WRITE=false
```

**Durasi:** 1 single-deployment log minimal (idealnya 3–6 jam), dibandingkan dengan baseline sub-flag OFF.
**Alat ukur:** `promotion_audit.py` funnel compare (di Downloads) + `report["family_counters"]`. Keputusan HANYA dari counter, bukan feeling.

---

## 4. Acceptance P2D′ canary (gerbang owner — LOCKED)

PASS jika SEMUA benar:

```text
[ ] raw_direction_missing / direction_missing_count TURUN signifikan vs baseline
[ ] watch_direction / candidate_direction MULAI MUNCUL (raw_direction ter-recover)
[ ] DIRECTION_NOT_RESOLVED tidak lagi mendominasi semua Watch
[ ] family MICROBOOST_COUNTER_ENTRY / EARLY_SELL_WATCH kembali muncul (otak May-27 hidup lagi)
[ ] valid_for_execution=true  ==  0   (tetap nol)
[ ] SignalJSON (final)        ==  0   (tidak ada perubahan)
[ ] tidak ada perubahan agresif ke execution; tidak ada exception/serialization error baru
```

FAIL = rollback instan (§6).

---

## 5. Diagnosa Akar #1 vs Akar #2 (baca counter dengan benar)

Re-canary ini sekaligus tes diagnostik **di mana** regresi 8–9 Jun berada:

| Pola hasil | Interpretasi | Tindakan |
| --- | --- | --- |
| `direction_missing` TURUN, COUNTER/EARLY_SELL kembali | Bias per-layer selamat di `direction_diagnostics.sources`; P2D′ (Akar #2) memang pemulihnya | ✅ Recovery terbukti — lanjut A |
| `direction_missing` tetap tinggi, recovery ~0 | `direction_diagnostics.sources` juga kosong → akarnya lebih dalam di **Akar #1** (`resolve_trade_direction` kolaps ke HOLD, synthesis.py:74-137) | ⛔ P2D′ tidak cukup; perlu fix Akar #1 (risk medium, scope terpisah) sebelum A |
| `valid_for_execution=true` muncul / SignalJSON melonjak | Pelanggaran kontrak (seharusnya mustahil secara struktural) | ⛔ Rollback + investigasi regresi kontrak |

> Kunci: kalau baris-1 menyala → C berhasil, gerbang A jadi realistis.
> Kalau baris-2 → C membuktikan akar sebenarnya **Akar #1 collapse-to-HOLD** (temuan berharga, bukan kegagalan canary).

---

## 6. Rollback (instan, tanpa redeploy kode)

| Gejala | Aksi |
| --- | --- |
| `valid_for_execution=true` / SignalJSON melonjak / error baru | `SIGNAL_THROTTLE_PRESSURE_DIRECTION_FROM_DIAGNOSTICS=false` |
| Recovery (C2 + P2D′) bermasalah total | `SIGNAL_THROTTLE_PRESSURE_DIRECTION_RECOVERY=false` (matikan kedua jalur) |

Flag flip tanpa build ulang. Kode tetap ter-deploy; hanya perilaku yang dimatikan.

---

## 7. Setelah P2D′ LULUS → barulah A

```text
1. Capture window directional Watch (EARLY_SELL / SELL_REJECTION / BUY_RECLAIM).
2. Validasi P2A degenerate guard pada case directional REAL:
   SL degenerate → STRUCTURE_PENDING (bukan STRUCTURE_READY palsu).
3. Kalau guard bersih live → baru pertimbangkan HTF swing-structure feed (HOLD sampai sini).
```

B (validasi degenerate guard) tidak didahulukan: guard sudah code-proven tapi belum live-proven pada case directional. Tutup blind-spot arah dulu (C), baru kunci guard (A) dengan window EARLY_SELL nyata.

---

## Lampiran — promote ke default (setelah LULUS)

Bila acceptance §4 LULUS dan funnel `promotion_audit.py` mengonfirmasi:
- [ ] Commit terpisah ubah **default** `SIGNAL_THROTTLE_PRESSURE_DIRECTION_FROM_DIAGNOSTICS` → `true` (di `.env.example` + dokumentasi).
- [ ] PR squash-merge `p2d-direction-diagnostic-source-recovery` → main (menormalkan 3 commit "Update X" jadi satu pesan konvensional).
- [ ] Baru jadwalkan langkah A (P2A degenerate guard pada window EARLY_SELL).
