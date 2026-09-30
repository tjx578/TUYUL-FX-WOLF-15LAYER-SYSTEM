# Wolf15 Strategy 5S-CR — Canonical Workflow SSOT v3.1 Candidate

```yaml
document_id: WOLF15-5SCR-SSOT-V3.1-CANDIDATE
strategy_rule_version: 5scr.dual-analysis-admission.pressure-hypothesis.structural-core.v3.1
repository_publication_status: FIRST_PUBLISHED_V3_SERIES_CANDIDATE
unpublished_draft_predecessor: WOLF15-5SCR-SSOT-V3-CANDIDATE
unpublished_draft_predecessor_status: INTERNAL_WORKING_DRAFT_NOT_COMMITTED_TO_REPOSITORY
repository_current_strategy_baseline:
  document: docs/strategy/strategy-5scr-final.md
  status: CURRENT_TRACKED_STRATEGY_BASELINE
historical_design_predecessor:
  document_id: WOLF15-5SCR-SSOT-V2
  repository_status: NOT_TRACKED_IN_CURRENT_REPOSITORY_HISTORY
supersedes_if_approved:
  - docs/strategy/strategy-5scr-final.md
status: PROPOSED_CANONICAL
approval_state: SHADOW_VALIDATION_REQUIRED
date: 2026-08-21
language: id-ID
execution_status: SHADOW_ONLY
runtime_authority: NONE_UNTIL_APPROVED
production_proven: false
out_of_sample_status: NOT_YET_VALIDATED
symbol_specific_rules_allowed: false
behavioral_change_notice: DUAL_ANALYSIS_ADMISSION_SHADOW_ONLY
pair_admission_coverage_contract_version: pair-admission-coverage.v1
strategy_analysis_admission_contract_version: strategy-analysis-admission.v1
advisory_analysis_execution_authority: false
normative_scope:
  - raw pressure normalization
  - canonical PairAdmission and raw-authority coverage classification
  - dual StrategyAnalysisAdmission
  - mature advisory analysis path
  - durable analysis lifecycle
  - microboost pulse and state
  - pressure directional hypothesis
  - market data and candle authority
  - material context epoch
  - legal direction domain and route
  - immutable directional thesis
  - ordered H1 and M15 structural proof
  - pressure range and execution box
  - target-first trade geometry
  - non-executable tradeplan candidate
non_normative_scope:
  - account risk percentage
  - broker command protocol details
  - EA authentication implementation
  - Railway deployment snapshot
  - historical profitability claims
source_documents:
  - docs/strategy/strategy-5scr-final.md
external_or_untracked_design_sources:
  - document_id: WOLF15-5SCR-SSOT-V2
    repository_status: NOT_TRACKED_IN_CURRENT_REPOSITORY_HISTORY
  - document_id: WOLF15-5SCR-FINAL-AUDIT-REPLAY-WORKFLOW-V3
    repository_status: NOT_TRACKED_IN_CURRENT_REPOSITORY_HISTORY
  - document_id: Strategy_5SCR_Legacy
    repository_status: NOT_TRACKED_IN_CURRENT_REPOSITORY_HISTORY
  - document_id: Strategy_5S_Final_Legacy
    repository_status: NOT_TRACKED_IN_CURRENT_REPOSITORY_HISTORY
approval_evidence:
  deterministic_replay_manifest: null
  shadow_comparison_manifest: null
  out_of_sample_manifest: null
  approval_record: null
```

Dokumen ini adalah **candidate single source of truth** untuk semantik Strategy 5S-CR dari raw pressure sampai `TradePlanCandidate` yang tetap non-executable. Versi 3.1 mempertahankan `PairAdmission` sebagai authority raw-only, tetapi menambahkan `StrategyAnalysisAdmissionV1` agar pressure advisory yang matang tidak hilang dari analisis lanjutan hanya karena tidak memiliki canonical raw block.

Versi 3.1 ini merupakan **candidate V3-series pertama yang dipublikasikan ke repository**. Identitas V3 tanpa suffix `.1` hanya dicatat sebagai working draft internal yang tidak pernah menjadi file repository, runtime authority, atau baseline pembanding resmi.

Dokumen ini **tidak** mengubah CANARY, derived pressure, Microboost, atau `SignalPressureStateJSON` menjadi order authority. Jalur advisory hanya boleh membuka analisis penuh dalam mode SHADOW dan dilarang menghasilkan risk reservation, FinalSignal executable, atau `ExecutionCommand`.

Dokumen ini hanya boleh menjadi `APPROVED_CANONICAL` setelah seluruh acceptance gate, deterministic replay, shadow comparison, dan out-of-sample gate pada dokumen ini lulus.

Kata **WAJIB**, **DILARANG**, **BOLEH**, **HARUS GAGAL-TERTUTUP**, dan **TIDAK BOLEH DIINFERENSIKAN** bersifat normatif.

---

## Ringkasan amendment v3.1

Perubahan konstitusional utama yang dikonsolidasikan dari working draft V3 yang tidak pernah dipublikasikan ke repository:

```text
PairAdmission
→ tetap raw-authority-only
→ tidak menerima CANARY atau derived pressure sebagai pengganti raw stream

PairAdmissionCoverage
→ membedakan EVALUATED, NOT_APPLICABLE, MISSING_EVALUATION_INCIDENT,
  dan INDETERMINATE_RAW_AUTHORITY_COVERAGE

StrategyAnalysisAdmission
→ mempunyai dua kelas:
   CANONICAL_RAW
   MATURE_ADVISORY

MATURE_ADVISORY
→ WAJIB membuka/attach AnalysisLifecycle
→ WAJIB membuka PressureDirectionalHypothesis bila direction lineage ALIGNED
→ WAJIB memicu prefetch dan analisis H4/H1/M15/M1
→ BOLEH menghasilkan TradePlanCandidate SHADOW_ONLY
→ DILARANG masuk Risk Authority atau ExecutionCommand

Upgrade authority
→ jika PairAdmission raw kemudian muncul, lifecycle advisory yang sama di-upgrade
→ tidak membuat lifecycle kedua
→ candidate advisory tidak otomatis dipromosikan; re-evaluation canonical wajib
```

Amendment ini bersifat universal untuk seluruh simbol. Nama pair, instrument tertentu, atau hasil satu episode DILARANG menjadi cabang strategy rule.

---

## Daftar isi

1. Otoritas dokumen dan batas scope
2. Putusan canonical
3. Kelas bukti dan status klaim
4. Model identitas dan cardinality
5. Workflow end-to-end
6. S0 — Pressure normalization dan telemetry boundary
7. S1A — PairAdmission v3.1 dan coverage
7A. S1B — StrategyAnalysisAdmissionV1
8. S2 — Durable AnalysisLifecycle
9. Microboost pulse dan state
10. PressureDirectionalHypothesis
11. Market-data, quote, dan candle authority
12. S3 — Material ContextEpoch dan legal direction domain
13. Liquidity state machine
14. S4 — Immutable DirectionalThesis dan ordered proof
15. Durable evaluation scheduler dan stage semantics
16. PressureRange dan ExecutionBox
17. S5 — Target-first trade geometry
18. Expiry dan revalidation clocks
19. Campaign, parent, child, dan reinforcement semantics
20. Monotonic handoff ke risk dan execution
21. Reason-code registry
22. Statistik, replay, dan reproducibility
23. Universal regression matrix
24. Acceptance dan promotion gate
25. Migrasi dari SSOT v2 dan working draft V3 yang tidak dipublikasikan
26. Policy registry dan change control
27. Final canonical workflow
28. Lampiran enum dan state minimum
29. Final status

---

# 1. Otoritas dokumen dan batas scope

## 1.1 Hierarki otoritas

Urutan otoritas final:

```text
1. Strategy SSOT ini
   → arti Strategy 5S-CR sampai TradePlanCandidate

2. Audit & Replay Workflow
   → cara mengukur, mereplay, mengklasifikasi outcome, dan menghitung statistik

3. Risk Authority Contract
   → risk percentage, reservation, campaign cap, dan account exposure

4. Execution Command Contract
   → signed command, idempotency, lease, report, dan broker reconciliation

5. EA Dumb Executor Contract
   → mechanical broker adapter

6. Release-readiness report
   → snapshot commit, deployment, database, feature flag, dan hasil test pada suatu tanggal
```

Jika terjadi konflik:

```text
semantik strategi        → Strategy SSOT menang
metode replay/statistik  → Audit Workflow menang
capital/risk policy      → Risk Authority Contract menang
broker delivery          → Execution Command Contract menang
kondisi repo/deployment  → Release-readiness report terbaru menang
```

## 1.2 Hal yang dikeluarkan dari SSOT

SSOT DILARANG memuat fakta yang cepat kedaluwarsa sebagai rule canonical, termasuk:

```text
commit SHA terkini
status PR
status Railway service
jumlah log pada satu ekspor
jumlah pair pada satu deployment
hasil win rate dari cohort tertentu
nama pair sebagai cabang strategi
```

Informasi tersebut harus berada di dokumen audit atau release-readiness.

## 1.3 Non-goals

Dokumen ini tidak:

```text
mengizinkan pressure langsung menjadi order
menetapkan win rate target
mengaktifkan DEMO/LIVE
mengubah EA menjadi strategy engine
membenarkan symbol-specific exception
menganggap satu hasil harga sesudah pressure sebagai trade WIN
```

---

# 2. Putusan canonical

## 2.1 Formula inti

```text
PRESSURE
→ menentukan arah yang harus diuji terlebih dahulu dan prioritas analisis

ANALYSIS ADMISSION
→ menentukan apakah analisis berasal dari CANONICAL_RAW atau MATURE_ADVISORY

CONTEXT
→ menentukan lokasi, route, legal direction domain, dan tingkat konflik

STRUCTURE
→ mengonfirmasi atau menginvalidasi arah melalui closed H1 dan ordered M15

TARGET + GEOMETRY
→ menentukan apakah trade memiliki entry legal, SL struktural, TP1, dan RR yang layak

RISK
→ hanya menerima candidate yang memiliki canonical raw authority dan mengotorisasi exposure secara durable

EA
→ mengeksekusi command secara mekanis dan idempotent
```

## 2.2 Pemisahan empat tingkat direction

```text
Pressure Direction
= arah force/tekanan yang terdeteksi

PressureDirectionalHypothesis
= arah prioritas yang harus diuji secara struktural
= non-executable

DirectionalThesis
= arah immutable yang sudah legal dan memiliki proof S3–S4
= tetap non-executable sampai S5 dan risk gate selesai

Final Executable Direction
= arah pada FinalSignal/ExecutionCommand setelah canonical risk authority
```

## 2.3 Pemisahan selection dan analysis admission

```text
PairAdmission
= canonical raw-selection authority
= hanya berasal dari ordered raw SignalThrottle / canonical raw ledger

StrategyAnalysisAdmission
= authority untuk membuka analisis lanjutan
= CANONICAL_RAW atau MATURE_ADVISORY
```

Invariant:

```text
PairAdmission ≠ StrategyAnalysisAdmission
PairAdmission NOT_APPLICABLE ≠ analysis ineligible
MATURE_ADVISORY ≠ canonical raw authority
MATURE_ADVISORY ≠ risk authority
MATURE_ADVISORY ≠ execution authority
```

## 2.4 Invariant utama

```text
pair selected ≠ trade selected
pressure event ≠ PairAdmission
PairAdmission ≠ StrategyAnalysisAdmission
StrategyAnalysisAdmission ≠ AnalysisLifecycle
AnalysisLifecycle ≠ ExecutionCampaign
pressure direction ≠ final executable direction
PressureDirectionalHypothesis ≠ DirectionalThesis
context conflict ≠ pressure evidence erased
location favorable ≠ order authorization
rejection ≠ automatic opposite authorization
reaction direction ≠ legal strategy direction
source_clean_block_id ≠ strategy_lifecycle_id
context epoch ≠ execution box version
source_stage ≠ monotonic strategy stage
reference price ≠ observed price ≠ execution price
WAIT ≠ WIN
NO_TRADE ≠ WIN
```

## 2.5 Prinsip universal untuk pressure matang

Ketika pressure directional diklasifikasikan `MATURE` atau `EXTREME` oleh policy versioned, direction lineage `ALIGNED`, pressure belum expired, dan evidence layak untuk Context Resolution:

```text
→ sistem WAJIB mengklasifikasikan StrategyAnalysisAdmission

→ jika PairAdmission GRANTED:
   admission_class = CANONICAL_RAW

→ jika tidak ada canonical raw authority tetapi advisory maturity memenuhi policy:
   admission_class = MATURE_ADVISORY

→ sistem WAJIB membuka atau memperbarui AnalysisLifecycle
→ sistem WAJIB membuka atau memperbarui PressureDirectionalHypothesis searah pressure
→ sistem WAJIB memprioritaskan evidence H1/M15 searah hypothesis
→ sistem DILARANG tetap hanya mencatat PRESSURE_ONLY tanpa durable analysis state
→ sistem DILARANG langsung membuat order
```

Absence of canonical raw PairAdmission DILARANG menghapus mature advisory candidate dari analisis lanjutan.

Jika context berlawanan:

```text
→ hypothesis tetap disimpan
→ status = CONTEXT_CONFLICT atau COUNTER_PRESSURE_PENDING_PROOF
→ context tidak boleh menghapus evidence pressure
→ order tetap 0 sampai proof dan geometry lengkap
```

Jika quote atau candle tidak authoritative:

```text
→ StrategyAnalysisAdmission dan lifecycle tetap hidup
→ hypothesis tetap hidup
→ status = WAITING_PRICE_QUALITY / WAITING_CANDLE_COVERAGE
→ execution authority = false
```

## 2.6 Authority matrix

| Object/class | Membuka lifecycle | Membuka hypothesis | Full H4/H1/M15/M1 analysis | TradePlanCandidate | Risk handoff | FinalSignal/Command |
|---|---:|---:|---:|---:|---:|---:|
| PairAdmission GRANTED | melalui `CANONICAL_RAW` | Ya | Ya | Ya | Setelah S3–S5 lulus | Setelah Risk Authority |
| StrategyAnalysisAdmission `CANONICAL_RAW` | Ya | Ya | Ya | Ya | Boleh setelah seluruh gate | Boleh setelah Risk Authority |
| StrategyAnalysisAdmission `MATURE_ADVISORY` | Ya | Ya | Ya, wajib SHADOW | Ya, `SHADOW_ONLY` | **Tidak** | **Tidak** |
| Pressure emission saja | Tidak otomatis | Tidak otomatis | Prefetch boleh | Tidak | Tidak | Tidak |
| DirectionalThesis saja | Sudah berada dalam lifecycle | — | Ya | Belum tentu | Tidak | Tidak |

# 3. Kelas bukti dan status klaim

Setiap klaim WAJIB mempunyai satu status:

```text
VERIFIED_RUNTIME
= dihitung dari artefak runtime yang lengkap dan lineage-nya tersedia

VERIFIED_REPLAY
= deterministic replay, as-of, tanpa future leakage, manifest lengkap

PROVISIONAL_LEGACY
= berasal dari audit lama tetapi denominator, manifest, atau evidence belum lengkap

HYPOTHESIS
= ide atau rule candidate yang belum lulus replay

SUSPENDED_DATA_QUALITY
= evidence tidak cukup atau tidak authoritative

AMBIGUOUS_PATH
= urutan fill/TP/SL tidak dapat dibuktikan
```

Rule execution DILARANG bergantung hanya pada `PROVISIONAL_LEGACY` atau `HYPOTHESIS`.

`PressureDirectionalHypothesis` pada versi ini merupakan **canonical analysis object**, tetapi perubahan route/counter-pressure yang memengaruhi jumlah trade harus tetap SHADOW sampai replay v3 lulus.

---

# 4. Model identitas dan cardinality

## 4.1 Identitas wajib

```text
transport_event_id
stream_partition_id
raw_event_id
active_block_id
admission_evaluation_id
admission_event_id
pair_admission_coverage_id
strategy_analysis_admission_id
market_episode_id
strategy_lifecycle_id
microboost_pulse_event_id
pressure_hypothesis_id
context_epoch_id
strategy_thesis_id
pressure_range_id
execution_box_id + box_version
tradeplan_id + tradeplan_revision
risk_reservation_id
execution_campaign_id
campaign_leg_id
final_signal_id
execution_command_id
broker_client_order_id
```

## 4.2 Cardinality

```text
raw block
→ tepat 0/1 durable PairAdmission evaluation

PairAdmission evaluation GRANTED
→ tepat 1 admission_event_id

PairAdmission coverage observation
→ tepat 1 coverage classification per symbol/window/rule version

mature advisory episode
→ tepat 0/1 StrategyAnalysisAdmission decision per maturity-policy revision

StrategyAnalysisAdmission GRANTED
→ tepat 1 lifecycle seed atau attachment

market episode
→ 1..N PairAdmission/advisory/evidence lineage

strategy lifecycle
→ 1..N StrategyAnalysisAdmission records
→ 1..N pressure emissions
→ 0..N MicroboostPulseEvent
→ 0..N PressureDirectionalHypothesis revisions
→ 1..N ContextEpoch
→ 0..N immutable DirectionalThesis

context epoch
→ 0..N thesis

thesis
→ 0..N ExecutionBox versions
→ 0..N TradePlanCandidate revisions

MATURE_ADVISORY lifecycle yang kemudian menerima CANONICAL_RAW
→ lifecycle ID tetap sama
→ authority class di-upgrade secara append-only
→ tidak membuat lifecycle kedua

advisory TradePlanCandidate yang kemudian memperoleh canonical raw authority
→ tidak dimutasi menjadi canonical
→ WAJIB dibuat candidate revision baru setelah canonical re-evaluation

authorized canonical thesis revision
→ maksimal 1 parent campaign per risk-policy rule

campaign
→ 1 parent + child sesuai risk-policy version

opposite direction
→ hypothesis/thesis baru
→ tidak memutasi direction lama
```

## 4.3 Identity anti-pattern

Field berikut hanya lineage/transport metadata dan DILARANG menjadi identity strategi:

```text
cluster_id
deployment_id
replica_id
emission timestamp
payload hash
source_clean_block_id
source_watch_id
pressure_lifecycle_key legacy
transport context version
telemetry counter
advisory emission count tanpa deduplication
```

`MATURE_ADVISORY` DILARANG membuat lifecycle ID dari satu emission. Identity harus berasal dari durable market-episode grouping policy.

# 5. Workflow end-to-end

```text
JALUR RAW CANONICAL
RAW SIGNALTHROTTLE STREAM
→ canonical raw event ledger
→ global active block FSM
→ durable PairAdmission evaluation
→ PairAdmissionCoverage classification
→ PairAdmission GRANTED / REJECTED / SUSPENDED
→ StrategyAnalysisAdmission CANONICAL_RAW
                         \
                          \
                           → open/attach durable AnalysisLifecycle
                          /
                         /
JALUR ADVISORY
DERIVED PRESSURE / CANARY / MICROBOOST STATE
→ canonical PressureEmission normalization
→ dedupe + pulse/state reduction
→ advisory maturity classification
→ PairAdmissionCoverage classification
→ StrategyAnalysisAdmission MATURE_ADVISORY

CONVERGED ANALYSIS
→ materialize available pressure/price evidence
→ create/update PressureDirectionalHypothesis
→ authoritative quote/candle quality evaluation
→ material ContextEpoch
→ legal direction domain + route + location alignment
→ liquidity transition
→ immutable DirectionalThesis
→ closed H1 authority
→ ordered M15 proof
→ PressureRange + route-specific ExecutionBox
→ nearest fresh structural target
→ feasible-entry intersection
→ structural SL + broker-aware cost/RR
→ non-executable TradePlanCandidate
```

Handoff setelah candidate:

```text
CANONICAL_RAW candidate
+ seluruh S3–S5 gate lulus
→ BOLEH masuk Risk Authority Contract

MATURE_ADVISORY candidate
→ promotion_eligibility = SHADOW_ONLY
→ risk_handoff_allowed = false
→ final_signal_allowed = false
→ execution_command_allowed = false
```

Jika PairAdmission raw muncul setelah lifecycle advisory sudah terbentuk:

```text
→ attach CANONICAL_RAW admission ke lifecycle yang sama
→ preserve lifecycle identity dan seluruh evidence lineage
→ re-evaluate context, proof, box, target, dan geometry
→ emit candidate revision baru
→ advisory candidate lama tetap immutable dan tidak dipromosikan otomatis
```

Jika satu gate tidak terbukti:

```text
WAIT
SUSPENDED_DATA_QUALITY
CONDITIONAL_SETUP
TERMINAL_NO_TRADE
```

Bukan forced order.

# 6. S0 — Pressure normalization dan telemetry boundary

## 6.1 Raw versus derived event

```text
Raw SignalThrottle event
= authority untuk global ordering dan PairAdmission

SignalPressureStateJSON / CANARY / pressure summary
= derived evidence, observability, advisory maturity, lifecycle enrichment
= bukan raw global ordering authority
= BOLEH membuka MATURE_ADVISORY analysis path setelah policy lulus
```

Urutan derived multi-pair emission DILARANG digunakan untuk merekonstruksi raw global block.

## 6.2 Canonical PressureEmission

Semua schema lama dan baru dinormalisasi ke satu envelope immutable:

```yaml
PressureEmissionV3_1:
  transport_event_id: uuid
  raw_event_id: string|null
  payload_hash: sha256
  event_time_utc: timestamp
  received_at_utc: timestamp
  symbol: string

  deployment:
    deployment_id: string|null
    commit_sha: string|null
    replica_id: string|null
    schema_version: string
    emitter_policy_version: string|null

  source:
    source_stage: string
    source_family: string|null
    source_authority_class: RAW_SIGNALTHROTTLE|DERIVED_PRESSURE_ADVISORY|UNKNOWN
    cluster_id: string|null
    source_clean_block_id: string|null
    source_watch_id: string|null

  pressure:
    raw_direction: BUY|SELL|null
    candidate_direction: BUY|SELL|null
    watch_direction: BUY|SELL|null
    block_direction: BUY|SELL|null
    direction_lineage_alignment: ALIGNED|CONFLICT|UNAVAILABLE
    pressure_consensus_status: BUY|SELL|CONFLICT|INCOMPLETE|STALE
    effective_ticks: integer|null
    event_count: integer|null
    duration_seconds: decimal|null
    density: decimal|null
    eligible_for_context_resolution: boolean
    advisory_maturity: IMMATURE|MATURE|EXTREME|EXPIRED|UNKNOWN
    advisory_maturity_policy_version: string|null

  reaction:
    pressure_resolution_direction: BUY|SELL|null
    pressure_resolution_direction_role: COUNTER_REACTION_ONLY_NOT_OPPOSITE_STRATEGY_AUTHORITY|SAME_DIRECTION_REACTION|UNAVAILABLE
    pressure_resolution_direction_authorized: boolean
    opposite_strategy_direction_authorized: boolean
    legal_strategy_direction: BUY|SELL|null

  microboost_snapshot:
    detected: boolean
    strength: string|null
    level: string|null

  price_snapshot:
    reference_price: decimal|null
    observed_price: decimal|null
    observed_price_status: LIVE|AVAILABLE|STALE|MISSING
    observed_price_time: timestamp|null
    provider_id: string|null
    source_tick_id: string|null

  context_snapshot:
    daily_bias: string|null
    h4_structure: string|null
    price_location: string|null
    liquidity_context: string|null
    allowed_playbook: string|null
    blocked_playbooks: array

  analysis_flags:
    pair_admission_applicable: boolean|null
    strategy_analysis_admission_class: CANONICAL_RAW|MATURE_ADVISORY|null
    strategy_next_required_stage: string|null

  execution_flags:
    final_direction: WAIT|BUY|SELL
    valid_for_execution: boolean
    tradeplan_valid: boolean
    execution_valid_now: boolean
```

## 6.3 Source stage semantics

```text
source_stage
= modul yang menerbitkan emission
= producer metadata
= non-monotonic

strategy_stage
= posisi durable lifecycle dalam S1–S5
= monotonic kecuali explicit revalidation/supersession

strategy_next_required_stage
= canonical next-stage authority
```

Sistem DILARANG membaca sequence seperti:

```text
CANDIDATE_LIFECYCLE → MICROBOOST
```

sebagai lifecycle “mundur”.

## 6.4 Derived-pressure coverage classifier dan advisory sentinel

Derived pressure BOLEH menjadi sentinel, tetapi DILARANG langsung menyimpulkan bahwa PairAdmission evaluation hilang.

```text
derived advisory menjadi MATURE/EXTREME
→ classify raw-authority coverage
→ classify PairAdmission applicability
→ classify StrategyAnalysisAdmission
```

Hasil PairAdmission coverage yang sah:

```text
raw coverage COMPLETE
+ eligible raw block tersedia
+ evaluation tersedia
→ EVALUATED

raw coverage COMPLETE
+ tidak ada eligible raw-authority block
→ NOT_APPLICABLE_NO_RAW_AUTHORITY_BLOCK

raw coverage COMPLETE
+ eligible raw block tersedia
+ evaluation hilang setelah SLA
→ MISSING_EVALUATION_INCIDENT

raw coverage INCOMPLETE atau UNKNOWN
→ INDETERMINATE_RAW_AUTHORITY_COVERAGE
→ replay_required = true
```

Hanya `MISSING_EVALUATION_INCIDENT` merupakan scheduler/evaluation incident.

Independen dari coverage tersebut:

```text
mature advisory evidence + direction ALIGNED + policy lulus
→ StrategyAnalysisAdmission MATURE_ADVISORY WAJIB dievaluasi
```

Sentinel DILARANG memberi PairAdmission grant, risk authority, atau execution authority.

# 7. S1A — PairAdmission v3.1 dan coverage

## 7.1 Authority

PairAdmission hanya berasal dari:

1. ordered raw `SignalThrottle` stream; atau
2. canonical raw block ledger yang membuktikan ordering, completeness, dan interruption.

CANARY, derived pressure, effective ticks, advisory maturity, Microboost state, dan `SignalPressureStateJSON` DILARANG menjadi PairAdmission authority.

## 7.2 Global block FSM

```text
IDLE
→ ACTIVE(symbol)
→ THRESHOLD_REACHED
→ ADMISSION_EVALUATING
→ ADMITTED atau REJECTED atau SUSPENDED
→ FINALIZED ketika symbol lain muncul
```

Gap tanpa symbol lain:

```text
gap <= freshness policy
→ block dapat lanjut

gap > freshness policy
→ SUSPENDED_SOURCE_GAP
→ tidak boleh diam-diam dianggap continuity atau interruption
```

## 7.3 Eligibility minimum

```text
threshold_event_time - block_started_at >= 300 detik
+ cross_symbol_interruption_count = 0
+ raw lineage complete
→ eligible for durable PairAdmission evaluation
```

Threshold 300 detik:

```text
memilih pair untuk canonical raw analysis
bukan direction authority
bukan tradeplan
bukan risk reservation
bukan order
```

Direction conflict tidak menghapus pair activity. Ia menurunkan pressure evidence quality.

## 7.4 PairAdmission evaluation FSM

```text
PENDING_RAW_COVERAGE
PENDING_THRESHOLD
EVALUATING
GRANTED
REJECTED
SUSPENDED_SOURCE_GAP
SUSPENDED_LEDGER_GAP
EXPIRED_GRANT
RECONCILIATION_REQUIRED
```

## 7.5 Evaluation completeness invariant

Setiap **eligible canonical raw block** WAJIB mempunyai tepat satu durable outcome:

```text
GRANTED
atau
REJECTED dengan reason code
atau
SUSPENDED dengan reason code
```

`NOT_EVALUATED` hanya state sementara sebelum evaluator SLA habis.

Kondisi berikut adalah incident:

```text
eligible raw block tanpa durable evaluation setelah SLA
persisted evaluation tanpa attachment ke lifecycle/emission
multiple grants untuk block yang sama
```

Mature derived/CANARY pressure tanpa eligible raw block **bukan** missed-evaluation incident.

## 7.6 Raw-authority coverage

Coverage raw authority WAJIB dinilai terpisah dari admission decision:

```text
COMPLETE
INCOMPLETE
UNKNOWN
```

`NOT_APPLICABLE_NO_RAW_AUTHORITY_BLOCK` hanya boleh diberikan jika:

```text
raw_authority_coverage_status = COMPLETE
+ tidak ada eligible raw-authority block pada window yang dinilai
```

Jika coverage `INCOMPLETE` atau `UNKNOWN`:

```text
→ status = INDETERMINATE_RAW_AUTHORITY_COVERAGE
→ replay_required = true
→ incident scheduler TIDAK BOLEH DIINFERENSIKAN
```

## 7.7 Trigger evaluator

Evaluator WAJIB berjalan ketika:

```text
threshold 300 detik pertama kali dilintasi
scanner cycle berjalan selama block aktif
block difinalisasi oleh symbol lain
late raw event masuk
service restart
feature cutover
raw-ledger backfill
attachment reconciliation
```

## 7.8 Startup recovery dan cutover backfill

```text
last committed admission watermark
→ replay raw ledger dari watermark - safety overlap
→ rebuild open/finalized block
→ idempotently evaluate missing block
→ preserve original admission identity
```

Pada first deployment/cutover, retention window harus cukup untuk mengevaluasi episode yang terjadi sebelum scanner aktif.

Process-local raw buffer DILARANG menjadi satu-satunya basis canonical PairAdmission.

## 7.9 Admission TTL

```text
ADMISSION_GRANT_VALID_UNTIL
= freshness token untuk attach evidence baru
≠ lifecycle expiry
≠ thesis expiry
≠ campaign expiry
```

Grant expiry tidak otomatis menutup lifecycle yang telah dibuka.

## 7.10 PairAdmission dan data quality harus independen

Kondisi berikut DILARANG menggagalkan PairAdmission:

```text
PRICE_FROZEN
PRICE_QUALITY_WARMING_UP
DAILY_CONTEXT_STALE
allowed_playbook=NONE
final_direction=WAIT
H1/M15 belum tersedia
```

Kondisi tersebut hanya memengaruhi S2–S5.

## 7.11 PairAdmission evaluation contract

```yaml
PairAdmissionEvaluationV3_1:
  admission_evaluation_id: uuid
  active_block_id: string
  symbol: string
  decision: GRANTED|REJECTED|SUSPENDED
  reason_code: string
  block_started_at: timestamp
  evaluated_at: timestamp
  duration_seconds: decimal
  raw_event_count: integer
  maximum_source_gap_seconds: decimal|null
  cross_symbol_interruption_count: integer
  raw_lineage_hash: sha256
  admission_rule_version: string
```

## 7.12 PairAdmission coverage contract

```yaml
PairAdmissionCoverageV1:
  pair_admission_coverage_id: uuid
  symbol: string
  observed_window_start_utc: timestamp
  observed_window_end_utc: timestamp

  raw_authority_coverage_status: COMPLETE|INCOMPLETE|UNKNOWN
  raw_authority_block_present: boolean
  raw_authority_block_eligible: boolean|null
  raw_authority_block_id: string|null

  admission_coverage_status: EVALUATED|NOT_APPLICABLE_NO_RAW_AUTHORITY_BLOCK|MISSING_EVALUATION_INCIDENT|INDETERMINATE_RAW_AUTHORITY_COVERAGE

  admission_evaluation_id: uuid|null
  admission_decision: GRANTED|REJECTED|SUSPENDED|null

  advisory_pressure_maturity: IMMATURE|MATURE|EXTREME|EXPIRED|UNKNOWN
  replay_required: boolean
  incident_required: boolean
  reason_code: string
  rule_version: pair-admission-coverage.v1
```

Invariant:

```text
advisory_pressure_maturity=MATURE/EXTREME
≠ raw_authority_block_eligible=true
```

# 7A. S1B — StrategyAnalysisAdmissionV1

## 7A.1 Tujuan

`StrategyAnalysisAdmissionV1` memisahkan dua pertanyaan:

```text
Apakah pair memiliki canonical raw PairAdmission?
≠
Apakah pressure episode wajib dianalisis lebih lanjut?
```

PairAdmission tetap raw-only. StrategyAnalysisAdmission adalah pintu menuju durable analysis lifecycle.

## 7A.2 Admission classes

### `CANONICAL_RAW`

Sumber:

```text
PairAdmission decision = GRANTED
```

Authority:

```text
membuka/attach AnalysisLifecycle
membuka PressureDirectionalHypothesis
menjalankan H4/H1/M15/M1 analysis
menghasilkan TradePlanCandidate
BOLEH menuju Risk Authority setelah seluruh S3–S5 gate lulus
```

### `MATURE_ADVISORY`

Sumber:

```text
CANARY / derived pressure / Microboost-derived state
+ advisory maturity policy lulus
+ direction lineage ALIGNED
+ pressure belum expired
+ evidence eligible untuk Context Resolution
```

Authority:

```text
WAJIB membuka/attach AnalysisLifecycle
WAJIB membuka PressureDirectionalHypothesis searah pressure
WAJIB memicu prefetch H4/H1/M15/M1
WAJIB dianalisis sampai WAIT / NO_TRADE / TradePlanCandidate SHADOW_ONLY
```

Larangan mutlak:

```text
risk_authority = false
risk_handoff_allowed = false
final_signal_allowed = false
execution_command_allowed = false
broker_side_effect_allowed = false
```

## 7A.3 Maturity eligibility universal

MATURE_ADVISORY admission diberikan bila seluruh syarat berikut lulus:

```text
advisory_maturity in MATURE|EXTREME
+ effective evidence sudah dideduplicate
+ direction_lineage_alignment = ALIGNED
+ pressure_consensus_status in BUY|SELL
+ pressure belum expired
+ lifecycle candidate belum terminal
+ pressure evidence coverage cukup untuk membuktikan maturity dan alignment
+ pressure eligible untuk Context Resolution
```

Quote/candle/market-data coverage BOLEH belum lengkap setelah admission. Kondisi tersebut tidak menghapus admission; lifecycle masuk `WAITING_PRICE_QUALITY`, `WAITING_PRICE_COVERAGE`, atau `SUSPENDED_DATA_QUALITY`. Namun pressure evidence yang dipakai untuk menetapkan maturity dan direction alignment harus cukup dan dapat diaudit.

Policy dapat menggunakan:

```text
duration material
effective ticks/events
pulse/reinforcement morphology
direction persistence
continuity quality
density bucket
source-family quality
```

Threshold parameter berada pada `AdvisoryPressureMaturityPolicyRegistry`, bukan hardcode tersebar di strategy code.

## 7A.4 Contract

```yaml
StrategyAnalysisAdmissionV1:
  strategy_analysis_admission_id: uuid
  symbol: string
  market_episode_id: uuid

  admission_class: CANONICAL_RAW|MATURE_ADVISORY
  admission_status: PENDING|GRANTED|REJECTED|SUSPENDED|EXPIRED
  analysis_authority: FULL_CANONICAL_ANALYSIS|FULL_SHADOW_ANALYSIS
  source_authority: RAW_SIGNALTHROTTLE_LEDGER|DERIVED_PRESSURE_ADVISORY

  pair_admission_evaluation_id: uuid|null
  pair_admission_coverage_id: uuid|null

  pressure_direction: BUY|SELL|CONFLICT|INCOMPLETE
  direction_lineage_alignment: ALIGNED|CONFLICT|UNAVAILABLE
  advisory_maturity: IMMATURE|MATURE|EXTREME|EXPIRED|UNKNOWN
  advisory_maturity_policy_version: string|null

  context_resolution_allowed: boolean
  structural_evidence_prefetch_required: boolean
  tradeplan_candidate_allowed: boolean
  promotion_eligibility: CANONICAL_RISK_PATH|SHADOW_ONLY

  risk_authority: false
  execution_authority: false
  reason_code: string
  evidence_hash: sha256
  rule_version: strategy-analysis-admission.v1
  granted_at_utc: timestamp|null
  expires_at_utc: timestamp|null
```

`risk_authority=false` pada object admission itu sendiri berlaku untuk kedua kelas. `promotion_eligibility` pada admission hanya merupakan batas maksimum downstream, bukan authorization saat ini. Risk authority baru dapat muncul pada contract terpisah setelah canonical candidate lulus seluruh gate.

## 7A.5 Mandatory analysis behavior

Jika `MATURE_ADVISORY` GRANTED:

```text
→ create/attach lifecycle
→ create/update PressureDirectionalHypothesis
→ set analysis priority dari policy
→ enqueue durable evidence job
→ prefetch authoritative H4/H1/M15/M1
→ preserve candidate walau quote frozen atau context conflict
→ zero risk reservation
→ zero command
```

Jika worker capacity penuh:

```text
→ state = ANALYSIS_QUEUED
→ durable priority queue
→ pair DILARANG silent-drop
```

## 7A.6 Upgrade dari advisory ke canonical raw

Jika PairAdmission GRANTED muncul setelah lifecycle advisory terbuka:

```text
→ attach CANONICAL_RAW admission ke lifecycle yang sama
→ highest_analysis_authority = CANONICAL_RAW
→ preserve strategy_lifecycle_id
→ preserve all advisory evidence lineage
→ do not create duplicate lifecycle
```

Advisory candidate DILARANG langsung dipromosikan. Sistem WAJIB:

```text
re-evaluate current ContextEpoch
rebuild/revalidate H1/M15 proof
revalidate ExecutionBox
reselect nearest target
recalculate geometry/cost/RR
emit new TradePlanCandidate revision dengan canonical raw lineage
```

## 7A.7 Rejection dan suspension

MATURE_ADVISORY dapat ditolak atau disuspensi hanya dengan reason code eksplisit, misalnya:

```text
ADVISORY_PRESSURE_IMMATURE
ADVISORY_DIRECTION_LINEAGE_CONFLICT
ADVISORY_PRESSURE_EXPIRED
ADVISORY_EVIDENCE_COVERAGE_INSUFFICIENT
ADVISORY_CONTEXT_RESOLUTION_INELIGIBLE
```

Absence of PairAdmission DILARANG menjadi reason penolakan MATURE_ADVISORY.

## 7A.8 Invariant

```text
CANARY ≠ PairAdmission authority
CANARY mature = wajib dinilai untuk MATURE_ADVISORY analysis admission
MATURE_ADVISORY = full analysis, shadow only
MATURE_ADVISORY candidate ≠ risk-eligible candidate
PairAdmission NOT_APPLICABLE ≠ no-analysis
quote frozen ≠ candidate erased
context conflict ≠ candidate erased
later canonical raw grant ≠ duplicate lifecycle
```

---

# 8. S2 — Durable AnalysisLifecycle

## 8.1 Object yang dibuka

`StrategyAnalysisAdmission GRANTED` membuka atau menggabungkan:

```text
market_episode_id
strategy_lifecycle_id
```

Keduanya non-executable.

Lifecycle menyimpan authority tertinggi yang pernah diterima:

```text
MATURE_ADVISORY
atau
CANONICAL_RAW
```

## 8.2 AnalysisLifecycle contract

```yaml
AnalysisLifecycleV3_1:
  strategy_lifecycle_id: uuid
  market_episode_id: uuid
  symbol: string
  state: string
  highest_analysis_authority: MATURE_ADVISORY|CANONICAL_RAW
  active_strategy_analysis_admission_id: uuid
  admission_lineage_ids: array[uuid]
  direction_state: BUY|SELL|CONFLICT|INCOMPLETE
  opened_at_utc: timestamp
  last_event_at_utc: timestamp
  last_material_event_at_utc: timestamp
  active_context_epoch_id: uuid|null
  active_pressure_hypothesis_id: uuid|null
  execution_authority: false
  material_state_hash: sha256
  lifecycle_rule_version: string
```

## 8.3 Lifecycle grouping

Emission masuk lifecycle yang sama bila:

```text
symbol sama
lifecycle belum terminal
market episode continuity terbukti
pressure contract compatible
belum ada hard structural invalidation
belum ada confirmed opposite transition
merge policy version sama
```

Lifecycle baru DILARANG dibuat hanya karena:

```text
cluster_id berubah
clean block baru
source_watch_id baru
deployment berubah
telemetry refresh
transport context berubah
Microboost snapshot tetap true
admission class berubah dari MATURE_ADVISORY ke CANONICAL_RAW
```

## 8.4 Lifecycle state minimum

```text
ANALYSIS_QUEUED
ANALYSIS_OPEN
WAITING_PRICE_COVERAGE
WAITING_PRICE_QUALITY
WAITING_CONTEXT
WAITING_STRUCTURE
CONDITIONAL_SETUP
TRADEPLAN_READY_NON_EXECUTABLE
TRANSITION_PENDING
TERMINAL_NO_TRADE
INVALIDATED
SUPERSEDED
SUSPENDED_DATA_QUALITY
```

## 8.5 Price buffering

### CANONICAL_RAW

```text
raw block starts
→ buffer M1/tick continuously

PairAdmission granted
→ materialize pressure range dari block_started_at
```

### MATURE_ADVISORY

```text
first retained material advisory event
→ buffer/materialize available price evidence
→ record exact coverage start and gaps
```

MATURE_ADVISORY DILARANG mengarang price coverage sebelum evidence tersedia.

Jika coverage tidak lengkap:

```text
lifecycle = WAITING_PRICE_COVERAGE
structural_authority = false
```

## 8.6 Authority upgrade

```text
MATURE_ADVISORY lifecycle
+ later CANONICAL_RAW admission
→ same lifecycle ID
→ append authority transition
→ re-evaluate evidence
→ no duplicate episode
```

Authority downgrade DILARANG. Expiry grant raw tidak menghapus historical canonical lineage.

## 8.7 Lifecycle close rules

Lifecycle terminal hanya jika:

```text
active hypothesis/thesis invalidated dan tidak ada dormant legal route
target map exhausted tanpa fresh route
hard revalidation gagal
market episode selesai menurut policy
provider/data quality tidak dapat dipulihkan sampai deadline
formal direction transition membuka episode baru
advisory analysis expired menurut policy tanpa canonical upgrade
```

Telemetry timeout tunggal tidak boleh otomatis mematikan cerita pasar yang masih valid.

# 9. Microboost pulse dan state

## 9.1 Prinsip

```text
microboost_detected=true
≠ pulse baru
```

Microboost adalah pressure/timing evidence. Ia bukan final direction dan bukan order authority.

## 9.2 Durable MicroboostState

```yaml
MicroboostStateV1:
  strategy_lifecycle_id: uuid
  symbol: string
  status: NONE|ACTIVE|WEAKENING|INVALIDATED|EXPIRED
  direction: BUY|SELL|null
  first_formed_at: timestamp|null
  last_pulse_at: timestamp|null
  last_confirmed_at: timestamp|null
  independent_pulse_count: integer
  reinforcement_count: integer
  current_effective_ticks: integer|null
  peak_effective_ticks: integer|null
  state_version: integer
  evidence_hash: sha256
```

## 9.3 Immutable pulse event

```yaml
MicroboostPulseEventV1:
  microboost_pulse_event_id: uuid
  strategy_lifecycle_id: uuid
  transition: FORMED|REINFORCED|WEAKENED|INVALIDATED|EXPIRED
  direction: BUY|SELL|null
  occurred_at: timestamp
  source_event_ids: array
  evidence_signature: sha256
  dedupe_key: string
```

## 9.4 Transition rule

```text
false → true
= FORMED

ACTIVE + material pulse evidence baru
= REINFORCED

ACTIVE + pressure strength/ticks turun material
= WEAKENED

formal opposite transition / structure invalidation
= INVALIDATED

TTL tanpa confirmation
= EXPIRED

sticky true tanpa evidence material baru
= NO NEW PULSE
```

Microboost pulse tidak memperpanjang setup expiry kecuali rule clock secara eksplisit mengizinkan material reset.

---

# 10. PressureDirectionalHypothesis

## 10.1 Tujuan

Object ini menjawab:

> **Arah mana yang harus diuji terlebih dahulu karena pressure episode telah matang?**

Ia bukan final thesis dan bukan order.

## 10.2 Creation rule

Canonical hypothesis dibuat setelah:

```text
StrategyAnalysisAdmission = GRANTED
+ admission_class in CANONICAL_RAW|MATURE_ADVISORY
+ pressure_consensus_status in BUY|SELL
+ direction_lineage_alignment = ALIGNED
+ canonical raw path memiliki pressure_maturity_status = QUALIFIED
  atau mature advisory path memiliki advisory_maturity in MATURE|EXTREME
+ pressure evidence tidak STALE/EXPIRED
+ lifecycle belum terminal
```

Absence of PairAdmission raw DILARANG memblokir hypothesis jika `MATURE_ADVISORY` sudah GRANTED.

`pressure_maturity_status` ditentukan oleh versioned policy yang dapat menggunakan:

```text
duration
effective event count/effective ticks
pulse morphology
density
continuity quality
direction stability
source-family quality
```

SSOT tidak mengunci universal advisory threshold; threshold berada pada policy registry.

## 10.3 PressureDirectionalHypothesis contract

```yaml
PressureDirectionalHypothesisV1_1:
  pressure_hypothesis_id: uuid
  strategy_lifecycle_id: uuid
  strategy_analysis_admission_id: uuid
  analysis_admission_class: CANONICAL_RAW|MATURE_ADVISORY
  analysis_authority: FULL_CANONICAL_ANALYSIS|FULL_SHADOW_ANALYSIS
  promotion_eligibility: CANONICAL_RISK_PATH|SHADOW_ONLY

  direction: BUY|SELL
  authority: ANALYSIS_PRIORITY_ONLY
  state: OPEN|CONTEXT_ALIGNED|CONTEXT_CONFLICT|WAITING_VALID_LOCATION|WAITING_PRICE_QUALITY|WAITING_STRUCTURE|INVALIDATED|EXPIRED

  pressure_authority_mode: RADAR_ONLY|CONSOLIDATED_DIRECTION_CONTRACT
  pressure_contract_status: OPEN|LOCKED|TRANSITION_PENDING|INVALIDATED|EXPIRED
  pressure_consensus_status: BUY|SELL
  direction_lineage_alignment: ALIGNED
  pressure_maturity_status: QUALIFIED|MATURE|EXTREME
  pressure_maturity_policy_version: string

  location_alignment: FAVORABLE|NEUTRAL|UNFAVORABLE|UNKNOWN
  context_alignment: ALIGNED|CONFLICT|UNRESOLVED|EMPTY

  risk_handoff_allowed: boolean
  final_signal_allowed: false
  execution_command_allowed: false

  evidence_hash: sha256
  created_at: timestamp
  last_material_update_at: timestamp
```

Invariant:

```text
analysis_admission_class=MATURE_ADVISORY
→ promotion_eligibility=SHADOW_ONLY
→ risk_handoff_allowed=false
```

## 10.4 Universal priority rule

Jika pressure consensus dan location sama-sama mendukung direction:

```text
→ hypothesis state = CONTEXT_ALIGNED atau WAITING_STRUCTURE
→ H1/M15 evidence searah diprioritaskan
```

Jika pressure kuat tetapi higher context berlawanan:

```text
→ hypothesis tetap disimpan
→ state = CONTEXT_CONFLICT
→ classification = COUNTER_PRESSURE_PENDING_PROOF
→ proof requirement lebih ketat
→ order tetap 0
```

Jika location tidak layak:

```text
→ hypothesis tidak dihapus
→ state = WAITING_VALID_LOCATION
→ no chase
```

Jika quote tidak authoritative:

```text
→ state = WAITING_PRICE_QUALITY
→ lifecycle dan hypothesis tetap durable
```

## 10.5 Pressure authority modes

### `RADAR_ONLY`

```text
pressure direction = primary analysis priority
context boleh mengizinkan separate opposite hypothesis/thesis
hanya dengan legal direction domain + full proof
```

### `CONSOLIDATED_DIRECTION_CONTRACT`

Producer harus membawa explicit fields:

```text
pressure_authority_mode
pressure_contract_status
pressure_contract_version
pressure_contract_invalidated_at
```

Kesamaan `raw=candidate=watch=block` saja TIDAK BOLEH DIINFERENSIKAN sebagai contract locked.

Jika explicit contract `LOCKED BUY`:

```text
BUY atau WAIT/NO_TRADE
SELL thesis dilarang sampai formal transition
```

Jika explicit contract `LOCKED SELL`:

```text
SELL atau WAIT/NO_TRADE
BUY thesis dilarang sampai formal transition
```

## 10.6 Direction-lineage conflict

```text
raw/candidate/watch/block tidak konsisten
→ direction_lineage_alignment = CONFLICT
→ pressure_consensus_status = CONFLICT
→ tidak membuat active hypothesis
→ lifecycle state = TRANSITION_PENDING atau WAITING_PRESSURE_RESOLUTION
```

Downstream DILARANG memilih satu direction secara diam-diam.

# 11. Market-data, quote, dan candle authority

## 11.1 Tiga harga berbeda

```text
reference_price
= audit anchor; tidak otomatis live

observed_price
= harga provider yang benar-benar diamati dengan timestamp dan quality

execution_price
= broker fill/quote yang menjadi authority eksekusi
```

Ketiganya DILARANG dicampur.

## 11.2 Tiga authority berbeda

```text
analysis_observation_authority
structural_candle_authority
execution_price_authority
```

StrategyAnalysisAdmission dan AnalysisLifecycle dapat tetap aktif pada level pressure meskipun structural/execution authority false. PairAdmission raw tidak wajib untuk jalur `MATURE_ADVISORY`.

## 11.3 Quote quality FSM

```text
UNPRIMED
→ PRICE_QUALITY_WARMING_UP
→ LIVE
→ STALE_PRESERVED
atau PRICE_FROZEN
atau INSUFFICIENT_HISTORY
→ RECOVERING
→ LIVE
```

Invariant:

```text
unprimed detector
→ PRICE_QUALITY_WARMING_UP

properly primed detector + stale/frozen scenario
→ STALE_PRESERVED atau PRICE_FROZEN
→ reference_price_is_live=false
→ execution blocked
```

Timestamp baru dengan harga identik tidak membuktikan quote sehat.

## 11.4 Frozen quote behavior

```text
PairAdmission tetap dapat GRANTED bila raw authority memenuhi rule
StrategyAnalysisAdmission tetap hidup
AnalysisLifecycle tetap hidup
PressureDirectionalHypothesis tetap hidup
trade geometry dan execution diblokir
state = WAITING_PRICE_QUALITY
```

Frozen quote DILARANG mengubah pressure direction atau menghapus episode.

## 11.5 Candle Authority v3

Semua D1/H4/H1/M15 evidence HARUS GAGAL-TERTUTUP.

Kontrak minimum:

```text
provider_id
provider_symbol
provider_timezone
session_calendar_version
timeframe
period_open
period_close
source_bar_ids
expected_subbars
actual_subbars
coverage_complete
gap_status
is_closed
structural_authority
source_hash
```

Aturan:

```text
closed flag hilang       → UNKNOWN
period belum berakhir    → FORMING
coverage tidak lengkap   → INCOMPLETE
gap/outlier unresolved   → QUARANTINED
source close > decision  → FUTURE_LEAKAGE_BLOCK
structural_authority     → false
```

Synthetic candle wajib mengikuti provider calendar, DST, rollover, weekend, holiday, dan timeframe anchor.

## 11.6 Daily freshness

Freshness harus berdasarkan:

```text
latest expected closed period
provider/session calendar
period_open
period_close
weekend/holiday closure
missed expected closed bars
```

Wall-clock age sendiri DILARANG menjadi authority.

---

# 12. S3 — Material ContextEpoch dan legal direction domain

## 12.1 Material ContextEpoch

Context epoch berubah hanya jika material market context berubah:

```text
authoritative D1/H4 source IDs
D1/H4 structure
price location
liquidity state
primary direction domain
counter-pressure policy
allowed/blocked route
target-map version
structural invalidation version
pressure contract status material
```

DILARANG masuk material hash:

```text
cluster_id
emission timestamp
deployment ID
replica ID
telemetry count
reference-price refresh
box version
transport context version
```

## 12.2 Location alignment

Location menjawab apakah harga berada di area yang mendukung direction hypothesis.

```text
FAVORABLE
NEUTRAL
UNFAVORABLE
UNKNOWN
```

Premium/discount tidak boleh menjadi shortcut universal. Location alignment dihitung oleh versioned `LocationRoutePolicy` berdasarkan instrument class, dealing range, route, target room, dan context.

## 12.3 Direction domain registry

```text
BUY_ONLY
SELL_ONLY
BOTH_CONDITIONAL
UNRESOLVED
EMPTY
```

Registry menghasilkan:

```text
primary_direction_domain
allowed_directions
allowed_routes
blocked_routes
counter_pressure_observation_allowed
counter_pressure_thesis_status
resolution_evidence_hash
registry_version
```

## 12.4 Context tidak boleh menghapus pressure evidence

Jika primary domain berbeda dari pressure hypothesis:

```text
pressure hypothesis tetap tersimpan
context_alignment = CONFLICT
same-direction thesis belum authorized
counter-pressure classification ditentukan secara eksplisit
```

Context hanya dapat:

```text
ALIGN
CONFLICT
DEFER
BLOCK_ROUTE
AUTHORIZE_PROOF_REQUIRED_COUNTER_PRESSURE
INVALIDATE berdasarkan material evidence
```

Context DILARANG mengubah historical pressure direction.

## 12.5 Counter-pressure separation

Pisahkan:

```text
counter_pressure_observation
= force lawan terlihat

counter_pressure_thesis_authorization
= PROHIBITED | PROOF_REQUIRED | AUTHORIZED
```

`WAIT_FOR_BUY_LOCATION` tidak otomatis memberi SELL permission, tetapi juga tidak boleh menghapus persistent SELL pressure.

`WAIT_FOR_SELL_LOCATION` tidak otomatis memberi BUY permission, tetapi juga tidak boleh menghapus persistent BUY pressure.

## 12.6 Rejection semantics

```text
BUY pressure + BUY_SIDE_REJECTED
≠ automatic SELL

SELL pressure + SELL_SIDE_REJECTED
≠ automatic BUY
```

Reaction direction harus dipisahkan dari legal strategy direction:

```yaml
pressure_resolution_direction: BUY|SELL|null
pressure_resolution_direction_role:
  COUNTER_REACTION_ONLY_NOT_OPPOSITE_STRATEGY_AUTHORITY
  |SAME_DIRECTION_REACTION
  |UNAVAILABLE
pressure_resolution_direction_authorized: false
opposite_strategy_direction_authorized: false
legal_strategy_direction: null
```

Hasil yang sah:

```text
same-direction hypothesis invalidated/deferred
atau
separate opposite thesis dibuat jika domain dan full proof mengizinkan
```

`legal_strategy_direction` baru boleh terisi setelah ContextEpoch, direction domain, dan full H1/M15 proof mengotorisasi direction tersebut.

---

# 13. Liquidity state machine

State minimum:

```text
UNTESTED
APPROACHING
TESTING
ACCEPTED
REJECTED
FAILED_ACCEPTANCE
CONSUMED
INVALIDATED
EXPIRED
```

Transition wajib berasal dari ordered authoritative candle dan level version yang sama.

Contoh generic:

```text
BUY_SIDE_TESTING
→ close above + hold/retest
→ ACCEPTED

BUY_SIDE_TESTING
→ sweep + close kembali + failed reclaim
→ REJECTED / FAILED_ACCEPTANCE
```

Liquidity resolution direction adalah observed reaction, bukan otomatis legal strategy direction.

```text
pressure_resolution_direction
≠ legal_strategy_direction
```

---

# 14. S4 — Immutable DirectionalThesis dan ordered proof

## 14.1 Thesis creation

DirectionalThesis dibuat hanya jika:

```text
active PressureDirectionalHypothesis atau legally authorized separate route
+ authoritative ContextEpoch
+ direction berada dalam legal domain
+ required proof tersedia
```

Thesis mewarisi `analysis_admission_class` dan `promotion_eligibility` dari lifecycle/hypothesis. Thesis dari `MATURE_ADVISORY` BOLEH dibentuk untuk shadow structural analysis, tetapi tetap tidak memiliki risk atau execution authority.

## 14.2 Thesis contract

```yaml
DirectionalThesisV3_1:
  strategy_thesis_id: uuid
  strategy_lifecycle_id: uuid
  strategy_analysis_admission_id: uuid
  analysis_admission_class: CANONICAL_RAW|MATURE_ADVISORY
  promotion_eligibility: CANONICAL_RISK_PATH|SHADOW_ONLY
  context_epoch_id: uuid
  source_pressure_hypothesis_id: uuid|null
  direction: BUY|SELL
  thesis_class: CONTINUATION|COUNTER_PRESSURE|RANGE_FADE|BREAKOUT|REVERSAL_NEW_EPISODE
  direction_immutable: true
  state: DORMANT|PENDING_CONTEXT|PENDING_H1|PENDING_M15|STRUCTURALLY_CONFIRMED|GEOMETRY_PENDING|INVALIDATED|SUPERSEDED|EXPIRED
  risk_handoff_allowed: boolean
  execution_authority: false
  resolution_evidence_hash: sha256
  created_at_decision_time: timestamp
```

Invariant:

```text
analysis_admission_class=MATURE_ADVISORY
→ promotion_eligibility=SHADOW_ONLY
→ risk_handoff_allowed=false
```

## 14.3 Continuation proof

Wajib:

```text
authoritative context epoch
direction berada dalam legal domain
closed H1 structure confirmed
closed M15 structural break
M15 acceptance atau failed reclaim/retest
timestamp H1 proof <= M15 proof <= decision_time
```

## 14.4 Counter-pressure proof

Semua continuation proof ditambah:

```text
counter_pressure_thesis_status = AUTHORIZED atau PROOF_REQUIRED yang seluruh proof-nya terpenuhi
location_alignment mendukung route
liquidity TESTING → REJECTED/FAILED_ACCEPTANCE
explicit fresh opposite target
no blocked route
formal pressure contract tidak melarang opposite direction
```

Rejection candle tunggal tidak cukup.

## 14.5 H1/M15 ordering

Evidence harus menyimpan:

```text
h1_proof_id
h1_source_candle_ids
h1_closed_at
m15_proof_id
m15_source_candle_ids
m15_closed_at
level_version
ordered_proof_hash
```

Status field saja tanpa source candle dan ordering tidak cukup.

## 14.6 Pattern registry

Pattern yang boleh dipakai bila objektif dan versioned:

```text
breakout acceptance
breakdown acceptance
break–retest continuation
failed breakout + failed reclaim
failed breakdown + reclaim
liquidity sweep + CHOCH/BOS
pullback continuation
range-edge rejection
```

---

# 15. Durable evaluation scheduler dan stage semantics

## 15.1 WAITING_EVIDENCE bukan terminal

Re-evaluate hanya pada material trigger:

```text
new StrategyAnalysisAdmission
PairAdmission recovery/attachment
raw-authority coverage transition
advisory maturity transition
new authoritative D1/H4/H1/M15/M1 close
material pressure evidence
Microboost pulse transition
liquidity transition
ContextEpoch transition
ExecutionBox material revision
target-map revision
stage deadline
quote-quality recovery
canonical authority upgrade
```

## 15.2 Duplicate telemetry

Duplicate atau carried-state telemetry:

```text
tidak membuat StrategyAnalysisAdmission baru
tidak membuat lifecycle baru
tidak membuat pulse baru
tidak membuat ContextEpoch baru
tidak membuat thesis baru
tidak membuat box version baru
tidak memperpanjang expiry
tidak menaikkan advisory maturity tanpa material evidence
```

## 15.3 Durable advisory queue

Jika `MATURE_ADVISORY` memenuhi policy tetapi worker capacity penuh:

```text
→ analysis_queue_state = QUEUED
→ persist priority dan evidence hash
→ retry secara durable
→ DILARANG silent-drop
```

Priority policy harus versioned dan tidak boleh memakai nama symbol sebagai cabang.

## 15.4 Canonical stage fields

```text
source_stage
= producer metadata

strategy_stage
= monotonic S1–S5 business stage

strategy_next_required_stage
= canonical stage berikut yang benar-benar diperlukan

next_material_trigger
= event/candle/transisi yang dapat menjalankan evaluasi ulang
```

Legacy generic `next_required_stage` dan `direction_next_required_stage` dipertahankan untuk kompatibilitas, tetapi tidak boleh menjadi canonical authority.

Precedence:

```text
strategy_next_required_stage
> direction_next_required_stage legacy
> next_required_stage legacy
```

## 15.5 Evaluation record

```yaml
StrategyEvaluationJobV3_1:
  evaluation_job_id: uuid
  strategy_lifecycle_id: uuid
  strategy_analysis_admission_id: uuid
  analysis_admission_class: CANONICAL_RAW|MATURE_ADVISORY
  decision_time: timestamp
  input_hash: sha256
  output_hash: sha256|null
  strategy_stage_before: string
  strategy_stage_after: string
  reason_code: string
  strategy_next_required_stage: string|null
  next_material_trigger: string|null
  retry_count: integer
  queue_priority: integer|null
```

## 15.6 Observability severity

Structured severity adalah authority. Wrapper log dan payload severity WAJIB konsisten.

```text
INFO
= expected state transition / WAIT / advisory analysis queued

WARNING
= data-quality block, missing raw evaluation, lifecycle inconsistency,
  raw coverage indeterminate, advisory analysis backlog SLA breach

ERROR
= persistence failure, future leakage attempt, duplicate authority,
  impossible transition, advisory candidate crossing risk boundary
```

# 16. PressureRange dan ExecutionBox

## 16.1 Pemisahan

```text
ActiveBlock
= pair-selection object

PressureRange
= material observed price range selama pressure episode

ExecutionBox
= route-specific legal entry geometry
```

Ketiganya bukan objek yang sama.

## 16.2 PressureRange

```yaml
PressureRangeV1:
  pressure_range_id: uuid
  strategy_lifecycle_id: uuid
  started_at: timestamp
  ended_at: timestamp|null
  high: decimal|null
  low: decimal|null
  price_coverage_status: COMPLETE|PARTIAL|MISSING|QUARANTINED
  source_price_ids: array
  evidence_hash: sha256
```

## 16.3 ExecutionBox FSM

```text
BUILDING
FROZEN
SUPERSEDED
INVALIDATED
CONSUMED
EXPIRED
```

ExecutionBox berubah hanya karena:

```text
material route change
new structural trigger
new retest interval
ContextEpoch transition
target/invalidation revision
```

DILARANG berubah hanya karena:

```text
emission baru
tick refresh
cluster baru
sticky Microboost state
transport context refresh
```

## 16.4 Route-specific relation

| Route | Entry relation |
|---|---|
| Pullback continuation | structural/retest interval dalam atau pada edge |
| Breakout acceptance | acceptance interval di luar origin range |
| Break–retest | boundary/retest interval |
| Failed breakout SELL | failed-reclaim/rejection interval |
| Failed breakdown BUY | reclaim/retest interval |
| Range fade | extreme/rejection interval |

Rule universal `fill harus berada di origin box` DILARANG.

---

# 17. S5 — Target-first trade geometry

## 17.1 Correct solve order

```text
1. Active immutable thesis + completed structural proof
2. Active ContextEpoch and route
3. Nearest fresh unconsumed structural target
4. Route-specific structural entry interval
5. Structural invalidation / SL boundary
6. Target-room and RR-valid entry interval
7. Broker/cost constraint interval
8. Feasible-entry intersection
9. Candidate entry and order type
10. Non-executable TradePlanCandidate
```

Actual broker fill terjadi setelah command dan bukan bagian dari Strategy Core candidate.

## 17.2 Target engine

Candidate target sources:

```text
authoritative swing high/low
D1/H4/H1 support/resistance
range boundary
breakout base
liquidity objective
versioned Fibonacci level dengan anchor as-of
```

TP1 adalah target struktural terdekat yang:

```text
authoritative
fresh
unconsumed
berada di arah thesis
belum dilewati pada decision time
```

Target lebih jauh DILARANG dipilih jika target dekat masih aktif.

## 17.3 Execution policy registry

Strategy Core tidak hardcode instrument floor di banyak fungsi.

Current project policy reference:

```yaml
execution_policy_id: FX_MIN_TARGET_10P_V1
instrument_class: FX
minimum_structural_target_pips: 10
minimum_net_rr: 1.5
target_source_required: STRUCTURAL
nearest_target_cannot_be_skipped: true
status: FROZEN_FOR_SHADOW_REPLAY
```

Instrument non-FX memakai policy terpisah.

Legacy replay BOLEH menggunakan `FX_LEGACY_6P_V1`, tetapi output harus membawa policy ID dan tidak boleh dicampur dengan hasil policy 10 pip.

## 17.4 Feasible-entry intersection

```text
feasible_entry =
  structural_entry_interval
∩ route_entry_interval
∩ target_room_interval
∩ RR_valid_interval
∩ broker_constraint_interval
```

Jika kosong:

```text
ROUTE_NO_VALID_ENTRY_DOMAIN
no fill search
no artificial SL adjustment
no reservation
no campaign
no command
```

Untuk target `T`, stop `S`, entry `E`, minimum RR `R` sebelum biaya:

```text
BUY : S < E < T dan E <= (T + R×S)/(1+R)
SELL: T < E < S dan E >= (T + R×S)/(1+R)
```

## 17.5 Structural SL

```text
BUY stop  → di bawah structural invalidation
SELL stop → di atas structural invalidation
```

Noise/spread buffer harus versioned. SL DILARANG dipersempit untuk mempercantik RR.

## 17.6 Cost and RR

```text
gross_RR
net_RR setelah spread, commission, slippage, swap bila relevan
```

Authorization baseline:

```text
net_RR_TP1 >= 1.5
```

## 17.7 TradePlanCandidate

```yaml
TradePlanCandidateV3_1:
  tradeplan_id: uuid
  tradeplan_revision: integer
  strategy_lifecycle_id: uuid
  strategy_analysis_admission_id: uuid
  analysis_admission_class: CANONICAL_RAW|MATURE_ADVISORY
  pressure_hypothesis_id: uuid|null
  strategy_thesis_id: uuid
  context_epoch_id: uuid
  execution_box_id: uuid
  box_version: integer
  direction: BUY|SELL
  state: TRADEPLAN_CANDIDATE
  final_direction: WAIT
  valid_for_execution: false

  promotion_eligibility: CANONICAL_RISK_PATH|SHADOW_ONLY
  risk_handoff_allowed: boolean
  final_signal_allowed: false
  execution_command_allowed: false
  strategy_next_required_stage: RISK_RESERVATION|SHADOW_TERMINAL_REVIEW

  target_id: uuid
  entry_interval: [decimal, decimal]
  candidate_entry: decimal
  structural_sl: decimal
  tp1: decimal
  gross_rr: decimal
  net_rr: decimal
  execution_policy_id: string
  evidence_hash: sha256
```

Invariant:

```text
analysis_admission_class=MATURE_ADVISORY
→ promotion_eligibility=SHADOW_ONLY
→ risk_handoff_allowed=false
→ strategy_next_required_stage=SHADOW_TERMINAL_REVIEW
```

```text
analysis_admission_class=CANONICAL_RAW
+ seluruh S3–S5 gate lulus
→ promotion_eligibility=CANONICAL_RISK_PATH
→ risk_handoff_allowed=true
→ valid_for_execution tetap false
```

Candidate advisory yang kemudian menerima canonical raw authority harus direplay/re-evaluate dan menghasilkan revision baru. Mutation in-place DILARANG.

Core output states:

```text
WAITING_EVIDENCE
WAITING_PRICE_QUALITY
CONDITIONAL_SETUP
ROUTE_NO_VALID_ENTRY_DOMAIN
TRADEPLAN_CANDIDATE_CANONICAL
TRADEPLAN_CANDIDATE_SHADOW_ONLY
TERMINAL_NO_TRADE
SUSPENDED_DATA_QUALITY
```

---

# 18. Expiry dan revalidation clocks

Clock WAJIB dipisahkan:

```text
PRESSURE_EVENT_TTL
ADMISSION_GRANT_VALID_UNTIL
STRATEGY_ANALYSIS_ADMISSION_VALID_UNTIL
ADVISORY_ANALYSIS_VALID_UNTIL
PRESSURE_HYPOTHESIS_VALID_UNTIL
CONTEXT_EPOCH_VALID_UNTIL
SETUP_STAGE_DEADLINE
ORDER_VALID_UNTIL
LIFECYCLE_HARD_REVALIDATION_AT
```

Telemetry refresh tidak memperpanjang clock.

Setiap clock menyimpan:

```text
clock_type
started_at
deadline
rule_version
material event yang boleh reset
expired_at
action setelah expiry
```

Expiry satu object tidak otomatis mematikan object lain.

---

# 19. Campaign, parent, child, dan reinforcement semantics

## 19.1 Scope Strategy Core

Strategy Core menentukan structural eligibility. Jumlah child dan risk amount ditentukan risk-policy version.

## 19.2 Parent

Parent hanya dapat lahir dari `TradePlanCandidate` yang:

```text
analysis_admission_class = CANONICAL_RAW
promotion_eligibility = CANONICAL_RISK_PATH
risk_handoff_allowed = true
```

serta telah lulus Risk Authority Contract. `MATURE_ADVISORY` candidate DILARANG membuat parent.

## 19.3 Sebelum parent fill

Material pressure/structure baru:

```text
→ lifecycle/ContextEpoch/ExecutionBox revision
→ pending tradeplan dapat disupersede
→ bukan child
```

## 19.4 Child

Child structurally eligible hanya jika:

```text
parent OPEN
campaign belum terminal
same immutable thesis
same compatible target map
target belum consumed
new material ExecutionBox
independent H1/M15 trigger
feasible entry valid
net RR/cost gate lulus
risk policy mengizinkan
```

## 19.5 Reinforcement

Pressure tambahan tanpa independent structure/box/trigger:

```text
REINFORCEMENT_ONLY
zero new leg
zero new risk reservation
```

## 19.6 Opposite direction

Opposite setup:

```text
new PressureDirectionalHypothesis bila formal transition
new DirectionalThesis
fresh ContextEpoch/target/route proof
new campaign jika risk-authorized
```

Bukan child dan bukan mutasi campaign lama.

---

# 20. Monotonic handoff ke risk dan execution

Detail schema berada di contract terpisah. SSOT hanya mengunci boundary berikut.

## 20.1 Transaction A — authority

Precondition:

```text
TradePlanCandidate.analysis_admission_class = CANONICAL_RAW
TradePlanCandidate.promotion_eligibility = CANONICAL_RISK_PATH
TradePlanCandidate.risk_handoff_allowed = true
```

Kemudian:

```text
lock TradePlanCandidate revision
validate fresh account snapshot
create durable risk reservation
create ExecutionCampaign
create parent PENDING leg
create FinalSignal record
write final_signal_outbox
COMMIT
```

## 20.2 Transaction B — delivery

```text
claim final_signal_outbox
verify reservation masih active
promote/sign ExecutionCommand
insert execution_commands
mark final_signal_outbox published
COMMIT
```

Temporary delivery failure tidak menghilangkan authority record.

## 20.3 EA dumb

EA hanya menerima signed/versioned command yang:

```text
active reservation
not expired
correct executor/account/broker binding
latest revision
idempotency key belum mempunyai broker effect
exact symbol/volume/entry/SL/TP representable
```

EA boleh menolak. EA DILARANG mengubah:

```text
direction
lot
entry
SL
TP
order type
risk
strategy logic
```

Timeout setelah submit menghasilkan reconciliation, bukan blind resubmit.

---

# 21. Reason-code registry minimum

## 21.1 Raw authority dan PairAdmission coverage

```text
RAW_AUTHORITY_COVERAGE_COMPLETE
RAW_AUTHORITY_COVERAGE_INCOMPLETE
RAW_AUTHORITY_COVERAGE_UNKNOWN
RAW_AUTHORITY_COVERAGE_INDETERMINATE
PAIR_ADMISSION_EVALUATED
PAIR_ADMISSION_NOT_APPLICABLE_NO_RAW_AUTHORITY_BLOCK
PAIR_ADMISSION_MISSING_EVALUATION_INCIDENT
PAIR_ADMISSION_GRANTED
PAIR_ADMISSION_PENDING_THRESHOLD
PAIR_ADMISSION_DURATION_BELOW_MINIMUM
PAIR_ADMISSION_RAW_AUTHORITY_MISSING
PAIR_ADMISSION_LINEAGE_INCOMPLETE
PAIR_ADMISSION_CROSS_SYMBOL_INTERRUPTION
PAIR_ADMISSION_SOURCE_GAP
PAIR_ADMISSION_LEDGER_GAP
PAIR_ADMISSION_EVALUATOR_NOT_SCHEDULED
PAIR_ADMISSION_PERSISTENCE_FAILED
PAIR_ADMISSION_ATTACHMENT_MISSING
PAIR_ADMISSION_DUPLICATE_BLOCK
PAIR_ADMISSION_RECONCILIATION_REQUIRED
```

## 21.2 StrategyAnalysisAdmission

```text
STRATEGY_ANALYSIS_ADMISSION_CANONICAL_RAW_GRANTED
STRATEGY_ANALYSIS_ADMISSION_MATURE_ADVISORY_GRANTED
ADVISORY_SOURCE_AUTHORITY_RADAR_ONLY
STRATEGY_ANALYSIS_ADMISSION_REJECTED
STRATEGY_ANALYSIS_ADMISSION_SUSPENDED
ADVISORY_PRESSURE_MATURE_ANALYSIS_REQUIRED
ADVISORY_PRESSURE_EXTREME_ANALYSIS_REQUIRED
ADVISORY_ANALYSIS_QUEUED
ADVISORY_ANALYSIS_OPENED
ADVISORY_ANALYSIS_SHADOW_ONLY
ADVISORY_ANALYSIS_RISK_HANDOFF_PROHIBITED
ADVISORY_PRESSURE_IMMATURE
ADVISORY_PRESSURE_EXPIRED
ADVISORY_DIRECTION_LINEAGE_CONFLICT
ADVISORY_EVIDENCE_COVERAGE_INSUFFICIENT
ADVISORY_CONTEXT_RESOLUTION_INELIGIBLE
ADVISORY_TO_CANONICAL_AUTHORITY_UPGRADE
ADVISORY_CANDIDATE_CANONICAL_REEVALUATION_REQUIRED
```

## 21.3 Pressure, reaction, dan lifecycle

```text
PRESSURE_DIRECTION_LINEAGE_ALIGNED
PRESSURE_DIRECTION_LINEAGE_CONFLICT
PRESSURE_DIRECTION_LINEAGE_UNAVAILABLE
PRESSURE_CONSENSUS_BUY
PRESSURE_CONSENSUS_SELL
PRESSURE_CONSENSUS_CONFLICT
PRESSURE_INCOMPLETE
PRESSURE_STALE
PRESSURE_HYPOTHESIS_OPENED
PRESSURE_HYPOTHESIS_CONTEXT_ALIGNED
PRESSURE_HYPOTHESIS_CONTEXT_CONFLICT
PRESSURE_HYPOTHESIS_WAITING_LOCATION
PRESSURE_HYPOTHESIS_WAITING_PRICE_QUALITY
PRESSURE_HYPOTHESIS_INVALIDATED
COUNTER_REACTION_NOT_STRATEGY_AUTHORIZED
OPPOSITE_STRATEGY_DIRECTION_NOT_AUTHORIZED
MICROBOOST_FORMED
MICROBOOST_REINFORCED
MICROBOOST_WEAKENED
MICROBOOST_INVALIDATED
MICROBOOST_EXPIRED
LIFECYCLE_CONTINUITY_UNPROVEN
LIFECYCLE_HARD_RESET
LIFECYCLE_AUTHORITY_UPGRADED
LIFECYCLE_DUPLICATE_ON_AUTHORITY_UPGRADE
```

## 21.4 Data quality

```text
PRICE_QUALITY_WARMING_UP
PRICE_INSUFFICIENT_HISTORY
PRICE_FROZEN
PRICE_STALE_PRESERVED
PRICE_COVERAGE_MISSING
CANDLE_FORMING
CANDLE_INCOMPLETE
CANDLE_QUARANTINED
FUTURE_LEAKAGE_BLOCKED
DAILY_EXPECTED_BAR_MISSING
PROVIDER_CALENDAR_INVALID
```

## 21.5 Context dan structure

```text
CONTEXT_UNRESOLVED
CONTEXT_CONFLICT
DIRECTION_DOMAIN_EMPTY
DIRECTION_OUTSIDE_DOMAIN
COUNTER_PRESSURE_NOT_AUTHORIZED
LIQUIDITY_UNRESOLVED
LIQUIDITY_ACCEPTED
LIQUIDITY_REJECTED
H1_STRUCTURE_UNCONFIRMED
M15_ORDERED_PROOF_MISSING
THESIS_INVALIDATED
THESIS_SUPERSEDED
```

## 21.6 Geometry dan promotion

```text
TARGET_MISSING
TARGET_CONSUMED
TARGET_ALREADY_PASSED
TARGET_BELOW_EXECUTION_FLOOR
ROUTE_NO_VALID_ENTRY_DOMAIN
RR_BELOW_MINIMUM
COST_FLOOR_FAILED
BOX_SUPERSEDED
BOX_INVALIDATED
ORDER_EXPIRED_NO_FILL
REINFORCEMENT_ONLY
TERMINAL_NO_TRADE
TRADEPLAN_CANDIDATE_SHADOW_ONLY
TRADEPLAN_CANONICAL_RISK_HANDOFF_ELIGIBLE
ADVISORY_CANDIDATE_RISK_HANDOFF_BLOCKED
```

Free text boleh melengkapi, tetapi tidak menggantikan reason code.

# 22. Statistik, replay, dan reproducibility

## 22.1 WAIT dan NO_TRADE

```text
WAIT = abstention/state
NO_TRADE = terminal strategy decision
```

Keduanya tidak masuk numerator atau denominator executed win rate.

## 22.2 Metric wajib

```text
PairAdmission rate
PairAdmission coverage classification rate
raw-authority coverage complete/incomplete/unknown rate
missing-evaluation incident rate
StrategyAnalysisAdmission rate by class
mature-advisory capture rate
mature-advisory silent-drop count
advisory analysis queue latency
advisory-to-shadow-candidate conversion
advisory-to-canonical-upgrade rate
lifecycle compression ratio
lifecycle duplicate-on-upgrade count
pressure hypothesis rate
context-alignment rate
setup coverage
trade rate
no-trade rate
suspended-data-quality rate
executed win rate
expectancy in R after cost
profit factor
maximum drawdown
MAE/MFE
OOS performance
```

## 22.3 Manifest immutable

```yaml
replay_manifest:
  replay_id: uuid
  strategy_rule_version: 5scr.dual-analysis-admission.pressure-hypothesis.structural-core.v3.1
  audit_rule_version: required
  code_commit: required
  cohort_id: required
  period_start_utc: required
  period_end_utc: required
  symbols: required
  raw_stream_hashes: []
  pressure_file_hashes: []
  price_file_hashes: []
  provider_id: required
  provider_timezone: required
  session_calendar_version: required
  raw_authority_coverage_policy_version: required
  pair_admission_rule_version: required
  pair_admission_coverage_rule_version: required
  strategy_analysis_admission_rule_version: required
  advisory_maturity_policy_version: required
  analysis_priority_policy_version: required
  lifecycle_merge_policy_version: required
  pressure_maturity_policy_version: required
  direction_domain_registry_version: required
  route_registry_version: required
  execution_policy_id: required
  cost_model_version: required
  fill_policy_version: required
  outcome_policy_version: required
  risk_policy_version: required
  parameter_freeze_time_utc: required
  in_sample_or_oos: required
```

Replay yang sama harus menghasilkan output hash yang sama.

## 22.4 Headline metric metadata

Setiap headline metric menyimpan:

```text
numerator
denominator
cohort
date range
symbol universe
analysis admission class
entry/fill policy
cost model
target/stop policy
outcome horizon
rule version
replay manifest hash
in-sample/OOS label
```

Mature-advisory shadow candidate DILARANG dicampur ke executed-trade statistic.

# 23. Universal regression matrix

Tidak boleh ada rule khusus satu pair. Regression cases harus berbentuk pola universal.

## 23.1 Canonical raw pressure + favorable location

```text
PairAdmission GRANTED
→ StrategyAnalysisAdmission CANONICAL_RAW
pressure consensus SELL
pressure maturity QUALIFIED
location alignment FAVORABLE
quote LIVE

→ open SELL PressureDirectionalHypothesis
→ prioritize H1/M15 SELL proof
→ no order before thesis + geometry + risk
```

Mirror BUY wajib menghasilkan behavior simetris.

## 23.2 Mature advisory tanpa raw-authority block

```text
PairAdmission coverage = NOT_APPLICABLE_NO_RAW_AUTHORITY_BLOCK
advisory maturity = MATURE|EXTREME
direction lineage = ALIGNED
pressure consensus SELL

→ StrategyAnalysisAdmission MATURE_ADVISORY GRANTED
→ open/attach lifecycle
→ open SELL PressureDirectionalHypothesis
→ prefetch H4/H1/M15/M1
→ risk reservation = 0
→ command = 0
```

Mirror BUY wajib simetris.

## 23.3 Mature advisory + frozen quote

```text
MATURE_ADVISORY GRANTED
pressure hypothesis valid
quote becomes PRICE_FROZEN

→ lifecycle and hypothesis remain durable
→ state WAITING_PRICE_QUALITY
→ structural/execution authority false
→ zero risk/command
```

## 23.4 Mature advisory + context conflict

```text
MATURE_ADVISORY SELL
higher context bullish/range conflict

→ preserve SELL hypothesis
→ state CONTEXT_CONFLICT / COUNTER_PRESSURE_PENDING_PROOF
→ stronger H1/M15 proof required
→ no automatic BUY
→ no automatic SELL order
```

## 23.5 Sticky telemetry dan advisory maturity

```text
100 duplicate/carried microboost snapshots
+ tidak ada material pulse/evidence baru

→ no maturity inflation
→ no duplicate StrategyAnalysisAdmission
→ no duplicate lifecycle
→ no duplicate hypothesis
```

## 23.6 Advisory kemudian memperoleh canonical raw authority

```text
MATURE_ADVISORY lifecycle exists
+ later PairAdmission GRANTED

→ attach CANONICAL_RAW to same lifecycle
→ no second lifecycle
→ re-evaluate all current evidence
→ create new canonical candidate revision if valid
→ advisory candidate not mutated/promoted automatically
```

## 23.7 Advisory geometry valid

```text
MATURE_ADVISORY
+ ContextEpoch resolved
+ H1/M15 proof valid
+ geometry valid

→ TRADEPLAN_CANDIDATE_SHADOW_ONLY
→ risk_handoff_allowed=false
→ risk reservation = 0
→ FinalSignal = 0
→ ExecutionCommand = 0
```

## 23.8 Raw PairAdmission missing evaluation

```text
raw coverage COMPLETE
+ eligible raw block crosses threshold
+ no durable evaluation after SLA

→ PAIR_ADMISSION_MISSING_EVALUATION_INCIDENT
→ raw-ledger replay/backfill
→ exactly one GRANTED/REJECTED/SUSPENDED
→ never remain silently NOT_EVALUATED
```

## 23.9 PairAdmission not applicable

```text
raw coverage COMPLETE
+ no eligible raw-authority block
+ mature derived pressure exists

→ PairAdmission NOT_APPLICABLE_NO_RAW_AUTHORITY_BLOCK
→ not a scheduler incident
→ MATURE_ADVISORY analysis still evaluated
```

## 23.10 Raw coverage indeterminate

```text
raw coverage INCOMPLETE|UNKNOWN

→ INDETERMINATE_RAW_AUTHORITY_COVERAGE
→ replay_required=true
→ no claim that PairAdmission is NOT_APPLICABLE
→ mature advisory analysis may continue SHADOW_ONLY if policy lulus
```

## 23.11 Direction conflict

```text
raw/candidate/watch BUY
block SELL

→ PRESSURE_DIRECTION_LINEAGE_CONFLICT
→ no active hypothesis
→ no thesis
→ no tradeplan
```

## 23.12 Rejection semantics

```text
BUY pressure + BUY_SIDE_REJECTED
→ reaction direction may be SELL
→ reaction role = COUNTER_REACTION_ONLY_NOT_OPPOSITE_STRATEGY_AUTHORITY
→ BUY hypothesis invalidated/deferred
→ SELL not authorized automatically
```

Mirror SELL wajib simetris.

## 23.13 Location unfavorable

```text
strong SELL pressure at unfavorable sell location
→ hypothesis preserved
→ WAITING_VALID_LOCATION
→ no chase
```

## 23.14 Target too close

```text
nearest structural target below policy floor
→ NO_TRADE_TARGET_BELOW_EXECUTION_FLOOR
→ farther target cannot be selected
```

## 23.15 Empty entry interval

```text
structure interval ∩ route interval ∩ target/RR interval = empty
→ ROUTE_NO_VALID_ENTRY_DOMAIN
→ no SL manipulation
→ no risk reservation
```

## 23.16 Parent/child

```text
new pressure before parent fill
→ box/tradeplan revision
→ not child

new pressure after parent fill without independent proof
→ REINFORCEMENT_ONLY
```

## 23.17 Capacity pressure

```text
qualified MATURE_ADVISORY arrives while workers full
→ durable ANALYSIS_QUEUED
→ eventually evaluated under SLA
→ no silent drop
```

# 24. Acceptance dan promotion gate

## 24.1 Strategy acceptance

```text
100% eligible raw block threshold crossing memiliki durable evaluation
100% PairAdmission coverage memiliki raw-coverage status dan reason code
100% PairAdmission outcome memiliki reason code dan lineage hash
100% qualifying mature advisory episode memiliki StrategyAnalysisAdmission outcome
100% MATURE_ADVISORY GRANTED membuka/attach stable lifecycle
100% advisory candidate membawa SHADOW_ONLY promotion eligibility
100% canonical candidate membawa complete canonical raw lineage
100% admitted lifecycle memiliki stable strategy_lifecycle_id
100% candidate memiliki complete evidence lineage
100% ContextEpoch hash hanya material fields
100% H1/M15 proof memakai closed/as-of candles
100% target adalah nearest fresh unconsumed target
100% TradePlanCandidate valid_for_execution=false
100% terminal/suspended lifecycle memiliki reason
100% repeated replay menghasilkan output hash sama
```

## 24.2 Zero-tolerance

```text
0 derived pressure stream menjadi raw PairAdmission authority
0 eligible raw block silently NOT_EVALUATED setelah SLA
0 raw coverage UNKNOWN diklasifikasikan sebagai NOT_APPLICABLE
0 mature advisory qualifying episode silent-dropped karena PairAdmission tidak ada
0 MATURE_ADVISORY candidate masuk risk reservation
0 MATURE_ADVISORY candidate menghasilkan FinalSignal/ExecutionCommand
0 duplicate lifecycle saat advisory di-upgrade ke canonical raw
0 advisory candidate dimutasi menjadi canonical candidate tanpa re-evaluation
0 quote/context menghapus StrategyAnalysisAdmission atau hypothesis
0 partial/future HTF candle authoritative
0 direction di luar legal domain
0 automatic opposite thesis dari rejection
0 mutable DirectionalThesis
0 target jauh melewati nearer target
0 empty feasible interval menghasilkan fill search
0 WAIT/NO_TRADE dihitung sebagai win
0 duplicate telemetry membuat admission/lifecycle/pulse/epoch/thesis/box baru
0 telemetry-driven expiry extension
0 command tanpa active reservation
0 symbol-specific strategy branch
```

## 24.3 Shadow promotion

Sebelum behavior-changing rule menjadi authoritative:

```text
old path dan V3.1 path menerima input yang sama
PairAdmission raw-only tetap identik
MATURE_ADVISORY path tetap non-executable
perbedaan analysis admission/lifecycle/hypothesis dicatat
all advisory risk/command counters remain zero
no broker side effect
restart determinism lulus
weekend/rollover/provider-disconnect lulus
capacity/backlog recovery lulus
```

## 24.4 Canonical promotion prerequisites

```text
PairAdmission coverage classifier deterministic
MATURE_ADVISORY maturity policy frozen
StrategyAnalysisAdmission contract stable
advisory-to-canonical upgrade deterministic
shadow candidate separation proven
no authority leak to risk/execution
OOS cohort frozen before evaluation
```

## 24.5 Demo gate

Dokumen ini sendiri tidak mengizinkan DEMO. DEMO memerlukan:

```text
Strategy acceptance PASS
Risk Authority Contract PASS
Execution bridge governance PASS
EA DEMO artifact PASS
kill-switch drill PASS
reconciliation drill PASS
explicit operator approval
```

# 25. Migrasi dari SSOT v2 dan working draft V3 yang tidak dipublikasikan

## 25.1 Perubahan non-behavioral yang boleh lebih dahulu

```text
keluarkan repo/runtime snapshot dari SSOT
PairAdmission coverage contract dan reason-code taxonomy
raw-authority coverage status
stable lifecycle identity
quote/candle authority separation
stage semantics
solver ordering correction
transaction authority versus delivery split
policy registry reference
```

## 25.2 Perubahan behavioral yang wajib SHADOW

```text
StrategyAnalysisAdmission dual path
MATURE_ADVISORY mandatory analysis
PressureDirectionalHypothesis dari advisory admission
context-conflict preservation
counter-pressure separation
Microboost pulse persistence
refined direction-domain registry
advisory-to-canonical authority upgrade
TradePlanCandidate SHADOW_ONLY separation
```

## 25.3 Rollout sequence

```text
1. Add PairAdmissionCoverageV1 contract
2. Add StrategyAnalysisAdmissionV1 contract and tables
3. Add advisory maturity reducer and policy registry
4. Add durable advisory analysis queue
5. Attach MATURE_ADVISORY to Lifecycle V3.1 in SHADOW
6. Add PressureDirectionalHypothesis from both admission classes
7. Add quote/context/structure evidence prefetch
8. Add advisory shadow candidate output
9. Add advisory-to-canonical lifecycle upgrade
10. Compare V2 versus V3.1 lifecycle and candidate deltas; gunakan working draft V3 hanya sebagai design-lineage reference, bukan repository baseline
11. Deterministic replay and OOS
12. Explicit authority promotion
```

## 25.4 Containment

Selama migrasi:

```text
PairAdmission tetap raw-only
execution flags tetap OFF
V3.1 valid_for_execution=false
MATURE_ADVISORY risk_handoff_allowed=false
no direct write ke execution_commands
kill switch unchanged
legacy outcome tidak di-overwrite
all identities dual-linked for audit
all advisory candidates isolated from Risk Authority
```

## 25.5 Promotion discipline

V3.1 Candidate DILARANG menggantikan SSOT V2 melalui overwrite diam-diam.

Promotion harus berupa commit governance terpisah yang membawa:

```text
approved rule version
shadow comparison manifest
replay manifest
OOS manifest
approval record
supersession metadata
```

# 26. Policy registry dan change control

Rule yang dapat dikalibrasi harus versioned, bukan hardcoded tersebar:

```text
RawAuthorityCoveragePolicyRegistry
PairAdmissionRuleRegistry
PairAdmissionCoveragePolicyRegistry
StrategyAnalysisAdmissionPolicyRegistry
AdvisoryPressureMaturityPolicyRegistry
AnalysisPriorityPolicyRegistry
LifecycleMergePolicyRegistry
PressureMaturityPolicyRegistry
MicroboostPulsePolicyRegistry
LocationRoutePolicyRegistry
DirectionDomainRegistry
LiquidityTransitionRegistry
StructuralPatternRegistry
ExecutionPolicyRegistry
CostModelRegistry
RiskPolicyRegistry
FillPolicyRegistry
OutcomePolicyRegistry
```

Setiap perubahan policy:

```text
new policy version
new replay manifest
no retroactive mutation
shadow comparison
reviewed changelog
OOS evidence sebelum promotion
```

Khusus advisory maturity policy, perubahan harus melaporkan:

```text
qualifying episode count
symbol-universe distribution
maturity duration/effective-evidence distribution
analysis queue load
shadow candidate conversion
false-positive/no-trade rate
zero risk/command leakage
```

SSOT version berubah hanya untuk perubahan semantik konstitusional, bukan perubahan parameter biasa.

# 27. Final canonical workflow

```text
RAW CANONICAL PATH
Raw SignalThrottle
→ canonical raw ledger
→ global ActiveBlock
→ mandatory durable PairAdmission evaluation
→ PairAdmissionCoverage
→ PairAdmission GRANTED
→ StrategyAnalysisAdmission CANONICAL_RAW
                         \
                          \
                           → stable AnalysisLifecycle
                          /
                         /
MATURE ADVISORY PATH
SignalPressureStateJSON / CANARY / Microboost-derived evidence
→ PressureEmission normalization
→ dedupe + pulse/state reduction
→ advisory maturity MATURE/EXTREME
→ PairAdmissionCoverage
→ StrategyAnalysisAdmission MATURE_ADVISORY

CONVERGED ANALYSIS
→ PressureDirectionalHypothesis
→ quote/candle authority
→ Material ContextEpoch
→ location alignment + direction domain + route
→ liquidity FSM
→ immutable DirectionalThesis
→ closed H1 + ordered M15 proof
→ PressureRange + versioned ExecutionBox
→ nearest fresh structural TP1
→ feasible-entry intersection
→ structural SL + net RR/cost
→ non-executable TradePlanCandidate
```

Promotion split:

```text
CANONICAL_RAW TradePlanCandidate
+ promotion_eligibility CANONICAL_RISK_PATH
→ Risk Authority Contract
→ FinalSignal outbox
→ signed ExecutionCommand
→ EA dumb
→ broker reconciliation

MATURE_ADVISORY TradePlanCandidate
→ SHADOW_ONLY
→ operator/replay/research evidence
→ zero risk reservation
→ zero FinalSignal
→ zero ExecutionCommand
```

Authority upgrade:

```text
MATURE_ADVISORY lifecycle
+ later PairAdmission GRANTED
→ same lifecycle ID
→ append CANONICAL_RAW authority
→ canonical re-evaluation
→ new candidate revision if valid
```

Formula akhirnya:

```text
Pressure menentukan arah yang diuji terlebih dahulu.
StrategyAnalysisAdmission memastikan pressure matang tidak hilang dari analisis.
Context menentukan apakah route searah aligned, conflict, deferred, atau blocked.
Structure mengonfirmasi atau menginvalidasi.
Target dan geometry menentukan apakah trade layak.
Hanya canonical raw path yang dapat menuju Risk Authority.
EA hanya mengeksekusi.
```

Jika pressure matang tetapi context, quote, structure, atau geometry belum lengkap:

```text
sistem WAJIB mempertahankan analysis lifecycle dan directional hypothesis
sistem WAJIB menjelaskan blocker dengan reason code
sistem DILARANG menghilangkan episode
sistem DILARANG memaksa order
```

# 28. Lampiran enum dan state minimum

## 28.1 Pressure consensus

```text
BUY
SELL
CONFLICT
INCOMPLETE
STALE
```

## 28.2 Direction-lineage alignment

```text
ALIGNED
CONFLICT
UNAVAILABLE
```

## 28.3 Raw-authority coverage status

```text
COMPLETE
INCOMPLETE
UNKNOWN
```

## 28.4 PairAdmission coverage status

```text
EVALUATED
NOT_APPLICABLE_NO_RAW_AUTHORITY_BLOCK
MISSING_EVALUATION_INCIDENT
INDETERMINATE_RAW_AUTHORITY_COVERAGE
```

## 28.5 PairAdmission decision

```text
GRANTED
REJECTED
SUSPENDED
```

## 28.6 StrategyAnalysisAdmission class

```text
CANONICAL_RAW
MATURE_ADVISORY
```

## 28.7 StrategyAnalysisAdmission status

```text
PENDING
GRANTED
REJECTED
SUSPENDED
EXPIRED
```

## 28.8 Analysis authority

```text
FULL_CANONICAL_ANALYSIS
FULL_SHADOW_ANALYSIS
```

## 28.9 Advisory maturity

```text
IMMATURE
MATURE
EXTREME
EXPIRED
UNKNOWN
```

## 28.10 Promotion eligibility

```text
CANONICAL_RISK_PATH
SHADOW_ONLY
```

## 28.11 Reaction direction role

```text
COUNTER_REACTION_ONLY_NOT_OPPOSITE_STRATEGY_AUTHORITY
SAME_DIRECTION_REACTION
UNAVAILABLE
```

## 28.12 Lifecycle state

```text
ANALYSIS_QUEUED
ANALYSIS_OPEN
WAITING_PRICE_COVERAGE
WAITING_PRICE_QUALITY
WAITING_CONTEXT
WAITING_STRUCTURE
CONDITIONAL_SETUP
TRADEPLAN_READY_NON_EXECUTABLE
TRANSITION_PENDING
TERMINAL_NO_TRADE
INVALIDATED
SUPERSEDED
SUSPENDED_DATA_QUALITY
```

## 28.13 Pressure hypothesis state

```text
OPEN
CONTEXT_ALIGNED
CONTEXT_CONFLICT
WAITING_VALID_LOCATION
WAITING_PRICE_QUALITY
WAITING_STRUCTURE
INVALIDATED
EXPIRED
```

## 28.14 Context alignment

```text
ALIGNED
CONFLICT
UNRESOLVED
EMPTY
```

## 28.15 Legal direction domain

```text
BUY_ONLY
SELL_ONLY
BOTH_CONDITIONAL
UNRESOLVED
EMPTY
```

## 28.16 Thesis state

```text
DORMANT
PENDING_CONTEXT
PENDING_H1
PENDING_M15
STRUCTURALLY_CONFIRMED
GEOMETRY_PENDING
INVALIDATED
SUPERSEDED
EXPIRED
```

## 28.17 Box state

```text
BUILDING
FROZEN
SUPERSEDED
INVALIDATED
CONSUMED
EXPIRED
```

## 28.18 Core output state

```text
WAITING_EVIDENCE
WAITING_PRICE_QUALITY
CONDITIONAL_SETUP
ROUTE_NO_VALID_ENTRY_DOMAIN
TRADEPLAN_CANDIDATE_CANONICAL
TRADEPLAN_CANDIDATE_SHADOW_ONLY
TERMINAL_NO_TRADE
SUSPENDED_DATA_QUALITY
```

# 29. Final status

```text
DOCUMENT STATUS                         : PROPOSED_CANONICAL
DOCUMENT VERSION                        : V3.1 CANDIDATE
STRATEGY EXECUTION                      : SHADOW_ONLY
RUNTIME AUTHORITY                       : NONE_UNTIL_APPROVED
PAIR ADMISSION AUTHORITY                : RAW ONLY
MATURE ADVISORY ANALYSIS                : REQUIRED WHEN POLICY QUALIFIES
MATURE ADVISORY RISK AUTHORITY          : PROHIBITED
MATURE ADVISORY EXECUTION AUTHORITY     : PROHIBITED
PRESSURE DIRECT ORDER                   : PROHIBITED
PRESSURE HYPOTHESIS                     : REQUIRED FOR QUALIFIED DIRECTIONAL EPISODE
PAIR ADMISSION SILENT GAP               : PROHIBITED FOR ELIGIBLE RAW BLOCK
MATURE ADVISORY SILENT DROP             : PROHIBITED
ADVISORY-TO-CANONICAL DUPLICATE LIFECYCLE: PROHIBITED
SYMBOL-SPECIFIC BRANCH                  : PROHIBITED
TRADEPLAN EXECUTABLE                    : FALSE
OOS VALIDATED                           : NO
PRODUCTION PROVEN                       : NO
```

Dokumen ini dirancang agar sistem tidak lagi memilih antara tiga kegagalan ekstrem:

```text
pressure kuat tetapi hilang sebagai telemetry pasif
atau
mature advisory keliru dipaksa menjadi PairAdmission raw
atau
pressure kuat langsung menjadi order
```

Solusi canonical v3.1 adalah:

```text
pressure matang
→ StrategyAnalysisAdmission
→ durable directional analysis priority
→ context dan structure proof
→ target-first geometry
→ candidate canonical atau shadow-only sesuai authority class
→ hanya canonical raw candidate boleh menuju Risk Authority
→ mechanical execution
```
