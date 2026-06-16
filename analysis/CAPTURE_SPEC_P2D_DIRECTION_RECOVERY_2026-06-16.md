# P2D′ Direction Recovery — Canary Capture Spec

**Tanggal:** 2026-06-16
**Status:** Locked work-decision (owner). Telemetry **belum diimplementasi** — spec ini kontraknya.
**Branch:** `p2d-direction-diagnostic-source-recovery`
**Pendamping:** [`CANARY_RUNBOOK_P2D_DIRECTION_RECOVERY_RECANARY_2026-06-16.md`](CANARY_RUNBOOK_P2D_DIRECTION_RECOVERY_RECANARY_2026-06-16.md)

---

## 0. Koreksi yang dikunci (hasil trace kode 2026-06-16)

```text
- P2D′ live recovery BELUM terbukti.
- BUY di DecisionUpdate allowed-quorum BUKAN bukti P2D′
  (sumbernya allowed_quorum.direction / l12_verdict.direction — pipeline:4621).
- Microboost null BUKAN karena wire ke builder hilang.
  Wire P2D′ → record_pressure_canary → event.direction → _dominant_direction
  → PressureBlock.direction → MicroboostWatchDiagnostic.raw_direction SUDAH ADA.
- Karena itu "P2D′-B (apply ke microboost builder)" salah sasaran.
- Akar harus dibedakan dulu: (b) flag OFF · (c) diagnostics-source kosong/collapse-to-HOLD
  · (q) quorum-source gap.
- Jangan tulis kode fix sebelum capture-spec ini bisa memisahkan ketiganya.
```

---

## 1. Tujuan

Membedakan **tiga akar** yang menghasilkan gejala identik:

> DecisionUpdate allowed-quorum punya `raw_direction=BUY/SELL`, tetapi `MicroboostWatchDiagnostic.raw_direction=null`.

| Kode | Akar | Lokasi fix nantinya |
| --- | --- | --- |
| **(b)** | Flag P2D′ OFF / tidak aktif | env, bukan kode |
| **(c)** | `direction_diagnostics.sources` kosong / `resolve_trade_direction` collapse ke HOLD | `pipeline/phases/synthesis.py` (Akar #1) |
| **(q)** | quorum-source gap: `allowed_quorum.direction` ada, tapi recorder tidak menerima report/quorum direction | `_resolve_pressure_observation_direction` / `_record_signal_throttle_downgrade_observation` |

---

## 2. Telemetry wajib — dipetakan ke titik kode (verified pada p2d)

Semua telemetry **flag-guarded, default OFF** (mis. `P2D_RECOVERY_TELEMETRY_ENABLED`), additive, `valid_for_execution` selalu `false`, tidak pernah emit SignalJSON.

### 2.1 Deployment metadata (header tiap capture)
```json
{ "deployment_id":"...", "git_sha":"...", "branch":"p2d-direction-diagnostic-source-recovery",
  "single_deployment": true, "timestamp_start_utc":"...", "timestamp_end_utc":"...",
  "env_flags": {
    "SIGNAL_THROTTLE_PRESSURE_DIRECTION_RECOVERY":"true/false",
    "SIGNAL_THROTTLE_PRESSURE_DIRECTION_FROM_DIAGNOSTICS":"true/false",
    "MICROBOOST_DIRECTION_INHERIT_ENABLED":"false",
    "SIGNAL_WATCH_MARKET_STRUCTURE_STATUS_ENABLED":"false",
    "ALLOW_MARKET_EXECUTION":"false", "TRADING_MODE":"paper" } }
```

### 2.2 `pressure_direction_recovery_diagnostic`
**Insertion point:** `_resolve_pressure_observation_direction` → **pipeline:4001**; `_recover_direction_from_diagnostics` → **pipeline:4055**.
Capture `l12_direction`, `source_text_direction`, `allowed_quorum_direction`, `diagnostics_sources_count`, `diagnostics_sources`, `diagnostics_candidate_direction`, `recovered_direction`, `direction_recovery_source`, `return_reason` (`FLAG_DISABLED` / `DIAGNOSTIC_SOURCES_EMPTY` / `DIAGNOSTIC_SOURCES_CONFLICT` / `RECOVERED`).
> Catatan: `allowed_quorum_direction` **belum** terlihat di sini — recorder tidak diberi `report` ([signature pipeline:4097](../pipeline/wolf_constitutional_pipeline.py)). Untuk meng-capture-nya, thread `report`/quorum-direction ke fungsi ini (juga prasyarat fix-q).

### 2.3 `pressure_canary_recorded`
**Insertion point:** sebelum/di `record_pressure_canary(...)` → **analyzer:773** (dipanggil dari recorder **pipeline:4118-4145**).
Capture `input_direction`, `stored_event_direction` (= `normalize_direction` hasil, analyzer:~800), `reason`, `synthesis_phase`, `l12_direction_seen`, `allowed_quorum_direction_seen`, `diagnostic_recovery_direction_seen`.

### 2.4 `pressure_block_direction_diagnostic`
**Insertion point:** `_dominant_direction(events)` / block creation → **analyzer:2764**.
Capture `events_count`, `event_directions[]`, `dominant_direction`, `block_direction`, `return_reason` (`NO_EVENT_DIRECTION` / `DOMINANT_FOUND`).

### 2.5 `microboost_watch_candidate_diagnostic` (extend yang sudah ada)
**Insertion point:** builder **analyzer:1231** (`raw_direction = block.direction`); emit **pipeline:5260-5274**.
Tambah field `direction_recovery_source` di samping `raw_direction` yang sudah ada. Sisanya (`effective_ticks`, `duration_seconds`, `eligible_for_watch`, `blocked_by`) sudah ada.

### 2.6 `p2d_direction_recovery_funnel` (aggregate per deployment)
**Insertion point:** sejajar `family_counters_snapshot()` (counters proses-lokal).
Counters:
```text
resolver_invoked_count, resolver_enabled_count, resolver_disabled_count,
diagnostics_sources_empty_count, diagnostics_sources_conflict_count, diagnostics_direction_recovered_count,
allowed_quorum_direction_present_count, allowed_quorum_direction_not_passed_to_pressure_count,
pressure_canary_direction_null_count, pressure_canary_direction_recovered_count,
microboost_raw_direction_null_count, microboost_raw_direction_recovered_count,
signal_watch_direction_missing_count, signal_watch_direction_recovered_count,
valid_for_execution_true_count, signal_json_count
```

---

## 3. Decision matrix

### Case (b) — Flag OFF / P2D′ tidak aktif
```text
resolver_enabled=false · resolver_disabled_count>0 · resolver_invoked_count=0 atau return_reason=FLAG_DISABLED
allowed_quorum_direction bisa tetap BUY/SELL · microboost raw_direction tetap null
→ KEPUTUSAN: bukan bug wiring. Nyalakan/verifikasi SIGNAL_THROTTLE_PRESSURE_DIRECTION_FROM_DIAGNOSTICS=true.
```

### Case (c) — Akar #1 / diagnostics-source kosong
```text
resolver_enabled=true · resolver_invoked_count>0 · diagnostics_sources_count=0
return_reason=DIAGNOSTIC_SOURCES_EMPTY · recovered_direction=null · allowed_quorum_direction tidak dipakai resolver
→ KEPUTUSAN: P2D′ tak punya bahan. Fix upstream: resolve_trade_direction / direction_diagnostics.sources (synthesis.py).
```

### Case (q) — Quorum-source gap
```text
allowed_quorum_direction=BUY/SELL · l12_direction=null · diagnostics_sources empty/null
pressure_canary direction=null · microboost direction=null · DecisionUpdate allowed-quorum punya BUY/SELL
→ KEPUTUSAN: fix P2D′-B′ = thread allowed_quorum.direction / report direction ke
  _resolve_pressure_observation_direction ATAU ke input record_pressure_canary.
  JANGAN tambah wire baru di microboost builder — builder sudah membaca event.direction.
```

---

## 4. Acceptance PASS P2D′
```text
resolver_enabled=true
resolver_invoked_count>0
diagnostics_direction_recovered_count>0  ATAU  allowed_quorum_direction_passed_to_pressure_count>0
pressure_canary_direction_recovered_count>0
microboost_raw_direction_recovered_count>0
SignalJSON=0
valid_for_execution=true=0
```

## 5. Hard NO-GO
```text
SignalJSON>0
valid_for_execution=true>0
resolver flag tidak jelas
single deployment tidak bersih
allowed_quorum BUY/SELL ada tapi tidak ada telemetry yang menjelaskan kenapa tidak masuk pressure_canary
```

---

## 6. Arah kerja (locked)
```text
1. Merge P2D′ flag-OFF boleh (kalau default OFF verified) — dorman, byte-identical.
2. Jangan klaim live PASS.
3. Jangan tulis P2D′-B lama (wire microboost — sudah ada).
4. Implementasi telemetry §2 dulu (flag-guarded default OFF, additive).
5. Setelah capture keluar → pilih: env/flag fix (b) · upstream diagnostics-source fix (c) · P2D′-B′ quorum-source threading (q).
```
