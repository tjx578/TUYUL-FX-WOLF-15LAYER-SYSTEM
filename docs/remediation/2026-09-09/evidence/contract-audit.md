# WOLF15 contract audit — 2026-09-09

The eight supplied inputs and 48 ZIP entries are acquired and reviewed as historical requirements/evidence. This is not an execution receipt. All 41 actions are mapped below; no milestone is closed by this audit.

## Material findings

1. The standalone backlog is malformed: row widths 13–16, extra semicolon padding and shifted acceptance/status cells. Its SHA-256 differs from the ZIP and DoD. Use the exact verified archived CSV exported alongside this report; retain original bytes.
2. ZIP CRC passes and every one of 47 declared artifacts matches SHA-256 and size. Artifact manifest itself is the 48th entry; it cannot prove itself or source/runtime truth.
3. Current fetched subject is `773150952311db3dbf5188f36536b7837d8ec296`; original local main ec316318 was behind initial origin/main 1837f4b7. Dirty checkout is preserved. Historical findings must be revalidated against final combined artifact.
4. The selected full v3.1 repo source is on existing PR414 branch at `dd27ae87d0207466caad4c3e098224112ac0eaf7`, path `docs/strategy/WOLF15_STRATEGY_5SCR_CANONICAL_SSOT_V3_1_CANDIDATE.md`, SHA-256 `6daea387745ffa305d3cd55b0fee4f0efed79be21e24503c2a1f8a16c6a83902`. It is exported byte-for-byte. The dirty lowercase candidate is a short analysis-admission stub and cannot stand in for the full SSOT.
5. Historical DoD design hash 2cd41d01... differs from the actual selected repo file. The original design copy is not in this ZIP, so full text parity is unverified; the relevant §17 and §24 requirements are confirmed from selected repo source.
6. S05 acceptance must use D1/H4/H1 and other legal structural targets in §17.2; §17.1 fixes solve order. Fifteen §24.1 and twenty §24.2 assertions need nonempty qualifying denominators/fault fixtures.
7. Canary rejection can prove reconciled outcome with BROKER_FILL_PROVEN=false. Natural parent and family require positive path and child-specific release evidence. Metadata SUCCESS, source hashes, compile or tests never substitute broker truth.
8. Historical PLANNING_ONLY instructions are historical context. The current user request authorizes engineering work and conditional safe Git/Railway progress; unresolved account/risk/window and artifact gates still require concrete binding. GitHub billing is deferred, not the required checks themselves.

## Plan structure

GOAP, canonical ZIP backlog and DoD register contain matching sets of 41 IDs; dependency graph is acyclic. Differences: 1 (see JSON; S05 is the intended acceptance correction). Milestone counts: P1=7, P2=6, P3=7, P4=10, P5=8, P6=3.

## All 41 action mappings

| ID | Milestone | Dependencies | Audit state | Required closure |
|---|---|---|---|---|
| A00 | P1 | — | SOURCE_ACQUISITION_VERIFIED_ONLY | PASS historis hanya untuk akuisisi source audit. Binding SSOT repo dan release baru wajib diperiksa pada S01/C01; tidak mengulang seluruh audit. |
| C01 | P1 | A00 | NOT_VERIFIED | Uji sengaja source A diuji tetapi B diminta deploy: harus ditolak; migration/deploy nonzero harus membuat job gagal. |
| C02 | P1 | A00 | NOT_VERIFIED | Exactly one lifecycle owner dan satu broker-capable executor per scope; duplicate/legacy consumer tidak boleh mengirim ke broker. |
| C03 | P1 | C01 | NOT_VERIFIED | Semua required checks benar-benar dijalankan; skipped/missing tidak dihitung PASS. Tidak mengendurkan gate untuk meluluskan kandidat. |
| C04 | P1 | A00 | NOT_VERIFIED | Runner bersih mempunyai identitas dan capacity evidence; provisioning atau biaya belum dilakukan oleh DoD. |
| C05 | P1 | C01, C03 | NOT_VERIFIED | Buktikan jalur release alternatif tidak dapat melewati required evidence yang ekuivalen. |
| C06 | P1 | A00 | NOT_VERIFIED | Matikan mandatory task/router pada fault fixture: served readiness 503, fatal exit nonzero. Health listener dan supervisor mengacu state yang sama. |
| S01 | P2 | A00 | PARTIAL_SOURCE_BINDING | SSOT v3.1 existing repo tetap acuan; path/full commit/digest harus bound. R1/R2 tidak diadopsi. Daftar interpretasi dan policy gaps diselesaikan eksplisit. |
| S02 | P2 | C02 | NOT_VERIFIED | Freeze quote sambil heartbeat berjalan: evidence tetap stale. Partial/future candle tidak boleh authoritative. |
| S03 | P2 | S01 | NOT_VERIFIED | Mixed direction mempertahankan pair activity bila continuity sah. BUY0/SELL150/BUY300 membutuhkan coverage/gap-policy yang valid, bukan otomatis GRANTED. |
| S04 | P2 | S03, C02 | NOT_VERIFIED | Qualifying advisory mendapat lifecycle/analisis tetapi nol capital reservation, FinalSignal executable atau command; upgrade wajib re-evaluation. |
| S05 | P2 | S01 | NOT_VERIFIED | Koreksi ringkasan H4-only: gunakan universe SSOT §17.2 D1/H4/H1 dan sumber struktural legal. §17.1 menjadi referensi solve order; konflik diagram dicatat dalam binding. |
| S06 | P2 | S02, S04, S05, C04 | NOT_VERIFIED | Seluruh 15 acceptance §24.1 dan 20 zero-tolerance §24.2 diuji dengan denominator dan fixture. Denominator nol bukan 100% PASS. |
| R01 | P3 | S01 | NOT_VERIFIED | Satu risk profile account/mode/currency terikat; tidak mencampur equal dengan asymmetric. Nilai yang belum terikat berstatus UNBOUND. |
| R02 | P3 | R01, S05 | NOT_VERIFIED | Race dua worker/akun; capacity serialized; below-min safe lot ditolak; filled/pending/reserved/unknown dihitung sekali. |
| R03 | P3 | R02 | NOT_VERIFIED | Natural source class memiliki lineage lengkap; ID regex substitution tidak menggantikan verifikasi strategy verdict/gates/risk. |
| E01 | P4 | A00 | NOT_VERIFIED | Monotonic elapsed scheduling terpisah dari UTC expiry; no-quote tetap bisa recovery, tidak bisa submit dengan quote stale. |
| E02 | P4 | A00 | NOT_VERIFIED | Executor heartbeat boolean tidak cukup; attestor/reader terikat dan hasil query lengkap. Unknown proof menahan new risk. |
| E03 | P4 | C01, C02, C03, C06, E01, E02 | NOT_VERIFIED | D0 memiliki manifest gabungan sendiri; projection #418 tidak otomatis menjadi dependency D0. |
| E04 | P4 | E03, C04 | NOT_VERIFIED | Fresh DB dan supported upgrade dari head nyata diuji; assertion failure, schema conflict atau required skip menggagalkan gate. |
| E05 | P4 | E03 | NOT_VERIFIED | Compile exact EA include closure; nol error, seluruh warning memiliki disposition sesuai gate repo; hash binary tercatat. |
| E06 | P4 | E02 | NOT_VERIFIED | Read-only binding account/server/DEMO/spec dan independent reader dibuktikan; jangan menyalin secret ke receipt. |
| D01 | P4 | E04, E05, E06 | NOT_VERIFIED | Satu migration owner; applied schema sesuai manifest; backup/recovery evidence; pertahankan history dan unknown ledger. |
| E07 | P4 | E04, E05, E06, D01 | NOT_VERIFIED | Image/config/schema/EA aktual cocok per service UUID; single ownership dibuktikan pada target. |
| E08 | P4 | E07 | NOT_VERIFIED | HTTPS poll/claim/report dan fault rehearsal pada artifact final; zero broker submit; inventory independen tetap tersedia. |
| E09 | P4 | E08 | NOT_VERIFIED | Record CANARY_OUTCOME_RECONCILED dan BROKER_FILL_PROVEN secara terpisah. Rejection/no-fill yang jelas dapat menutup uji outcome, tetapi tidak membuktikan fill. Satu logical submit bukan satu deal. |
| N01 | P3 | R03, E02 | NOT_VERIFIED | Same intent/same bytes idempotent; same ID/different payload ditolak. Outbox delivery tidak menjadi approval risiko baru. |
| N02 | P3 | R03, E01 | NOT_VERIFIED | Python/MQL5 contract vectors cocok; EA hanya menjalankan keputusan terikat; SHADOW dan invalid signature/account/expiry menghasilkan zero submit. |
| N03 | P3 | N01, N02, E03, S04, S05 | NOT_VERIFIED | Combined commit nyata, protokol kompatibel, migration target converged dan jelas; riwayat applied migration tidak ditulis ulang. |
| N04 | P3 | N03, S06, C04 | NOT_VERIFIED | PASS pada source/schema/config/policy/EA gabungan natural, termasuk recovery unknown dan partial fill. D0 PASS tidak menggantikan natural gates. |
| D02 | P5 | N04, E09 | NOT_VERIFIED | Natural schema diterapkan dari observed target head; compatibility SHADOW/canary/history dipertahankan. |
| N05 | P5 | N04, E09, D02 | NOT_VERIFIED | Final SHADOW diulang pada artifact natural aktual; tidak mewarisi deployment PASS D0. |
| N06 | P5 | N05 | NOT_VERIFIED | Bukti positif natural parent dan lifecycle protection/closure wajib; belum ada sinyal/no-fill dilaporkan NOT_OBSERVED, bukan sukses eksekusi. |
| N07 | P5 | R02, S04 | NOT_VERIFIED | Child independent proof, lifetime slot dan risk-release mengikuti SSOT/profile; floating profit dengan static SL tidak dianggap release. |
| J01 | P5 | N07, N04, C04 | NOT_VERIFIED | Child bytes diuji sendiri termasuk replay, migrations, race, recovery dan MetaEditor; parent PASS bukan bukti child. |
| J02 | P5 | J01, N06 | NOT_VERIFIED | Migration child atau compatible no-op mempunyai bukti schema binding; riwayat dan unresolved exposure dipertahankan. |
| J03 | P5 | J01, J02 | NOT_VERIFIED | Child release parity dan final SHADOW dibuktikan pada image/config/schema/policy/EA baru. |
| N08 | P5 | N06, J03 | NOT_VERIFIED | Parent+child alami, lifecycle kedua leg, slot tetap consumed setelah close, dan compounding campaign berikutnya terbukti independen. |
| O01 | P6 | N08 | NOT_VERIFIED | Soak/fault drill mengukur source freshness, queue lag, latency, recovery/resource; SLO/window harus ditetapkan sebelum dinilai. |
| O02 | P6 | S06, C04 | NOT_VERIFIED | OOS/walk-forward cohort dibekukan; biaya/no-fill/unknown/campaign clustering dilaporkan; threshold tidak dipilih setelah hasil. |
| O03 | P6 | O01, O02, C05 | NOT_VERIFIED | Dossier lengkap boleh berakhir HOLD. REAL_REVIEW_DONE tidak sama dengan REAL_READY atau REAL_ACTIVE. |

## Binding and verification limits

Missing active account risk profile, exact EA/compiler and terminal identity, independent broker proof, applied DB schema and migration owner, final image/config/source parity, policy thresholds, SLO/soak and preregistered OOS criteria remain unclosed. No percentage, timing, sample size or risk level was guessed.

The JSON contains full original/corrected acceptance, owner, dependencies, historical mutation scope, every receipt field, 44 historical domain finding entries, all 83 debt references and current-vs-historical source hash checks. H01–H04 are supporting workstreams, not four additional primary actions.

Verification verdict: audit complete with discrepancies; ENGINEERING/RUNTIME/BROKER acceptance not verified. No required skip or absent test was converted to PASS.

Artifacts: `contract-audit.json`, `WOLF15_Master_Backlog_2026-09-08.canonical.csv`, `selected-ssot-v3.1.md`.
