# Instruksi mulai — WOLF15 Goal Pursuit untuk Codex Desktop

Gunakan file ini bersama paket lengkap. Letakkan paket pada folder kerja yang dapat dibaca Codex Desktop. Tempel instruksi di bawah sebagai tugas implementasi; referensi file bersifat relatif terhadap folder paket. File ini tidak meminta perubahan README.

---

Laksanakan goal WOLF15 secara persisten menggunakan `WOLF15_PURSUIT_GOAL.md`, `WOLF15_PURSUIT_PLAN.json`, `WOLF15_ACTION_MAP.md`, dan `WOLF15_FAILURE_PLAYBOOK.md` dalam paket ini. Outcome akhir adalah **NATURAL_DEMO_DONE** sesuai SSOT v3.1 repo, termasuk parent, child yang sah dan compounding campaign berikutnya dengan rekonsiliasi broker independen, kemudian **REAL_REVIEW_DONE** untuk P6. Jangan menyamakan review REAL dengan aktivasi REAL atau menjanjikan hasil profit.

Instruksi ini memberi scope engineering: baca dan telusuri repo, buat worktree terisolasi bila diperlukan, perbaiki source/kontrak/test/migrasi, jalankan pengujian lokal pada resource yang telah terikat dan diizinkan, review diff, serta commit dan push perubahan ke branch PR remediasi yang terikat. Pertahankan PR sebagai Draft selama gate terkait belum terpenuhi. Pastikan branch tersebut tidak memicu deployment yang belum diotorisasi; periksa konfigurasi yang berlaku terlebih dahulu. Jangan force-push atau menimpa perubahan pihak lain. Gunakan otorisasi sesi yang sudah sah, sehingga tidak perlu bertanya ulang untuk pekerjaan dalam scope yang sama.

**Keputusan yang tetap berlaku:** SSOT v3.1 existing repository; monorepo dan Railway project/service existing; EA MT5 mekanis; independent account-risk dan broker reconciliation; README tidak diperbarui. Pertahankan seluruh input asli, 46 perubahan lama bila masih ada, VPS historis dan workload Windows. Scope ini tidak memberi mandat baru untuk billing/provisioning berbayar, menutup proses host, mengubah rulesets, merge main, migrasi database produksi, deploy atau eksekusi broker. Untuk tindakan tersebut, gunakan otorisasi yang memang sudah berlaku beserta binding yang sesuai; bila belum ada, siapkan paket konkret sebelum satu permintaan keputusan.

Mulai dengan **G00**: temukan workspace repo aktual, baca AGENTS/instruksi berlaku, periksa HEAD/main/PR/worktree, SSOT binding, register41 dan evidence existing. Checkpoint chat adalah locator awal: PR #428, branch `codex/s03-runtime-recovery-20260909`, source `5219624a92253b66fe8bc67a1acace99b71e61e7`, publication HEAD `01fd6f9c1d0e34dc896eace92c81083e2b718653`. Periksa ulang jika source sudah bergerak; jangan reset ke checkpoint lama.

Import status/evidence yang masih sah. A00 telah dilaporkan DONE untuk akuisisi asal; jangan mengulang arsip atau menghapus status itu tanpa sebab. Producer outbox, counter row transaksional, relay dan guard receipt sudah dilaporkan tersedia. Cari gap konkret sebelum mengubahnya. Focus berikutnya **K03/S04 consumer transaksional, fencing seluruh writer lifecycle termasuk legacy, autentikasi tujuan consumer, serta ACK setelah commit**. Periksa kebutuhan K01/K02 dahulu dan gunakan hasil existing jika masih valid.

Kerjakan frontier yang executable sampai selesai. Jika runtime terblokir, lanjut K04/K05/K06/K07/K08/K09/K11/K12 yang independen dan sesuai capability. Jangan menyebut action BLOCKED sebagai executable. Kode/fixture lokal tidak menutup acceptance PostgreSQL, MetaEditor, broker atau CI yang belum berjalan. Requirement strategy/risk yang belum terikat tidak diisi default dari contoh; validator/interface dengan profile TEST_ONLY boleh diselesaikan sementara active policy tetap unbound.

Gunakan salinan `WOLF15_PURSUIT_STATE.template.json` sebagai state operasional, tanpa menimpa register canonical. Catat setiap blocker dan pertanyaan dengan key stabil, evidence, scope terdampak, kondisi membuka blokir, serta jawaban yang sudah berlaku. Runner Linux belum terikat, CI platform billing lock, dan paket DEMO belum lengkap adalah blocker yang sudah diketahui. Jangan mengulang pertanyaan atau rerun karena kondisi yang sama. Pilih pekerjaan independen; jika seluruh frontier terblokir, tinggalkan checkpoint dan satu paket intervensi owner yang konkret.

Saat pengujian database tersedia, ikat runner/database/source/config dan migrasi aktual. Jalankan inventaris 45 existing, tujuh producer/relay, dan tambahan consumer sesuai manifest terbaru. Petakan `delivery.D01–D11` dari inventory PR aktual; jangan mengarang nomor atau mencampurnya dengan `action.D01` migrasi D0. Skip, receipt hilang, source berubah, test-ID mismatch dan database identity mismatch tidak diterima. Jangan jumlahkan suite176/126/241/613 yang bertumpang tindih.

Untuk tiap slice: implementasikan → jalankan tes bermakna yang terdampak serta required gates → review → simpan evidence → perbarui state/register secukupnya → commit/push branch jika scope publikasi berlaku → lanjut slice berikutnya. Tugas source boleh selesai parsial; milestone DONE hanya berdasarkan seluruh acceptance dan dependency wajibnya. Jangan berhenti pada rencana, jumlah tes, atau laporan kemajuan bila masih ada pekerjaan executable.

Gunakan paling banyak pola koordinasi yang bermanfaat: satu coordinator dan sampai dua worker independen bila tersedia. Satu owner per file/module, satu integrator protokol/migrasi. Jika agent mencapai quota, lanjutkan serial, tandai independent review belum dilakukan, dan jangan mencoba spawn berulang. Pertahankan review mandatory yang memang diwajibkan repo.

Di akhir setiap checkpoint laporkan singkat: source/branch, outcome slice, evidence yang benar-benar dijalankan, canonical actions yang ditutup, blocker baru/berubah, dan next executable slice. Selesai hanya pada `GOAL_COMPLETE` sesuai definisi, atau `BLOCKED_EXTERNAL` setelah seluruh pekerjaan independen yang sah dituntaskan dan handoff lengkap. Tidak ada perubahan README.

---

`WOLF15_PURSUIT_PLAN.json` saat disusun berstatus **PARTIAL_PLAN / PLANNING_ONLY**. Ketika instruksi implementasi di atas diadopsi pengguna dalam sesi Desktop, catat scope otorisasi itu satu kali pada state sesi; jangan mengubah template menjadi blanket permission untuk produksi/broker. Validasi struktur paket tidak membuktikan kelulusan sistem.
