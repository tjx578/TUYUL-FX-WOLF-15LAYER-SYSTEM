# S01 — binding SSOT, kontrak, policy dan authority

**Status S01: SOURCE_BOUND_POLICY_AND_SCHEMA_CLOSURE_INCOMPLETE; DONE=false.** Binding source dan pemetaan berhasil diselesaikan; tidak ada perubahan strategi, runtime, account, broker atau memory. Source implementasi untuk review ini dibekukan pada `261a3b476055accc3d0ea45ebc80a910e0e80f6b`.

## Binding yang sudah ditutup

Full repo v3.1 berasal dari `dd27ae87d0207466caad4c3e098224112ac0eaf7`, path `docs/strategy/WOLF15_STRATEGY_5SCR_CANONICAL_SSOT_V3_1_CANDIDATE.md`, Git blob `cd848447a2e923d0ea0de6c566a558c7205d3d3b`, SHA-256 `6daea387745ffa305d3cd55b0fee4f0efed79be21e24503c2a1f8a16c6a83902`,86002bytes/3491lines. Salinan committed di `../source-binding/selected-ssot-v3.1.md` cocok byte-for-byte. Pemilihan v3.1 yang sudah berlaku dipertahankan; tidak mengadopsi R1/R2 atau meminta persetujuan versi ulang.

Dokumen assessment lama mencatat hash `2cd41d01fdd3661af59284c78df669f7b312a7b7e4870f1620cfcfbe1aedb624`,85414bytes/3478lines, pada `deduplicated-corpus.json` dan DoD. Semua48 anggota ZIP diperiksa; tidak ada konten dengan hash tersebut. Selisih588bytes/13lines bukan bukti bahwa perubahan hanya metadata. Perbandingan penuh tidak dapat dibuktikan tanpa bytes asli. Temuan yang masih terlihat diverifikasi ulang pada selected source; nomor baris historical tidak dipindahkan otomatis. File lowercase untracked AnalysisAdmission adalah stub berbeda, bukan pengganti fullSSOT.

## Perbedaan dan resolusi

| ID | Pokok | Status | Keputusan atau gap |
|---|---|---|---|
| D01 | SELECTED_SOURCE_IDENTITY | RESOLVED_BINDING | Uppercase full SSOT exact Git bytes verified; lowercase untracked AnalysisAdmission stub is distinct. Ref:S01 |
| D02 | HISTORICAL_COPY_PARITY | UNRESOLVED_MISSING_BYTES | Original reported2cd41... document is represented by metadata only; do not assert complete old-versus-selected semantic equivalence. Ref:S01 source provenance |
| D03 | S05_H4_ONLY_SUMMARY | RESOLVED_REQUIREMENT_PRECEDENCE | DoD correction follows selected17.2 D1/H4/H1 plus legal structural sources. Current P5 has newer authority/cohort contracts, but TargetKind atcontracts/strategy_5scr_tradeplan_candidate_v2.py:21 remains H4_STRICT_SWING_HIGH/LOW. The H4-only universe remains an S05 implementation gap. Ref:17.2;DoD section1 |
| D04 | SOLVER_DIAGRAM_ORDER | RESOLVED_REQUIREMENT_PRECEDENCE | Selected27 diagram places feasible intersection before structuralSL/netcost; DoD explicitly chooses normative17.1: target, route interval, structuralSL, RR/cost constraints, intersection, candidate. Ref:17.1;27;DoD section1 |
| D05 | MISSING_PRESSURE_CONTRACT_FIELDS | UNRESOLVED_SCHEMA_CLOSURE | 10.5 requires pressure_contract_version and pressure_contract_invalidated_at, but10.3 hypothesis example omits both. Do not infer LOCKED from aligned direction labels. Typed V1 pressure authority exists; no fullV3.1 generated schema/example parity demonstrated. Ref:10.3;10.5 |
| D06 | WAITING_PRESSURE_RESOLUTION_ENUM | UNRESOLVED_SCHEMA_CLOSURE | 10.6 allows lifecycle WAITING_PRESSURE_RESOLUTION;28.12 consolidated lifecycle enum omits it. Need versioned explicit state/reason serialization and generated examples; do not silently add or alias state. Ref:10.6;28.12 |
| D07 | CANDIDATE_ORDER_TYPE | UNRESOLVED_SCHEMA_CLOSURE | 17.1 selects candidate entry and order type;17.7 schema has no order_type field, and bound TradePlanCandidateV2 has no such field. Natural command/order-mode mapping belongs to R03/N02; no value guessed. Ref:17.1;17.7 |
| D08 | RADAR_SEPARATE_ROUTE_VS_CONFLICT | UNRESOLVED_DECISION_TABLE | 10.5 and14.1 allow legally authorized separate routes;23.11 globally says no hypothesis/thesis/tradeplan on lineage conflict. Pressure-path prohibition is clear; whether an independent separate route can coexist for same episode/conflict needs explicit typed policy/table. Default no natural promotion while unresolved. Ref:10.2;10.5;10.6;14.1;23.11 |
| D09 | LIQUIDITY_DISPLAY_LABEL | RESOLVED_DOCUMENTARY_INTERPRETATION | 13 minimum machine state TESTING and directional example BUY_SIDE_TESTING should be distinguished as machine state versus directional presentation; not a demonstrated serialized enum alias. Ref:13 |
| D10 | CANDIDATE_VS_CORE_OUTPUT_STATES | RESOLVED_DOCUMENTARY_INTERPRETATION | 17.7 object stateTRADEPLAN_CANDIDATE and28.18 core-output canonical/shadow categories are different objects/projections, not automatically one union enum. Implementation adapter still required. Ref:17.7;28.18 |
| D11 | V2_V31_IDENTITY_AND_FIELDS | UNRESOLVED_IMPLEMENTATION_MAPPING | PairAdmissionGrantV2 requires BUY/SELL and effective_ticks;V3.1 pair evaluation is direction-independent. V2 candidate lacks analysis-admission/promotion fields and uses different IDs than natural risk. Never regex-rewrite identity to bypass semantics. Ref:7.11;17.7;R02/R03 |
| D12 | L12_POST_VERDICT_AUTHORITY | UNRESOLVED_MANDATORY_POLICY_AND_NATURAL_WIRING | LegacyL12 and constitutionalPhase5 overlay coexist; overlay errors nonfatal. V11 veto downgrades but missing import passes and other errors append without guaranteed downgrade. Mandatory-versus-optional policy and natural consumption of final gates are not bound by selectedSSOT. No runtime PASS claimed. Ref:S01 authority acceptance;pipeline source |

## Rule → contract → tests

Seluruh35 clause acceptance §24.1/§24.2 dipetakan secara individual, dengan numerator/denominator null dan tidak ada PASS baru. Semua15 kelompok requirement mempunyai path source, path test, keberadaan pada commit dan status cakupan di `s01-rule-contract-test-matrix.json`. Inventaris AST dalam `s01-contract-binding.json` membawa class/field, policy/version constants, nama test dan baris. Path test membuktikan traceability, bukan PASS; tidak ada runtime suite dieksekusi pada slice dokumen ini.

| Mapping | Requirement | Source utama | Status |
|---|---|---|---|
| M01 | 6;7.1 | analysis/strategy_5scr_raw_admission_blocks.py | CURRENT_RAW_V2_BOUND_V31_PARITY_OPEN |
| M02 | 7.2;7.3;7.7;7.8 | contracts/strategy_5scr_pair_admission.py | V2_DIRECTION_AND_GAP_CONTRACT_DIFFERENCE_S03 |
| M03 | 7.6;7.12 | contracts/strategy_5scr_pair_admission.py | FULL_PAIR_ADMISSION_COVERAGE_V1_SCHEMA_NOT_BOUND |
| M04 | 7A;8 | contracts/strategy_5scr_analysis_admission.py | DUAL_ANALYSIS_ADMISSION_NOT_PRESENT_ON_BOUND_COMMIT |
| M05 | 8;9 | contracts/strategy_5scr_lifecycle_v2.py | EXISTING_COMPONENTS_BOUND_V31_POLICY_COMPOSITION_OPEN |
| M06 | 10.2;10.5;10.6;23.11 | contracts/strategy_5scr_directional_thesis_v1.py | TYPED_DIRECTION_AUTHORITY_EXISTS_FULL_HYPOTHESIS_V31_SCHEMA_OPEN |
| M07 | 11;12 | contracts/strategy_5scr_context_epoch_v1.py | COMPONENT_MAPPING_ONLY_RUNTIME_COHORT_NOT_MEASURED |
| M08 | 13;14 | contracts/strategy_5scr_directional_thesis_v1.py | TYPED_COMPONENT_EXISTS_V31_ADMISSION_CLASS_LINK_OPEN |
| M09 | 15;16 | contracts/strategy_5scr_execution_box_v1.py | COMPONENT_EXISTS_V31_FULL_LIFECYCLE_MAPPING_OPEN |
| M10 | 17.1;17.2;17.5;17.6 | contracts/strategy_5scr_tradeplan_candidate_v2.py | S05_GAP_TARGET_KIND_H4_ONLY_DESPITE_NEWER_AUTHORITY_CONTRACTS |
| M11 | 17.7;18 | contracts/strategy_5scr_tradeplan_candidate_v2.py | V2_CANDIDATE_NOT_FULL_V31_SCHEMA_OR_NATURAL_RISK_ADAPTER |
| M12 | 19;20 | risk/s5_campaign_risk.py | ACCOUNT_PROFILE_NATURAL_ADAPTER_AND_CHILD_BINDING_OPEN |
| M13 | 21;22;24 | contracts/strategy_5scr_replay.py | EXISTING_OUTCOME_REPLAY_NOT_FULL_V31_COHORT_MANIFEST |
| M14 | 26;S01 acceptance | contracts/strategy_5scr_execution_policy.py | PARTIAL_POLICY_CONSTANTS_BOUND_ACTIVE_REGISTRY_SELECTION_OPEN |
| M15 | S01 authority acceptance;20;24.5 | pipeline/wolf_constitutional_pipeline.py | SOURCE_CALL_GRAPH_BOUND_MANDATORY_GATE_POLICY_AND_NATURAL_RUNTIME_OPEN |

## Policy yang belum boleh ditebak

Terdapat18 registry yang disebut §26. Mapping lengkap ada pada JSON. Constants existing seperti raw-ledger.v2,maxgap300s,TTL900s,FX_MIN_TARGET_10P_V1,FX_LEGACY_6P_V1 dan risk parent-only dicatat sebagai source, bukan automatic active profile v3.1. Baseline normative duration300s dan netRR≥1.5 dapat dibaca dari source; freshness/gap coverage,SLA,advisory maturity,priority,fill/expiry,cost buffer,account/currency/risk dan child-release tetap membutuhkan binding terpisah. Angka baru tidak dipilih.

## Peta authority

L1–L11 menganalisis/menilai/memvalidasi. Callsite2886–2889 mengevaluasi9gates lalu memanggil legacy `generate_l12_verdict`; constitutionalPhase5 overlay berbeda dipanggil pada2903–2927 dengan exception nonfatal. L13/L15,market-context,throttle danV11 dapat membatasi verdict. Pada9288–9347,V11 false menurunkan EXECUTE menjadiHOLD, tetapi ImportError lewat dan exception lain dicatat tanpa downgrade yang pasti. Karena status mandatory/optional dan hubungan natural candidate ke hasil final belum terikat, ini source mapping, bukan proof gate mandatory PASS.

Risk tetap terpisah untuk account,exposure,size dan reservation. Producer existing memaksa SHADOW pada284–285; tidak membuktikan natural candidate→L12/postgates→risk→FinalSignal→EA. Journal record-only dan enrichment non-authorizing adalah batas normative; natural end-to-end proof belum ada. Tidak menyimpulkan adanya broker exposure atau live exploit dari source semata.

## Batas yang harus dibawa ke S03

1. Pair activity boleh mempertahankan eventBUY/SELL pada pair sama; directional hypothesis tetap membutuhkan consensus+ALIGNED menurut§10.2.
2. Threshold300s membuka eligible durable evaluation, bukan risk/command permission.
3. Gap di atas policy berarti suspension; coverage UNKNOWN/INCOMPLETE berarti INDETERMINATE+replay_required.
4. New evaluation/grant contract harus merepresentasikan conflict tanpa memalsukan BUY/SELL; jangan hanya menghapus direction-change conditional sementara typed grant downstream tetap direction-uniform.
5. Dedupe,first-threshold lineage,lateevent,restart/backfill dan material revision harus tetap deterministik; perubahan diberi ruleversion tersendiri.
6. Tidak ada advisory capital authority atau natural broker enable; unknown separate-route conflict tetap ditahan sampai typed policy jelas.

## Kapan S01 benar-benar DONE

Selain source binding yang kini selesai, tutup missing fields/enum dan generated schema-example parity; freeze required policy IDs dan mode×alignment×domain×proof table; tetapkan mandatory post-verdict gate contract dan sumber verdict yang dikonsumsi oleh jalur natural. Bytes salinan lama tetap dicatat unavailable tanpa klaim parity penuh. Ini limitation provenance, bukan permintaan persetujuan versi ulang dan bukan alasan menghentikan S03 source-only terhadap repo v3.1 yang sudah dipilih. S01 tidak boleh ditutup hanya dengan hash dokumen.

Pemeriksaan structural artifact lulus dan semua authority flags tetapfalse. Skill `audit-wolf15-constitution/SKILL.md` dibaca, tetapi reference files/envelope resource yang diwajibkannya tidak ada; official envelope validation adalahNOT_EXECUTED_RESOURCE_UNAVAILABLE, bukanPASS. Pemeriksaan source/AST dan assertions lokal tetap dijalankan. Semua output disiapkan pada stagingC; tidak menulis keD,tidak commit,dan tidak mengubah README/register.

Section-anchor verification: all 15 mapping rows were checked against the selected SSOT headings. StrategyAnalysisAdmission is section 7A (line 962), durable lifecycle is section 8 (line 1170), and Microboost is section 9 (line 1316). The matrix records the exact heading and line for every numeric reference; backlog S01 references remain explicitly external. No section 8B is asserted.
