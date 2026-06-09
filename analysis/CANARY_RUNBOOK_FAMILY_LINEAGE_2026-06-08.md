# Canary Runbook — Family Lineage + Microboost Direction Resolver

**Tanggal:** 2026-06-08
**Tujuan:** Membuktikan runtime behavior patch Step 2-6 (lineage + counters + direction resolver). **Tidak menambah logic** — hanya validasi.
**Prinsip:** Keputusan tuning HANYA berdasarkan counter, bukan feeling.

---

## 0. Pre-flight (lokal, sebelum deploy)

```bash
# Semua tes yang relevan harus hijau:
pytest \
  tests/test_pressure_family_lineage.py \
  tests/test_family_counters.py \
  tests/test_microboost_direction_resolver.py \
  tests/test_official_watch_lifecycle_tracking.py \
  tests/test_signal_block_finalizer.py \
  tests/test_pipeline_signal_json_continuation.py \
  tests/test_signal_throttle_log_analyzer.py -q

# (Saat virtualisasi/pyright tersedia) sanity tipe:
pyright analysis/signal_throttle_log_analyzer.py pipeline/wolf_constitutional_pipeline.py
```

**Gate 0:** semua tes hijau + tidak ada error pyright pada 2 file di atas. Kalau merah → **stop**, perbaiki dulu.

---

## 1. Canary 1 — Lineage + Counters ON, Resolver OFF

**Env:**
```env
SIGNAL_FAMILY_LINEAGE_ENABLED=true
SIGNAL_FAMILY_COUNTERS_ENABLED=true
MICROBOOST_DIRECTION_INHERIT_ENABLED=false
```

**Durasi:** 3-6 jam (ambil baseline).

**Yang dipantau (dari `report["family_counters"]` + log):**
- `direction_missing_count` → **baseline** masalah arah saat ini.
- `stale_intel_count` → seberapa sering intel arah ada tapi basi.
- `pressure_decision_count`, `microboost_watch_count` → volume normal.
- DecisionUpdate mulai bervariasi: `source_family` ∈ {ALLOWED_CANARY_QUORUM, REPEATED_MICROBOOST, TIMING_BLOCK, IGNITION_WATCH, THEME_PRESSURE, THROTTLE_PRESSURE_CANARY} — **bukan** 100% generik.

**Gate lulus Canary 1 (semua harus benar):**
- [ ] `microboost_direction_resolver_enabled = false` di snapshot (konfirmasi resolver dorman).
- [ ] Tidak ada error serialization / exception baru di log.
- [ ] Jumlah `SignalJSON` (final execution) **tidak berubah** vs sebelum patch.
- [ ] Semua SignalWatch/DecisionUpdate tetap `valid_for_execution=false`.
- [ ] `source_family` bervariasi (bukan satu nilai saja).

Kalau lolos → catat baseline counter, lanjut Canary 2.

---

## 2. Canary 2 — Resolver ON, window 600

**Env (ubah satu baris):**
```env
MICROBOOST_DIRECTION_INHERIT_ENABLED=true
MICROBOOST_DIRECTION_INHERIT_WINDOW_SECONDS=600
```

**Durasi:** 3-6 jam, dibandingkan langsung dengan baseline Canary 1.

**Yang HARUS naik / muncul:**
- [ ] `inherited_direction_count` naik dari ~0.
- [ ] `direction_source = INHERITED_FROM_PRESSURE_INTEL` muncul di SignalWatch.
- [ ] `resolved_family` watch tidak lagi selalu `WATCH_ONLY_DIRECTION_MISSING` (sebagian jadi `WATCH_ONLY_PENDING_CONTEXT`).
- [ ] `direction_missing_count` turun relatif terhadap baseline.

**Yang DILARANG terjadi (fail = rollback langsung):**
- [ ] `valid_for_execution` **tiba-tiba true** pada path inherited-only.
- [ ] `SignalJSON` (final) naik **hanya** karena inherited direction.
- [ ] `latest["direction"]` berubah (engine continuation/counter ikut bergeser).
- [ ] `microboost_counter_entry` / `continuation_entry` naik tidak wajar.
- [ ] Error/exception baru.

### Rubrik LULUS (kriteria Anda, dikunci)
```text
PASS jika:
  inherited_direction_count NAIK
  DAN SignalJSON (final) TIDAK melonjak
  DAN tidak ada valid_for_execution=true dari inherited-only path
  DAN latest["direction"] tidak berubah
```
Kalau keempatnya benar → **patch LULUS**.

---

## 3. Canary 3 — Tuning window (HANYA berdasarkan counter)

| Pengamatan counter | Aksi |
| --- | --- |
| `price_phase_conflict_count` tinggi **dan** `inherited_direction_count` tinggi | window terlalu longgar → `MICROBOOST_DIRECTION_INHERIT_WINDOW_SECONDS=300` |
| `recent_conflict_count` tinggi | intel campur arah terlalu sering → kecilkan window → `300` |
| `inherited_direction_count` rendah **tapi** `direction_missing_count`/`stale_intel_count` masih tinggi | window terlalu ketat → `900` |
| Seimbang (inherited naik sehat, conflict rendah) | **biarkan 600** (default rasional) |

Ubah **satu variabel** (window) per iterasi. Jangan ubah hal lain bersamaan.

---

## 4. Rollback (instan, tanpa redeploy kode)

| Gejala | Aksi rollback |
| --- | --- |
| Ada `valid_for_execution=true` dari inherited-only / SignalJSON melonjak | `MICROBOOST_DIRECTION_INHERIT_ENABLED=false` |
| Lineage bikin masalah serialization/dashboard | `SIGNAL_FAMILY_LINEAGE_ENABLED=false` |
| Counter bikin noise/masalah | `SIGNAL_FAMILY_COUNTERS_ENABLED=false` |

Semua flag bisa di-flip tanpa build ulang. Kode tetap ter-deploy; hanya perilaku yang dimatikan.

---

## 5. Acceptance & promote ke default

Setelah Canary 2 LULUS dan Canary 3 menemukan window stabil:
- [ ] Catat window final yang dipilih.
- [ ] Buat commit terpisah yang mengubah **default** `MICROBOOST_DIRECTION_INHERIT_ENABLED` jadi `true` (dan window terpilih) — di `signal_throttle_log_analyzer.py` (`_apply_microboost_direction_inheritance` / `_env_bool` default) dan `pyrightconfig`/env docs.
- [ ] (Opsional, P2) kerjakan Step 1: taxonomy constants/enum agar string family tidak tersebar.

---

## Lampiran — Flag & counter ringkas

**Flag:**
| Flag | Default | Fase |
| --- | --- | --- |
| `SIGNAL_FAMILY_LINEAGE_ENABLED` | true | Lineage |
| `SIGNAL_FAMILY_COUNTERS_ENABLED` | true | Counters |
| `MICROBOOST_DIRECTION_INHERIT_ENABLED` | **false** | Resolver (nyalakan saat Canary 2) |
| `MICROBOOST_DIRECTION_INHERIT_WINDOW_SECONDS` | 600 | Tuning Canary 3 |

**`report["family_counters"]`:** `pressure_decision_count`, `microboost_watch_count`, `direction_missing_count`, `inherited_direction_count`, `pattern_resolved_count`, `phase_ambiguous_count`, `recent_conflict_count`, `price_phase_conflict_count`, `stale_intel_count`, `microboost_direction_resolver_enabled`, `direction_inheritance_window_seconds`.

**`direction_source` enum:** `BLOCK_DIRECT` (HIGH) · `INHERITED_FROM_PRESSURE_INTEL` (MEDIUM) · `INHERITED_BUT_PHASE_AMBIGUOUS` (LOW, requires_m15_close) · `DIRECTION_CONFLICT_PRICE_PHASE` (REJECTED) · `DIRECTION_CONFLICT_RECENT_INTEL` (REJECTED) · `DIRECTION_STALE_INTEL` (NONE) · `DIRECTION_MISSING` (NONE).
