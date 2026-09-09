# Register enam paket — WOLF15 D1 DEMO terbatas

Status rencana: PARTIAL_PLAN. Edisi awal register: 7 September 2026.

Target: satu rule version canonical 5S-CR yang tervalidasi dan diotorisasi untuk scope DEMO, menghasilkan command dari sinyal alami, dieksekusi EA, dan direkonsiliasi terhadap broker truth.

Register ini mengoperasionalkan rencana terakhir pengguna. Pembuatan register merupakan pekerjaan dokumentasi; tidak membuktikan integrasi, test aplikasi, deployment, pemeriksaan runtime, atau transaksi.

Revisi dokumentasi 1 dipertahankan. Rekonsiliasi 1 — 7 September 2026, snapshot 03:40:40 UTC (11:40:40 Asia/Makassar): source Git lokal dan receipt existing diperiksa untuk P1/P3/P5. Tidak ada test aplikasi atau pemeriksaan runtime baru. Rincian dan locator: [receipt rekonsiliasi](C:/Users/INTEL/.codex/visualizations/2026/09/07/01a079d8-179a-7301-8236-ba92019a6079/reconciliation-p1-p3-p5-20260907.json).

Status sesi di bawah hanya mencakup pekerjaan sistem pada sesi revisi dokumentasi ini. Status paket dan kelulusan tidak menyimpulkan bahwa pekerjaan historis belum pernah dilakukan. Hasil rekonsiliasi kini berisi bukti lokal dan historis yang benar-benar diperiksa. Label VERIFIED_LOCAL_GIT / VERIFIED_SOURCE_LOCAL / VERIFIED_RECEIPT_CONTENT_HASH tidak berarti VERIFIED_RUNTIME_CURRENT.

Rekonsiliasi 2 — 7 September 2026, 03:56:23 UTC: locator source D0 kini terikat ke receipt preflight historis b17887c9; lineage freeze dan enam artefak pendukung cocok. Data audit mentah P5 yang ditemukan tetap agregat tanpa episode ID. [Addendum bukti v2](C:/Users/INTEL/.codex/visualizations/2026/09/07/01a079d8-179a-7301-8236-ba92019a6079/reconciliation-p1-p3-p5-addendum-v2.json). Kelulusan sistem tidak berubah.

## Binding dan provenance bersama

| Field | Nilai setelah rekonsiliasi 1 | Kelas bukti / batas |
| --- | --- | --- |
| Candidate asal | a95f6ad83a560eae4abe0bd377603305f11937ee; tree b7e57d91a63f603190cc21e1346b4f9161c77384 | VERIFIED_LOCAL_GIT; candidate bukan ancestor resulting commit, tetapi dua patch asal cocok dengan commit integrasi |
| Checkpoint integrasi | c64b0145d7df835dc8aa438d59e96ef85f373209 | Provenance awal DECLARED dari laporan asisten; kini VERIFIED_LOCAL_GIT melalui git show dan worktree. Bukan bukti deployment |
| Tree checkpoint | e85d0c4fcef556f5915d87fdd3d1a53ab889ad25 | VERIFIED_LOCAL_GIT; cocok dengan manifest dan attestation v3 |
| Full baseline, ancestry, diff | 1837f4b7cbded620c35933af980e9abd166de39e / tree 4a687c6669d9ed7d0da48cc5b20fcc005b2ad59a; ancestor, 8 commit, 45 path berubah | VERIFIED_LOCAL_GIT; CACHED_LOCAL_ORIGIN_MAIN tidak membuktikan remote terbaru |
| Kebersihan checkout integrasi | git status --porcelain=v1 kosong pada snapshot rekonsiliasi | VERIFIED_LOCAL_GIT pada waktu pemeriksaan saja |
| Checkout utama | Dirty; 45 file perubahan lain diinventarisasi sebelum pembaruan register | VERIFIED_LOCAL_STATUS; perubahan lain dipertahankan, bukan source final release |
| Approval baseline | Pesan pengguna 01a0764a-2b67-7b73-a4df-f6690c5febc2 dalam tugas Validasi D0 execution canary | VERIFIED_APPROVAL_RECORD untuk baseline exact dan scope integrasi lokal; tidak memberi izin deploy/trading; locator di bagian P1 |
| Resulting release commit/tree dan image | Commit/tree c64b0145d7df835dc8aa438d59e96ef85f373209 / e85d0c4fcef556f5915d87fdd3d1a53ab889ad25 terikat receipt v3; release image belum diikat | VERIFIED_LOCAL_GIT + VERIFIED_RECEIPT_CONTENT_HASH; image T14 historis bukan image release tersedia |
| Rule version D1 | Calon source: 5scr.final.2026-07-19; existing pressure processor memakai FX_LEGACY_6P_V1 | VERIFIED_SOURCE_LOCAL; pemilihan target dan authority DEMO tetap NOT_MEASURED |
| EA/EX5, command/schema, akun/server, konfigurasi | Source D0 terpisah b17887c9d901af3248a2c645d6da3f69e584c07b; Demo EA tidak termuat pada c64b0145 | D0_FINAL_RELEASE_BINDING=NOT_BOUND; installed EX5 dan binding runtime NOT_MEASURED; tanpa kredensial |
| T01–T15 / R01–R08 | Matriks tracked pada c64b0145 dan attestation v3 telah dibaca | Gate ID dipertahankan; matriks tracked masih memuat label pra-closure, receipt v3 melengkapi closure historis lokal. R01–R08 bukan bukti runtime baru |
| Pemilik | Peran pada tiap paket | Pelaksana, akses, dan scope perlu diikat sebelum pelaksanaan |
| Waktu dan critical path durasi | NOT_MEASURED | Tidak ada estimasi hari atau janji percepatan numerik |

## Register utama

### P1 — Integrasi release

| Kolom | Isi |
| --- | --- |
| Alur / pemilik | A / penanggung jawab release; identitas pelaksana belum diikat |
| Release / artefak | Mulai dari checkpoint yang dilaporkan c64b0145…; rekonsiliasi full commit/tree, baseline, dan lineage candidate asal |
| Rule version | Catat versi strategi aktual dalam resulting release; belum direkonsiliasi |
| Receipt / cakupan / validitas | Manifest v3: 3/3 hash dan ukuran artefak cocok; 7/7 hash dokumen cocok. Receipt mengikat resulting commit/tree; focused 80 PASS / 3 SKIP, T09/T11 PASS_LOCAL, T14 PASS_OPERATOR_RECONCILED. Bukti existing diverifikasi, bukan test ulang; full-suite tidak diklaim PASS. |
| Status paket | LOCAL_RELEASE_RECEIPTS_RECONCILED |
| Status sesi | SESSION_SOURCE_RECONCILIATION=EXECUTED_READ_ONLY; SESSION_RECEIPT_REVIEW=EXECUTED_READ_ONLY; SESSION_IMPLEMENTATION=NOT_EXECUTED; SESSION_APPLICATION_TESTS=NOT_EXECUTED |
| Kelulusan paket | PACKAGE_ACCEPTANCE=PASS_HISTORICAL_LOCAL_WITH_STATED_LIMITS; RECEIPT_VERDICT=PASS_LOCAL_RELEASE_INTEGRATION; RUNTIME_ACCEPTANCE=NOT_MEASURED_CURRENT |
| Hasil rekonsiliasi | VERIFIED_LOCAL_GIT / VERIFIED_APPROVAL_RECORD / VERIFIED_RECEIPT_CONTENT_HASH — full commit/tree, baseline ancestry, patch equivalence, approval exact dan receipt resulting tree terikat. Lihat rincian P1 di bawah dan [receipt rekonsiliasi](C:/Users/INTEL/.codex/visualizations/2026/09/07/01a079d8-179a-7301-8236-ba92019a6079/reconciliation-p1-p3-p5-20260907.json). Tidak perlu membangun ulang integrasi atau mengulang T09/T11/T14 untuk rekonsiliasi ini. |
| Gap | Binding image release dan penerimaan runtime diteruskan ke P2. Batas receipt: full-suite pernah tertahan missing mcp; T14 operator-reconciled tidak memiliki seluruh raw log/container ID/timestamp dalam JSON. Jangan mengubah bukti terarah menjadi full-suite atau production PASS. |
| Dependensi | Akses source/matriks/receipt; approval baseline exact sebelum integrasi sesuai batas pengguna |
| Tindakan penutup | Pertahankan release c64b0145 dan evidence historis. Gunakan receipt terverifikasi untuk handoff P2; setiap perubahan resulting tree memerlukan penilaian dampak dan gate yang relevan. Tidak ada repair lokal baru yang dijalankan dalam rekonsiliasi ini. |
| Acceptance | Satu commit/tree final, seluruh gate wajib terjawab, bukti sesuai sumber/artefak, konflik dokumentasi tertutup; skip/xfail tidak dipakai untuk menyembunyikan kegagalan |
| Stop condition | Approval/binding tidak cocok, gate wajib gagal atau tidak memiliki bukti, perubahan sumber membuat receipt tidak berlaku; pertahankan perubahan checkout utama |

### P2 — Single-owner runtime

| Kolom | Isi |
| --- | --- |
| Alur / pemilik | A / penanggung jawab runtime; identitas pelaksana belum diikat |
| Release / artefak | Release P1, image dan konfigurasi efektif, deployment serta pasangan artefak-konfigurasi recovery yang kompatibel |
| Rule version | Sama dengan release yang diterapkan; execution tetap OFF |
| Receipt / cakupan / validitas | R01–R08 belum dibuktikan di sesi ini. Campaign GAP-CLOSURE-20260906T184003Z dilaporkan parsial dan tidak mengotorisasi cutover |
| Status paket | BLOCKED untuk pelaksanaan runtime |
| Status sesi | SESSION_DEPLOYMENT=NOT_EXECUTED; SESSION_RUNTIME_INSPECTION=NOT_EXECUTED |
| Kelulusan paket | PACKAGE_ACCEPTANCE=NOT_MEASURED |
| Gap | Konfigurasi produksi, trigger publikasi, nilai canRollback, account state, ownership efektif, recovery API-only, dan verifikasi runtime |
| Dependensi | P1 PASS; otorisasi deployment/cutover dengan target dan scope exact; akses audit yang sesuai |
| Tindakan penutup | Lengkapi paket cutover; setelah diotorisasi, verifikasi effective config, ownership/fencing, readiness, account state, containment, serta recovery sesuai matriks aktual |
| Acceptance | API tidak menjalankan orchestrator; satu owner efektif; stale owner ditolak; account state berfungsi; execution OFF; bukti runtime dan recovery tersedia |
| Stop condition | Ownership ambigu/ganda, state tidak konsisten, recovery tidak terbukti, atau execution berubah di luar scope; hentikan issuance sambil mempertahankan observasi dan reconciliation |

### P3 — Kesiapan D0

| Kolom | Isi |
| --- | --- |
| Alur / pemilik | C / penanggung jawab executor; identitas pelaksana belum diikat |
| Release / artefak | Release orchestrator c64b0145 hanya memuat EA SHADOW. Source D0 ditemukan pada repo terpisah d0-canary-control-v3, commit b17887c9d901af3248a2c645d6da3f69e584c07b / tree ceee09eb36f171b2eb75f34a0e7d4255aec78e89; final binding belum ditetapkan. |
| Rule version | D0 adalah engineering canary; tidak memperoleh authority strategi dari rule version |
| Receipt / cakupan / validitas | VERIFIED_SOURCE_LOCAL pada D0 b17887c9: dua OrderCheck pada jalur sukses ke submit, durable submit marker, pending-report retry, idempotency backend dan broker scan ditemukan. Bukan receipt test atau bukti EX5 terpasang. |
| Status paket | PREPARATION=PARTIAL; D0_FINAL_RELEASE_BINDING=NOT_BOUND; P3_RECOVERY_CONTINUITY_GAP=OPEN |
| Status sesi | SESSION_SOURCE_RECONCILIATION=EXECUTED_READ_ONLY; SESSION_APPLICATION_TESTS=NOT_EXECUTED; SESSION_RUNTIME_INSPECTION=NOT_EXECUTED |
| Kelulusan paket | PACKAGE_ACCEPTANCE=NOT_MEASURED; SOURCE_RECONCILIATION=PARTIALLY_VERIFIED; RUNTIME_ACCEPTANCE=NOT_MEASURED |
| Hasil rekonsiliasi | VERIFIED_SOURCE_LOCAL / VERIFIED_RECEIPT_CONTENT_HASH — locator checks/submit, ambiguous recovery, pending reporting dan backend idempotency terikat source b17887c9 yang disebut receipt preflight D0 historis. Lineage freeze 751a9694 → b17887c9 terbukti; EA/backend terkait tidak berubah di antaranya. Preflight historis tetap HOLD, bukan approval deploy/DEMO. g_demo_blocked tetap menyisakan continuity gap; installed EX5 dan compatibility terhadap release c64b0145 belum terbukti. |
| Gap | Binding source D0 final terhadap release, installed EX5/account/server, issuance/writer runtime, serta P3_RECOVERY_CONTINUITY_GAP: status unavailable/hash mismatch, reconciliation failure atau partial fill dapat memblokir recovery timer berikutnya. |
| Dependensi | Inventarisasi dokumentasi dapat dimulai sekarang; penerimaan akhir bergantung pada P1/P2 dan akses binding final |
| Tindakan penutup | Ikat versi D0 dan artefak terpasang ke release yang dipilih; tentukan kontrak recovery pada cabang blocked dan buktikan observasi/reconciliation yang tetap berwenang. Sesudah gap ditutup dalam scope terotorisasi, lakukan acceptance final; jangan menyamakan source inspection dengan test atau runtime. |
| Acceptance | Tidak ada mismatch artefak/binding; jumlah pemeriksaan dan batas submit jelas; paket D0 lengkap; belum ada transaksi |
| Stop condition | Kontrak tidak cocok, jumlah pemeriksaan belum terselesaikan, binding stale/mismatch, broker truth atau writer tidak lengkap |

### P4 — D0 engineering

| Kolom | Isi |
| --- | --- |
| Alur / pemilik | Operator serta penanggung jawab reconciliation; identitas pelaksana belum diikat |
| Release / artefak | Paket D0 exact dari P3, approval operator, dan identitas serta parameter transaksi yang dibekukan |
| Rule version | Tidak membuktikan kelulusan strategi; scope engineering saja |
| Receipt / cakupan / validitas | Tidak ada receipt transaksi D0 yang dibuktikan dalam sesi ini |
| Status paket | BLOCKED |
| Status sesi | SESSION_BROKER_TRANSACTION=NOT_EXECUTED; SESSION_RUNTIME_INSPECTION=NOT_EXECUTED |
| Kelulusan paket | PACKAGE_ACCEPTANCE=NOT_MEASURED |
| Gap | Kelulusan P3 dan approval D0 beserta parameter/batas/kondisi akhir |
| Dependensi | P3 PASS; otorisasi D0 tersendiri; paket operator lengkap |
| Tindakan penutup | Jalankan seluruh pemeriksaan wajib; maksimum satu percobaan submit sesuai paket, tanpa resubmit otomatis; rekonsiliasi broker/ledger, verifikasi proteksi dan kondisi akhir |
| Acceptance | Maksimum satu percobaan submit dan maksimum satu broker effect transaksi yang diotorisasi sesuai kontrak final serta paket D0; seluruh pemeriksaan wajib tetap dijalankan, tanpa resubmit otomatis. Order, deal, dan posisi terkait tidak otomatis dihitung sebagai submit terpisah; pemetaan broker effect mengikuti kontrak final. Tidak duplikat, hasil broker sesuai command, ambiguity terselesaikan, ledger lengkap, proteksi dan kondisi akhir terbukti. Batas maksimum ini tidak dengan sendirinya membuktikan keberhasilan D0. |
| Stop condition | Pemeriksaan gagal, binding berubah, window habis, batas dilanggar, atau hasil submit ambigu. Jangan resubmit; reporting idempotent, broker scan, dan reconciliation tetap berjalan sesuai kontrak |

### P5 — Natural strategy dan authority

| Kolom | Isi |
| --- | --- |
| Alur / pemilik | B / penanggung jawab strategi; identitas pelaksana belum diikat |
| Release / artefak | Rule version canonical terpilih, implementasi/rule configuration, evidence episode, replay, natural SHADOW, serta approval DEMO |
| Rule version | Calon yang ada pada release: 5scr.final.2026-07-19. Existing pressure processor menggunakan FX_LEGACY_6P_V1; FX_MIN_TARGET_10P_V1 adalah policy Hybrid V3 terpisah. Target dan approval DEMO belum ditetapkan; MATURE_ADVISORY tetap non-executable. |
| Receipt / cakupan / validitas | Source c64b0145 dan SSOT v3.1 terpisah diperiksa. Audit historis 2026-09-05T16:30:09.634028Z (hash cocok) membuktikan nol outcome pada dua periode, tetapi tidak menghitung candidate atau memberi episode ID/hop. Tidak terikat runtime release c64b0145. |
| Status paket | PREPARATION=PARTIAL; SOURCE_RECONCILIATION=PARTIALLY_VERIFIED; EPISODE_EVIDENCE=NOT_MEASURED |
| Status sesi | SESSION_SOURCE_RECONCILIATION=EXECUTED_READ_ONLY; SESSION_RECEIPT_REVIEW=EXECUTED_READ_ONLY; SESSION_APPLICATION_TESTS=NOT_EXECUTED; SESSION_RUNTIME_INSPECTION=NOT_EXECUTED |
| Kelulusan paket | PACKAGE_ACCEPTANCE=NOT_MEASURED; NATURAL_DECISION=NOT_MEASURED; DETERMINISTIC_HANDOFF=NOT_MEASURED; NATURAL_RUNTIME_HANDOFF=NOT_MEASURED; STRATEGY_AUTHORITY=NOT_MEASURED |
| Hasil rekonsiliasi | VERIFIED_SOURCE_LOCAL / VERIFIED_RECEIPT_CONTENT_HASH — calon rule dan policy aktual, wiring hingga candidate serta batas operator handoff dipetakan. Identitas episode dan hop terakhir episode tetap NOT_MEASURED; receipt historis hanya membuktikan agregat outcome dan laporan konfigurasi/instance. AUDIT_DATABASE_URL tidak tersedia pada proses pemeriksaan; tidak ada query runtime baru. Lihat rincian P5. |
| Gap | Target rule + execution policy dan approval DEMO, final release binding, episode ID/hop/canonical lineage, receipt replay dan natural handoff runtime. Source berisi operator shadow handoff, belum bukti otomatisasi natural. Root cause terminal nol tetap UNKNOWN. |
| Dependensi | Diagnosis awal dapat dilakukan tanpa D0; penerimaan natural SHADOW memerlukan runtime release yang dipilih. Perubahan kode harus direkonsiliasi kembali ke P1 |
| Tindakan penutup | Tentukan target rule bersama execution policy berdasarkan validasi/approval yang berlaku, tanpa mengganti policy diam-diam. Peroleh snapshot SELECT-only atau export terikat release/waktu yang memuat episode dan hop pressure/admission/inbox/evidence/candidate/handoff. Isi dimensi keputusan dan handoff terpisah; jangan meluluskan P5 dari outcome nol atau definisi test. |
| Acceptance | Keputusan natural dan canonical handoff dibuktikan terpisah, lineage lengkap, replay/validasi wajib lulus, natural runtime terbukti, serta authority strategi DEMO berlaku |
| Stop condition | Hanya WAIT teramati untuk klaim handoff, lineage tidak lengkap, rule belum tervalidasi/diotorisasi, atau advisory memasuki risk/command. Pertahankan penolakan strategi yang sah |

### P6 — D1 otomatis terbatas

| Kolom | Isi |
| --- | --- |
| Alur / pemilik | Operator serta penanggung jawab runtime; identitas pelaksana belum diikat |
| Release / artefak | Release dan rule version tervalidasi, binding akun/executor, serta paket D1 yang membatasi universe, window, risiko, transaksi, penghentian, dan pengelolaan posisi |
| Rule version | Sama dengan authority strategi DEMO pada P5; tidak boleh berubah diam-diam selama window |
| Receipt / cakupan / validitas | Tidak ada receipt D1 yang dibuktikan dalam sesi ini |
| Status paket | BLOCKED |
| Status sesi | SESSION_AUTOMATED_DEMO=NOT_EXECUTED; SESSION_RUNTIME_INSPECTION=NOT_EXECUTED |
| Kelulusan paket | PACKAGE_ACCEPTANCE=NOT_MEASURED |
| Gap | Kelulusan P4/P5, kompatibilitas bukti terhadap release final, serta paket/approval D1 |
| Dependensi | D0 PASS + keputusan natural terbukti + canonical handoff terbukti + validasi/authority strategi DEMO + otorisasi D1 tersendiri |
| Tindakan penutup | Jalankan hanya dalam paket yang disetujui; sistem membentuk command dari sinyal alami; EA mengeksekusi mekanis; pantau, rekonsiliasi, dan tutup window sesuai paket |
| Acceptance | Sinyal alami menghasilkan command berwenang dan broker effect yang direkonsiliasi, tanpa operator membuat command per transaksi; proteksi, duplicate-safety, dan kondisi akhir terbukti |
| Stop condition | Window/batas habis, authority/binding berubah, safety condition terpicu, atau hasil ambigu. Tanpa sinyal layak: NO_TRADE_OBSERVED / D1_EXECUTION_NOT_PROVEN; jangan memperpanjang window atau melonggarkan strategi otomatis |

## Matriks bukti P5

| Dimensi | Kebutuhan bukti | Status awal | Batas kesimpulan |
| --- | --- | --- | --- |
| Keputusan natural | Pressure → admission → lifecycle → evidence → analisis → keputusan terminal, dengan lineage dan reason yang tersedia | NOT_MEASURED | WAIT/NO_TRADE membuktikan keputusan yang teramati, tidak membuktikan handoff |
| Handoff deterministik | Replay candidate canonical yang memenuhi syarat melalui evaluasi/risk/command di lingkungan terisolasi tanpa broker effect | NOT_MEASURED | Bukti simulasi/perilaku deterministik; tidak memberi authority produksi dan tidak menggantikan natural runtime |
| Handoff runtime | Natural SHADOW canonical melewati handoff yang diizinkan kontrak SHADOW, dengan broker execution terlarang | NOT_MEASURED | Hanya WAIT berarti handoff NOT_PROVEN; jangan mengaktifkan risk/command produksi untuk membuat bukti SHADOW |
| Validasi dan authority | Rule version, acceptance/replay/OOS yang diwajibkan versi tersebut, serta approval DEMO yang sesuai | NOT_MEASURED | Candidate, nama canonical, atau approval dokumen saja tidak menggantikan gate eksekusi |

## Bukti rekonsiliasi 1 — P1/P3/P5

Pemeriksa: asisten pada tugas ini, dengan dua investigator source read-only. Snapshot Git dan hash diperiksa 7 September 2026; hasil test/runtime historis tetap memiliki waktu dan scope asal. Locator file dengan nomor baris di bawah merujuk commit yang dinyatakan, bukan izin menjalankan file. Snapshot awal register berstatus DECLARED; tabel terbaru memperbaruinya hanya sejauh bukti yang diperiksa.

### P1 — identitas, approval, dan receipt

- Baseline: `1837f4b7cbded620c35933af980e9abd166de39e`, tree `4a687c6669d9ed7d0da48cc5b20fcc005b2ad59a`. Result: `c64b0145d7df835dc8aa438d59e96ef85f373209`, tree `e85d0c4fcef556f5915d87fdd3d1a53ab889ad25`. Baseline ancestor exit 0; 8 commit, 45 path (+2338/-127).
- Candidate `a95f6ad83a560eae4abe0bd377603305f11937ee` bukan ancestor result (exit 1). Dua perubahan diintegrasikan sebagai patch equivalent: `eb9c6d… → 711e926a…` dengan stable patch ID `9d19bb6bb0d2107ab5bf76bdde51c3bf56bb8df7`, dan `a95f6ad… → adae23b6…` dengan stable patch ID `ce8069ebe8eda34d638b8a4ee80587de31ff2c48`. Merge base `ec31631864204ca183079966d7834338f7a986cd`.
- Approval ditemukan melalui `read_thread`, tugas **Validasi D0 execution canary**, thread `01a03a35-3b96-7123-8cb5-c175c455f2e7`, turn `01a0764a-262f-7b00-a864-71d781503d40`, user-message `01a0764a-2b67-7b73-a4df-f6690c5febc2`. Pesan menyetujui full baseline commit/tree di atas sebagai `CACHED_LOCAL_ORIGIN_MAIN`, integrasi lokal candidate, local/disposable tests serta local commit/freeze. Push, merge bersama, deployment, production migration, Railway config, execution controls, EX5/MT5 dan broker dikecualikan. Excerpt dan locator disimpan pada [receipt rekonsiliasi](C:/Users/INTEL/.codex/visualizations/2026/09/07/01a079d8-179a-7301-8236-ba92019a6079/reconciliation-p1-p3-p5-20260907.json).
- [Manifest v3](C:/Users/INTEL/.codex/visualizations/2026/08/25/01a03a35-3b96-7123-8cb5-c175c455f2e7/orchestrator-release-integration-1837f4b7-attestation/evidence-manifest-v3.json): SHA-256 `917ced35e18c629fe680028aba62386b5f94c55ab6f609f4941cae421c52412c`, sidecar cocok; 3/3 artefak cocok ukuran/hash.
- [Attestation v3](C:/Users/INTEL/.codex/visualizations/2026/08/25/01a03a35-3b96-7123-8cb5-c175c455f2e7/orchestrator-release-integration-1837f4b7-attestation/release-integration-attestation-v3.json): SHA-256 `b4c59eeead67dec37d99a0d00c82d2457ec04d1fdff9e68efcf87fb6b1885e6e`; 7/7 hash dokumen cocok. Verdict historis `PASS_LOCAL_RELEASE_INTEGRATION`, timestamp `2026-09-06T16:49:51.0164279Z`.
- [Local receipt v3](C:/Users/INTEL/.codex/visualizations/2026/08/25/01a03a35-3b96-7123-8cb5-c175c455f2e7/orchestrator-release-integration-1837f4b7-attestation/local-verification-receipt-v3.json): SHA-256 `f90775da119c2a9ba5bf752b54909b0b681d28cfb8f4060f0d14e8b35abf840f`. Focused 80 PASS / 3 SKIP / 0 FAIL; Pyright 0 error / 5 warning; T09/T11 PASS_LOCAL. Skip adalah opt-in T14 dan dua Redis tests pada invocation tanpa endpoint; lane terpisah tidak disamakan dengan invocation tersebut.
- [T14 receipt](C:/Users/INTEL/.codex/visualizations/2026/08/25/01a03a35-3b96-7123-8cb5-c175c455f2e7/orchestrator-release-integration-1837f4b7-attestation/t14-runtime-observation-c64b0145.json): SHA-256 `a265ac3ba206532b0550e606a81f454066f4b51747dd70cf2b66e80d4f9102c9`; campaign `wolf15-t14-8a7c322104b7`, `ENV=test`, verdict `PASS_OPERATOR_RECONCILED`. Image test `sha256:d7430e2391df2d0e4f77cd7f4792c243c87b4a796a0c05629d6ae6489a2a7e57`; bukan image release yang tersedia.
- [Receipt v1](C:/Users/INTEL/.codex/visualizations/2026/08/25/01a03a35-3b96-7123-8cb5-c175c455f2e7/orchestrator-release-integration-1837f4b7-attestation/local-verification-receipt.json) memuat Redis `PASS_2_OF_2` pada `b89dd971…`. Diff `b89dd971..c64b0145` hanya file test T14; cakupan source/test recovery dan Redis tidak berubah. V1 juga merekam full-suite collection tertahan missing `mcp`; tidak ada klaim full-suite PASS.
- [Release handoff](C:/Users/INTEL/.codex/visualizations/2026/08/25/01a03a35-3b96-7123-8cb5-c175c455f2e7/orchestrator-release-integration-1837f4b7-attestation/../release-handoff-c64b0145.md) membatasi penerimaan lokal dan menyatakan T14 image telah dihapus. JSON T14 tidak memuat seluruh raw build log, container ID, atau timestamp per observasi; rekonstruksi offline lengkap dari JSON saja terbatas. [Matriks tracked](C:/Users/INTEL/AppData/Local/Temp/wolf15-orchestrator-release-integration-1837f4b7/docs/architecture/orchestrator-acceptance-traceability.md:3) tetap sumber definisi T01–T15/R01–R08; receipt eksternal melengkapi status historis tanpa mengubah frozen tree.

### P3 — source D0 terpisah dan batas recovery

Semua locator dalam tabel ini memakai commit `b17887c9d901af3248a2c645d6da3f69e584c07b`, tree `ceee09eb36f171b2eb75f34a0e7d4255aec78e89`. Blob Demo EA `4185f0a87d215127f7caad7c4f8e730f9cf5a6b7`; blob repository backend `0ed2e744c8d42c29e0c4f0a9edd8d70e989cab8c`. Source ini ditemukan pada repository lokal terpisah; keberadaannya tidak mengikatnya ke release orchestrator.

| Kebutuhan | Locator source pinned | Hasil dan batas |
| --- | --- | --- |
| Pemeriksaan wajib | [BuildCheckedDemoRequest](C:/Users/INTEL/.codex/visualizations/2026/08/25/01a03a35-3b96-7123-8cb5-c175c455f2e7/d0-canary-control-v3/ea_interface/wolf15_executor/Wolf15_DumbExecutor_Demo.mq5:915); pemanggil baris 933 dan 944 | Satu static OrderCheck dipanggil dua kali pada jalur sukses ke submit; pemeriksaan kedua setelah ACK SUBMITTING. Early failure dapat berhenti sebelum dua check. |
| Submit | [Durable marker](C:/Users/INTEL/.codex/visualizations/2026/08/25/01a03a35-3b96-7123-8cb5-c175c455f2e7/d0-canary-control-v3/ea_interface/wolf15_executor/Wolf15_DumbExecutor_Demo.mq5:950), OrderSend baris 959 | submit_attempted disimpan sebelum submit, ATTEMPT_1_OF_1; recovery tidak memanggil OrderSend. Bukan bukti at-most-once runtime. |
| Persistensi laporan | [SaveDemoState](C:/Users/INTEL/.codex/visualizations/2026/08/25/01a03a35-3b96-7123-8cb5-c175c455f2e7/d0-canary-control-v3/ea_interface/wolf15_executor/Wolf15_DumbExecutor_Demo.mq5:216), FileFlush 247/FileMove 249; prepared report 592–614 | Implementasi persist-before-POST ditemukan; crash/restart acceptance belum diperiksa. |
| Reporting idempotent | [PostPreparedDemoReport](C:/Users/INTEL/.codex/visualizations/2026/08/25/01a03a35-3b96-7123-8cb5-c175c455f2e7/d0-canary-control-v3/ea_interface/wolf15_executor/Wolf15_DumbExecutor_Demo.mq5:673), pending tetap pada 680–683; [backend](C:/Users/INTEL/.codex/visualizations/2026/08/25/01a03a35-3b96-7123-8cb5-c175c455f2e7/d0-canary-control-v3/execution/mt5_command_repository.py:2016), sequence/payload check 2055, duplicate ACK 2065/2128 | Pending dibersihkan setelah ACK; source tidak membuktikan writer/database/transport live. |
| Broker scan dan hasil ambigu | [ReconcileDemoBrokerState](C:/Users/INTEL/.codex/visualizations/2026/08/25/01a03a35-3b96-7123-8cb5-c175c455f2e7/d0-canary-control-v3/ea_interface/wolf15_executor/Wolf15_DumbExecutor_Demo.mq5:759), recovery 1066–1183 | History, orders, positions, deals dan unique lineage diperiksa; recovery tidak resubmit. |
| P3_RECOVERY_CONTINUITY_GAP | [Status failure/hash mismatch](C:/Users/INTEL/.codex/visualizations/2026/08/25/01a03a35-3b96-7123-8cb5-c175c455f2e7/d0-canary-control-v3/ea_interface/wolf15_executor/Wolf15_DumbExecutor_Demo.mq5:1082), reconciliation failure 1108–1112, partial fill 1150–1153; [timer](C:/Users/INTEL/.codex/visualizations/2026/08/25/01a03a35-3b96-7123-8cb5-c175c455f2e7/d0-canary-control-v3/ea_interface/wolf15_executor/Wolf15_DumbExecutor_Demo.mq5:1252) | g_demo_blocked dipasang; heartbeat mendahului return 1257–1258, sedangkan RecoverDemoState berada sesudahnya pada 1263. Recovery/report retry otomatis tidak berlanjut melalui timer pada cabang blocked tersebut. Ini gap source terhadap kebutuhan continuity, bukan observasi kegagalan broker aktual. |

Tree `c64b0145` memuat `Wolf15_DumbExecutor_Shadow.mq5` (blob `84e73471fd26eb1f1b81da11f15146e3735a6c52`), tanpa Demo EA. Packaging EA terpisah sendiri bukan bukti inkompatibilitas. Namun, tree ini juga tidak memuat empat path capability D0 yang diperiksa: `contracts/mt5_mode_transition_authority.py`, `contracts/direct_broker_reconciliation.py`, `execution/mt5_demo_canary_authority_packet.py`, dan migration `20260905_01_d0_canary_control_capabilities.py`. Mapping implementasi ekuivalen serta kompatibilitas backend/schema/EA belum dibuktikan; `D0_FINAL_RELEASE_BINDING=NOT_BOUND` dipertahankan atas gap mapping tersebut. Kegagalan POST sendiri mempertahankan pending tanpa memasang blocked; jangan memperluas temuan blocked ke semua kegagalan reporting.

**Binding historis source D0:** [freeze receipt](C:/Users/INTEL/.codex/visualizations/2026/08/25/01a03a35-3b96-7123-8cb5-c175c455f2e7/d0-canary-control-v3-freeze/freeze-receipt.json) mengikat `751a9694bc7eff1e3e6b1d20405a840066d478bf` / tree `a37030a9398056d576df5eca555e66d10f857720`. Git membuktikan freeze tersebut ancestor `b17887c9`; diff hanya migration capability D0 dan test-nya, bukan EA atau command repository. [Preflight receipt](C:/Users/INTEL/.codex/visualizations/2026/08/25/01a03a35-3b96-7123-8cb5-c175c455f2e7/d0-v3-production-preflight-b17887c9/production-preflight-receipt.json) mengikat full commit/tree b17887c9 dengan authorization ID `WOLF15-D0-V3-PRODUCTION-PREFLIGHT-READONLY-B17887C9-V1`. Manifest kedua paket cocok **6/6 hash dan ukuran artefak**. Verdict preflight `HOLD_READ_AUTHORITY_UNAVAILABLE_AND_ORCHESTRATOR_STATE_DRIFT`, `execution_ready=false`, `demo_ordersend=NO-GO`; identitas source preflight bukan authority deploy/DEMO. Hash EX5 kandidat dan terpasang dalam freeze berbeda, dan EA compile tidak dijalankan pada freeze tersebut; itu observasi historis, bukan status instalasi sekarang.

### P5 — rule, wiring, dan evidence episode

Seluruh locator release di bawah memakai `c64b0145d7df835dc8aa438d59e96ef85f373209`. Status EXISTS/WIRED hanya source; EXECUTED/EFFECT natural runtime belum terbukti.

| Dimensi | Locator | Hasil rekonsiliasi |
| --- | --- | --- |
| Rule calon target | [Strategy contract](C:/Users/INTEL/AppData/Local/Temp/wolf15-orchestrator-release-integration-1837f4b7/contracts/strategy_5scr.py:20), literal 126 | `5scr.final.2026-07-19`; bukan approval DEMO. |
| Policy aktual | [Pressure processor](C:/Users/INTEL/AppData/Local/Temp/wolf15-orchestrator-release-integration-1837f4b7/storage/strategy_5scr_pressure_inbox.py:87); [policy definitions](C:/Users/INTEL/AppData/Local/Temp/wolf15-orchestrator-release-integration-1837f4b7/contracts/strategy_5scr_execution_policy.py:11) | Existing processor default `FX_LEGACY_6P_V1`; source menyatakan belum Hybrid V3. `FX_MIN_TARGET_10P_V1` tidak boleh diasumsikan aktif di jalur ini. |
| Raw ledger → admission/radar | [Analyzer](C:/Users/INTEL/AppData/Local/Temp/wolf15-orchestrator-release-integration-1837f4b7/analysis/signal_throttle_log_analyzer.py:658), 770/875–876; [radar](C:/Users/INTEL/AppData/Local/Temp/wolf15-orchestrator-release-integration-1837f4b7/analysis/strategy_5scr_pressure_radar.py:539), 557–582 | Source mengikat grant, rule, expiry, ledger hash dan lifecycle. Tidak membuktikan episode runtime melewatinya. |
| Pressure → inbox/evidence → candidate | [Runner](C:/Users/INTEL/AppData/Local/Temp/wolf15-orchestrator-release-integration-1837f4b7/services/pressure_outbox/runner.py:40); [inbox](C:/Users/INTEL/AppData/Local/Temp/wolf15-orchestrator-release-integration-1837f4b7/storage/strategy_5scr_pressure_inbox.py:76); [evidence worker](C:/Users/INTEL/AppData/Local/Temp/wolf15-orchestrator-release-integration-1837f4b7/services/pressure_outbox/evidence_worker.py:262), 410–514 | Worker terhubung secara source; inbox WAITING_EVIDENCE, READY/BLOCK/DEFER dan candidate persistence tersedia. Kandidat tetap non-executable. |
| Batas handoff | [Operator shadow wiring](C:/Users/INTEL/AppData/Local/Temp/wolf15-orchestrator-release-integration-1837f4b7/execution/mt5_operator_shadow_wiring.py:347); [promotion](C:/Users/INTEL/AppData/Local/Temp/wolf15-orchestrator-release-integration-1837f4b7/execution/mt5_command_promotion.py:106) | reserve_parent → produce_next ditemukan pada jalur operator. Komponen risk/command ada, automatic natural handoff belum dibuktikan. |
| Definisi replay/test | [Pressure tests](C:/Users/INTEL/AppData/Local/Temp/wolf15-orchestrator-release-integration-1837f4b7/tests/test_strategy_5scr_pressure_to_tradeplan.py:193), 219/232/239/256/297; [evidence tests](C:/Users/INTEL/AppData/Local/Temp/wolf15-orchestrator-release-integration-1837f4b7/tests/test_strategy_5scr_evidence_worker.py:278); [reservation tests](C:/Users/INTEL/AppData/Local/Temp/wolf15-orchestrator-release-integration-1837f4b7/tests/test_strategy_5scr_risk_reservation.py:97) | TEST_DEFINITION_EXISTS; test tidak dijalankan dan tidak menggantikan receipt replay atau natural SHADOW. |
| Authority v3.1 | [SSOT terpisah](C:/Users/INTEL/OneDrive/Documents/GitHub/TUYUL-FX-WOLF-15LAYER-SYSTEM-SSOT-V31/docs/strategy/WOLF15_STRATEGY_5SCR_CANONICAL_SSOT_V3_1_CANDIDATE.md:17) | Ref `dd27ae87d0207466caad4c3e098224112ac0eaf7`, blob `cd848447a2e923d0ea0de6c566a558c7205d3d3b`: PROPOSED_CANONICAL, SHADOW_ONLY, OOS NOT_YET_VALIDATED; approval record null. Bukan bagian tree release atau authority DEMO. |

[Audit outcome historis](C:/Users/INTEL/.codex/visualizations/2026/09/05/01a07021-1fae-7fc3-8141-63ddc817604b/WOLF15_5SCR_WEEKLY_PRECISION_AUDIT.json) memiliki hash `1680511f82ea30f7c819d097fa9fbef69591410a389f197a9e73378e36aa1944` yang cocok. Snapshot `2026-09-05T16:30:09.634028Z`, transaksi READ ONLY / REPEATABLE READ / ROLLBACK, dua periode 7 hari masing-masing nol outcome dan terminal denominator; precision null. Ini bukti isi receipt historis, bukan query ulang atau bukti runtime c64b0145.

[Addendum diagnosis](C:/Users/INTEL/.codex/visualizations/2026/09/05/01a07021-1fae-7fc3-8141-63ddc817604b/ADDENDUM_DIAGNOSIS_OUTCOME_NOL_5SCR_2026-09-06.md) memiliki hash `08396c1c823b689a26f5538cba0b9df1f0bf4aba26fce13804ec9b1860515fcd` yang cocok. Receipt tidak menyediakan episode ID, candidate count atau pending candidate count. Tahap historis yang dilaporkan hanya konfigurasi pipeline dan instance berjalan; tidak boleh diubah menjadi hop terakhir episode. Maka:

- `EPISODE_ID=NOT_MEASURED`; `LAST_EPISODE_HOP=NOT_MEASURED`.
- `NATURAL_DECISION=NOT_MEASURED`; `DETERMINISTIC_HANDOFF=NOT_MEASURED`; `NATURAL_RUNTIME_HANDOFF=NOT_MEASURED`.
- `STRATEGY_DEMO_AUTHORITY=NOT_MEASURED`; `ZERO_OUTCOME_ROOT_CAUSE=UNKNOWN`.
- Pemeriksaan keberadaan `AUDIT_DATABASE_URL` dan `AUDIT_REDIS_URL` pada lingkup Process, User, dan Machine yang terlihat sesi ini semuanya FALSE. Nilai credential tidak ditampilkan; tidak ada database query, perubahan privilege, atau runtime probe baru. Snapshot auditor terikat release/waktu atau export setara diperlukan untuk mengisi episode dan hop.

**Rekonsiliasi data mentah historis:** record `custom_tool_call_output` pada [session audit](C:/Users/INTEL/.codex/sessions/2026/09/05/rollout-2026-09-05T14-13-27-01a07033-3c76-73d0-858a-f62e2e7a141b.jsonl:710), SHA-256 `a56fdf7f60d0941453acd239c8d68c53fa248f482994e285b8d54e01f3f797ac`, menyimpan snapshot `2026-09-05T07:41:33.135613+00:00`: inbox WAITING_EVIDENCE sebanyak 2, dengan received_at tertua `2026-07-28T09:17:55.296743+00:00` dan terbaru `2026-07-29T12:35:57.285099+00:00`. Ini hitungan all-time, bukan episode baru atau bukti runtime release final. Record baris 1090 memuat snapshot `2026-09-05T09:56:26.878013+00:00` READ ONLY / REPEATABLE READ / ROLLBACK, dua manifest ANALYSIS_READY/outbox-linked serta dua inbox WAITING_EVIDENCE. Agregat tersebut tidak membuktikan join per episode atau bahwa dua kelompok adalah episode yang sama.

[Source query historis](C:/Users/INTEL/.codex/visualizations/2026/09/05/01a07033-3c76-73d0-858a-f62e2e7a141b/postgres_funnel_detail_probe.py) hanya memilih group status/count/min/max, tanpa episode ID. Script memakai application DSN environment; tidak dijalankan atau dipakai sebagai pengganti akses auditor SELECT-only pada sesi ini. Hasil pencarian mentah memperkuat batas bukti: `EPISODE_ID` dan `LAST_EPISODE_HOP` tetap `NOT_MEASURED`, bukan hilang karena ringkasan laporan saja.

## Aturan pembaruan dan recovery

Satu penanggung jawab integrasi menggabungkan perubahan A/B/C. Pengamatan read-only dapat disiapkan bersamaan; penerimaan akhir mengikuti dependensi P1 → P2 → P3 → P4, dengan P4 dan P5 menjadi prasyarat P6.

Bukti historis tetap dipertahankan. Setiap receipt dinilai cakupan sumber, lingkungan, konfigurasi, dan freshness-nya sebelum digunakan ulang.

Perubahan setelah freeze menghasilkan identitas release baru. Nyatakan gate yang terpengaruh dan alasannya; hasil tree lama tidak otomatis membuktikan tree baru.

Submit D0 tidak diulang otomatis. Retry pelaporan yang idempotent, broker scan, dan reconciliation mengikuti kontrak yang berlaku serta tidak boleh menghasilkan order tambahan.

Hentikan issuance ketika diperlukan; pertahankan observasi, ledger, dan kemampuan menyelesaikan hasil ambigu. Penutupan posisi atau pembatalan order hanya sesuai paket operator.

Recovery aplikasi memakai predecessor artefak-konfigurasi yang kompatibel dan mempertahankan single ownership. Menjalankan ulang image candidate tidak memperbaiki defect yang ada di kode candidate tersebut.

Tidak ada rollback database atau penghapusan ledger untuk menghilangkan ambiguity transaksi. Pertahankan seluruh pekerjaan pengguna.

Tidak ada nilai risiko, universe, window, retry budget, atau tindakan posisi yang diisi secara asumsi. Ikat ke kebijakan/kontrak/paket yang disetujui sebelum pelaksanaan terkait.

## Field minimum untuk setiap receipt yang akan ditambahkan

Receipt harus memiliki locator artefak aktual; source commit/tree atau digest; identitas build/EA/rule yang relevan; lingkungan dan konfigurasi relevan yang disanitasi; binding non-rahasia; waktu observasi; cakupan gate; hasil beserta failure/timeout/skip; pelaksana; serta dasar validitas terhadap release target. Field yang belum tersedia dicatat sebagai gap, tidak direkayasa.

Receipt belum diperiksa = NOT_MEASURED. Receipt historis yang baru dilaporkan = DECLARED. Isi dokumen yang dibaca = VERIFIED terhadap dokumen, bukan VERIFIED_RUNTIME. Test replay/simulasi tidak boleh dilabeli sebagai observasi produksi.

## Dasar register

Rencana terakhir pengguna: sumber target enam paket, dependensi, batas D0/D1, dan stop condition.

Laporan checkpoint dalam percakapan, termasuk laporan pemeriksaan Git oleh asisten: sumber DECLARED bagi register ini untuk candidate/integration tree, perubahan checkout, dan hasil campaign historis; belum diverifikasi ulang pada sesi revisi dokumentasi.

project_sources/14-road-map.txt, §4 dan §7: dua OrderCheck historis, batas D0, serta perbedaan D0/D1. Keadaan Git/PR dalam dokumen bersifat historis.

project_sources/04-RANCANGAN_EA_DUMB_WOLF15_RAILWAY.md, §9 dan §16: idempotensi, hasil ambigu, reporting dan reconciliation; merupakan kontrak/desain, bukan hasil pengujian artefak final.

project_sources/11-WOLF15_STRATEGY_5SCR_CANONICAL_SSOT_V2-1-.md, metadata dan §18: status dokumen serta gate promosi v2.

project_sources/13-WOLF15_STRATEGY_5SCR_CANONICAL_SSOT_V3_1_CANDIDATE_REPO_READY-1-.md, §2.6, §7A.6, §24–25: pemisahan authority, re-evaluasi advisory, promosi, dan containment migrasi.

Status sesi rekonsiliasi 1: DOCUMENTATION=UPDATED; SESSION_SOURCE_RECONCILIATION=EXECUTED_READ_ONLY; SESSION_RECEIPT_REVIEW=EXECUTED_READ_ONLY; SESSION_IMPLEMENTATION=NOT_EXECUTED; SESSION_APPLICATION_TESTS=NOT_EXECUTED; SESSION_DEPLOYMENT=NOT_EXECUTED; SESSION_RUNTIME_INSPECTION=NOT_EXECUTED; SESSION_BROKER_TRANSACTION=NOT_EXECUTED. code_config_mutation=NONE; runtime_mutation=NONE; documentation_mutation=register dan receipt rekonsiliasi. Verdict alur source PARTIALLY_VERIFIED; rencana sistem PARTIAL_PLAN. Rekonsiliasi episode runtime masih belum selesai.

Sumber edisi awal: lampiran pengguna `ddb9105e-fe6d-4282-ae7a-b7a744ae3904/pasted-text-1.txt` (SHA-256: `8a9f1e9d3d8db0df3ecadf36a6c07542b8ed6e3fd12c5be2572c48edeffc6be0`). Referensi `project_sources/...` di atas dipertahankan dari lampiran; isi sumber tersebut tidak diperiksa ulang pada revisi ini.
