PARTIAL_PLAN — Kriteria DONE telah dirumuskan; kelulusan implementasi dan runtime belum dibuktikan. Beberapa parameter acceptance dan binding rilis masih terbuka.

# WOLF15 — Definition of Done program perbaikan

**Keputusan utama:** target dekat dianggap selesai ketika jalur natural DEMO 5S-CR bekerja menurut SSOT v3.1 repo, mencakup parent, child yang memenuhi syarat, compounding, dan rekonsiliasi broker independen. Pekerjaan assessment, kemampuan kode, canary, natural DEMO dan kesiapan REAL mempunyai status yang berbeda.

Dokumen ini menetapkan kriteria, bukan melaksanakan 41 tindakan. SSOT v3.1 yang saat ini dipilih pengguna di repo tetap acuan. R1/R2 tidak diadopsi. Tanggal dokumen 9 September 2026 WITA; pengamatan lokal dibuat 8 September UTC.

## 1. Sumber dan status awal

Sumber: laporan induk dan backlog 41 tindakan bertanggal 8 September 2026, salinan v3.1 rinci §7–17/§24, serta klarifikasi pengguna untuk tetap memakai SSOT repo. Source kritis assessment lama terikat main `1837f4b7cbded620c35933af980e9abd166de39e`; angka itu tidak diklaim sebagai HEAD saat ini. Review ini tidak mengakses ulang repo/Railway/akun.

Backlog historis berisi A00 PASS untuk akuisisi sumber, 39 aksi BLOCKED dan O03 NOT_EXECUTED. Ini bukan 1/41 kemampuan trading selesai. Status assessment yang selesai tidak menutup perbaikan kode maupun pengujian.

S01 harus mengikat path/full commit/digest SSOT repo dan membandingkannya dengan salinan yang dipakai. Pengguna sudah memilih v3.1; ini pekerjaan binding teknis, bukan permintaan persetujuan ulang untuk pilihan versi tersebut.

Koreksi terhadap ringkasan backlog: S05/master menyebut nearest H4 terlalu sempit. DoD mengikuti §17.2: D1/H4/H1 serta sumber struktural legal lainnya. Reference solver adalah §17.1; konflik diagram harus dicatat dalam resolusi kontrak. Ini koreksi kesetiaan backlog terhadap SSOT, bukan adopsi R1 atau perubahan strategi baru.

## 2. Arti DONE pada setiap tingkat

| Status | Kondisi yang harus terbukti | Yang belum dibuktikan oleh status itu |
|---|---|---|
| ASSESSMENT_DONE | Temuan, source, backlog, dependency dan rancangan tersedia | Perbaikan telah terpasang |
| ENGINEERING_DONE | P1/P2/P3 beserta required local/CI/integration gates pada source gabungan lulus | Terminal/broker sudah menjalankannya |
| D0_OUTCOME_DONE | Canary engineering terbatas mencapai outcome yang direkonsiliasi; E09 selesai sesuai kontrak | Fill atau natural 5S-CR; laporkan BROKER_FILL_PROVEN terpisah |
| NATURAL_PARENT_DONE | Event canonical alami menghasilkan parent yang valid, broker proof dan lifecycle lengkap | Child dan compounding |
| NATURAL_DEMO_DONE | P1–P5 mandatory closure, parent-child alami dan next-campaign compounding terbukti pada artifact terikat | Kelayakan akun REAL atau profit masa depan |
| REAL_REVIEW_DONE | O01/O02/O03 dan dependency wajib lengkap; dossier menghasilkan verdict beralasan | Bahwa hasil verdict harus READY |
| REAL_READY_FOR_REVIEW | Seluruh kriteria strategi/operasi/risiko yang dibekukan lulus, residual risk dapat dinilai dan tidak ada blocker wajib | Aktivasi REAL |

`D0_OUTCOME_DONE=true` dengan rejection yang jelas harus menyatakan `BROKER_FILL_PROVEN=false`. N06/N08 tetap memerlukan bukti positif kemampuan yang dideklarasikan. Belum munculnya sinyal natural valid berarti NOT_OBSERVED untuk jalur tersebut; jangan mengganti input dengan sinyal manual agar gate terlihat selesai.

## 3. Syarat umum DONE setiap aksi

Seluruh syarat berikut berlaku bersama, tidak dirata-ratakan menjadi skor:

1. Outcome acceptance yang ditentukan sebelum evaluasi benar-benar tercapai; requirement terhubung ke kode dan test.
2. Hard dependencies dan policy/capability yang dibutuhkan terpenuhi. Missing proof tetap UNBOUND/NOT_MEASURED/NOT_EXECUTED.
3. Positive path serta negative/fault cases relevan lulus. Required test yang skipped tidak dianggap PASS. Nol occurrence pada dataset kosong tidak membuktikan invariant.
4. Bukti mengikat full commit/tree, SSOT/policy/schema/config, fixture/data, runner, waktu, artifact dan account bila relevan.
5. Tidak ada blocker terbuka pada scope yang dapat menghasilkan wrong account/side/volume/protection, duplicate submission, authority leak, lost/unknown exposure atau false readiness. Debt nonblocking memiliki owner dan alasan penundaan.
6. Recovery/compensation yang relevan telah diuji, bukan hanya ditulis sebagai runbook; posisi, ledger dan riwayat broker tetap dapat direkonsiliasi.
7. Reviewer dapat mereproduksi atau menelusuri hasil dari receipt. Hash membuktikan identitas bytes, bukan kualitas strategi.

Status PATCHED, COMPILED, TESTED_LOCAL, DEPLOYED, VERIFIED_BROKER dan DONE tidak saling menggantikan. Bukti versi lama boleh menjadi konteks, tetapi tidak menutup gate artifact yang berubah. Ulangi hanya pemeriksaan yang terdampak beserta dependency-nya, dan tetap jalankan required suite sesuai kebijakan repo.

## 4. Acceptance per milestone

| Milestone | Kriteria lulus | Bukti minimum | Kondisi belum DONE |
|---|---|---|---|
| P1 — Release/ownership/readiness | Source yang diuji sama dengan yang dirilis; satu owner per scope; mandatory task/router failure menghasilkan readiness gagal; CI/migration failure nyata menggagalkan job; runner dan release controls siap | Source/image/config/schema/EA manifest, CI logs, fault receipts, role/service map | Default ready; source mismatch; silent skip; owner ganda |
| P2 — Evidence/strategi | Admission, lifecycle dan geometri sesuai v3.1; same evidence+policy menghasilkan output sama; semua acceptance wajib §24 teruji | Frozen fixtures/data/policy, persisted identities/reasons, replay hashes, coverage denominators | Direction memecah pair activity; future candle; silent drop; advisory punya capital authority |
| P3 — Risk/natural contract | Current candidate sampai risk, FinalSignal, producer dan EA tersambung; capacity atomik; protokol/migrasi gabungan kompatibel | Combined build/MetaEditor, transaction/race/fault tests, Python/MQL5 vectors, complete lineage | Projection/canary disamakan dengan natural; lot/cap salah; protocol atau migration tidak konvergen |
| P4 — D0 engineering | Artifact dan account DEMO aktual terikat; SHADOW final nol submit; bounded canary outcome lengkap dan independen; unknown nol sebelum rearm | Terminal HTTP trace, exact EA hash, canary scope, broker reader reconciliation | HTTP ACK dianggap fill; outcome ambiguous; blind retry; wrong mode/account |
| P5a — Natural parent | Natural canonical event melewati proof, risk, command, EA hingga parent broker; protection/closure teramati | Complete episode/candidate/reservation/command/order/deal linkage dan outcome | Hanya canary, sinyal manual, no-fill tanpa bukti positive path |
| P5b — Natural family | Parent+child legal, lifetime slot dan released-risk benar; compound campaign berikutnya; child release diuji sendiri | J01/J02/J03 receipts, family broker lifecycle, realized-balance/risk-basis evidence | Parent-only; child belum observed; parent PASS dipakai untuk artifact child |
| P6 — REAL dossier | Soak/recovery dan OOS/walk-forward lengkap dengan biaya/uncertainty; preregistered criteria dinilai | Metrics, evaluated criteria, incident/recovery records, residual-risk verdict | Threshold sesudah hasil; sample/biaya/recovery belum cukup; dossier disamakan dengan REAL active |

P2/P3 dan pekerjaan D0 dapat berjalan paralel sesuai hard dependencies; parent natural menunggu konvergensinya. Group P1/P2/P3 di atas bukan urutan serial wajib. P5b memakai release child terikat sendiri dan tidak mewarisi PASS parent begitu saja.

## 5. Uji penentu yang harus tampak di evidence

**Admission dan evidence.** Untuk symbol sama, BUY@0, SELL@150, BUY@300 tidak boleh terpecah hanya karena arah. Jika continuity, raw provenance dan gap policy sah, threshold crossing membuka evaluasi admission pada 300 detik; tidak otomatis memberi order permission. Fixture harus menyertakan coverage yang cukup agar contoh ini tidak menyelundupkan asumsi bahwa setiap gap150 detik sah. Duplicate/replay tidak menaikkan pulse; source gap menangguhkan sesuai policy; backfill/restart mempertahankan episode identity. Unknown coverage tidak boleh berubah menjadi NOT_APPLICABLE.

**Lifecycle dan strategy.** Qualifying mature advisory tetap dianalisis dengan nol capital reservation/FinalSignal executable/command. Upgrade menggunakan lifecycle yang sama, re-evaluation dan candidate revision baru. Raw grant dengan direction conflict tidak memaksa directional hypothesis sebelum §10.2 terpenuhi. H1/M15 closed/as-of, target nearest fresh unconsumed, structural SL, net costs dan interval kosong diuji. RR/floor/target universe mengikuti profile v3.1 yang terikat; angka advisory maturity, gap atau SLA tidak ditebak.

**Risk dan sizing.** Dua candidate/worker bersamaan tidak melampaui kapasitas akun. Volume mengikuti step broker dengan pembulatan aman; jika ukuran aman di bawah minimum, tolak. Filled, pending residual, reserved-unsubmitted dan unknown dihitung tanpa tumpang tindih. Account currency, symbol spec dan cost assumptions terikat. Estimasi profit/loss dalam mata uang akun dapat memakai loss oracle sesuai kontrak; dokumentasi MetaQuotes menjelaskan keluaran OrderCalcProfit dalam account currency. Planned loss-at-stop tidak menjamin batas aktual saat gap. [MetaQuotes OrderCalcProfit](https://www.mql5.com/en/docs/trading/ordercalcprofit).

**Command/EA/recovery.** Duplicate delivery/report idempotent; identitas sama dengan payload berbeda ditolak. Uji restart/crash sebelum-sesudah submit marker, disconnect, stale quote, expired command, invalid signature, wrong account, partial fill, out-of-order report, cancel-versus-fill, kill switch dan unavailable attestor. Unknown submission menahan exposure; expiry delivery atau cancel yang belum terkonfirmasi tidak melepaskannya. Hentikan new risk sambil reconciliation dan pengelolaan proteksi yang terotorisasi tetap berjalan.

**Broker truth.** Evidence mencakup account/server, reader identity, waktu dan kelengkapan query, orders/positions/deals/history terkait, errors dan immutable verdict. Heartbeat boolean dari executor tidak cukup. Satu logical submit dapat menghasilkan lebih dari satu transaction callback atau deal; hitung duplicate logical effect melalui linkage, bukan jumlah baris fill semata. OrderSend true bukan bukti fill. [MetaQuotes OrderSend](https://www.mql5.com/en/docs/trading/ordersend), [OnTradeTransaction](https://www.mql5.com/en/docs/event_handlers/ontradetransaction).

P4 membatasi scope canary sesuai kontrak, maksimum satu logical submit. Rejection tidak memicu percobaan otomatis lain. Setelah seluruh outcome diketahui, laporan harus tetap memisahkan keberhasilan mekanisme rekonsiliasi dari keberhasilan jalur fill.

## 6. Kriteria kuantitatif dan parameter terbuka

SSOT §24.1 menetapkan 15 acceptance dengan 100% cakupan; §24.2 menetapkan 20 zero-tolerance. Angka ini adalah assertion pada test/episode cohort yang dinyatakan, bukan jaminan seluruh kejadian masa depan. Setiap laporan mencantumkan numerator, denominator, cakupan dan window. Bila kasus qualifying tidak terjadi, gunakan NOT_OBSERVED dan fixture yang relevan; jangan melaporkan 100% tanpa sampel.

| Parameter | Cara menutup sebelum gate terkait | Status pada penyusunan DoD |
|---|---|---|
| SSOT repo path/commit/digest | S01 mencocokkan file repo yang dipilih dan versi implementasi | Belum diverifikasi ulang pada review ini |
| Risk profile akun DEMO/REAL | R01 mengikat pilihan yang berlaku beserta account/mode/currency | Exact active binding belum terbukti |
| Advisory maturity, source gap, freshness, SLA, TTL, cost buffers | Registry versi existing; gap diberi owner dan keputusan eksplisit | Nilai acceptance belum seluruhnya bound |
| Child release dan campaign basis | Policy terpilih + broker-proved release semantics | Implementasi/pengujian belum terbukti |
| Latency/lag/freshness SLO, soak window, RTO/RPO | Definisikan metric dan target sebelum drill; budget selaras expiry/market horizon | NOT_MEASURED; angka baru tidak ditetapkan di sini |
| OOS cohort/sample adequacy, drawdown/risk/cost criteria | Preregistered evaluation protocol dan reviewer/policy owner | Belum ada hasil acceptance untuk rilis ini |

Durasi DEMO atau win rate tertentu tidak dipilih secara arbitrer. Jika angka wajib belum terikat, gate terkait belum DONE. Laporkan latency per tahap, queue age, stale ratio, failed/unknown reconciliation, resource saturation dan recovery time; targetnya harus berasal dari policy/SLO berversi, bukan dari hasil yang sudah terlihat.

Minimal bukti positif untuk kemampuan parent/child harus tersedia; jumlah episode untuk evaluasi statistik adalah keputusan terpisah. Keuntungan satu transaksi atau profit agregat saja tidak membuktikan ketahanan strategi.

## 7. Bentuk receipt penutupan

Setiap gate membawa: `gate_id`, `action_ids`, `requirement_refs`, `expected_result`, `actual_result`, `status`, `run_id`, UTC dan WITA timestamps, subject commit/tree, SSOT/policy/config/schema/EA digests, fixture/dataset digest, environment identity, account binding yang aman bila diperlukan, command/test output, numerator/denominator, reviewer, unresolved items dan recovery evidence. Secret tidak dimasukkan.

Contoh negative gate: same intent + duplicated network delivery → no additional logical submit; expected count=0 duplicate, actual count harus dicatat bersama jumlah fault cases. Receipt yang hanya menulis PASS tanpa subjek, scope atau output tidak menutup aksi.

## 8. Penutupan layanan, debt dan rollout

Tidak perlu membuat seluruh 20 service selalu RUNNING untuk mengklaim jalur trading teruji. Buat disposition per service UUID: required pada jalur rilis, optional/isolated, atau intentionally disabled. Required dependencies harus sehat dan mempunyai role/entrypoint/artifact yang terikat; optional failure tidak boleh memberi authority atau false ready. Mandatory failure harus terlihat di readiness.

Setiap blocker correctness/integrasi harus memiliki closure action dan bukti. Debt di luar jalur mandatory boleh ditunda dengan owner, dampak dan dependency yang eksplisit. Ini mencegah proyek terus melebar sambil tetap menutup risiko pada jalur trading.

Sebelum side effect, final artifact dan acceptance harus sudah konkret. Pemilihan SSOT serta penyusunan DoD tidak mengaktifkan broker. §24.5 v3.1 sendiri mensyaratkan strategy, risk, bridge, EA, kill-switch, reconciliation PASS serta operator approval. Keputusan aktivasi yang sudah sah dipakai pada scope-nya; tidak meminta persetujuan ulang untuk tindakan yang sama.

Rollback source tidak membatalkan broker effect. Setelah exposure muncul, jangan menghapus ledger agar state terlihat bersih. Stop new risk, jaga proteksi dan teruskan reconciliation; gunakan compatible recovery atau forward repair yang teruji.

## 9. Koordinasi, batas bukti dan langkah berikutnya

Satu coordinator menyusun DoD; dua reviewer independen memeriksa P2 dan P3–P6. Tidak ada simultaneous edit. Input: master/backlog/salinan v3.1; output: kriteria dan source ambiguity. Stopping condition reviewer: mapping acceptance selesai, tanpa runtime/network mutation. Pengukuran: 41 aksi tercakup; 6 milestone; 15 acceptance dan 20 zero-tolerance ditemukan pada §24. Latency, biaya dan speedup koordinasi NOT_MEASURED; tidak ada dasar untuk mengubah topology statis.

Kasus ambiguity yang diselesaikan: H4-only pada ringkasan backlog dikoreksi mengikuti v3.1; rejected canary dibedakan dari positive fill; source HEAD saat ini unavailable dalam scope review dipertahankan sebagai binding task. Synthesis dilakukan terpusat, tanpa merata-ratakan kesimpulan reviewer.

Langkah yang sudah diotorisasi pada turn ini adalah menyusun dan memeriksa kriteria. Langkah engineering berikutnya ialah binding source/SSOT dan penerapan C01/C02/C06 serta S01/S03 sesuai dependency, kemudian membuktikan jalur risk→producer→EA→reconciliation. Implementasi, provisioning, merge, migrasi, deployment, MetaEditor, replay, broker dan aktivasi belum dijalankan oleh dokumen ini.

`IMPLEMENTATION=NOT_EXECUTED; RUNTIME_ACCEPTANCE=NOT_EXECUTED; CRITICAL_PATH_DURATION=NOT_MEASURED`.

## Lampiran A — Pemetaan seluruh 41 aksi

CSV pendamping memuat acceptance asli, klarifikasi DoD, owner, dependency, bukti dan status terpisah. Satu-satunya koreksi teks acceptance sumber adalah S05 untuk mengikuti universe target v3.1; klarifikasi lain diberi kolom tersendiri. Backlog asli tidak diubah.

| Milestone | Action IDs | Jumlah |
|---|---|---|
| P1 | A00, C01, C02, C03, C04, C05, C06 | 7 |
| P2 | S01, S02, S03, S04, S05, S06 | 6 |
| P3 | R01, R02, R03, N01, N02, N03, N04 | 7 |
| P4 | E01, E02, E03, E04, E05, E06, D01, E07, E08, E09 | 10 |
| P5 | D02, N05, N06, N07, J01, J02, J03, N08 | 8 |
| P6 | O01, O02, O03 | 3 |

## Lampiran B — Acceptance v3.1 yang sudah tertulis

Salinan untuk traceability; interpretasi dan implementation binding tetap mengikuti source repo yang dipilih.

### 24.1 Strategy acceptance

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

### 24.2 Zero-tolerance

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


## Lampiran C — Binding sumber lokal

- `WOLF15_Master_Backlog_2026-09-08.csv` — SHA-256 `9672d5bf6e07b3d6db5f6d6cd92f903ce53fec12369df744c88aaab7ce1c8490`.
- `WOLF15_Master_Remediation_2026-09-08.md` — SHA-256 `787f2ca210dd9099f6495919c61a7481fa3f327973df2c9d90a8e9c2f144adfe`.
- `13-WOLF15_STRATEGY_5SCR_CANONICAL_SSOT_V3_1_CANDIDATE_REPO_READY-1-.md` — SHA-256 `2cd41d01fdd3661af59284c78df669f7b312a7b7e4870f1620cfcfbe1aedb624`.
