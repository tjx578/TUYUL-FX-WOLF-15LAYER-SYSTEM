# 🐺 TUYUL FX — Reference Constitutional Architecture v3.0

**Version**: 3.0
**Status**: Reference Architecture
**Role**: High-level system worldview and constitutional boundary map
**Last Updated**: 2026-04-15

**Not a source of truth for:**

- current runtime topology
- current deployment topology
- live threshold values
- real-time inte

rface inventory

- per-file component inventory

**See also:**

| Concern | Canonical document |
| ------- | ----------------- |
| Runtime topology | `runtime-topology-current.md` |
| Dashboard authority | `dashboard-control-surface.md` |
| Deployment shape | `deployment-classification.md` |
| Real-time interfaces | `realtime-interfaces-current.md` |
| Component inventory | `component-inventory-current.md` |
| Threshold divergences | `wolf30-divergence-map.md` |
| Active thresholds | `config/constitution.yaml`, `config/v11.yaml` |

---

## 1. Purpose

Dokumen ini adalah **reference constitutional architecture** untuk TUYUL FX.

Tujuannya menjelaskan:

- worldview sistem
- separation of concerns
- high-level logical flow
- constitutional authority map
- zone boundaries yang tidak boleh dilanggar

Dokumen ini **bukan** dokumen operasional current-state.
Untuk current-state runtime truth, gunakan dokumen yang dirujuk di tabel **See also**.

---

## 2. Design Principles

| Principle | Rule |
| --------- | ---- |
| Constitutional separation | `analysis/` ≠ `constitution/` ≠ `execution/` ≠ `dashboard/` — setiap zona punya peran utama sendiri |
| Sole decision authority | **L12 adalah satu-satunya modul yang boleh mengeluarkan constitutional trade verdict** |
| Dumb executor | EA adalah **zero-intelligence file-polling executor**; ia tidak menilai kondisi market |
| Owner-operated control surface | Dashboard adalah surface operator untuk monitoring, diagnostics, dan controlled operations; dashboard **bukan constitutional verdict authority** |
| No bypass | Modul apa pun yang override hasil L12 tanpa governed authority = **invalid system** |
| Boundary-first design | Perubahan fitur tidak boleh melanggar batas antar zona demi kenyamanan implementasi |
| Runtime truth hierarchy | Current runtime behavior ditentukan oleh config aktif, profile aktif, dan enforcement code — bukan oleh dokumen referensi ini |
| Additive evolution first | Evolusi sistem harus dimulai dari observability, config, dan advisory output sebelum menjadi hard enforcement |

---

## 3. Architectural Scope

Dokumen ini menjelaskan arsitektur pada level:

- prinsip
- alur logika
- pemisahan concern
- jalur authority

Detail berikut **bukan tanggung jawab dokumen ini** dan harus berada di dokumen current-state terpisah:

- startup order tiap service
- daftar lengkap container aktif
- semua endpoint real-time
- angka gate / threshold aktif
- env contract deploy tertentu

---

## 4. Logical System Flow Overview

```text
Market / event ingestion
  → filtering, buffering, and candle formation
  → live context and event propagation
  → constitutional analysis pipeline
  → synthesis and L12 verdict authority
  → governed distribution to journals, state stores, UI streams, alerts, and execution bridge
  → execution state machine and EA bridge
```

Flow ini adalah **logical flow view**, bukan deployment diagram.
Runtime process aktual dapat dipisah menjadi dedicated services tanpa mengubah prinsip constitutional flow ini.

---

## 5. High-Level Zone Model

```text
╔══════════════════════════════════════════════════════════════════════════════╗
║  ZONE A  INGESTION & FILTERING                                              ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  - menerima market feed / event feed                                        ║
║  - filtering, dedup, initial hygiene                                        ║
║  - memisahkan data valid dari noise / rejected events                       ║
╚════════╪═════════════════════════════════════════════════════════════════════╝
         │
╔════════▼═════════════════════════════════════════════════════════════════════╗
║  ZONE B  BUFFERING & CANDLE FORMATION                                       ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  - menyimpan tick/candle input jangka pendek                                ║
║  - membentuk candle lintas timeframe                                        ║
║  - menyiapkan data yang layak dipakai pipeline                              ║
╚════════╪═════════════════════════════════════════════════════════════════════╝
         │
╔════════▼═════════════════════════════════════════════════════════════════════╗
║  ZONE C  CONTEXT & EVENT PROPAGATION                                        ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  - menjaga live context (data layer + inference layer)                      ║
║  - mendistribusikan event internal                                          ║
║  - memisahkan source authority per event type                               ║
╚════════╪═════════════════════════════════════════════════════════════════════╝
         │
╔════════▼═════════════════════════════════════════════════════════════════════╗
║  ZONE D  ANALYSIS ORCHESTRATION                                             ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  - mengorkestrasi kapan analisis berjalan                                   ║
║  - memicu pipeline ketika context/data siap                                 ║
║  - mengelola warmup / readiness / continuation                              ║
║                                                                              ║
║  Zona ini boleh diimplementasikan lewat root runtime loop, dedicated        ║
║  engine service, atau orchestrated process lain. Dokumen ini tidak          ║
║  mengunci satu entrypoint runtime literal.                                  ║
╚════════╪═════════════════════════════════════════════════════════════════════╝
         │
╔════════▼═════════════════════════════════════════════════════════════════════╗
║  ZONE E  CONSTITUTIONAL PIPELINE                                            ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  - memproses L1 → L15 worldview                                             ║
║  - membangun synthesis                                                      ║
║  - L12 tetap sole verdict authority                                         ║
║  - overlay/gating tambahan tidak boleh melanggar L12 authority              ║
╚════════╪═════════════════════════════════════════════════════════════════════╝
         │
╔════════▼═════════════════════════════════════════════════════════════════════╗
║  ZONE F  GOVERNED DISTRIBUTION                                              ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  - fan-out ke journal, cache/state, UI stream, alerts, metrics, tracing     ║
║  - menyebarkan hasil pipeline tanpa menciptakan authority baru              ║
╚════════╪═════════════════════════════════════════════════════════════════════╝
         │
╔════════▼═════════════════════════════════════════════════════════════════════╗
║  ZONE G  EXECUTION PATH                                                     ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  - menjalankan state machine eksekusi                                       ║
║  - mengirim command ke EA bridge                                            ║
║  - menerima report hasil eksekusi                                           ║
║  - tidak menciptakan arah market baru                                       ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

---

## 6. Constitutional Pipeline Worldview

### Phase 1 — Perception & Context

L1 Context → L2 MTA → L3 Technical

Tujuan: membaca market state, membangun konteks, memastikan continuation awal layak.

### Phase 2 — Confluence & Behavioral Alignment

L4 Scoring / FTA / session → L5 Psychology / discipline

Tujuan: mengubah pembacaan awal menjadi struktur konfluensi eksplisit; mengurangi setup yang tampak menarik tetapi tidak disiplin.

### Phase 2.5 — Engine Enrichment

Kumpulan enrichment engines (correlation, Monte Carlo, posterior, momentum, volume, orderflow, HTF, macro, dll.) yang berfungsi sebagai **analytical support**, bukan constitutional authority baru.

### Phase 3 — Probability & Validation

L7 Probability → L8 TII → L9 structural/validation

Tujuan: menguji apakah setup layak secara probabilistik, struktural, dan coherently aligned.

### Phase 4 — Execution Preparation

L11 RR → L6 Risk → L10 Position Sizing

Catatan: L11 sebelum L6 adalah **intentional ordering** — risk firewall membutuhkan R:R sebagai input.

### Phase 5 — L12 Constitutional Verdict ★

L12 adalah **sole verdict authority**. Ia membangun synthesis final, mengevaluasi constitutional gates, dan menghasilkan verdict.

Possible outputs: `EXECUTE` | `HOLD` | `NO_TRADE`

Angka threshold gate **tidak dipegang oleh dokumen ini**. Nilai aktif harus dibaca dari `config/constitution.yaml`.

### Phase 6 — Governance / Reflective

Post-verdict refinement, reflective coherence, governance-awareness. Tidak boleh menciptakan unconstitutional override.

### Phase 7 — Sovereignty / Drift Control

Drift awareness, integrity terhadap baseline, downgrade bila sistem bergerak dari safe state.

### Overlay — V11 Selectivity Filter

Post-pipeline overlay yang:

- boleh veto (block trade bila L12 = EXECUTE)
- **tidak boleh** menggantikan L12 sebagai verdict authority
- hanya sah posisinya sebagai governed overlay, bukan decision authority paralel
- threshold aktif di `config/v11.yaml`, bukan di dokumen ini

### Final Assembly / Export

Output akhir dibentuk sebagai payload/export contract untuk UI, journal, observability, execution mapping, dan audit trail. Export tidak mengubah constitutional authority.

---

## 7. L12 Constitutional Rule

L12 memiliki posisi yang **tidak boleh dinegosiasikan**:

1. Hanya L12 yang boleh mengeluarkan constitutional trade verdict
2. Execution layer tidak boleh menciptakan arah baru
3. Dashboard tidak boleh mengeluarkan verdict baru
4. Journal tidak boleh mengubah state runtime
5. Overlay/selectivity layer tidak boleh menjadi verdict authority kedua
6. Angka gate aktif diambil dari runtime config, bukan dari dokumen ini

```text
analysis   may THINK
constitution may DECIDE
execution  may ACT
dashboard  may OPERATE
journal    may RECORD
```

Tetapi hanya **constitution / L12** yang boleh memutuskan secara constitutional.

---

## 8. Output Philosophy

Hasil pipeline boleh didistribusikan ke banyak channel, tetapi distribusi itu tidak menciptakan otoritas baru.

Output secara prinsip dapat difan-out ke:

- journal / audit trail
- state store / cache / bus
- dashboard / UI streams
- alerts / notification systems
- metrics / tracing
- execution bridge

Daftar channel aktif tidak didefinisikan di sini.
Lihat `realtime-interfaces-current.md` untuk inventaris real-time endpoint aktif.

---

## 9. Zone Authority Summary

Detail lengkap authority per zona ada di `system-overview.md` dan `authority-boundaries.md`.
Berikut ringkasan prinsip:

| Zone | Role | Boleh | Tidak Boleh |
| ---- | ---- | ----- | ----------- |
| Ingestion | Data acquisition | Filter, dedup, normalize, produce heartbeat | Strategy logic, execution |
| Context | State hydration | Distribute live state, track freshness | Decision authority |
| Analysis | Market reasoning | Score, infer, enrich | Place orders, bypass L12 |
| Constitution | Verdict authority | Issue EXECUTE/HOLD/NO_TRADE | Be overridden without governance |
| Governance | Flow coordination | Veto, pause, degrade, hold | Synthesize market direction |
| Execution | Order lifecycle | Execute approved commands, cancel, expire | Create new direction |
| Dashboard | Operator surface | Monitor, diagnose, controlled operations | Verdict authority, hidden override |
| Journal | Audit trail | Record immutably | Runtime control |

Detail dashboard authority & auth boundary: `dashboard-control-surface.md`

---

## 10. Runtime Truth Hierarchy

Hierarchy ini menentukan apa yang menang saat ada konflik:

1. **Effective runtime config** (`config/constitution.yaml`, `config/v11.yaml`)
2. **Active profile & enforcement code**
3. **Runtime service topology** (`runtime-topology-current.md`)
4. **Canonical current-state docs** (`component-inventory-current.md`, `deployment-classification.md`, dll.)
5. **Reference architecture** (dokumen ini)

Artinya:

- Jika angka di dokumen ini berbeda dari config aktif → config aktif menang
- Jika daftar channel di sini berbeda dari routes aktif → routes aktif menang
- Jika deploy shape berbeda dari current topology → topology docs menang

---

## 11. Constitutional Boundaries

```text
analysis/      → THINKS      — read-only market analysis; no execution side effects
constitution/  → DECIDES     — L12 is sole verdict authority
execution/     → ACTS        — governed execution and state progression; no strategy authorship
ea_interface/  → EXECUTES    — zero-intelligence bridge/executor
dashboard/     → OPERATES    — operator-facing control surface; not verdict authority
journal/       → RECORDS     — append-only audit and reflection; no runtime control
```

Setiap modul yang melanggar boundary ini secara tidak sah membuat sistem **constitutionally invalid**.

Contoh pelanggaran:

- execution menghitung arah market
- dashboard membuat verdict baru
- EA menambahkan strategi sendiri
- journal memodifikasi keputusan runtime
- modul overlay menggantikan L12 tanpa governed authority

---

## 12. Interpretation Guide

### Gunakan dokumen ini saat

- memahami sistem secara keseluruhan
- menjelaskan TUYUL FX ke orang baru (bersama `overview.md`)
- menjaga worldview dan authority boundaries
- memeriksa apakah perubahan melanggar konstitusi sistem

### Gunakan dokumen current-state saat

- mengecek threshold aktif → `config/constitution.yaml`
- mengecek service deploy aktif → `deployment-classification.md`
- mengecek endpoint aktif → `realtime-interfaces-current.md`
- mengecek service entrypoints → `deployment-classification.md`
- mengecek component paths → `component-inventory-current.md`

---

## 13. Changelog

```text
v1.0 — Initial compact architecture diagram
v2.0 — Expanded source-verified architecture writeup
v2.1 — Unified architecture worldview (mixed current-state + worldview)
v2.2 — Revised v2.1; threshold and topology corrections (legacy/history)
v3.0 — Reframed as Reference Constitutional Architecture
       - Current-state sections split to dedicated canonical docs
       - Dashboard: "monitor-only" → "owner-operated control surface"
       - Zone D: no longer locked to single entrypoint
       - Thresholds removed from doc body; runtime config is source of truth
       - WS/output inventory moved to realtime-interfaces-current.md
       - Deployment moved to deployment-classification.md
       - Component inventory moved to component-inventory-current.md
```

---

## 14. Lineage

Dokumen ini adalah evolusi dari:

- `docs/legacy/architecture-history/unified-architecture-v2.1.md` (v2.1 → v2.2)

v2.1/v2.2 tetap tersedia di legacy history untuk reference. Dokumen v3.0 ini menggantikannya sebagai reference architecture aktif.
