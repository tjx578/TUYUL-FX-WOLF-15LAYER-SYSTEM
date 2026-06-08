# Audit Konformansi — SignalThrottle Pressure-Radar Architecture

**Tanggal:** 2026-06-08
**Ruang lingkup:** Verifikasi klaim "hasil assessment" terhadap kode riil repo + analisis dua risiko + rekomendasi optimasi.
**Verdict singkat:** Sistem **sudah** mengimplementasikan rancangan pressure-radar. Kelima fakta assessment terkonfirmasi. Kedua "risiko" sudah ditangani — termasuk satu yang ternyata **keputusan desain yang disengaja dan dikunci test**, bukan bug.

---

## 1. Verifikasi Klaim Assessment vs Kode

| # | Klaim assessment | Status | Lokasi kode |
| --- | ------------------ | -------- | ------------- |
| 1 | `signal_throttle_check` → `PRESSURE_CANARY`, `OBSERVE`, non-execute | ✅ Benar | `analysis/signal_throttle_log_analyzer.py:166-178` |
| 2 | `record_pressure_canary()` menulis event_type `PRESSURE_CANARY` | ✅ Benar | `analysis/signal_throttle_log_analyzer.py:724-761` |
| 3 | `PressureBlock` kaya (durasi, density, gap, effective ticks, dll) | ✅ Benar | `analysis/signal_throttle_log_analyzer.py:94-113` |
| 4 | Boundary pressure vs eksekusi (`eligible_for_pressure_block=True`, `eligible_for_execution=False`) | ✅ Benar | `analysis/signal_throttle_log_analyzer.py:158-160, 177, 228-229` |
| 5 | Shadow watch decoupled (kerja di copy, hanya `*_WATCH`, tak sentuh finalizer) | ✅ Benar | `pipeline/wolf_constitutional_pipeline.py:4292-4338` |
| 6 | `NO_TRADE_REASONED` di-emit saat pressure tapi non-execute | ✅ Benar | `pipeline/wolf_constitutional_pipeline.py:4099-4138` |
| 7 | M15 close bukan gate universal (hanya kondisi tertentu) | ✅ Benar | `analysis/signal_block_finalizer.py` (`M15CloseDecision`/`M15CloseConfirmationGate`) |
| 8 | Microboost multi-fase (>3 level) | ✅ Benar | `analysis/microboost_detector.py` (fase `IGNITION_*`, `NEAR_TIMING_GATE_*`, `REPEATED_*`, dll) |

**Kesimpulan bagian ini:** narasi assessment akurat. Tidak ada klaim yang meleset.

---

## 2. Risiko 1 — "PRESSURE_CANARY jangan cepat dipromosikan jadi microboost"

**Status: sudah dimitigasi berlapis.** `is_mature()` versi assessment memang tidak ada sebagai satu method, tetapi konsepnya tersebar dalam beberapa gate:

- `_is_meaningful_candidate_block()` — butuh `duration ≥ clean_block` **dan** `effective_ticks/events ≥ 10` (`signal_throttle_log_analyzer.py:1126-1127`).
- `_is_ignition_watch_block()` — `18s ≤ duration < clean_block`, `effective_ticks ≥ 5`, `effective_density ≥ 8.0` (`:1130-1133`).
- `_signal_watch_gate()` — eligibility butuh symbol+direction cocok dengan clean-block candidate (`:1410-1438`).
- Engine continuation — minimum `density 25.0` & `duration 60s` sebelum valid (`:1311-1317`).
- Aturan YAML — `do_not_auto_promote..._single_block`, `require_own_price_phase_and_retest_before_signaljson_promotion` (`analysis/signalthrottle_patterns/historical_validation_log.yaml`, `reference_cases.yaml`).

Jadi canary **tidak** otomatis menjadi microboost valid. Urutan yang dikhawatirkan assessment sudah dipaksakan oleh gate-gate ini.

---

## 3. Risiko 2 — "Semua valid watch harus punya terminal decision, tidak boleh menggantung"

**Status: sudah dipenuhi — dengan pemisahan yang disengaja antara watch _actionable_ dan watch _observability_.**

### 3.1 Watch actionable DIJAMIN terminal
- Watch dari counter-entry (`*_ABSORPTION_WATCH`/`*_TIMING_WATCH`, membawa `pending_decision_id` + `requires_m15_close`) di-`track()` ke finalizer (`pipeline/wolf_constitutional_pipeline.py:4043`).
- Finalizer menjamin terminal: expiry → `PENDING_WATCH_EXPIRED` setelah ≥3 bar M15/45 mnt (`signal_block_finalizer.py:328-339, 571-572`); confirmed → final execution (`:340-354`); else → decision update WAIT.
- `_finalize_idle_signal_blocks` dipanggil **setiap tick**, EXECUTE maupun non-EXECUTE (`pipeline/...:4505`), sehingga pending watch selalu didrain — shadow **bukan** satu-satunya jalur.

### 3.2 Watch observability SENGAJA tidak diberi lifecycle
- `microboost_watch_entry` berstatus `MICROBOOST_WATCH` (`signal_throttle_log_analyzer.py:1365`) dan continuation murni berstatus `WAIT_M15_CLOSE_OR_STRUCTURE_TARGET` + `orchestration_status="VALIDATION_ONLY_REQUIRES_SIGNAL_WATCH"` (`pipeline/...:4002`).
- Keduanya **tidak** lolos `_is_pending_watch` (`signal_block_finalizer.py:786-792`), sehingga tidak diadopsi finalizer.

> **Bukti bahwa ini DISENGAJA, bukan bug:** ada test eksplisit
> `tests/test_signal_block_finalizer.py:84-116`
> **`test_generic_microboost_watch_is_not_tracked_for_finalization`** — men-`track()` payload `MICROBOOST_WATCH` lalu meng-assert `pending_symbols() == []` dan `finalize() == []`.

Artinya: watch fallback/observability memang **didesain** sebagai "radar ping" tanpa lifecycle, sedangkan watch yang benar-benar actionable (counter-entry) yang dibawa ke terminal. Ini justru **persis** maksud assessment ("PRESSURE_CANARY = data radar; MICROBOOST_WATCH = kandidat timing; hanya yang matang masuk lifecycle"), hanya saja assessment mencampur "observability watch" dengan "actionable watch".

---

## 4. Temuan Kunci & Rekomendasi

**Temuan:** Repo sudah konform dengan rancangan. Satu-satunya "celah" (continuation/watch entry tidak di-`track()`) adalah **boundary yang disengaja dan dikunci test**. Menutupnya (memaksa `MICROBOOST_WATCH` masuk finalizer) akan:
1. Mematahkan `test_generic_microboost_watch_is_not_tracked_for_finalization`.
2. Membalik keputusan arsitektur yang eksplisit.
3. Menaikkan volume emisi decision-update/expiry untuk watch yang sebenarnya cuma observability.

**Rekomendasi (tanpa mengubah perilaku):**
1. **Jangan** override tracking. Pertahankan pemisahan actionable vs observability.
2. **Kunci invariant dengan test regresi tambahan** (lihat Lampiran) — khususnya Risiko 1 (canary tidak auto-promote), agar refactor masa depan tidak merusak boundary.
3. Jika tetap ingin "terminal untuk semua watch" demi dashboard, **jangan** lewat finalizer — cukup tambah **field audit observasional** (mis. `lifecycle_tracked: false`, `terminal_guarantee: "OBSERVABILITY_ONLY"`) pada `microboost_watch_entry`/continuation, sehingga niat desain terlihat di telemetry tanpa mengubah alur eksekusi.

---

## 5. Lampiran — Snippet Test Regresi Siap Pakai

> Catatan: sandbox eksekusi sedang nonaktif (virtualisasi host mati), sehingga snippet ini **belum dijalankan**. Jalankan `pytest tests/ -k "canary or watch or finalizer"` sebelum merge.

```python
# tests/test_signal_throttle_canary_no_auto_promote.py
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from analysis.signal_throttle_log_analyzer import SignalThrottleLiveAnalyzer


def test_pressure_canary_alone_does_not_auto_promote_to_microboost():
    """Risiko 1: canary murni (tanpa blok matang) tidak boleh jadi microboost valid."""
    analyzer = SignalThrottleLiveAnalyzer()
    base = datetime(2026, 6, 8, 3, 0, 0, tzinfo=UTC)
    for i in range(3):
        analyzer.record_pressure_canary(
            symbol="USDCAD",
            verdict="NO_TRADE",
            direction="BUY",
            reason="non_execute_verdict",
            timestamp=base + timedelta(seconds=i * 20),
        )
    report = analyzer.snapshot()

    # Pressure tercatat sebagai radar...
    assert report["counts"]["total_events"] == 3
    # ...tetapi TIDAK auto-promote ke entry microboost yang executable.
    assert report.get("microboost_continuation_entry") in (None, {}) or \
        report["microboost_continuation_entry"].get("status") == "NONE"
    assert report.get("microboost_counter_entry") in (None, {}) or \
        report["microboost_counter_entry"].get("status") == "NONE"
```

Boundary yang sudah dijaga test eksisting (jangan dihapus):
- `tests/test_signal_block_finalizer.py::test_generic_microboost_watch_is_not_tracked_for_finalization` — MICROBOOST_WATCH observability tidak masuk finalizer.
- `tests/test_signal_block_finalizer.py::test_pending_watch_expires_after_three_m15_bars_without_confirmation` — watch actionable dijamin terminal via expiry.
