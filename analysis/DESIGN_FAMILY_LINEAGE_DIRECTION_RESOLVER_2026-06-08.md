# Design — Family Lineage + Microboost Direction Resolver

**Tanggal:** 2026-06-08
**Status:** Design / belum diimplementasikan (menunggu go-ahead scope)
**Sumber masalah:** Analisis 3 file log (`logs.1780975980757`, `…476953`, `…491085`) + verifikasi kode.
**Verdict ringkas:** Sistem sekarang **aman** (tidak ada SignalJSON palsu, NO_TRADE tidak hilang) tapi **belum pintar** — DecisionUpdate kehilangan asal-usul family dan microboost kehilangan arah. Patch ini menambah *makna*, bukan menambah volume log.

---

## 1. Current State (Verified)

| Gejala (dari log) | Akar di kode | Lokasi |
|---|---|---|
| Semua `SignalDecisionUpdateJSON` → `signal_family=SIGNAL_THROTTLE_PRESSURE` | `signal_family` di-hardcode di payload NO_TRADE | `pipeline/wolf_constitutional_pipeline.py:4586` |
| Family kaya tak muncul saat NO_TRADE | Cabang family spesifik (`SIGNAL_THROTTLE_ALLOWED_QUORUM`) hanya menyala untuk verdict EXECUTE | `:4330` di-gate oleh `:4230` (`source_text.startswith("EXECUTE")`) |
| `microboost raw_direction=NONE` | `raw_direction = latest.get("direction")`, dan `PressureBlock.direction` dari event canary NO_TRADE = `None` | `analysis/microboost_event_log.py:152`; `record_pressure_canary` → `normalize_direction(None,"NO_TRADE")=None` |
| Watch hanya `MICROBOOST_WATCH` generik | Tanpa arah, engine tak bisa naik ke family spesifik | `analysis/signal_throttle_log_analyzer.py:1359-1373` |

**Kesimpulan:** Bukan bug fatal — ini efek patch P0 (jangan diam saat pressure non-execute). Cabang yang menyala = `SignalThrottle pressure → NO_TRADE_REASONED`, bukan `Microboost/Pattern → SignalWatch → Decision family spesifik`. Data untuk memperkaya **sudah tersedia** di `report` (`candidate_lifecycle`, `latest_phase`, `allowed_quorum`, `microboost_summary`) dan di analyzer (`_latest_direction_for_symbol`). Tidak perlu sumber data baru.

---

## 2. Requirements

**Functional**
- F1. `SignalDecisionUpdateJSON` mempertahankan lineage: `source_family`, `source_stage`, `resolved_family` (tanpa menghapus `signal_family` parent — kompatibilitas dashboard).
- F2. Microboost dengan `raw_direction=NONE` mencoba mewarisi arah dari SignalThrottleIntel terdekat (symbol sama, dalam jendela waktu), divalidasi terhadap price phase.
- F3. Jika arah tetap tak terselesaikan → status eksplisit `WATCH_ONLY_DIRECTION_MISSING` (bukan diam).
- F4. Family resolver dipanggil sebelum emit DecisionUpdate.
- F5. Summary counter per snapshot/deployment (pressure_decision, microboost_watch, direction_missing, inherited_direction, pattern_resolved).

**Non-functional**
- N1. Zero perubahan pada kontrak keamanan: `valid_for_execution` tetap `false` untuk semua jalur non-execute. Resolver **tidak** boleh menghasilkan eksekusi.
- N2. Aditif & reversibel: semua perilaku baru di balik env flag, default dapat di-rollback.
- N3. Tidak menambah volume emisi (hanya menambah field; tidak menambah baris log).
- N4. Tidak mengubah cara sistem membaca market (hanya pelabelan & inheritance arah untuk observability/lifecycle).

**Constraints**
- C1. Pertahankan boundary yang sudah dikunci test (observability watch ≠ actionable watch).
- C2. Inheritance arah **tidak** otomatis jadi final; tetap lewat validasi price phase + tetap `valid_for_execution=false` sampai finalizer/engine mengonfirmasi.

---

## 3. High-Level Design (Data Flow)

```text
SignalThrottle events ─► SignalThrottleLiveAnalyzer.snapshot() ─► report{
        allowed_quorum, candidate_lifecycle, latest_phase,
        microboost_summary{latest{direction?}}, symbol_activity }
                                   │
                 ┌─────────────────┴───────────────────┐
                 ▼                                       ▼
   [NEW] _resolve_microboost_direction()      [NEW] _resolve_pressure_family()
   (isi direction bila NONE via intel)         (turunkan source/stage/resolved)
                 │                                       │
                 ▼                                       ▼
   microboost_watch_entry / continuation     _no_trade_pressure_decision_update_payload
   (+direction_source)                       _allowed_quorum_decision_update_payload
                 │                                       │ (+source_family,+source_stage,+resolved_family)
                 └───────────────► _emit_signal_json_payload() ──► JSON + [NEW] _bump_family_counters()
```

---

## 4. Deep Dive

### 4.1 Taxonomy 3-tier (jangan buang parent, tambah lineage)

| Field | Peran | Contoh nilai |
|---|---|---|
| `signal_family` | Parent (tetap, kompat dashboard) | `SIGNAL_THROTTLE_PRESSURE`, `SIGNAL_THROTTLE_ALLOWED_QUORUM`, `MICROBOOST_WATCH` |
| `source_family` | Asal-usul sinyal | `ALLOWED_CANARY_QUORUM`, `IGNITION_WATCH`, `TIMING_BLOCK`, `REPEATED_MICROBOOST`, `THEME_PRESSURE`, `THROTTLE_PRESSURE_CANARY` |
| `source_stage` | Tahap pipeline penghasil | `SIGNAL_THROTTLE_INTEL`, `MICROBOOST`, `PRESSURE_BLOCK`, `CANDIDATE_LIFECYCLE` |
| `resolved_family` | Semantik hasil akhir | `NO_TRADE_PRESSURE_TELEMETRY_ONLY`, `WATCH_ONLY_PENDING_DIRECTION`, `WATCH_ONLY_PENDING_CONTEXT`, `TIMING_BLOCK_VALID_WAIT` |
| `direction_source` | Asal arah | `BLOCK_DIRECT`, `INHERITED_FROM_PRESSURE_INTEL`, `DIRECTION_MISSING`, `DIRECTION_CONFLICT_PRICE_PHASE` |

### 4.2 Family resolver (NO_TRADE / allowed-quorum)

Helper baru `_resolve_pressure_family(report, *, symbol, pressure_event_count, microboost_detected) -> dict` — murni, tanpa I/O, deterministik:

```text
quorum         = report["allowed_quorum"]            (sudah dict-safe)
lifecycle      = report["candidate_lifecycle"]["status"]
phase          = report["latest_phase"]
block_ticks    = symbol_activity[sym]["latest_block_effective_ticks"]

if quorum.get("quorum_reached"):        source=ALLOWED_CANARY_QUORUM ; stage=SIGNAL_THROTTLE_INTEL
elif microboost_detected and "REPEATED" in phase: source=REPEATED_MICROBOOST ; stage=MICROBOOST
elif lifecycle == "LATEST_IGNITION_WATCH_ONLY":    source=IGNITION_WATCH ; stage=CANDIDATE_LIFECYCLE
elif lifecycle.startswith("PAIR_SIGNAL_CANDIDATE"):source=TIMING_BLOCK ; stage=CANDIDATE_LIFECYCLE
elif phase in {"THEME_PRESSURE","BROAD_ROTATION_FRAGMENTED"}: source=THEME_PRESSURE ; stage=PRESSURE_BLOCK
else:                                    source=THROTTLE_PRESSURE_CANARY ; stage=SIGNAL_THROTTLE_INTEL

resolved = NO_TRADE_PRESSURE_TELEMETRY_ONLY     # non-execute → selalu telemetry-only di jalur ini
return {source_family, source_stage, resolved_family, family_lineage_version: 1}
```

Semua input sudah ada di `report` — **tidak ada sumber data baru**.

### 4.3 Microboost direction resolver

Helper baru di analyzer `resolve_microboost_direction(block, *, ordered_events, now, window_seconds=600) -> (direction|None, source)`:

```text
if block.direction in {BUY,SELL}:            return (block.direction, "BLOCK_DIRECT")
intel_dir = _latest_directional_event(ordered_events, block.symbol, within=window_seconds)  # reuse _latest_direction_for_symbol
if intel_dir in {BUY,SELL}:
    if _price_phase_consistent(intel_dir, block.m15_phase, block.h1_phase):
        return (intel_dir, "INHERITED_FROM_PRESSURE_INTEL")
    return (None, "DIRECTION_CONFLICT_PRICE_PHASE")
return (None, "DIRECTION_MISSING")
```

Aturan keselamatan (C2): arah warisan **tidak** mempromosikan ke eksekusi; ia hanya mengisi `raw_direction`/`watch_direction` + `direction_source`, supaya engine family (continuation/counter/absorption) bisa mengklasifikasi. `valid_for_execution` tetap `false` sampai finalizer/engine mengonfirmasi via jalur yang sudah ada.

`_price_phase_consistent`: BUY butuh m15/h1 phase tidak bearish-dominan (mis. bukan `BEARISH`+`DOWNTREND`), SELL sebaliknya. Konservatif: bila ambigu → tetap inherit tapi tandai `requires_m15_close=True` (bukan diblok).

### 4.4 Integration points (titik sisip)

| Perubahan | Method | Lokasi |
|---|---|---|
| Panggil `_resolve_pressure_family`, merge 3 field ke payload | `_no_trade_pressure_decision_update_payload` | `:4582-4586` (saat membangun dict) |
| Idem untuk jalur quorum | `_allowed_quorum_decision_update_payload` | `:4323-4330` |
| Resolusi arah saat membangun watch/continuation | `_microboost_watch_payload` / `_continuation_entry_payload` | `analysis/signal_throttle_log_analyzer.py:1359`, `:1294` |
| Counter | helper baru `_bump_family_counters`, dipanggil di `_emit_signal_json_payload` | titik emit terpusat |

### 4.5 Summary counters

Dict proses-lokal `self._family_counters` (atau di `report["family_counters"]`), di-bump saat emit:
`pressure_decision_count`, `microboost_watch_count`, `direction_missing_count`, `inherited_direction_count`, `pattern_resolved_count`. Di-flush ke satu baris `MicroboostTable`/intel ringkas per N detik (reuse mekanisme dedupe yang ada).

---

## 5. Trade-off Analysis

| Keputusan | Plus | Minus / risiko | Mitigasi |
|---|---|---|---|
| Tambah field lineage (bukan ganti parent) | Kompat dashboard, info kaya | Payload sedikit lebih besar | 3-4 field kecil saja |
| Inherit arah dari intel | Microboost bisa naik family | Arah warisan bisa salah | Validasi price phase + `valid_for_execution=false` + `direction_source` jelas |
| Resolver deterministik dari `report` | Mudah diuji, tanpa data baru | Bergantung kualitas `candidate_lifecycle` | Sudah teruji di modul analyzer |
| Env-flag gating | Rollback instan | Dua jalur kode sementara | Hapus flag setelah stabil |

---

## 6. Rollout & Flags

- `SIGNAL_FAMILY_LINEAGE_ENABLED` (default `true`) — aktifkan field `source_family/source_stage/resolved_family`.
- `MICROBOOST_DIRECTION_INHERIT_ENABLED` (default `true`) — aktifkan resolver arah.
- `MICROBOOST_DIRECTION_INHERIT_WINDOW_SECONDS` (default `600`).
- Rollback: set flag `false` → payload kembali ke perilaku sekarang.

Urutan rilis: (1) lineage fields dulu (paling aman, murni label) → (2) direction resolver → (3) counters.

---

## 7. Test Plan

1. `_resolve_pressure_family`: tabel input→output untuk tiap source_family (quorum, ignition, repeated, timing, theme, canary).
2. Direction resolver: (a) block punya arah → BLOCK_DIRECT; (b) NONE + intel searah + phase konsisten → INHERITED; (c) NONE + intel lawan phase → CONFLICT; (d) NONE tanpa intel → DIRECTION_MISSING.
3. Invariant keamanan: semua output jalur non-execute tetap `valid_for_execution=false`.
4. Regresi: payload NO_TRADE lama tetap punya `signal_family=SIGNAL_THROTTLE_PRESSURE` (parent tak berubah).
5. Counters: jumlah cocok dengan emisi.

---

## 8. Tech-Debt Register (terprioritas)

| ID | Item | Dampak | Effort | Prioritas |
|---|---|---|---|---|
| TD-1 | `signal_family` di-hardcode per cabang; tak ada lineage | Kehilangan signal intelligence di dashboard/analitik | S | **P0** |
| TD-2 | Microboost kehilangan arah (`raw_direction=NONE`) → semua jadi WATCH generik | Family kaya tak pernah terbentuk | M | **P0** |
| TD-3 | Family logic tersebar (hardcode string di banyak payload) | Sulit dirawat, rawan drift | M | P1 |
| TD-4 | Tidak ada counter/observability lineage per deployment | Sulit ukur efektivitas patch | S | P1 |
| TD-5 | `_price_phase_consistent` belum ada (validasi arah) | Risiko inherit arah salah | S | P1 |
| TD-6 | Taxonomy family belum terpusat (enum/const) | String magic, typo-prone | S | P2 |
| TD-7 | Cabang allowed-quorum hanya EXECUTE; tak ada decision untuk quorum non-execute | Kasus quorum-tanpa-eksekusi kurang terlabel | M | P2 |

Rekomendasi: kerjakan **TD-1 + TD-2 bersama** (satu sprint "Family Lineage + Direction Resolver"), karena TD-2 memberi arah yang membuat TD-1 menghasilkan family yang benar-benar kaya.

---

## 9. Yang TIDAK diubah (sesuai audit sebelumnya)

- Boundary observability-vs-actionable watch (dikunci `test_generic_microboost_watch_is_not_tracked_for_finalization`).
- Kontrak `valid_for_execution` (tetap dipisah dari validity analisa).
- M15 close tetap bukan gate universal.
- Theme tetap booster/context, bukan blocker hidup-mati.

---

## 10. Definition of Done

- DecisionUpdate memuat `source_family/source_stage/resolved_family` dan **mulai bervariasi** (bukan 100% `SIGNAL_THROTTLE_PRESSURE`).
- Microboost yang punya intel searah menampilkan `direction_source=INHERITED_FROM_PRESSURE_INTEL`; sisanya `WATCH_ONLY_DIRECTION_MISSING` (eksplisit, tidak diam).
- Semua test baru hijau; invariant keamanan tetap.
- Counter lineage muncul per deployment.

---

## 11. Addendum v2 — Koreksi pasca-review (LOCKED)

Hasil review menyetujui arah besar + menambah 4 koreksi production-safety. Semua dikunci di sini sebagai spec final untuk Fase 2-3.

### 11.1 Koreksi 1 — `direction_confidence` (wajib di setiap output yang punya arah)

| `direction_source` | `direction_confidence` |
|---|---|
| `BLOCK_DIRECT` | `HIGH` |
| `INHERITED_FROM_PRESSURE_INTEL` | `MEDIUM` |
| `INHERITED_BUT_PHASE_AMBIGUOUS` | `LOW` |
| `DIRECTION_CONFLICT_PRICE_PHASE` | `REJECTED` |
| `DIRECTION_CONFLICT_RECENT_INTEL` | `REJECTED` |
| `DIRECTION_MISSING` | `NONE` |

Arah warisan **tidak** setara arah asli — dashboard/analitik harus bisa membedakan.

### 11.2 Koreksi 2 — guard intel basi / berlawanan (sebelum inherit)

Inherit hanya bila SEMUA benar:
- symbol sama;
- intel arah dalam `window_seconds` (default 600);
- `cluster_id`/pressure-block sama bila tersedia;
- **tidak ada** intel arah berlawanan yang lebih baru dalam window.

Aturan tolak:
```text
ada opposite directional intel lebih baru di window → JANGAN inherit
  → direction_source = DIRECTION_CONFLICT_RECENT_INTEL ; confidence = REJECTED
intel arah terbaru lebih tua dari window → direction_source = DIRECTION_MISSING ; confidence = NONE
```

### 11.3 Koreksi 3 — `_price_phase_consistent` presisi (bukan sekadar "bukan bearish")

```text
BUY inherit valid jika:
  - m15_phase ∉ {BEARISH_BREAKDOWN, STRONG_BEARISH}
  - h1_phase  ≠ DOWNTREND_STRONG
  - NOT (price_position == MAIN_RESISTANCE AND phase_priced == RESISTANCE_PRESSURE_WARNING)
SELL inherit valid jika:
  - m15_phase ∉ {BULLISH_BREAKOUT, STRONG_BULLISH}
  - h1_phase  ≠ UPTREND_STRONG
  - NOT (price_position == MAIN_SUPPORT AND phase_priced == SUPPORT_RECLAIM_WARNING)

Bila price phase AMBIGU (bukan konsisten, bukan konflik tegas):
  - inherit BOLEH, tapi:
    status = WATCH_ONLY_PENDING_CONTEXT
    direction_source = INHERITED_BUT_PHASE_AMBIGUOUS ; confidence = LOW
    requires_m15_close = true ; valid_for_execution = false
Bila price phase KONFLIK tegas (mis. BUY di MAIN_RESISTANCE + RESISTANCE_PRESSURE_WARNING):
  - direction_source = DIRECTION_CONFLICT_PRICE_PHASE ; confidence = REJECTED
  - final_direction = WAIT
```

### 11.4 Koreksi 4 — `family_lineage_reason` ✅ SUDAH DIIMPLEMENTASI (Fase 1)

`_pressure_family_lineage` kini mengembalikan `family_lineage_reason` (alasan singkat per `source_family`, mis. `allowed_quorum_reached_but_execution_quality_missing`). Tetap ringkas, tidak menggemukkan log.

### 11.5 `schema_version` — PROPOSAL, butuh keputusan terpisah

Output ideal review memuat `schema_version: "2.1-family-lineage"`. Ini **payload-level & cross-cutting** (mempengaruhi SEMUA payload, bukan hanya 2 ini) → diputuskan terpisah agar tidak inkonsisten antar-event. **Tidak** ditambahkan di Fase 1.

### 11.6 Anti-pattern yang DILARANG

```text
SALAH:  raw_direction NONE → inherit BUY → MICROBOOST_CONTINUATION → SignalJSON BUY
BENAR:  raw_direction NONE → inherit BUY → MICROBOOST_WATCH_WITH_INHERITED_DIRECTION
        → price-phase validation → pattern classification → finalizer → baru Valid/Wait/NoTrade
```
Inheritance hanya membuka **pintu klasifikasi**, bukan pintu eksekusi. `valid_for_execution` tetap `false`.

### 11.7 5 Tes wajib untuk direction resolver (Fase 3)

1. Inherited direction **tidak** membuat execution true → `valid_for_execution==false` & `direction_source==INHERITED_FROM_PRESSURE_INTEL`.
2. Opposite intel lebih baru → `direction_source==DIRECTION_CONFLICT_RECENT_INTEL` (bukan inherit arah lama).
3. Intel lebih tua dari window → `direction_source==DIRECTION_MISSING`.
4. Price-phase conflict (BUY @ MAIN_RESISTANCE + RESISTANCE_PRESSURE_WARNING) → `DIRECTION_CONFLICT_PRICE_PHASE` & `final_direction==WAIT`.
5. Parent kompat → `signal_family` tetap `SIGNAL_THROTTLE_PRESSURE`; `source_family` & `resolved_family` ada.

### 11.8 Urutan implementasi final (7 step)

```text
Step 1 — taxonomy constants/enum            (kurangi string magic; TD-6)
Step 2 — lineage resolver only              ✅ DONE (Fase 1)
Step 3 — lineage fields ke NO_TRADE+quorum  ✅ DONE (Fase 1) + family_lineage_reason ✅
Step 4 — counters                           ◀ FASE BERIKUTNYA (low-risk)
Step 5 — direction resolver (flag)          (medium-risk; pakai guard 11.2)
Step 6 — price-phase guard                  (11.3) + direction_confidence (11.1)
Step 7 — canary deploy 6 jam, lalu evaluasi
```

### 11.9 `direction_source` enum (final)

`BLOCK_DIRECT` · `INHERITED_FROM_PRESSURE_INTEL` · `INHERITED_BUT_PHASE_AMBIGUOUS` · `DIRECTION_CONFLICT_PRICE_PHASE` · `DIRECTION_CONFLICT_RECENT_INTEL` · `DIRECTION_MISSING`

### 11.10 Klasifikasi sprint

```text
Sprint P1 — Family Lineage + Microboost Direction Resolver
Priority: P0/P1 hybrid · Risk: Low–Medium · Impact: High
Pagar tetap: jangan ubah contract eksekusi, jangan tambah volume log,
             jangan jadikan inherited direction entry otomatis.
```
