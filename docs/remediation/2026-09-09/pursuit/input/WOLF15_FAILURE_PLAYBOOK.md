# WOLF15 — Proyeksi masalah dan playbook pemulihan

48 kasus dipetakan ke canonical actions. `FORECAST` berarti proyeksi mekanisme kegagalan, bukan temuan runtime baru. Label `REPORTED_*` berasal dari checkpoint pengguna; Desktop tetap memverifikasi status actual. `CORRECTED_INTERPRETATION` mempertahankan koreksi diagnosis sebelumnya.

Gunakan key blocker stabil. Jalankan diagnosis berbatas sekali untuk failure signature baru; ulang hanya jika source, input, capability atau scope yang relevan berubah. Ikuti retry policy runtime repo. Lanjutkan action independen saat satu gate terblokir. Nama/path secret boleh direferensikan secara privat; secret tidak dimasukkan ke log/commit.

Pola escalation: **temuan → penyebab terikat → perbaikan lokal → tes affected scope → recovery proof → closure**. Bila keputusan manusia diperlukan, siapkan target/diff/options/impact/recovery dahulu; gabungkan input pada cohort runner, policy, atau operasi yang sedang siap.

## Source dan koordinasi

### F01 — PR/main berubah sejak checkpoint

**Aksi:** A00, C01, N03. **Status asal:** `FORECAST`.

- **Diagnosis:** Baca full OID, diff executable/config/schema dan receipt; gunakan worktree aktual yang terikat. Jangan reset ke SHA chat.
- **Respons:** Import bukti yang masih cocok; ulang hanya affected gates dan required suite pada combined candidate.
- **Kapan mencoba lagi / bukti keluar:** Candidate baru selesai direkonsiliasi; konflik dan source ownership jelas.

### F02 — Checkout bersama mempunyai perubahan di luar task

**Aksi:** A00, N03. **Status asal:** `REPORTED_CONSTRAINT`.

- **Diagnosis:** Inventaris hash dan pemilik perubahan; gunakan worktree terisolasi, hindari reset/clean/stash menyeluruh.
- **Respons:** Lanjut slice pada checkout terisolasi. Jangan meminta penghapusan pekerjaan lama sebagai jalan pintas.
- **Kapan mencoba lagi / bukti keluar:** Base/owned changes sudah terikat tanpa kehilangan perubahan.

### F03 — Salinan assessment lama tidak tersedia/berbeda bytes

**Aksi:** S01. **Status asal:** `REPORTED_GAP`.

- **Diagnosis:** Cari repo archive, sumber lampiran dan manifest existing; bandingkan encoding/bytes tanpa mengklaim semantic parity.
- **Respons:** Gunakan selected repo v3.1. Isolasi hanya clause normatif yang memang ambigu; jangan re-audit semua lampiran terus-menerus.
- **Kapan mencoba lagi / bukti keluar:** Sumber ditemukan atau keputusan clause yang konkret tersedia; jika tidak, gap parity tetap tercatat.

### F04 — Push branch memicu automation deployment di luar scope

**Aksi:** C01, C05. **Status asal:** `FORECAST`.

- **Diagnosis:** Baca trigger workflow dan environment mapping sebelum push. Buat commit lokal dan diff yang reviewable.
- **Respons:** Gunakan branch/path publikasi yang sudah sah bila tersedia. Jangan mengubah ruleset/automation tanpa scope yang berlaku.
- **Kapan mencoba lagi / bukti keluar:** Scope publikasi tidak lagi mempunyai side effect yang belum diotorisasi.

### F05 — Agent quota atau review independen tidak tersedia

**Aksi:** S04, N03. **Status asal:** `REPORTED_CONSTRAINT`.

- **Diagnosis:** Catat status agent; jangan spawn/rerun berulang pada kegagalan sama. Root mengerjakan source serial dan mengintegrasikan satu penulis per file.
- **Respons:** Self-review diberi label tepat. Mandatory independent review tetap pending; local implementation lain berlanjut.
- **Kapan mencoba lagi / bukti keluar:** Reviewer tersedia atau governance memberi jalur review lain yang sah.

### F06 — Bukti stale, file ganda atau jumlah tes membesar semu

**Aksi:** C01, N03, O03. **Status asal:** `FORECAST`.

- **Diagnosis:** Bandingkan source tree, config, schema, fixture/test identities dan cohort. Pisahkan source commit dari publication HEAD.
- **Respons:** Pertahankan valid evidence; tandai affected receipts stale. Jangan menjumlahkan hasil suite overlap sebagai coverage unik.
- **Kapan mencoba lagi / bukti keluar:** Receipt baru mempunyai exact scope/identity dan denominator yang dapat ditelusuri.

## Runner dan CI

### F07 — Linux disposable belum mempunyai host/config yang sah

**Aksi:** C04. **Status asal:** `REPORTED_GAP`.

- **Diagnosis:** Cari registry/config existing dan capability read-only; siapkan bootstrap/test bundle dan target proposal.
- **Respons:** Jangan memakai VPS lama/produksi. Masukkan satu blocker runner, kemudian lanjut K03/K04/K06/K07/K08/K09/K11/K12 yang siap.
- **Kapan mencoba lagi / bukti keluar:** Alias/config host, isolasi database dan scope penggunaannya benar-benar tersedia.

### F08 — Committed memory Windows tinggi; Docker/Linux tidak aktif

**Aksi:** C04. **Status asal:** `REPORTED_CONSTRAINT`.

- **Diagnosis:** Read-only preflight pada host actual, simpan checkpoint sebelum workload berat. Jangan menganggap threshold historis cocok untuk host lain.
- **Respons:** Hindari heavy run pada resource tak memadai; jangan menutup aplikasi, reboot, mengubah pagefile atau mengaktifkan VM existing tanpa scope.
- **Kapan mencoba lagi / bukti keluar:** Operator/runner menyediakan capacity yang terukur dan scope uji yang sah.

### F09 — GitHub job tidak mulai karena account-lock billing annotation

**Aksi:** C03, C05. **Status asal:** `REPORTED_PLATFORM_CAUSE`.

- **Diagnosis:** Baca annotation run pada exact HEAD bila diperlukan untuk perubahan status; catat platform-reported cause.
- **Respons:** Billing dikecualikan. Jangan rerun keadaan sama, menonaktifkan checks, atau menyebut local test sebagai remote PASS.
- **Kapan mencoba lagi / bukti keluar:** Platform telah pulih menurut bukti baru; jalankan required checks yang sesuai source.

### F10 — Daftar runner repository kosong

**Aksi:** C04, C05. **Status asal:** `CORRECTED_INTERPRETATION`.

- **Diagnosis:** Endpoint itu hanya inventaris self-hosted. Periksa runs-on/workflow dan annotation untuk diagnosis aktual.
- **Respons:** Jangan menyimpulkan GitHub-hosted Linux tidak tersedia dari daftar kosong.
- **Kapan mencoba lagi / bukti keluar:** Runner/workflow/annotation baru menunjukkan capability yang dapat digunakan.

### F11 — API Pydantic pin berbenturan dengan MCP dependency

**Aksi:** C03, N04. **Status asal:** `REPORTED_DEPENDENCY_CONFLICT`.

- **Diagnosis:** Gunakan environment terpisah sesuai constraints revision aktual; ukur pip check pada masing-masing environment.
- **Respons:** Pertahankan API pin dan fixture MCP lane; jangan upgrade dependency global agar satu suite lolos.
- **Kapan mencoba lagi / bukti keluar:** Setiap environment memenuhi dependency native scope dan required tests yang relevan.

### F12 — FakeMT5, compile atau Linux backend dianggap bukti terminal

**Aksi:** E05, N04. **Status asal:** `REPORTED_EVIDENCE_LIMIT`.

- **Diagnosis:** Pisahkan pure fixture, MetaEditor compile, native library capability, terminal HTTP dan actual broker receipts.
- **Respons:** Selesaikan source/golden vectors secara lokal. Kekurangan terminal memblokir gate terminal, bukan seluruh backend.
- **Kapan mencoba lagi / bukti keluar:** Exact binary dan terminal run tersedia pada environment yang terikat.

## Database dan migrasi

### F13 — 45 existing dan tujuh producer/relay PG skipped

**Aksi:** C03, E04, N04. **Status asal:** `REPORTED_EVIDENCE_LIMIT`.

- **Diagnosis:** Baca JUnit/inventory dan acceptance runner receipt; pytest exit 0 tidak berarti gate PASS.
- **Respons:** Jangan replay negative control terus. Siapkan actual database run, tambah inventory consumer secara reviewed.
- **Kapan mencoba lagi / bukti keluar:** Migrasi dan required PostgreSQL inventories benar-benar dijalankan dengan nol required skip.

### F14 — Test selection kosong atau identitas parameter berubah

**Aksi:** C03, S06. **Status asal:** `FORECAST`.

- **Diagnosis:** Bandingkan collection/JUnit dengan manifest revision yang sama; cari path/filter/import error sebelum mengubah expected IDs.
- **Respons:** Perbaiki command/fixture yang salah; perubahan scope acceptance memerlukan alasan kontrak. Jangan sekadar menurunkan jumlah expected tests.
- **Kapan mencoba lagi / bukti keluar:** Identitas test cocok dan scope wajib benar-benar executed.

### F15 — DSN mengarah ke database shared/produksi

**Aksi:** C04, D01, D02, J02. **Status asal:** `FORECAST`.

- **Diagnosis:** Gunakan target non-secret identity, ownership dan isolation proof sebelum init/reset/migrate; nama database saja tidak membuktikan isolasi.
- **Respons:** Hentikan mutasi target itu. Lanjut menyiapkan bundle dan gunakan disposable yang benar-benar milik test.
- **Kapan mencoba lagi / bukti keluar:** Target identity/schema/authorization terikat dan verified isolated.

### F16 — Dua Alembic head atau actual applied head drift

**Aksi:** N03, D01, D02, J02. **Status asal:** `FORECAST`.

- **Diagnosis:** Baca graph dan actual applied history. Buat additive convergence berdasarkan history; uji fresh dan supported upgrade.
- **Respons:** Jangan rewrite applied revision atau memilih satu head dengan menghapus yang lain. Offline SQL tetap persiapan.
- **Kapan mencoba lagi / bukti keluar:** Migration plan baru diuji lalu actual application menghasilkan receipt sesuai scope.

### F17 — Nonce, source/config atau DB metadata receipt tidak cocok

**Aksi:** C03, E04, N04. **Status asal:** `FORECAST`.

- **Diagnosis:** Simpan failure receipt; tentukan field stabil vs planned schema/data change. Verifikasi command dan environment yang sungguh berjalan.
- **Respons:** Perbaiki penyebab run/capture; jangan melonggarkan guard agar receipt stale diterima.
- **Kapan mencoba lagi / bukti keluar:** Run baru memakai identity yang benar dan metadata invariant konsisten.

### F18 — Deadlock, timeout atau unique violation pada concurrency

**Aksi:** S03, S04, R02. **Status asal:** `FORECAST`.

- **Diagnosis:** Reproduce bound transactions; periksa lock order, scope, isolation dan retries sesuai policy. Unique conflict harus dibedakan committed duplicate vs changed payload.
- **Respons:** Perbaiki transaksi/locking; jangan menahan network I/O di lock atau menjadikan semua symbol satu global mutex tanpa kebutuhan.
- **Kapan mencoba lagi / bukti keluar:** Race/rollback/retry tests membuktikan invariants dengan transaksi PostgreSQL aktual.

## Delivery dan ownership

### F19 — Same ID digunakan untuk payload berbeda

**Aksi:** S03, S04. **Status asal:** `FORECAST`.

- **Diagnosis:** Bandingkan immutable persisted bytes/digest, producer identity dan source evaluation.
- **Respons:** Quarantine dengan reason; jangan overwrite payload, ACK success atau advance cursor sebagai data sah.
- **Kapan mencoba lagi / bukti keluar:** Sumber konflik diperbaiki dan recovery versioned mempertahankan bukti original.

### F20 — Predecessor hilang atau sequence gap permanen

**Aksi:** S03, S04. **Status asal:** `FORECAST`.

- **Diagnosis:** Periksa committed outbox/counter/evaluation dan predecessor lineage; bedakan pending delivery dari nomor yang tidak pernah committed.
- **Respons:** Jangan skip predecessor. Pertahankan incident/wait per activity; unrelated partition boleh lanjut bila kontrak mengizinkan.
- **Kapan mencoba lagi / bukti keluar:** Predecessor terkirim atau controlled reconciliation yang sah menyelesaikan gap.

### F21 — Consumer commit sukses tetapi ACK hilang/lease relay expired

**Aksi:** S04. **Status asal:** `FORECAST`.

- **Diagnosis:** Reproduce commit lalu lost ACK; relay lease baru mengirim payload yang sama.
- **Respons:** Inbox mengenali committed duplicate, mengembalikan outcome/ACK yang sama tanpa extra effect; successor maju hanya setelah ACK valid.
- **Kapan mencoba lagi / bukti keluar:** Crash/retry test membuktikan satu lifecycle/emission effect dan progress berikutnya.

### F22 — Legacy writer melewati lifecycle owner fence

**Aksi:** C02, S04. **Status asal:** `REPORTED_IMPLEMENTATION_GAP`.

- **Diagnosis:** Inventaris seluruh write path ke state yang sama; guard ownership/epoch di transaksi setiap mutasi.
- **Respons:** Relay lease fence saja tidak cukup. Satukan fence semantics termasuk legacy writer dan lakukan takeover test.
- **Kapan mencoba lagi / bukti keluar:** Stale owner/legacy writes ditolak; owner baru menulis dengan history konsisten.

### F23 — Consumer destination atau transport authentication belum bound

**Aksi:** S04. **Status asal:** `REPORTED_IMPLEMENTATION_GAP`.

- **Diagnosis:** Implement principal/destination/purpose/payload validation dan fixtures pada explicit interface; secret berupa reference.
- **Respons:** Jangan memperlakukan 2xx delivery sebagai commit proof, atau mengaktifkan endpoint anonymous sementara.
- **Kapan mencoba lagi / bukti keluar:** Consumer terautentikasi terikat dan ACK sesudah atomic commit teruji.

### F24 — Notifikasi eksternal sukses/gagal di tengah DB transaction

**Aksi:** S04. **Status asal:** `FORECAST`.

- **Diagnosis:** Bedakan durable emission intent dengan actual external notification; external send setelah commit melalui worker/outbox.
- **Respons:** Gunakan emission ID stabil dan retry policy. Jangan mengklaim atomic DB+HTTP atau mengirim pesan eksternal tanpa scope.
- **Kapan mencoba lagi / bukti keluar:** Crash/retry mempertahankan intent dan sink dedup sesuai kontrak.

## Evidence dan strategi

### F25 — Gap/backfill atau forming candle dianggap fresh/closed

**Aksi:** S02, S03. **Status asal:** `FORECAST`.

- **Diagnosis:** Audit source time, receive time, availability, closed flag, selection policy, coverage dan watermarks.
- **Respons:** Preserve gap/suspension/revision history; jangan memberi authority retroaktif dari backfill.
- **Kapan mencoba lagi / bukti keluar:** Live/replay as-of, retention dan recovery menghasilkan data/reason yang konsisten.

### F26 — Direction kembali membelah pair activity; facet dihitung ganda

**Aksi:** S03. **Status asal:** `FORECAST`.

- **Diagnosis:** Jalankan caller BUY@0→SELL@150→BUY@300 dan facet/duplicate fixtures pada explicit v3.1 context.
- **Respons:** Perbaiki logical observation reducer; pisahkan kualitas direction dari continuity.
- **Kapan mencoba lagi / bukti keluar:** Satu activity 300 detik, dedup stabil, dan PostgreSQL restart mempertahankan identity.

### F27 — V1 adapter aktif atau advisory memperoleh authority order

**Aksi:** S01, S04. **Status asal:** `FORECAST`.

- **Diagnosis:** Telusuri actual producer/caller/consumer/policy; test invalid/expired/conflicting policy termasuk equality valid_until.
- **Respons:** Explicit version adapter; advisory analysis SHADOW_ONLY, tanpa risk reservation/command. Raw upgrade re-evaluates lifecycle yang sama.
- **Kapan mencoba lagi / bukti keluar:** V3.1 binding lengkap dan zero-sink negative scenarios serta upgrade positif terbukti.

### F28 — Job analisis lama selesai setelah revision/generation baru

**Aksi:** S04. **Status asal:** `FORECAST`.

- **Diagnosis:** Bind material revision dan owner generation pada publish; uji slow worker/cancel/restart.
- **Respons:** Reject stale late result; single-flight/coalescing hanya untuk work yang tidak menghilangkan material evidence.
- **Kapan mencoba lagi / bukti keluar:** Latest revision tetap authoritative; stale completion tidak overwrite atau emit new authority.

### F29 — Target lebih jauh dipilih untuk memaksakan RR

**Aksi:** S05. **Status asal:** `FORECAST`.

- **Diagnosis:** Periksa solver normatif v3.1 dan target universe D1/H4/H1/legal structural sources serta consumed/fresh states.
- **Respons:** Pilih nearest legal target; empty feasible interval menghasilkan WAIT/NO_TRADE sesuai kontrak.
- **Kapan mencoba lagi / bukti keluar:** BUY/SELL mirror, nearest-target dan interval boundary fixtures lulus.

### F30 — Pip/tick FX, JPY atau metal salah; cost masih gross

**Aksi:** S05, R02. **Status asal:** `FORECAST`.

- **Diagnosis:** Bind broker specs/currency/step dan net cost model; cek representability setelah rounding.
- **Respons:** Jangan clamp volume ke minimum yang melanggar cash risk atau mengganti SL/TP agar lolos.
- **Kapan mencoba lagi / bukti keluar:** Projected loss/net RR sesuai oracle bound untuk supported symbols; unsupported ditolak.

## Risk dan execution

### F31 — Profile risiko, account/server atau policy wajib belum dipilih

**Aksi:** R01, E06. **Status asal:** `REPORTED_BINDING_GAP`.

- **Diagnosis:** Cari existing binding dan keputusan pengguna; pisahkan historical 5+5 dan DEMO3.5+1.5.
- **Respons:** Generic TEST_ONLY adapters boleh maju; kumpulkan pilihan nyata dengan impact dan minta satu cohort decision bila masih diperlukan.
- **Kapan mencoba lagi / bukti keluar:** Satu active profile account/mode/currency/version memiliki sumber authority yang sah.

### F32 — TradePlan ID atau lineage antar komponen tidak kompatibel

**Aksi:** R02, R03, N01. **Status asal:** `FORECAST`.

- **Diagnosis:** Bandingkan actual candidate/proof/reservation/FinalSignal IDs dan validators; test positive current lineage dan old/shadow negative.
- **Respons:** Buat adapter/schema eksplisit. Jangan regex/string replace untuk memaksa lineage atau downgrade unknown version.
- **Kapan mencoba lagi / bukti keluar:** Current positive pipeline lolos; malformed/stale/advisory/projection tetap ditolak.

### F33 — Dua worker oversubscribe atau risk release terlalu dini

**Aksi:** R02, N07. **Status asal:** `FORECAST`.

- **Diagnosis:** Lock capacity dan campaign/role pada atomic transaction; model filled/pending/reserved/unknown tanpa double count.
- **Respons:** Cancel queue/expiry transport tidak membuktikan broker zero effect. Unknown capacity tetap dihitung hingga independent reconciliation.
- **Kapan mencoba lagi / bukti keluar:** Concurrent/partial-fill/cancel-race/restart oracles menjaga caps dan release hanya sesuai proof.

### F34 — Signature/decimal/time serialization berbeda Python-MQL5

**Aksi:** N01, N02, E05. **Status asal:** `FORECAST`.

- **Diagnosis:** Golden vectors byte-level pada field order, UTF-8, canonical numeric/time representations dan keyID.
- **Respons:** Pertahankan invalid signature rejection; jangan menonaktifkan validasi atau mengubah payload sesudah sign.
- **Kapan mencoba lagi / bukti keluar:** Exact producer/EA binary menerima valid vectors dan menolak tampered vectors.

### F35 — EA binary lama atau terminal HTTP rehearsal belum bekerja

**Aksi:** E05, E08, N02. **Status asal:** `FORECAST`.

- **Diagnosis:** Bind output binary/include/source/MetaEditor digest; inspect WebRequest target/allowlist/auth dan actual terminal.
- **Respons:** Compile bukan HTTP/broker proof. Blocking I/O diikuti revalidation fields mekanis yang mutable; terminal handler cepat sesuai desain.
- **Kapan mencoba lagi / bukti keluar:** Final binary menjalankan expected poll/claim/report/restart dan SHADOW zero-submit.

### F36 — OrderSend diterima tetapi outcome ambigu/partial/out-of-order

**Aksi:** E02, E09, N02, N08. **Status asal:** `FORECAST`.

- **Diagnosis:** Gunakan submit marker, retcodes dan independent orders/deals/positions/history dengan query completeness.
- **Respons:** Jangan automatic resend, close-all atau delete journal. Satu logical request bisa punya banyak event/deal.
- **Kapan mencoba lagi / bukti keluar:** Outcome known, exposure/protection direkonsiliasi; ambiguity tetap blocker jika proof belum lengkap.

## Release dan natural DEMO

### F37 — Railway staged changes atau image/config/schema tidak sama

**Aksi:** D01, E07, J02, J03. **Status asal:** `REPORTED_RELEASE_RISK`.

- **Diagnosis:** Read exact serviceUUID, source/image/config/schema; pisahkan shared staged diff dari scoped proposed repair.
- **Respons:** Siapkan release packet konkret; jangan apply-all atau menyimpulkan parity dari deployment SUCCESS.
- **Kapan mencoba lagi / bukti keluar:** Exact intended diff diterapkan dalam scope dan running parity/owner dibuktikan.

### F38 — Reader tidak independen atau empty query tidak lengkap

**Aksi:** E02, E06, E09. **Status asal:** `REPORTED_BINDING_GAP`.

- **Diagnosis:** Bind principal/channel/account/history coverage/challenge/freshness. Nilai boundary independensi berdasarkan implementation nyata.
- **Respons:** Executor bool/heartbeat/positions=[] dari error tidak menjadi proof flat; implement verifier dan lanjut source lain.
- **Kapan mencoba lagi / bukti keluar:** Attestation fresh/comprehensive disetujui backend yang sesuai purpose, tanpa credential leak.

### F39 — Window kedaluwarsa atau account/mode berubah

**Aksi:** E09, N06, N08. **Status asal:** `FORECAST`.

- **Diagnosis:** Verifikasi binding saat arm/claim/pre-submit; cocokkan exact DEMO server/account/session/caps.
- **Respons:** Stop new submit sesuai contract; jangan memperpanjang canary, mengganti akun atau menaikkan cap sendiri.
- **Kapan mencoba lagi / bukti keluar:** Binding operasi baru/masih berlaku memenuhi scoped authority dan fresh preflight.

### F40 — Tidak ada natural setup/child eligible dalam window

**Aksi:** N06, N08. **Status asal:** `FORECAST`.

- **Diagnosis:** Simpan coverage, reasons, data quality dan NOT_OBSERVED; bedakan strategy WAIT sah dari wiring defect.
- **Respons:** Jangan synthetic order untuk menutup natural milestone, mengganti rule atau extend window otomatis. Lanjut offline analysis/review yang siap.
- **Kapan mencoba lagi / bukti keluar:** Natural episode memenuhi policy pada observation window yang sah; proof positif benar-benar tersedia.

### F41 — Child close membuka slot lagi atau floating profit dianggap released risk

**Aksi:** N07, N08. **Status asal:** `FORECAST`.

- **Diagnosis:** Bind lifetime role policy dan locked campaign R; evaluasi parent OPEN/thesis/target/new structure/fresh entry.
- **Respons:** Slot lifetime tidak dihapus sesudah close. Released risk perlu proof sesuai policy; jangan menciptakan BE/trailing atau memperbesar budget.
- **Kapan mencoba lagi / bukti keluar:** Legal child dan forbidden reopen/risk-release cases terbukti dengan consistent family ledger.

### F42 — Parent-only evidence diwariskan ke binary child

**Aksi:** J01, J02, J03, N08. **Status asal:** `FORECAST`.

- **Diagnosis:** Freeze exact child source/schema/EA, rerun affected release/compile/PG gates dan final SHADOW pada artifact child.
- **Respons:** Jangan enable child lewat flag yang membuka jalur legacy tak terklasifikasi.
- **Kapan mencoba lagi / bukti keluar:** Child release parity dan positive family/next-campaign compounding terikat pada artifact tersebut.

## Operasi, evaluasi dan penutupan

### F43 — Readiness hijau tetapi mandatory task mati/backlog hilang

**Aksi:** C06, O01. **Status asal:** `FORECAST`.

- **Diagnosis:** Uji actual served probe, supervisor task, late crash dan queue identity; gunakan mandatory-vs-disabled role inventory.
- **Respons:** Required failure menghasilkan readiness unavailable; jangan membuang job untuk membuat queue tampak pulih.
- **Kapan mencoba lagi / bukti keluar:** Fault/recovery receipts membuktikan outcome, completeness dan measured recovery terhadap policy.

### F44 — Drill/kill switch memutus proteksi atau reconciliation

**Aksi:** O01. **Status asal:** `FORECAST`.

- **Diagnosis:** Susun bounded drill scope terlebih dahulu, pisahkan new risk dari existing obligations.
- **Respons:** Stop new risk dalam authority yang berlaku sambil mempertahankan protection/reader. Jangan mematikan seluruh service/VPS.
- **Kapan mencoba lagi / bukti keluar:** Recovery/exposure before-after known dan RTO/RPO yang ditetapkan dinilai dari run aktual.

### F45 — Leakage, duplikat log atau parent-child dianggap sampel independen

**Aksi:** O02. **Status asal:** `FORECAST`.

- **Diagnosis:** Bind availability/as-of, dedup inputs, freeze IS/OOS/walk-forward protocol sebelum melihat hasil dan gunakan campaign cohort.
- **Respons:** Laporkan cost/fill assumptions dan uncertainty; WAIT bukan win, data ganda bukan new sample.
- **Kapan mencoba lagi / bukti keluar:** Reproducible clean evaluation dengan cohort/denominator yang memadai dan jelas.

### F46 — SLO, soak window, sample adequacy atau threshold ekonomi belum bound

**Aksi:** O01, O02, O03. **Status asal:** `REPORTED_CRITERIA_GAP`.

- **Diagnosis:** Cari versioned policy/requirement dan buat candidate evaluation protocol dengan sumber/rationale/impact.
- **Respons:** Jangan mengisi angka arbitrer atau tuning setelah hasil. Kerjakan instrumentation/data acquisition yang sah sambil menunggu keputusan minimum.
- **Kapan mencoba lagi / bukti keluar:** Protocol dan thresholds relevan ditetapkan sebelum evaluation, lalu actual evidence cukup.

### F47 — Evaluasi lengkap menunjukkan performa tidak memenuhi target

**Aksi:** O02, O03. **Status asal:** `FORECAST`.

- **Diagnosis:** Pertahankan negative results dan nilai seluruh criteria berdasarkan protocol yang dibekukan.
- **Respons:** P6 review dapat complete dengan verdict HOLD jika evidence/dependencies lengkap. Defect wajib pada P1–P5 tetap membuka gate terkait; jangan menutupnya melalui dossier.
- **Kapan mencoba lagi / bukti keluar:** Reviewer dapat menelusuri complete evidence dan alasan verdict; REAL tetap tidak aktif.

### F48 — Semua frontier tertutup external blocker dan pertanyaan berulang

**Aksi:** O03. **Status asal:** `FORECAST`.

- **Diagnosis:** Baca blocker/question ledger: lokasi yang sudah dicari, jawaban yang berlaku dan recheck trigger.
- **Respons:** Selesaikan independent source work yang sah; keluarkan satu intervention packet konkret dan checkpoint. Jangan menyebut BLOCKED sebagai DONE.
- **Kapan mencoba lagi / bukti keluar:** Ada source/input/capability/authority baru yang membuka dependency; resume dari receipt terakhir.

## Dasar teknis dan cara membaca hasil

Perbedaan ACK/submit/fill mengikuti [OrderSend](https://www.mql5.com/en/docs/trading/ordersend) dan [OnTradeTransaction](https://www.mql5.com/en/docs/event_handlers/ontradetransaction). Sifat sequence/locking merujuk [PostgreSQL sequence](https://www.postgresql.org/docs/17/functions-sequence.html) dan [explicit locks](https://www.postgresql.org/docs/17/explicit-locking.html). Arti daftar self-hosted runner mengikuti [GitHub REST](https://docs.github.com/en/rest/actions/self-hosted-runners#list-self-hosted-runners-for-a-repository). Solusi di atas adalah rancangan yang harus diturunkan ke source aktual, bukan klaim implementasi sudah selesai.

Tidak ada timeout, risk percentage, minimum sample count, SLO atau kapasitas host baru yang dianggap aktif dari dokumen ini. Input tersebut harus bersumber dari requirement/policy terikat. Validasi paket hanya memeriksa struktur dan integritas rencana.
