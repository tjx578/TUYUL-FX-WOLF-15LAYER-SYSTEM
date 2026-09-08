# WOLF15 — hasil rekonsiliasi dan perbaikan 41 aksi

**Status program: INCOMPLETE / HOLD. Milestone engineering selesai: 0 dari 6.**
Akuisisi dan rekonsiliasi source A00 selesai dalam scope assessment. Sebagian
C01/C02/C03/C06 sudah diperbaiki dan diuji lokal. Ini tidak menutup seluruh
aksi tersebut, natural DEMO, child/compounding, atau kesiapan REAL.

Permintaan pengguna pada 9 September 2026 WITA mencakup analisis seluruh input,
pelaksanaan engineering, verifikasi kondisi repo/GitHub/Railway, dan commit yang
layak. GitHub billing dikecualikan. Instruksi `PLANNING_ONLY` pada lampiran
adalah scope pekerjaan historis, bukan pembatalan permintaan engineering baru.
Pengguna kemudian mengonfirmasi bahwa paket binding DEMO yang sah belum
terverifikasi; register hanya berisi tugas penyiapannya. Tidak ada account,
risk profile, instrumen, window, atau approval order yang diisi dengan asumsi.

## Follow-up S01/S03 dan dependency API

[Laporan lanjutan](followup-s01-s03/README.md) mengikat perbaikan activity v3.1, pemetaan S01, dan 334 tes yang lulus pada environment API dengan Pydantic 2.9.2. Temuan S03 `FAIL` historis di bawah tetap merupakan bukti checkpoint lama; status pada follow-up tersebut adalah `PATCHED_TESTED_LOCAL_PARTIAL`. Status terbaru tersedia dalam [follow-up runtime S03](followup-s03-runtime/README.md). S01 dan semua milestone tetap belum DONE.

## Mulai membaca

- [Register status aktual seluruh 41 aksi](CURRENT_DONE_Register_41_Actions.csv)
  mempertahankan acceptance, dependency, owner, bukti dan blocker setiap aksi.
- [Status GOAP aktual](CURRENT_GOAP_Status.json) dapat diproses mesin. `DONE`
  A00 hanya berarti source acquisition; semua action engineering belum ditutup.
- [Audit dokumen lengkap](evidence/contract-audit.md) dan
  [ledger kontrak](evidence/contract-audit.json) mencakup 44 temuan domain
  historis, 83 referensi debt, H01–H04, dan 172 pemeriksaan receipt source.
- [Audit strategi/risk](evidence/strategy-audit.md),
  [35 acceptance v3.1](evidence/strategy-acceptance-matrix.json), serta
  [diagnostik aktual](evidence/strategy-diagnostic-output.json) menjelaskan
  perbedaan antara component tests yang lolos dan DoD yang belum dipenuhi.
- [Audit release/GitHub/Railway](evidence/release-audit.md),
  [20 service dispositions](service-disposition.json) dan
  [usulan koreksi Railway](railway-proposed-repair.json) memisahkan metadata,
  config, runtime, dan perubahan yang belum dilaksanakan.
- [Validasi candidate](validation.json) mengikat perintah, environment,
  source hashes dan hasil test; [JUnit](evidence/candidate-validation.xml)
  memuat kasus individual. Bukti historis pada laporan domain tetap terikat
  subjeknya sendiri dan tidak otomatis menjadi kelulusan candidate ini.

## Identitas dan integritas

Checkout asli berada di `ec31631864204ca183079966d7834338f7a986cd` dengan 46
perubahan lokal. Semuanya dipertahankan; disposition per path dan checksum
terdapat di [dirty-checkout-disposition.json](dirty-checkout-disposition.json).
Perubahan lama yang berbenturan dengan main terbaru tidak digabung otomatis.

Remote main berubah selama intake dari `1837f4b7cbded620c35933af980e9abd166de39e`
ke `773150952311db3dbf5188f36536b7837d8ec296` melalui PR #422. Worktree
`codex/master-remediation-20260909` dibuat dari SHA kedua tersebut. Owner-login
lama tidak di-cherry-pick ulang di atas perubahan dashboard #422.

Seluruh delapan input asli ada di `inputs/`, termasuk enam file Downloads dan
dua pasted notes dengan nama berbeda. Bytes diikat oleh
[input-manifest.json](input-manifest.json); attributes lokal mencegah konversi
line ending pada input. ZIP tetap arsip dokumenter; tidak ada script lampiran
yang dieksekusi sebagai perintah.

Temuan integritas penting:

1. CSV Downloads rusak: lebar baris 13–16 kolom, semicolon tambahan dan field
   acceptance/status bergeser. Hash asli `628b48a3d5565619028ce59d980af6d2e8a409460443d211612c2445f01973ab`.
   Original dipertahankan tanpa edit. Gunakan
   [CSV canonical dari ZIP](inputs/WOLF15_Master_Backlog_2026-09-08.canonical.csv),
   hash `9672d5bf6e07b3d6db5f6d6cd92f903ce53fec12369df744c88aaab7ce1c8490`,
   untuk parsing backlog.
2. Semua 48 anggota ZIP dapat dibaca dan CRC cocok; 47/47 file yang dideklarasikan
   manifest cocok hash/ukuran. Manifest sendiri adalah entry ke-48. Integritas
   bytes tidak membuktikan isi assessment benar di runtime sekarang.
3. ID seluruh 41 aksi konsisten pada GOAP, canonical CSV, dan DoD; graph dependency
   acyclic. Koreksi acceptance S05 dari H4-only ke universe v3.1 memang disengaja.
4. Full SSOT terpilih ditemukan pada docs commit
   `dd27ae87d0207466caad4c3e098224112ac0eaf7`, path
   `docs/strategy/WOLF15_STRATEGY_5SCR_CANONICAL_SSOT_V3_1_CANDIDATE.md`.
   [Exact Git bytes](source-binding/selected-ssot-v3.1.md) berhash
   `6daea387745ffa305d3cd55b0fee4f0efed79be21e24503c2a1f8a16c6a83902`.
   File lowercase untracked adalah stub Analysis Admission, bukan full SSOT.
   Salinan historis DoD berhash berbeda dan parity lengkapnya belum terbukti.
   R1/R2 tidak diadopsi.
5. Semua 172 receipt historis cocok immutable Git bytes lokal. Terhadap main
   terbaru: 131 receipt sama, 12 berbeda, 29 path tidak ada. Angka adalah receipt
   entries, bukan jumlah file unik yang direview baris demi baris.

Bounded secret/ZIP scan menemukan nol credential match pada sembilan artifact
utama dan 56 subjek teks. Semua input layak di-commit sebagai dokumentasi.
[Admissibility receipt](evidence/commit-admissibility.json) mencatat aturan dan
batas pemeriksaan; gitleaks/trufflehog tidak tersedia. Ini bukan jaminan nol risiko.

## Perbaikan yang diimplementasikan

| Aksi | Perubahan teruji | Batas kelulusan |
|---|---|---|
| C01 | Deploy memakai exact SHA/current main dan successful CI run yang sesuai repository/workflow/attempt; menolak missing/skipped/failed steps, runner kosong, checkout kotor, rerun, dan source A diuji tetapi B diminta deploy. Empat target existing diikat service UUID; CLI dipin; cancellation dimatikan. | Arbitrary-command canary workflow dan direct provider path belum tercakup; final source/image/config/schema/EA parity dan successful remote CI belum ada. |
| C02 | API lifespan menolak embedded owner sebelum import consumer; embedded thread dihapus. Shell menormalisasi flag, menolak truthy legacy switch; consolidated entrypoint hanya mendelegasikan API. Railway source manifest menunjuk API-only. | Dedicated runtime ownership/fencing, broker-capable executor uniqueness dan deployed config belum dibuktikan. |
| C03 | Dashboard lint gagal secara nyata; dashboard tests menjadi required. AST guard menolak kontrak hilang, class palsu dalam komentar, duplicate/malformed class dan account fields. Migration test sesuai redacting runner dan membuktikan exit nonzero tidak tertelan. | Ini tidak mengintegrasikan seluruh PR #415/#416 atau menggantikan full required CI dan disposable DB tests. |
| C06 | `/readyz` memberikan503 untuk router boot gagal/belum lengkap sebelum mengimpor router rusak; fallback readiness503. Detail exception tidak masuk readiness. Strict router policy benar-benar raise; auth dan healthy-heartbeat path dipertahankan. | Default diagnostic fail-open liveness tetap ada; full mandatory-task supervisor/fatal process/production fault proof belum lengkap. |

Perubahan C02 menggunakan pola source terdahulu `711e926a` secara terbatas,
bukan merge seluruh kandidat lama. Tidak ada strategy permission, reservation,
lot, SL/TP, natural producer, atau EA trading flag yang dinaikkan.

Validasi pada commit fungsional `08e902b3576cc4c76ac73a9504b5b2b285122589`:
**484 passed, zero failure/error/skipped**. Dua UserWarning hanya melaporkan test
berdurasi6.8s dan7.0s; peringatan encoding awal sudah diperbaiki dan tidak berulang.
Pemeriksaan format seluruh repo kemudian menemukan11 file baseline. Commit
format tersendiri mempertahankan AST yang identik pada11/11 file;
[receipt before/after](evidence/format-baseline-receipt.json) mengikat hash dan
perintah. Whole-source Ruff lint dan format sekarang PASS. Empat suite tambahan
memberikan88 PASS. Pengujian MCP awal terhenti karena dependency `mcp` belum
tersedia di Python host. Verifikasi lanjutan dalam venv terisolasi menghasilkan
7 PASS, `pip check` PASS, paket MetaTrader5 tidak tersedia dan nol percobaan
import native. Seluruh kasus memakai FakeMT5. Lihat
[receipt MCP](evidence/mcp-dependency-validation.md).

Metadata MCP2.0.0 mewajibkan Pydantic>=2.12, sementara requirements API mematok
2.9.2. Karena itu satu file test MCP dipindahkan dari job API ke job fixture
terpisah yang tetap wajib pada CI Gate dan source-release gate. Tidak ada test
yang diubah menjadi optional atau soft-fail. Sebanyak55 tes CI/source gate
lulus setelah perubahan ini; review independen tidak menemukan blocker.
Job baru memasang MCP2.0.0 dan psutil7.2.2 tanpa package native MetaTrader5.

Environment host untuk484 tes memakai Pydantic2.10.3, bukan pin API2.9.2;
environment MCP terpisah memakai2.13.5. Hasil lokal tersebut tidak membuktikan
full dependency closure API pada clean Linux CI atau PostgreSQL disposable.
Jumlah tes di atas adalah receipt dari run berbeda, sebagian cakupannya
bertumpang tindih; tidak dijumlahkan sebagai unique acceptance cases.

Untuk menjaga input ber-CRLF/trailing spaces tetap identik, Git memperlakukan
direktori input, source-binding dan receipt sebagai arsip byte-exact tanpa text
diff. File tetap dapat dibaca normal dari tree; whitespace check source code
dan narasi baru tidak dinonaktifkan. Hash manifest tetap diverifikasi ulang.

Pengikatan SHA menangani sifat `workflow_run`: GitHub membedakan source workflow
pemicu dari default branch workflow berikutnya. Rujukan:
[GitHub workflow_run](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_run).

## Milestone yang masih terbuka

| Milestone | Kondisi aktual dan alasan belum DONE |
|---|---|
| P1 — release/ownership/readiness | Ada patch lokal; tidak ada successful exact-source CI, runner khusus terverifikasi, release governance aktif, atau production single-owner/fault receipts. |
| P2 — evidence/strategi | Mixed direction masih memecah aktivitas pair; mature-advisory producer belum tersedia; target contract hanya H4; seluruh15+20 clause belum memiliki denominator cohort terikat. |
| P3 — risk/natural | Risk menerima `5scr-plan:` tetapi candidate aktual `5scr-tradeplan-v2:`. Producer yang ada SHADOW, bukan natural. Profile akun, distinct-candidate DB race, natural command/EA/FinalSignal convergence belum lengkap. |
| P4 — D0 | Account/server/DEMO/reader dan scope belum bound; exact combined artifact/schema/EA belum ada; final SHADOW dan independent broker outcome belum dijalankan. |
| P5 — natural family | Parent alami, child lifetime slot/released-risk, child-specific release, lifecycle dan next-campaign compounding belum dibuktikan. |
| P6 — REAL dossier | Soak/SLO/RTO/RPO dan preregistered OOS/cost/risk cohort belum bound atau diukur. Dossier sementara HOLD tidak menutup REAL_REVIEW_DONE. |

Diagnostik mixed direction memakai synthetic complete ledger dan gap300s yang
ditandai DIAGNOSTIC_ONLY: BUY0/BUY150/BUY300 menghasilkan satu block300s dan satu
grant; BUY0/SELL150/BUY300 menghasilkan tiga block0s dan nol grant. Ini bukti
direction coupling, bukan izin memilih gap300s untuk produksi. Memotong kondisi
direction-change saja akan bertentangan dengan downstream contract yang masih
mewajibkan direction uniform. Perbaikan perlu kontrak activity-versus-hypothesis,
persistence, policy binding dan replay bersama.

MetaEditor64 ditemukan pada tiga instalasi MT5 lokal, tetapi E03 belum mempunyai
exact combined EA closure. Compiler tidak dijalankan terhadap artifact sembarang
agar tidak menghasilkan klaim E05 yang tidak relevan. Akun/broker tidak diakses.

## GitHub dan Railway

Main CI `34268107881` berstatus failure, tetapi enam job mempunyai `runner_id=0`
dan `steps=[]`. Tidak ada bukti bahwa test source dijalankan. Tidak disimpulkan
sebagai enam regresi atau dipastikan penyebab billing. Tidak ada billing action
atau workflow rerun untuk mengakali keterbatasan ini.

Main tidak protected, required checks kosong, ruleset disabled, dan repository
runner inventory kosong. Enam kandidat PR historis masih open; #418 konflik.
Candidate digabung hanya setelah source yang kompatibel serta required checks
dibuktikan; tidak ada mass merge.

Railway: 20 service/config/deployment inventories diperiksa tanpa membaca nilai
secret. Banyak source menunjuk main; autodeploy eksplisit UNKNOWN. Seluruh config
melaporkan shared staged patch `68c2214f-679f-4674-842d-fa052617e986`. Accept/deploy
patch tersebut dapat mengikutkan perubahan yang belum direview. Perubahan staged
itu tidak disentuh.

Observed pressure-outbox startCommand berbentuk Markdown link ke path Windows.
Usulan perbaikannya sudah konkret dalam `railway-proposed-repair.json`, tetapi
effective runtime, exact source/schema/flags dan recovery gate belum terikat.
Metadata SUCCESS dan satu HTTP200 tidak membuktikan useful work atau readiness
semua task. Log orchestrator yang diambil memuat ACCOUNT_STATE_MISSING.

**Main merge/push dan Railway deployment: HOLD.** Feature branch dapat menyimpan
patch dan documentary evidence yang sudah direview. Tidak ada production restart,
migrasi/schema/role mutation, staged-patch acceptance, broker submit, atau aktivasi
REAL. Status publikasi branch/PR dicatat pada laporan akhir task; perubahan
source lokal tidak otomatis menjadi production acceptance.

## Langkah lanjutan dan recovery

Urutan yang dapat ditelusuri: tutup C01/C03/C04/C05/C06 serta policy binding S01;
pisahkan activity admission dari direction pada S03 dan implementasikan dual
admission S04; perluas target universe S05; konvergensikan R02/R03/N01/N02/N03
pada artifact terikat. E02/E06/R01 harus menyediakan binding aktual sebelum D0.
E03/E04/E05 memerlukan satu artifact gabungan, migrations disposable, full gates
dan compile closure sebelum E07/E08/E09. Parent, child dan REAL dossier tetap
mengikuti dependency masing-masing, tanpa mewarisi PASS artifact yang berubah.

Perbaikan source ini terisolasi di branch. Pembatalan patch dilakukan melalui
reviewed revert sebelum rilis; tidak perlu mengubah checkout asli. Jika kelak
broker exposure ada, rollback code tidak membatalkan broker effect: pertahankan
ledger/proteksi, hentikan new risk dan gunakan compatible forward recovery.

Tidak ada memory writeback karena pengguna tidak meminta pembaruan durable
memory secara langsung. Persistence pekerjaan terdapat di artifact repo ini.

Current-main integration: [followup-main-merge/README.md](followup-main-merge/README.md) records conflict resolution against main e3a0d8c8, independent review and 434 passing selected tests. Program remains HOLD; S01/S03 runtime acceptance remains open.

Latest continuation: [S03 durable caller implementation](followup-s03-runtime/README.md), source59f2db54 aligned with main68ad0794. Final local613 cases pass;45 realPostgreSQL cases remain NOT_EXECUTED. Program remains INCOMPLETE/HOLD,0/6 milestones.


Latest bounded follow-up: [runner evidence binding and pressure expiry](followup-runner-binding/README.md), source `94cd6a5d`. Current changed-source regression241 PASS; no new PostgreSQL/Linux acceptance. Runner remains UNBOUND and program INCOMPLETE / HOLD,0/6 milestones. Prior613 and current241 overlap and must not be summed.
